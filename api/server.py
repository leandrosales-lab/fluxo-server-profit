"""
API HTTP — Servidor de Sinais para o Profit Pro
================================================
Expõe endpoints REST que o robô NTSL consulta via DDE,
e um dashboard web para monitoramento em tempo real.

Porta padrão: 5000

Endpoints:
  GET  /signal          → sinal atual (BUY/SELL/WAIT/CLOSE)
  GET  /state           → estado completo do motor
  POST /tick            → injetar tick manualmente (testes)
  POST /book            → injetar snapshot do book (testes)
  GET  /health          → status do servidor
  GET  /dashboard       → interface web de monitoramento
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

logger = logging.getLogger("API")


# ──────────────────────────────────────────────────────────────
# DASHBOARD HTML (embutido no servidor)
# ──────────────────────────────────────────────────────────────

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="2">
<title>Robô Leitura de Fluxo — Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d0d0d; color: #e0e0e0; font-family: 'Consolas', monospace; padding: 16px; }
  h1 { color: #00bcd4; font-size: 1.4rem; border-bottom: 1px solid #333; padding-bottom: 8px; margin-bottom: 16px; }
  .grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; }
  .card { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 16px; }
  .card h2 { font-size: 0.85rem; color: #888; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 1px; }
  .signal-box { text-align: center; padding: 24px; border-radius: 8px; }
  .signal-BUY   { background: #0d2b0d; border: 2px solid #00c853; }
  .signal-SELL  { background: #2b0d0d; border: 2px solid #f44336; }
  .signal-WAIT  { background: #1a1a1a; border: 2px solid #555; }
  .signal-CLOSE { background: #2b2b0d; border: 2px solid #ffd600; }
  .signal-label { font-size: 3rem; font-weight: bold; letter-spacing: 4px; }
  .signal-BUY   .signal-label { color: #00c853; }
  .signal-SELL  .signal-label { color: #f44336; }
  .signal-WAIT  .signal-label { color: #888; }
  .signal-CLOSE .signal-label { color: #ffd600; }
  .signal-price { font-size: 1.5rem; margin-top: 8px; color: #fff; }
  .signal-stop  { font-size: 0.9rem; margin-top: 4px; color: #f44336; }
  .signal-broker { font-size: 0.85rem; margin-top: 4px; color: #888; }
  .signal-conf  { font-size: 0.9rem; margin-top: 8px; color: #ffd600; }
  .reason       { font-size: 0.8rem; color: #aaa; margin-top: 12px; line-height: 1.5; }
  .flow-bars    { display: flex; gap: 8px; align-items: flex-end; height: 80px; }
  .bar          { flex: 1; border-radius: 4px 4px 0 0; transition: height 0.3s; position: relative; }
  .bar-buy      { background: #00c853; }
  .bar-sell     { background: #f44336; }
  .bar-label    { text-align: center; font-size: 0.75rem; margin-top: 4px; }
  .bar-pct      { text-align: center; font-size: 1.1rem; font-weight: bold; }
  .badge        { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; margin: 2px; }
  .badge-green  { background: #0d2b0d; color: #00c853; border: 1px solid #00c853; }
  .badge-red    { background: #2b0d0d; color: #f44336; border: 1px solid #f44336; }
  .badge-yellow { background: #2b2b0d; color: #ffd600; border: 1px solid #ffd600; }
  .badge-blue   { background: #0d1f2b; color: #00bcd4; border: 1px solid #00bcd4; }
  .list-item    { padding: 6px 0; border-bottom: 1px solid #222; font-size: 0.8rem; }
  .list-item:last-child { border-bottom: none; }
  .ts           { color: #555; font-size: 0.7rem; }
  .conf-bar     { height: 6px; background: #333; border-radius: 3px; margin-top: 6px; }
  .conf-fill    { height: 100%; border-radius: 3px; background: linear-gradient(90deg, #f44336, #ffd600, #00c853); }
  .stat         { display: flex; justify-content: space-between; padding: 4px 0; font-size: 0.85rem; border-bottom: 1px solid #222; }
  .stat:last-child { border-bottom: none; }
  .stat-val     { color: #00bcd4; font-weight: bold; }
  footer        { margin-top: 24px; text-align: center; color: #444; font-size: 0.75rem; }
  .blink        { animation: blink 1s infinite; }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.3} }
</style>
</head>
<body>
<h1>📊 Robô Leitura de Fluxo — Dashboard em Tempo Real <span class="ts">(atualiza a cada 2s)</span></h1>
<div class="grid" id="main"></div>
<footer>Fluxo Server v1.0 | Sociedade dos Traders | Atualizado: <span id="ts"></span></footer>
<script>
const data = __STATE_JSON__;

function pct(n) { return Math.round(n); }

function renderSignal(sig) {
  const cls = `signal-${sig.signal}`;
  const icon = {BUY:'▲', SELL:'▼', WAIT:'—', CLOSE:'✕'}[sig.signal] || '?';
  return `<div class="card">
    <h2>🎯 Sinal Atual</h2>
    <div class="signal-box ${cls}">
      <div class="signal-label">${icon} ${sig.signal}</div>
      <div class="signal-price">R$ ${sig.price?.toFixed(2) || '—'}</div>
      <div class="signal-stop">Stop: R$ ${sig.stop_price?.toFixed(2) || '—'}</div>
      <div class="signal-broker">${sig.broker || '—'}</div>
      <div class="signal-conf">${sig.pattern} | Confiança: ${pct(sig.confidence*100)}%</div>
      <div class="conf-bar"><div class="conf-fill" style="width:${pct(sig.confidence*100)}%"></div></div>
      <div class="reason">${sig.reason || ''}</div>
    </div>
  </div>`;
}

function renderFlow(s) {
  const buy = s.flow_pct_buy || 50;
  const sell = s.flow_pct_sell || 50;
  const dom = buy > sell ? 'COMPRA' : 'VENDA';
  const domColor = buy > sell ? '#00c853' : '#f44336';
  return `<div class="card">
    <h2>📈 Pressão de Fluxo</h2>
    <div class="flow-bars">
      <div style="flex:1;text-align:center">
        <div class="bar bar-buy" style="height:${buy*0.7}px;margin:0 auto;max-width:80px"></div>
        <div class="bar-label" style="color:#00c853">COMPRA</div>
        <div class="bar-pct" style="color:#00c853">${buy.toFixed(1)}%</div>
      </div>
      <div style="flex:1;text-align:center">
        <div class="bar bar-sell" style="height:${sell*0.7}px;margin:0 auto;max-width:80px"></div>
        <div class="bar-label" style="color:#f44336">VENDA</div>
        <div class="bar-pct" style="color:#f44336">${sell.toFixed(1)}%</div>
      </div>
    </div>
    <div style="text-align:center;margin-top:12px;font-size:1.1rem;color:${domColor};font-weight:bold">
      Dominante: ${dom}
    </div>
    <div style="margin-top:12px">
      <div class="stat"><span>Ticks processados</span><span class="stat-val">${s.tick_count?.toLocaleString()}</span></div>
      <div class="stat"><span>Ativo</span><span class="stat-val">${s.asset}</span></div>
    </div>
  </div>`;
}

function renderPatterns(s) {
  let html = '<div class="card"><h2>🧠 Padrões Detectados</h2>';

  if (s.icebergs_confirmed?.length) {
    html += '<div style="margin-bottom:12px"><b style="color:#00bcd4">🧊 Icebergs Confirmados</b>';
    s.icebergs_confirmed.forEach(ic => {
      const cls = ic.side === 'compra' ? 'badge-green' : 'badge-red';
      html += `<div class="list-item">
        <span class="badge ${cls}">${ic.side === 'compra' ? '▲' : '▼'} ${ic.side.toUpperCase()}</span>
        <b>${ic.broker}</b> @ R$ ${ic.price?.toFixed(2)}
        | ${ic.renewals} renovações | ${ic.total_vol?.toLocaleString()} vol
      </div>`;
    });
    html += '</div>';
  } else {
    html += '<div class="list-item" style="color:#555">Nenhum Iceberg ativo</div>';
  }

  if (s.urgent_brokers?.length) {
    html += '<div style="margin-bottom:12px"><b style="color:#ffd600">⚡ Urgência</b>';
    s.urgent_brokers.forEach(u => {
      html += `<div class="list-item">
        <span class="badge badge-yellow">URGÊNCIA</span>
        <b>${u.broker}</b> — ${u.side} em ${u.levels} níveis
      </div>`;
    });
    html += '</div>';
  }

  if (s.absorbed_levels?.length) {
    html += '<div><b style="color:#888">🛡️ Absorção</b>';
    s.absorbed_levels.forEach(a => {
      html += `<div class="list-item">
        Nível R$ ${a.price?.toFixed(2)} — ${a.touches} toques
      </div>`;
    });
    html += '</div>';
  }

  if (s.best_ask_brokers?.length || s.best_bid_brokers?.length) {
    html += '<div style="margin-top:8px"><b style="color:#888">📌 Best Offer</b><br>';
    (s.best_ask_brokers || []).forEach(b => {
      html += `<span class="badge badge-red" title="Best Ask (venda)">▼ ${b}</span>`;
    });
    (s.best_bid_brokers || []).forEach(b => {
      html += `<span class="badge badge-green" title="Best Bid (compra)">▲ ${b}</span>`;
    });
    html += '</div>';
  }

  html += '</div>';
  return html;
}

document.getElementById('main').innerHTML =
  renderSignal(data.signal) + renderFlow(data) + renderPatterns(data);
document.getElementById('ts').textContent = new Date().toLocaleTimeString('pt-BR');
</script>
</body>
</html>"""


# ──────────────────────────────────────────────────────────────
# HANDLER HTTP
# ──────────────────────────────────────────────────────────────

class FlowHandler(BaseHTTPRequestHandler):
    engine: FlowEngine = None   # referência estática, preenchida no start

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
        path = urlparse(self.path).path

        if path == "/signal":
            sig = self.engine.get_signal()
            self._send_json(sig.to_dict())

        elif path == "/state":
            state = self.engine.get_state()
            self._send_json(state)

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
            state = self.engine.get_state()
            html  = DASHBOARD_HTML.replace(
                "__STATE_JSON__", json.dumps(state, ensure_ascii=False)
            )
            self._send_html(html)

        else:
            self._send_json({"error": "endpoint não encontrado"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/tick":
            # Injetar tick manualmente (para testes ou integração via DDE)
            body = self._read_body()
            try:
                side = Side.BUY if body.get("side", "C").upper() in ("C", "BUY") else Side.SELL
                tick = Tick(
                    timestamp = body.get("timestamp", time.time()),
                    price     = float(body["price"]),
                    qty       = int(body["qty"]),
                    broker    = str(body.get("broker", "DESCONHECIDA")),
                    side      = side,
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
                    side = Side.BUY if row.get("side", "C").upper() in ("C", "BUY") else Side.SELL
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
