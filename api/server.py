"""
API HTTP — Servidor de Sinais para o Profit Pro
================================================
Expõe endpoints REST que o robô NTSL consulta via DDE,
e um dashboard web para monitoramento em tempo real.

Porta padrão: 5000

Endpoints:
  GET  /signal          → sinal atual (BUY/SELL/WAIT/CLOSE)
  GET  /state           → estado completo do motor
  POST /tick            → injetar tick (side obrigatório: C/V; passive_broker opcional)
  POST /rtd             → retrato do RTD do Profit; o servidor infere o tick
  POST /book            → injetar snapshot do book (testes)
  GET  /health          → status do servidor
  GET  /dashboard       → interface web (api/static/dashboard.html com o estado inicial)
  GET  /static/<nome>   → arquivos de api/static/ (ex.: Lightweight Charts)
  GET  /trades?limit=N  → Times & Trades: últimos N negócios (padrão 200, máx. 1000)
  GET  /candles?tf=S&since=T → candles de S segundos (15, 60 ou 300) a partir de T
  GET  /signals?since=T → sinais BUY/SELL novos a partir de T
  GET  /book            → último snapshot do book e a profundidade da fonte (none/top/full)
  GET  /log?since=T&nivel=INFO → log do servidor em memória (credenciais mascaradas)
  POST /config          → atualizar configurações em tempo real
  POST /reset           → reset do motor (início de dia)
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
# ARQUIVOS ESTÁTICOS DO DASHBOARD
# ──────────────────────────────────────────────────────────────

# api/static/dashboard.html: __STATE_JSON__ é trocado pelo estado inicial em GET /dashboard
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

_TIPOS = {
    ".js":    "application/javascript; charset=utf-8",
    ".html":  "text/html; charset=utf-8",
    ".css":   "text/css; charset=utf-8",
    ".json":  "application/json; charset=utf-8",
    ".png":   "image/png",
    ".svg":   "image/svg+xml",
    ".woff2": "font/woff2",
}


def caminho_estatico(nome: str):
    """Caminho de um arquivo direto em STATIC_DIR, ou None (subpasta, '..', tipo não servido)."""
    if not nome or "/" in nome or "\\" in nome or ".." in nome or nome.startswith("."):
        return None
    if os.path.splitext(nome)[1].lower() not in _TIPOS:
        return None
    caminho = os.path.join(STATIC_DIR, nome)
    return caminho if os.path.isfile(caminho) else None



# ──────────────────────────────────────────────────────────────
# HANDLER HTTP
# ──────────────────────────────────────────────────────────────

class FlowHandler(BaseHTTPRequestHandler):
    engine: FlowEngine = None   # referência estática, preenchida no start
    rtd: RTDTradeInferer = None
    dll = None                  # ProfitDLLBridge no modo dll (contadores no /state)
    log: "log_memoria.LogMemoria" = None   # GET /log (tela Conexão)

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

    def _send_html(self, html: str, code: int = 200):
        body = html.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
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
                "time": time.time()
            })

        elif path == "/dashboard":
            arquivo = os.path.join(STATIC_DIR, "dashboard.html")
            try:
                with open(arquivo, encoding="utf-8") as f:
                    modelo = f.read()
            except OSError:
                self._send_bytes("Dashboard indisponível: api/static/dashboard.html não encontrado.\n"
                                 .encode(), "text/plain; charset=utf-8", code=503)
                return
            # "</" escapado: um nome de corretora não consegue fechar o <script>
            html = modelo.replace(
                "__STATE_JSON__",
                json.dumps(self._estado_completo(), ensure_ascii=False).replace("</", "<\\/"))
            self._send_html(html)

        elif path.startswith("/static/"):
            caminho = caminho_estatico(path[len("/static/"):])
            if caminho is None:
                self._send_json({"error": "arquivo não encontrado"}, 404)
                return
            ext = os.path.splitext(caminho)[1].lower()
            with open(caminho, "rb") as f:
                corpo = f.read()
            self._send_bytes(corpo, _TIPOS[ext], "max-age=3600" if ext == ".js" else "no-cache")

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
                registros = self.log.registros(since, qs.get("nivel", ["INFO"])[0])
            except ValueError as e:
                self._send_json({"error": str(e)}, 400)
                return
            self._send_json({"registros": registros})

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
                    ))
                self.engine.update_book(levels)
                self._send_json({"ok": True, "levels": len(levels)})
            except (KeyError, ValueError) as e:
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

        elif path == "/reset":
            self.engine.reset()
            self.rtd.reset()
            self._send_json({"ok": True, "message": "Motor resetado"})

        else:
            self._send_json({"error": "endpoint não encontrado"}, 404)


# ──────────────────────────────────────────────────────────────
# SERVIDOR
# ──────────────────────────────────────────────────────────────

class FlowServer:
    def __init__(self, engine: FlowEngine, host: str = "127.0.0.1", port: int = 5000):
        self.engine  = engine
        self.host    = host
        self.port    = port
        self._server = None
        self._thread = None

        # Injetar referência estática no handler
        FlowHandler.engine = engine
        FlowHandler.rtd    = RTDTradeInferer()
        FlowHandler.dll    = None
        FlowHandler.log    = log_memoria.instalar()

    def registrar_dll(self, bridge):
        """Expõe os contadores da ProfitDLL no GET /state (bloco "dll")."""
        FlowHandler.dll = bridge

    def start(self):
        self._server = HTTPServer((self.host, self.port), FlowHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info(f"Servidor HTTP iniciado em http://{self.host}:{self.port}")
        logger.info(f"Dashboard: http://{self.host}:{self.port}/dashboard")

    def stop(self):
        if self._server:
            self._server.shutdown()
            logger.info("Servidor HTTP encerrado")
