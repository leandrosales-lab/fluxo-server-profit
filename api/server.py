"""
API HTTP — Servidor de Sinais para o Profit Pro
================================================
Expõe endpoints REST que o robô NTSL consulta via DDE,
e as telas web Operar e Conexão para acompanhar em tempo real.

Porta padrão: 5000

Endpoints:
  GET  /signal          → sinal atual (BUY/SELL/WAIT/CLOSE)
  GET  /state           → estado completo do motor
  POST /tick            → injetar tick (side obrigatório: C/V; passive_broker opcional)
  POST /rtd             → retrato do RTD do Profit; o servidor infere o tick
  POST /book            → injetar snapshot do book (testes)
  GET  /health          → status do servidor (modo, fonte e tick do ativo)
  GET  / , /operar      → tela Operar (api/static/operar.html; /dashboard também abre)
  GET  /conexao         → tela Conexão (api/static/conexao.html)
  GET  /leilao          → tela Leilão (api/static/leilao.html)
  GET  /api/leilao?ativo=X&visao=sobra|livro → papéis do leilão de abertura (desequilíbrio, escora) e o book de X
  GET  /static/[css|js|fonts/]<nome> → arquivos de api/static/
  GET  /trades?limit=N  → Times & Trades: últimos N negócios (padrão 200, máx. 1000)
  GET  /candles?tf=S&since=T → candles de S segundos (15, 60, 300, 900 ou 3600) a partir de T
  GET  /signals?since=T → sinais BUY/SELL novos a partir de T
  GET  /book            → último snapshot do book e a profundidade da fonte (none/top/full)
  GET  /log?apos=SEQ&nivel=INFO → log do servidor em memória (credenciais mascaradas; também since=T)
  POST /config          → atualizar configurações em tempo real
  POST /reset           → reset do motor (início de dia)
  POST /encerrar        → encerra o servidor com a ProfitDLL finalizada (Unsubscribe + DLLFinalize); 202
  POST /dll/reconectar  → stop()+start() da ProfitDLL numa thread (202; 409 se já reconectando; 404 fora do modo dll)
"""

import json
import time
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

# Importações internas
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.engine import FlowEngine, Tick, BookLevel, Side, EngineConfig
from core.rtd import RTDTradeInferer, RTDSnapshot
from api import log_memoria


def _parse_side(value) -> Side:
    """C/COMPRA/BUY → BUY, V/VENDA/SELL → SELL. Qualquer outro valor é erro."""
    v = str(value).strip().upper()
    if v in ("C", "COMPRA", "BUY"):
        return Side.BUY
    if v in ("V", "VENDA", "SELL"):
        return Side.SELL
    raise ValueError(f"side inválido: {value!r} (use C ou V)")

logger = logging.getLogger("API")


# ──────────────────────────────────────────────────────────────
# PÁGINAS E ARQUIVOS ESTÁTICOS DAS TELAS
# ──────────────────────────────────────────────────────────────

# Páginas e arquivos das telas (api/static/). As páginas buscam o estado no GET /state.
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

_TIPOS = {
    ".js":    "application/javascript; charset=utf-8",
    ".html":  "text/html; charset=utf-8",
    ".css":   "text/css; charset=utf-8",
    ".json":  "application/json; charset=utf-8",
    ".png":   "image/png",
    ".svg":   "image/svg+xml",
    ".woff2": "font/woff2",
    ".mjs":   "application/javascript; charset=utf-8",
    ".txt":   "text/plain; charset=utf-8",
}

_SUBPASTAS = ("css", "js", "fonts")

# Rota → página em STATIC_DIR
PAGINAS = {"/": "operar.html", "/dashboard": "operar.html", "/operar": "operar.html",
           "/conexao": "conexao.html", "/radar": "radar.html", "/leilao": "leilao.html"}


def caminho_estatico(nome: str):
    """
    Caminho de um arquivo de STATIC_DIR ou de uma subpasta css/, js/ ou fonts/.
    None para '..', caminho absoluto, arquivo oculto, outra subpasta, tipo não servido ou inexistente.
    """
    if not nome or "\\" in nome or nome.startswith("/"):
        return None
    partes = nome.split("/")
    if len(partes) > 2 or (len(partes) == 2 and partes[0] not in _SUBPASTAS):
        return None
    if any(not p or p.startswith(".") or ":" in p for p in partes):
        return None
    if os.path.splitext(nome)[1].lower() not in _TIPOS:
        return None
    caminho = os.path.join(STATIC_DIR, *partes)
    return caminho if os.path.isfile(caminho) else None



# ──────────────────────────────────────────────────────────────
# HANDLER HTTP
# ──────────────────────────────────────────────────────────────

_PAPEIS = None


def papeis_cadastrados() -> list[str]:
    """Tickers de config/acoes_b3.txt (lidos uma vez; linhas com # são comentário)."""
    global _PAPEIS
    if _PAPEIS is None:
        caminho = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "acoes_b3.txt")
        try:
            with open(caminho, encoding="utf-8") as f:
                _PAPEIS = [l.strip().upper() for l in f if l.strip() and not l.lstrip().startswith("#")]
        except OSError:
            _PAPEIS = []
    return _PAPEIS


class FlowHandler(BaseHTTPRequestHandler):
    engine: FlowEngine = None   # referência estática, preenchida no start
    rtd: RTDTradeInferer = None
    dll = None                  # ProfitDLLBridge no modo dll (contadores no /state)
    radar = None                # core.radar.Radar quando o servidor sobe com --radar (GET /api/radar)
    leilao = None               # core.leilao.PainelLeilao (GET /api/leilao); --leilao-demo liga o simulado
    portao = None               # core.portao_historico.PortaoHistorico (histórico do dia, modo dll)
    encerrar = None             # função sem argumentos que encerra o processo de forma limpa (main.py)
    log: "log_memoria.LogMemoria" = None   # GET /log (tela Conexão)
    modo = "manual"             # GET /health: modo do main.py
    fonte = None                # GET /health: nome da fonte (ex.: exemplo_petr4.csv, ProfitDLL)

    # Reconexão da ProfitDLL pedida pela tela Conexão (uma de cada vez)
    reconexao = {"em_andamento": False, "ultima": None, "resultado": None}
    _trava_reconexao = threading.Lock()

    @staticmethod
    def _reconectar(bridge):
        """Roda numa thread: stop() + start() na MESMA ponte (o engine continua ligado em on_tick)."""
        logger.info("ProfitDLL: reconectando (pedido pela tela Conexão)")
        try:
            bridge.stop()
            ok = bridge.start()
            resultado = "ok" if ok else f"falhou: {bridge.motivo_falha or 'veja o log'}"
        except Exception as e:
            resultado = f"falhou: {e}"
        with FlowHandler._trava_reconexao:
            FlowHandler.reconexao = {"em_andamento": False, "ultima": time.time(), "resultado": resultado}
        (logger.info if resultado == "ok" else logger.error)(f"ProfitDLL: reconexão {resultado}")

    def log_message(self, fmt, *args):
        logger.debug(f"{self.client_address[0]} — {fmt % args}")

    def _send_json(self, data: dict, code: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


    def _send_bytes(self, body: bytes, content_type: str, cache: str = "no-store", code: int = 200):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", len(body))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def _estado_completo(self) -> dict:
        state = self.engine.get_state()
        state["rtd"] = self.rtd.stats()
        if self.dll is not None:
            state["dll"] = self.dll.stats()
            state["dll"]["reconexao"] = dict(FlowHandler.reconexao)
            # Defesa em profundidade: textos livres que vêm de exceções passam pela mesma máscara do /log
            segredos = [os.environ.get(n, "") for n in log_memoria.VARIAVEIS_SECRETAS]
            if state["dll"].get("motivo_falha"):
                state["dll"]["motivo_falha"] = log_memoria.mascarar(state["dll"]["motivo_falha"], segredos)
            if state["dll"]["reconexao"].get("resultado"):
                state["dll"]["reconexao"]["resultado"] = log_memoria.mascarar(
                    state["dll"]["reconexao"]["resultado"], segredos)
        return state

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length:
            raw = self.rfile.read(length)
            return json.loads(raw)
        return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        qs = parse_qs(url.query)

        def num(nome, padrao=None, tipo=float):
            v = qs.get(nome, [None])[0]
            return padrao if v in (None, "") else tipo(v)

        if path == "/signal":
            sig = self.engine.get_signal()
            self._send_json(sig.to_dict())

        elif path == "/state":
            self._send_json(self._estado_completo())

        elif path == "/health":
            with self.engine._lock:
                tick_count = len(self.engine._ticks)
            self._send_json({
                "status": "ok",
                "asset": self.engine.asset,
                "ticks": tick_count,
                "time": time.time(),
                "modo": self.modo,
                "fonte": self.fonte,
                "tick_size": self.engine.cfg.tick_size,
            })

        elif path == "/api/ativos":
            # Lista de papéis para o autocompletar da tela Operar (config/acoes_b3.txt; vazia se o arquivo faltar)
            self._send_json({"ativos": papeis_cadastrados()})

        elif path == "/api/radar":
            radar = FlowHandler.radar
            if radar is None:
                self._send_json({"resumo": None, "lista": []})
            else:
                try:
                    limite = num("limite", 300, int)
                except ValueError:
                    self._send_json({"error": "limite inválido"}, 400)
                    return
                sit = qs.get("situacao", [None])[0] or None
                try:
                    janela = num("janela", 0, int) or None      # segundos; 120 = 2 min, 300 = 5 min
                except ValueError:
                    self._send_json({"error": "janela inválida"}, 400)
                    return
                with self.engine._lock:          # o radar recebe negócios sob este lock (Radar.envolver)
                    ordem = "giros" if qs.get("ordem", [""])[0] == "giros" else "padrao"
                    corpo = {"resumo": radar.resumo(), "lista": radar.lista(sit, max(1, limite), janela, ordem),
                             "agora": radar._agora}
                self._send_json(corpo)

        elif path == "/api/leilao":
            painel = FlowHandler.leilao
            if painel is None:
                self._send_json({"fonte": None, "resumo": None, "lista": [], "book": None})
                return
            visao = "livro" if qs.get("visao", [""])[0] == "livro" else "sobra"
            lista = painel.lista()
            ativo = (qs.get("ativo", [""])[0] or "").strip().upper() or (lista[0]["ativo"] if lista else "")
            self._send_json({"fonte": painel.fonte, "agora": painel.agora, "abertura_prevista": painel.abertura_prevista,
                             "modo": painel.modo,
                             "razao_min": painel.cfg.razao_min, "banda": painel.cfg.banda,
                             "resumo": painel.resumo(lista), "lista": lista,
                             "book": painel.book(ativo, visao) if ativo else None})

        elif path in PAGINAS:
            arquivo = os.path.join(STATIC_DIR, PAGINAS[path])
            try:
                with open(arquivo, "rb") as f:
                    corpo = f.read()
            except OSError:
                self._send_bytes(f"Tela indisponível: api/static/{PAGINAS[path]} não encontrado.\n"
                                 .encode(), "text/plain; charset=utf-8", code=503)
                return
            self._send_bytes(corpo, "text/html; charset=utf-8")

        elif path.startswith("/static/"):
            caminho = caminho_estatico(path[len("/static/"):])
            if caminho is None:
                self._send_json({"error": "arquivo não encontrado"}, 404)
                return
            ext = os.path.splitext(caminho)[1].lower()
            with open(caminho, "rb") as f:
                corpo = f.read()
            # JS/CSS das telas nunca ficam velhos depois de uma atualização; fontes e a biblioteca, sim
            cache = "max-age=86400" if ext == ".woff2" or "lightweight-charts" in caminho else "no-cache"
            self._send_bytes(corpo, _TIPOS[ext], cache)

        elif path == "/trades":
            try:
                limite = num("limit", 200, int)
            except ValueError:
                self._send_json({"error": "limit inválido"}, 400)
                return
            self._send_json({"trades": self.engine.get_trades(max(0, min(limite, 1000)))})

        elif path == "/candles":
            try:
                tf = num("tf", 60, int)
                since = num("since")
                self._send_json({"tf": tf, "candles": self.engine.get_candles(tf, since)})
            except ValueError as e:
                self._send_json({"error": str(e)}, 400)

        elif path == "/signals":
            try:
                since = num("since")
            except ValueError:
                self._send_json({"error": "since inválido"}, 400)
                return
            self._send_json({"signals": self.engine.get_signals(since)})

        elif path == "/book":
            self._send_json(self.engine.get_book())

        elif path == "/log":
            try:
                since = num("since")
                apos = num("apos", None, int)
                registros = self.log.registros(since, qs.get("nivel", ["INFO"])[0], apos)
            except ValueError as e:
                self._send_json({"error": str(e)}, 400)
                return
            self._send_json({"registros": registros, "ultimo_seq": self.log.ultimo_seq})

        else:
            self._send_json({"error": "endpoint não encontrado"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/tick":
            # Injetar tick manualmente (para testes ou integração via DDE)
            body = self._read_body()
            try:
                side = _parse_side(body["side"])
                tick = Tick(
                    timestamp = body.get("timestamp", time.time()),
                    price     = float(body["price"]),
                    qty       = int(body["qty"]),
                    broker    = str(body.get("broker", "DESCONHECIDA")),
                    side      = side,
                    # Corretora passiva (opcional): habilita o iceberg pela passiva
                    passive_broker = str(body.get("passive_broker") or "").strip(),
                )
                self.engine.add_tick(tick)
                self._send_json({"ok": True, "signal": self.engine.get_signal().to_dict()})
            except (KeyError, ValueError) as e:
                self._send_json({"error": str(e)}, 400)

        elif path == "/book":
            # Injetar snapshot do book
            body = self._read_body()
            try:
                levels = []
                for row in body.get("levels", []):
                    side = _parse_side(row["side"])
                    levels.append(BookLevel(
                        price  = float(row["price"]),
                        qty    = int(row["qty"]),
                        broker = str(row.get("broker", "")),
                        side   = side,
                        ordens = int(row.get("ordens", 0)),
                        corretoras = [[str(nome), int(q)] for nome, q in row.get("corretoras", [])],
                    ))
                self.engine.update_book(levels)
                self._send_json({"ok": True, "levels": len(levels)})
            except (KeyError, ValueError, TypeError) as e:
                self._send_json({"error": str(e)}, 400)

        elif path == "/rtd":
            # Retrato do RTD: price, volume, trades, buyer, seller, [bid, ask]
            body = self._read_body()
            try:
                snap = RTDSnapshot.from_dict(body)
                if snap.bid > 0 and snap.ask > 0:
                    # Topo do book (OCP/OVD). O RTD não traz quantidade nem corretora do nível.
                    self.engine.update_book([
                        BookLevel(price=snap.bid, qty=0, broker="", side=Side.BUY, timestamp=snap.timestamp),
                        BookLevel(price=snap.ask, qty=0, broker="", side=Side.SELL, timestamp=snap.timestamp),
                    ])
                tick = self.rtd.update(snap)
                if tick:
                    self.engine.add_tick(tick)
                # Campos do sinal no nível raiz (a macro VBA os lê por texto)
                resp = self.engine.get_signal().to_dict()
                resp["ok"] = True
                resp["tick"] = None if tick is None else {
                    "side": tick.side.value, "qty": tick.qty, "broker": tick.broker,
                }
                self._send_json(resp)
            except (KeyError, ValueError) as e:
                self._send_json({"error": str(e)}, 400)

        elif path == "/config":
            # Atualizar configurações em tempo real
            body = self._read_body()
            cfg  = self.engine.cfg
            for k, v in body.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
                    logger.info(f"Config atualizada: {k} = {v}")
            self._send_json({"ok": True})

        elif path == "/operar/ativo":
            # Troca o papel da tela Operar: o motor zera e passa a receber o papel novo dali em diante
            from profitdll.bridge import validar_ativo
            if FlowHandler.radar is None:
                self._read_body()
                self._send_json({"error": "trocar o papel só com o radar ligado (--radar)"}, 409)
                return
            try:
                ativo = validar_ativo(str(self._read_body().get("ativo") or ""))
                if not ativo:
                    raise ValueError("papel vazio")
            except (ValueError, json.JSONDecodeError, AttributeError) as e:
                self._send_json({"error": str(e) or "papel inválido"}, 400)
                return
            portao, dll = FlowHandler.portao, self.dll
            with self.engine._lock:
                self.engine.asset = ativo
                self.engine.reset()
                if portao is not None and dll is not None:
                    portao.abrir(ativo)         # o ao vivo espera o histórico do dia do papel novo
            historico = False
            if portao is not None and dll is not None:
                historico = bool(dll.trocar_ativo(ativo))
                if not historico:               # sem DLL no ar: segue ao vivo, sem histórico
                    portao.cancelar()
            logger.info(f"Operar: papel trocado para {ativo}")
            self._send_json({"ativo": ativo, "historico": historico})

        elif path == "/reset":
            self.engine.reset()
            self.rtd.reset()
            self._send_json({"ok": True, "message": "Motor resetado"})

        elif path == "/encerrar":
            self._read_body()
            if FlowHandler.encerrar is None:
                self._send_json({"error": "encerramento pela API não está disponível neste modo"}, 404)
                return
            self._send_json({"ok": True, "message": "encerrando"}, 202)
            threading.Thread(target=FlowHandler.encerrar, daemon=True).start()

        elif path == "/dll/reconectar":
            self._read_body()   # lê o corpo (vazio) antes de responder: senão o cliente vê a conexão anulada
            if self.dll is None:
                self._send_json({"error": "reconectar só existe no modo dll"}, 404)
                return
            with FlowHandler._trava_reconexao:
                if FlowHandler.reconexao["em_andamento"]:
                    self._send_json({"error": "reconexão já em andamento"}, 409)
                    return
                if getattr(self.dll, "ocupado", False):   # conexão inicial do main.py ainda em curso
                    self._send_json({"error": "conexão da ProfitDLL em curso"}, 409)
                    return
                FlowHandler.reconexao = {"em_andamento": True, "ultima": time.time(), "resultado": None}
            threading.Thread(target=FlowHandler._reconectar, args=(self.dll,), daemon=True).start()
            self._send_json({"ok": True, "reconexao": dict(FlowHandler.reconexao)}, 202)

        else:
            self._send_json({"error": "endpoint não encontrado"}, 404)


# ──────────────────────────────────────────────────────────────
# SERVIDOR
# ──────────────────────────────────────────────────────────────

class FlowServer:
    def __init__(self, engine: FlowEngine, host: str = "127.0.0.1", port: int = 5000,
                 modo: str = "manual", fonte=None):
        self.engine  = engine
        self.host    = host
        self.port    = port
        self._server = None
        self._thread = None

        # Injetar referência estática no handler
        FlowHandler.engine = engine
        FlowHandler.rtd    = RTDTradeInferer()
        FlowHandler.dll    = None
        FlowHandler.portao = None
        FlowHandler.encerrar = None
        FlowHandler.modo   = modo
        FlowHandler.fonte  = fonte
        FlowHandler.reconexao = {"em_andamento": False, "ultima": None, "resultado": None}
        FlowHandler.log    = log_memoria.instalar()

    def registrar_radar(self, radar):
        """Expõe o radar de fluxo no GET /api/radar (None desliga)."""
        FlowHandler.radar = radar

    def registrar_leilao(self, painel):
        """Expõe o painel do leilão de abertura no GET /api/leilao (None desliga)."""
        FlowHandler.leilao = painel

    def registrar_encerrar(self, funcao):
        """Função que encerra o processo com a DLL finalizada (POST /encerrar). None desliga a rota."""
        FlowHandler.encerrar = funcao

    def registrar_portao(self, portao):
        """Portão do histórico do dia: a troca de papel da Operar abre um novo download."""
        FlowHandler.portao = portao

    def registrar_dll(self, bridge):
        """Expõe os contadores da ProfitDLL no GET /state (bloco "dll")."""
        FlowHandler.dll = bridge

    def start(self):
        self._server = HTTPServer((self.host, self.port), FlowHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f"Servidor HTTP iniciado em http://{self.host}:{self.port}")
        logger.info(f"Telas: http://{self.host}:{self.port}/operar  (F2 = Conexão)")

    def stop(self):
        if self._server:
            self._server.shutdown()
            logger.info("Servidor HTTP encerrado")
