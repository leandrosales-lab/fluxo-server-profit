"""
PROFITDLL EM PROCESSO FILHO
===========================
A ProfitDLL não aceita DLLFinalize seguido de um novo DLLInitializeMarketLogin
no mesmo processo (testado em 16/10/2026: Access violation em CreateDataLoader,
dentro da ProfitDLL.dll). Para o Reconectar da tela Conexão funcionar sem perder
o estado do engine, a DLL roda num processo filho e o servidor só conversa com ele.

Protocolo (uma linha JSON por mensagem):
  filho → pai (stdout):
    {"tipo": "inicio", "ok": bool, "motivo": str|None}   resultado do start()
    {"tipo": "tick", "ts", "preco", "qtd", "corretora", "lado": "compra"|"venda", "passiva"}
    {"tipo": "book", "ts", "niveis": [[preco, qtd, "compra"|"venda"], ...]}
    {"tipo": "stats", "dados": {...ProfitDLLBridge.stats()}}   a cada 0,5 s
    {"tipo": "log", "nivel", "origem", "msg"}                  registros de log do filho
  pai → filho (stdin):
    qualquer linha (ou EOF) = encerrar: bridge.stop() (Unsubscribe + DLLFinalize) e sair.

Uso do filho (o pai monta o comando):
  python -m profitdll.processo --asset WDOFUT [--bolsa F] [--agentes agentes.json] [--timeout 30]
"""
import os
import sys
import json
import time
import logging
import argparse
import threading
import subprocess
from typing import Optional, Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.engine import Tick, BookLevel, Side
from profitdll.bridge import bolsa_padrao, mascarar_caminho, CAMINHO_PADRAO_DLL

logger = logging.getLogger("ProfitDLL")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Contadores que acumulam no dia, somados entre processos filhos
CONTADORES = ("trades_recebidos", "trades_editados", "trades_ignorados", "horarios_fallback",
              "book_atualizacoes", "quedas_market", "avisos_partial")


# ──────────────────────────────────────────────────────────────
# PROTOCOLO (puro, testado)
# ──────────────────────────────────────────────────────────────

def tick_para_msg(t: Tick) -> dict:
    return {"tipo": "tick", "ts": t.timestamp, "preco": t.price, "qtd": t.qty,
            "corretora": t.broker, "lado": t.side.value, "passiva": t.passive_broker}


def msg_para_tick(m: dict) -> Tick:
    return Tick(timestamp=m["ts"], price=m["preco"], qty=m["qtd"], broker=m["corretora"],
                side=Side(m["lado"]), passive_broker=m.get("passiva") or "")


def book_para_msg(niveis: list[BookLevel], ts: float) -> dict:
    return {"tipo": "book", "ts": ts, "niveis": [[n.price, n.qty, n.side.value] for n in niveis]}


def msg_para_book(m: dict) -> list[BookLevel]:
    return [BookLevel(price=p, qty=q, broker="", side=Side(lado), timestamp=m["ts"])
            for p, q, lado in m["niveis"]]


# ──────────────────────────────────────────────────────────────
# PAI: mesma interface da ProfitDLLBridge para o main.py e o server.py
# ──────────────────────────────────────────────────────────────

class PonteDLLProcesso:
    """
    Sobe a ProfitDLL num processo filho e repassa ticks/book ao engine.
    start()/stop() criam/encerram o filho; reconectar = stop() + start() (processo novo).
    """

    def __init__(self, asset: str, exchange: Optional[str] = None,
                 agentes_path: Optional[str] = None, timeout: int = 30,
                 comando: Optional[list] = None):
        self.asset = asset
        self.exchange = exchange or bolsa_padrao(asset)
        self.timeout = timeout
        self.on_tick: Optional[Callable[[Tick], None]] = None
        self.on_book: Optional[Callable[[list[BookLevel]], None]] = None
        self.motivo_falha: Optional[str] = None
        if comando is None:
            comando = [sys.executable, "-X", "utf8", "-m", "profitdll.processo", "--asset", asset,
                       "--bolsa", self.exchange, "--timeout", str(timeout)]
            if agentes_path:
                comando += ["--agentes", agentes_path]
        self._comando = comando
        self._proc: Optional[subprocess.Popen] = None
        self._leitor: Optional[threading.Thread] = None
        self._inicio = threading.Event()
        self._inicio_ok = False
        self._parando = False
        self._trava = threading.Lock()
        self._ultimo: dict = {}                    # stats mais recentes do filho atual
        self._base: dict = {k: 0 for k in CONTADORES}
        self._base_tipos: dict[str, int] = {}

    # ── ciclo de vida
    def start(self) -> bool:
        self.motivo_falha = None
        self._parando = False
        self._inicio.clear()
        self._inicio_ok = False
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        sem_janela = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._proc = subprocess.Popen(self._comando, cwd=RAIZ, env=env, stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                          text=True, encoding="utf-8", errors="replace",
                                          bufsize=1, creationflags=sem_janela)
        except OSError as e:
            self.motivo_falha = f"não foi possível iniciar o processo da ProfitDLL: {e}"
            logger.error(self.motivo_falha)
            return False
        self._leitor = threading.Thread(target=self._ler_saida, args=(self._proc,), daemon=True)
        self._leitor.start()
        threading.Thread(target=self._ler_erros, args=(self._proc,), daemon=True).start()

        if not self._inicio.wait(self.timeout + 15):
            self.motivo_falha = "processo da ProfitDLL não respondeu"
        if self._inicio_ok:
            logger.info(f"ProfitDLL rodando no processo filho (pid {self._proc.pid})")
            return True
        if not self.motivo_falha:
            self.motivo_falha = "falha ao conectar"
        self._encerrar_filho()
        return False

    def stop(self):
        self._encerrar_filho()

    def _encerrar_filho(self):
        proc = self._proc
        if proc is None:
            return
        self._parando = True
        if proc.poll() is None:
            try:
                proc.stdin.write("stop\n")
                proc.stdin.flush()
            except (OSError, ValueError):
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Processo da ProfitDLL não encerrou em 10 s — finalizando à força")
                proc.kill()
                proc.wait(timeout=5)
        if self._leitor:
            self._leitor.join(timeout=5)
        self._proc = None

    # ── leitura do filho (thread)
    def _ler_saida(self, proc: subprocess.Popen):
        for linha in proc.stdout:
            try:
                m = json.loads(linha)
            except ValueError:
                logger.warning(f"ProfitDLL (filho): linha fora do protocolo: {linha.strip()[:200]}")
                continue
            try:
                self._tratar(m)
            except Exception as e:
                logger.error(f"Erro ao tratar mensagem do processo da ProfitDLL: {e}")
        codigo = proc.wait()
        with self._trava:                           # o dia continua: soma o que este filho contou
            for k in CONTADORES:
                self._base[k] += int(self._ultimo.get(k) or 0)
            for tipo, n in (self._ultimo.get("ignorados_por_tipo") or {}).items():
                self._base_tipos[tipo] = self._base_tipos.get(tipo, 0) + n
            self._ultimo = {}
        if not self._inicio.is_set():
            self.motivo_falha = self.motivo_falha or f"processo da ProfitDLL encerrou (código {codigo})"
            self._inicio.set()
        elif not self._parando:
            self.motivo_falha = f"processo da ProfitDLL encerrou (código {codigo})"
            logger.error(f"ProfitDLL: {self.motivo_falha}")

    def _ler_erros(self, proc: subprocess.Popen):
        for linha in proc.stderr:
            if linha.strip():
                logger.warning(f"ProfitDLL (filho, stderr): {linha.rstrip()[:300]}")

    def _tratar(self, m: dict):
        tipo = m.get("tipo")
        if tipo == "tick":
            if self.on_tick:
                self.on_tick(msg_para_tick(m))
        elif tipo == "book":
            if self.on_book:
                self.on_book(msg_para_book(m))
        elif tipo == "stats":
            with self._trava:
                self._ultimo = m.get("dados") or {}
        elif tipo == "log":
            nivel = logging.getLevelName(str(m.get("nivel", "INFO")))
            logging.getLogger(m.get("origem") or "ProfitDLL").log(
                nivel if isinstance(nivel, int) else logging.INFO, m.get("msg", ""))
        elif tipo == "inicio":
            self._inicio_ok = bool(m.get("ok"))
            if not self._inicio_ok:
                self.motivo_falha = m.get("motivo") or "falha ao conectar"
            self._inicio.set()

    # ── estado para GET /state (bloco "dll")
    def stats(self) -> dict:
        with self._trava:
            ultimo = dict(self._ultimo)
            base, base_tipos = dict(self._base), dict(self._base_tipos)
        vivo = self._proc is not None and self._proc.poll() is None
        st = {
            "conectado": False, "estado_market": None, "fila_pendente": 0, "bid": None, "ask": None,
            "estados": {"login": None, "ativacao": None, "market": None}, "latencia_ms": None,
            "ativo": self.asset, "bolsa": self.exchange,
            "dll_path": mascarar_caminho(os.getenv("PROFITDLL_PATH", CAMINHO_PADRAO_DLL)),
        }
        st.update(ultimo)
        for k in CONTADORES:
            st[k] = base[k] + int(ultimo.get(k) or 0)
        tipos = dict(base_tipos)
        for tipo, n in (ultimo.get("ignorados_por_tipo") or {}).items():
            tipos[tipo] = tipos.get(tipo, 0) + n
        st["ignorados_por_tipo"] = tipos
        st["conectado"] = bool(vivo and ultimo.get("conectado"))
        st["motivo_falha"] = self.motivo_falha or ultimo.get("motivo_falha")
        st["processo"] = {"pid": self._proc.pid if vivo else None, "vivo": vivo}
        return st


# ──────────────────────────────────────────────────────────────
# FILHO: roda a ProfitDLLBridge e fala o protocolo no stdout
# ──────────────────────────────────────────────────────────────

def main_filho(argv=None) -> int:
    from profitdll.bridge import ProfitDLLBridge

    p = argparse.ArgumentParser(description="ProfitDLL em processo filho do Fluxo Server")
    p.add_argument("--asset", required=True)
    p.add_argument("--bolsa", default=None)
    p.add_argument("--agentes", default=None)
    p.add_argument("--timeout", default=30, type=int)
    args = p.parse_args(argv)

    saida = sys.stdout
    sys.stdout = sys.stderr            # o stdout real é só do protocolo; print perdido vai para o stderr
    trava = threading.Lock()

    def enviar(m: dict):
        with trava:
            saida.write(json.dumps(m, ensure_ascii=False) + "\n")
            saida.flush()

    class HandlerProtocolo(logging.Handler):
        def emit(self, r: logging.LogRecord):
            try:
                enviar({"tipo": "log", "nivel": r.levelname, "origem": r.name, "msg": r.getMessage()})
            except Exception:
                pass

    logging.basicConfig(level=logging.INFO, handlers=[HandlerProtocolo()])

    bridge = ProfitDLLBridge(args.asset, args.bolsa, args.agentes, timeout=args.timeout)
    bridge.on_tick = lambda t: enviar(tick_para_msg(t))
    bridge.on_book = lambda niveis: enviar(book_para_msg(niveis, time.time()))
    ok = bridge.start()
    enviar({"tipo": "inicio", "ok": ok, "motivo": bridge.motivo_falha})
    if not ok:
        return 1

    parar = threading.Event()
    threading.Thread(target=lambda: (sys.stdin.readline(), parar.set()), daemon=True).start()
    while not parar.wait(0.5):
        enviar({"tipo": "stats", "dados": bridge.stats()})
    bridge.stop()
    enviar({"tipo": "stats", "dados": bridge.stats()})
    return 0


if __name__ == "__main__":
    sys.exit(main_filho())
