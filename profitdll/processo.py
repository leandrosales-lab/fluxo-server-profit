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
    {"tipo": "book", "ts", "ativo"?, "niveis": [[preco, qtd, "compra"|"venda"(, ordens, corretoras)], ...]}
        ordens (int) e corretoras ([[nome, qtd], ...]) são OPCIONAIS (livro de ofertas); o formato
        antigo de 3 campos (TinyBook) continua valendo nos dois sentidos.
    {"tipo": "stats", "dados": {...ProfitDLLBridge.stats()}}   a cada 0,5 s
    {"tipo": "log", "nivel", "origem", "msg"}                  registros de log do filho
    {"tipo": "historico", "ativo", "ticks": [<tick>, ...]}     pedaço do histórico do dia (cronológico)
    {"tipo": "historico_fim", "ativo", "n"}                    o histórico do papel terminou
  pai → filho (stdin):
    "trocar ATIVO"  = abrir outro papel (livro da tela, TinyBook e histórico do dia passam a ser dele)
    qualquer outra linha (ou EOF) = encerrar: bridge.stop() (Unsubscribe + DLLFinalize) e sair.

Uso do filho (o pai monta o comando):
  python -m profitdll.processo --asset PETR4 [--agentes agentes.json] [--timeout 30]
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
from profitdll.bridge import validar_ativo, BOLSA, mascarar_caminho, CAMINHO_PADRAO_DLL

logger = logging.getLogger("ProfitDLL")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Contadores que acumulam no dia, somados entre processos filhos
CONTADORES = ("trades_recebidos", "trades_editados", "trades_ignorados", "horarios_fallback",
              "book_atualizacoes", "quedas_market", "avisos_partial",
              "livro_atualizacoes", "livro_erros", "livro_divergencias")


# ──────────────────────────────────────────────────────────────
# PROTOCOLO (puro, testado)
# ──────────────────────────────────────────────────────────────

def tick_para_msg(t: Tick) -> dict:
    return {"tipo": "tick", "ts": t.timestamp, "preco": t.price, "qtd": t.qty,
            "corretora": t.broker, "lado": t.side.value, "passiva": t.passive_broker, "ativo": t.asset}


def msg_para_tick(m: dict) -> Tick:
    return Tick(timestamp=m["ts"], price=m["preco"], qty=m["qtd"], broker=m["corretora"],
                side=Side(m["lado"]), passive_broker=m.get("passiva") or "", asset=m.get("ativo") or "")


def _nivel_para_msg(n: BookLevel) -> list:
    base = [n.price, n.qty, n.side.value]
    if n.ordens or n.corretoras:       # só o livro de ofertas leva os campos extras
        base += [n.ordens, [list(c) for c in n.corretoras]]
        if n.fila:
            base.append([list(c) for c in n.fila])
    return base


def book_para_msg(niveis: list[BookLevel], ts: float, ativo: str = "") -> dict:
    msg = {"tipo": "book", "ts": ts, "niveis": [_nivel_para_msg(n) for n in niveis]}
    if ativo:                      # papel a que o livro pertence (a troca de papel deixa livros velhos no pipe)
        msg["ativo"] = ativo
    return msg


def msg_para_book(m: dict) -> list[BookLevel]:
    saida = []
    for p, q, lado, *extra in m["niveis"]:
        ordens = int(extra[0]) if extra else 0
        corretoras = [[str(c[0]), int(c[1])] for c in extra[1]] if len(extra) > 1 and extra[1] else []
        fila = [[str(c[0]), int(c[1])] for c in extra[2]] if len(extra) > 2 and extra[2] else []
        saida.append(BookLevel(price=p, qty=q, broker="", side=Side(lado), timestamp=m["ts"],
                               ordens=ordens, corretoras=corretoras, fila=fila))
    return saida


TICKS_POR_MSG = 2000


def historico_para_msgs(ativo: str, ticks: list) -> list[dict]:
    """Histórico do dia em pedaços (uma linha JSON não pode crescer sem limite) + a mensagem de fim."""
    msgs = [{"tipo": "historico", "ativo": ativo, "ticks": [tick_para_msg(t) for t in ticks[i:i + TICKS_POR_MSG]]}
            for i in range(0, len(ticks), TICKS_POR_MSG)]
    msgs.append({"tipo": "historico_fim", "ativo": ativo, "n": len(ticks)})
    return msgs


def renovacao_para_msg(ativo: str, corretora: str, lado: str, preco: float, ts: float) -> dict:
    return {"tipo": "renovacao", "ativo": ativo, "corretora": corretora, "lado": lado,
            "preco": preco, "ts": ts}


# ──────────────────────────────────────────────────────────────
# PAI: mesma interface da ProfitDLLBridge para o main.py e o server.py
# ──────────────────────────────────────────────────────────────

class PonteDLLProcesso:
    """
    Sobe a ProfitDLL num processo filho e repassa ticks/book ao engine.
    start()/stop() criam/encerram o filho; reconectar = stop() + start() (processo novo).
    """

    def __init__(self, asset: str, agentes_path: Optional[str] = None, timeout: int = 30,
                 comando: Optional[list] = None, folga: float = 15.0, radar: Optional[str] = None):
        self.asset = validar_ativo(asset)
        self.exchange = BOLSA
        self.timeout = timeout
        self.folga = folga                         # além do timeout da DLL: subir o Python e carregar a DLL
        self.on_tick: Optional[Callable[[Tick], None]] = None
        self.on_book: Optional[Callable[[list[BookLevel]], None]] = None
        self.on_renovacao: Optional[Callable[..., None]] = None
        # histórico do dia: (ativo, [Tick]) por pedaço; o fim vem em on_historico_fim(ativo, n)
        self.on_historico: Optional[Callable[[str, list], None]] = None
        self.on_historico_fim: Optional[Callable[[str, int], None]] = None
        self.motivo_falha: Optional[str] = None
        if comando is None:
            comando = [sys.executable, "-X", "utf8", "-m", "profitdll.processo", "--asset", self.asset,
                       "--timeout", str(timeout)]
            if agentes_path:
                comando += ["--agentes", agentes_path]
            if radar:
                comando += ["--radar", radar]
        self._comando = comando
        self._proc: Optional[subprocess.Popen] = None
        self._leitor: Optional[threading.Thread] = None
        self._inicio = threading.Event()
        self._inicio_ok = False
        self._parando = False
        self._trava = threading.Lock()
        # start()/stop() um de cada vez: a conexão inicial (main.py), o Reconectar e o Ctrl+C
        # podem chegar de threads diferentes e não podem mexer no mesmo filho ao mesmo tempo
        self._ciclo = threading.Lock()
        self._ultimo: dict = {}                   # stats mais recentes do filho atual
        self._base: dict = {k: 0 for k in CONTADORES}
        self._base_tipos: dict[str, int] = {}

    # ── ciclo de vida
    @property
    def ocupado(self) -> bool:
        """True enquanto um start()/stop() está em curso (o servidor responde 409 ao Reconectar)."""
        return self._ciclo.locked()

    def start(self) -> bool:
        with self._ciclo:
            return self._start()

    def stop(self):
        with self._ciclo:
            self._encerrar_filho()

    def _start(self) -> bool:
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

        if not self._inicio.wait(self.timeout + self.folga):
            # o filho só lê o "stop" depois que o login termina: esperar por ele seria inútil
            self.motivo_falha = "processo da ProfitDLL não respondeu"
            self._parando = True
            self._proc.kill()
        if self._inicio_ok:
            self.motivo_falha = None
            logger.info(f"ProfitDLL rodando no processo filho (pid {self._proc.pid})")
            return True
        if not self.motivo_falha:
            self.motivo_falha = "falha ao conectar"
        self._encerrar_filho()
        return False

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

    def trocar_ativo(self, ativo: str) -> bool:
        """Abre outro papel no filho (livro, TinyBook e histórico do dia). False se não há filho vivo."""
        ativo = validar_ativo(ativo)
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return False
        try:
            proc.stdin.write(f"trocar {ativo}\n")
            proc.stdin.flush()
        except (OSError, ValueError):
            return False
        # o Reconectar sobe um filho novo: ele já abre no papel de agora
        self.asset = ativo
        if "--asset" in self._comando:
            self._comando[self._comando.index("--asset") + 1] = ativo
        return True

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
            if self.on_book and (not m.get("ativo") or m["ativo"] == self.asset):
                self.on_book(msg_para_book(m))
        elif tipo == "historico":
            if self.on_historico:
                self.on_historico(m.get("ativo") or "", [msg_para_tick(t) for t in m.get("ticks") or []])
        elif tipo == "historico_fim":
            if self.on_historico_fim:
                self.on_historico_fim(m.get("ativo") or "", int(m.get("n") or 0))
        elif tipo == "renovacao":
            if self.on_renovacao:
                self.on_renovacao(m.get("ativo") or "", m.get("corretora") or "", m.get("lado") or "",
                                  float(m.get("preco") or 0), float(m.get("ts") or 0))
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
        proc = self._proc                         # cópia local: o Reconectar pode zerar self._proc
        vivo = proc is not None and proc.poll() is None
        st = {
            "conectado": False, "estado_market": None, "fila_pendente": 0, "bid": None, "ask": None,
            "livro_ativo": False, "livro_ordens": 0,
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
        st["processo"] = {"pid": proc.pid if vivo else None, "vivo": vivo}
        st["ocupado"] = self.ocupado
        return st


# ──────────────────────────────────────────────────────────────
# FILHO: roda a ProfitDLLBridge e fala o protocolo no stdout
# ──────────────────────────────────────────────────────────────

def main_filho(argv=None, fabrica_ponte=None, entrada=None, saida=None) -> int:
    """
    Corpo do processo filho. fabrica_ponte, entrada e saida existem para o teste
    (ponte falsa e streams em memória); no uso real ficam None.
    """
    if fabrica_ponte is None:
        from profitdll.bridge import ProfitDLLBridge as fabrica_ponte

    p = argparse.ArgumentParser(description="ProfitDLL em processo filho do Fluxo Server")
    p.add_argument("--asset", required=True)
    p.add_argument("--agentes", default=None)
    p.add_argument("--timeout", default=30, type=int)
    p.add_argument("--radar", default=None, help="lista de ações a assinar além do --asset (config/acoes_b3.txt)")
    args = p.parse_args(argv)

    entrada = entrada or sys.stdin
    stdout_original = None
    if saida is None:
        # O protocolo ganha uma cópia própria do fd 1, e o fd 1 passa a apontar para o stderr:
        # assim nem print do Python nem escrita nativa da DLL no stdout se misturam ao JSON.
        sys.stdout.flush()
        fd_protocolo = os.dup(1)
        os.dup2(2, 1)
        saida = os.fdopen(fd_protocolo, "w", encoding="utf-8", newline="\n")
        stdout_original = sys.stdout
        sys.stdout = sys.stderr
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

    raiz = logging.getLogger()
    handler = HandlerProtocolo(logging.INFO)
    raiz.addHandler(handler)
    if raiz.level > logging.INFO or raiz.level == logging.NOTSET:
        raiz.setLevel(logging.INFO)
    try:
        extras = None
        if args.radar:
            sys.path.insert(0, os.path.join(RAIZ, "tools"))
            from acoes_b3 import carregar_lista
            extras = carregar_lista(args.radar)
        bridge = (fabrica_ponte(args.asset, args.agentes, timeout=args.timeout, extras=extras)
                  if extras is not None else fabrica_ponte(args.asset, args.agentes, timeout=args.timeout))
        bridge.on_tick = lambda t: enviar(tick_para_msg(t))
        bridge.on_book = lambda niveis: enviar(book_para_msg(niveis, time.time(), getattr(bridge, "asset", "")))
        bridge.on_renovacao = lambda *a: enviar(renovacao_para_msg(*a))

        def enviar_historico(ativo, ticks):
            for msg in historico_para_msgs(ativo, ticks):
                enviar(msg)
        bridge.on_historico = enviar_historico
        ok = bridge.start()
        enviar({"tipo": "inicio", "ok": ok, "motivo": bridge.motivo_falha})
        if not ok:
            return 1
        if hasattr(bridge, "pedir_historico"):
            bridge.pedir_historico()     # o gráfico do papel inicial começa no início do pregão

        parar = threading.Event()        # EOF no stdin (pai encerrou) ou qualquer linha que não seja "trocar" = parar

        def ler_comandos():
            for linha in iter(entrada.readline, ""):
                partes = linha.split()
                if len(partes) == 2 and partes[0] == "trocar" and hasattr(bridge, "trocar_ativo"):
                    try:
                        bridge.trocar_ativo(partes[1])
                    except ValueError as e:
                        logger.warning(f"Troca de papel recusada: {e}")
                    continue
                break
            parar.set()
        threading.Thread(target=ler_comandos, daemon=True).start()
        while not parar.wait(0.5):
            enviar({"tipo": "stats", "dados": bridge.stats()})
        bridge.stop()
        enviar({"tipo": "stats", "dados": bridge.stats()})
        return 0
    finally:
        raiz.removeHandler(handler)
        if stdout_original is not None:
            sys.stdout = stdout_original


if __name__ == "__main__":
    sys.exit(main_filho())
