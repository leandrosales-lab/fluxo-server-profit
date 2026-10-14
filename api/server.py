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
from core.rtd import RTDTradeInferer, RTDSnapshot


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
# DASHBOARD HTML (embutido no servidor)
# ──────────────────────────────────────────────────────────────

# Sem meta refresh: a página busca GET /state a cada 1 s e atualiza só os valores.
# __STATE_JSON__ é o estado inicial, injetado pelo handler de /dashboard.
DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#0A0D10">
<link rel="icon" href="data:,">
<title>Fluxo Server</title>
<style>
  /* Tokens da landing (contraste AA verificado): fundo de mesa de operação */
  :root {
    --bg: #0A0D10; --surface: #12171C; --surface-2: #181F26; --card: #1A1A1A; --card-b: #2B2B2B;
    --border: #1F2830; --border-input: #5F6E7C;
    --text: #E1E7EC; --muted: #8E9AA8; --subtle: #7D8A97;
    --accent: #00BCD4; --buy: #00C853; --sell: #F44336; --warn: #FFC107;
    --sans: Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    --mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    --ease: cubic-bezier(.2, .8, .2, 1);
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.5 var(--sans); -webkit-font-smoothing: antialiased; }
  :focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .mono { font-family: var(--mono); }
  header { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;
    padding: 12px 20px; border-bottom: 1px solid var(--border); background: var(--surface); position: sticky; top: 0; z-index: 5; }
  .brand { font: 600 15px var(--mono); display: flex; align-items: center; gap: 10px; }
  .brand .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--buy); box-shadow: 0 0 8px var(--buy); }
  .brand .asset { color: var(--accent); }
  .status { display: flex; align-items: center; gap: 12px; font: 12px var(--mono); color: var(--subtle); }
  .pill { padding: 3px 10px; border-radius: 999px; border: 1px solid var(--border); background: var(--bg); }
  .pill.off { color: var(--sell); border-color: rgba(244, 67, 54, .5); }
  .pill.on { color: var(--buy); border-color: rgba(0, 200, 83, .4); }
  button.pause { width: 30px; height: 30px; border-radius: 50%; border: 1px solid var(--border-input); background: var(--surface-2);
    color: var(--text); cursor: pointer; font-size: 11px; }
  button.pause:hover { border-color: var(--accent); color: var(--accent); }
  main { max-width: 1280px; margin: 0 auto; padding: 16px; }
  .grid { display: grid; gap: 12px; }
  .grid > * { min-width: 0; }
  @media (min-width: 900px) { .g3 { grid-template-columns: 1.05fr 1fr 1fr; } .g2 { grid-template-columns: 1.6fr 1fr; } }
  .card { background: var(--card); border: 1px solid var(--card-b); border-radius: 8px; padding: 16px; }
  .h { display: block; font: 600 11px var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--subtle); margin-bottom: 12px; }
  /* Sinal */
  .sig { border: 2px solid #555; border-radius: 8px; padding: 14px; text-align: center; transition: border-color .3s, background .3s; }
  .sig[data-k="BUY"] { border-color: var(--buy); background: #0D2B0D; }
  .sig[data-k="SELL"] { border-color: var(--sell); background: #2B0D0D; }
  .sig[data-k="CLOSE"] { border-color: var(--warn); background: #2B2B0D; }
  .sig-l { display: block; font: 700 32px var(--mono); letter-spacing: 3px; color: var(--muted); }
  .sig[data-k="BUY"] .sig-l { color: var(--buy); }
  .sig[data-k="SELL"] .sig-l { color: var(--sell); }
  .sig[data-k="CLOSE"] .sig-l { color: var(--warn); }
  .sig-p { display: block; font: 600 16px var(--mono); margin-top: 6px; }
  .sig-s { display: block; font: 12px var(--mono); color: var(--warn); min-height: 1.4em; margin-top: 2px; }
  .conf { display: block; height: 5px; background: #333; border-radius: 3px; margin-top: 10px; overflow: hidden; }
  .conf i { display: block; height: 100%; width: 0; background: linear-gradient(90deg, var(--sell), var(--warn), var(--buy)); transition: width .4s var(--ease); }
  .reason { margin: 12px 0 0; font: 12px/1.6 var(--mono); color: var(--muted); overflow-wrap: anywhere; }
  /* Pressão */
  .bars { display: grid; gap: 8px; margin-bottom: 12px; }
  .bar { position: relative; height: 26px; background: #222; border-radius: 4px; overflow: hidden; }
  .bar i { position: absolute; inset: 0 auto 0 0; width: 0; transition: width .35s var(--ease); }
  .bar.buy i { background: rgba(0, 200, 83, .55); }
  .bar.sell i { background: rgba(244, 67, 54, .55); }
  .bar span { position: relative; display: flex; justify-content: space-between; padding: 0 10px; font: 600 12px/26px var(--mono); }
  dl.kv { display: grid; grid-template-columns: 1fr auto; margin: 0; font: 13px var(--mono); }
  dl.kv dt, dl.kv dd { padding: 4px 0; border-bottom: 1px solid #262626; margin: 0; color: var(--muted); }
  dl.kv dd { text-align: right; color: var(--accent); font-weight: 600; }
  dl.kv dd.pos { color: var(--buy); } dl.kv dd.neg { color: var(--sell); }
  /* Padrões */
  ul.pats { list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; font: 13px/1.5 var(--mono); color: var(--muted); }
  ul.pats li { padding: 8px 10px; border-left: 3px solid var(--warn); background: #202020; border-radius: 0 4px 4px 0; animation: entra .3s var(--ease); }
  ul.pats li.buy { border-left-color: var(--buy); } ul.pats li.sell { border-left-color: var(--sell); } ul.pats li.info { border-left-color: var(--accent); }
  ul.pats li b { color: var(--text); display: block; }
  ul.pats li .tag { font-size: 11px; color: var(--warn); }
  ul.pats .empty { border-left-color: #333; color: var(--subtle); animation: none; }
  @keyframes entra { from { opacity: 0; transform: translateX(8px); } }
  /* Fita */
  .tape { display: flex; gap: 8px; justify-content: flex-end; overflow: hidden; height: 32px; margin: 12px 0;
    -webkit-mask-image: linear-gradient(90deg, transparent, #000 25%); mask-image: linear-gradient(90deg, transparent, #000 25%); }
  .trade { flex: none; font: 500 12.5px var(--mono); white-space: nowrap; padding: 6px 12px; border-radius: 999px; border: 1px solid var(--border);
    background: var(--bg); color: var(--muted); animation: entra-d .35s var(--ease); }
  .trade b { font-weight: 700; } .trade em { font-style: normal; color: var(--text); }
  .trade.buy { border-color: rgba(0, 200, 83, .35); } .trade.buy b { color: var(--buy); }
  .trade.sell { border-color: rgba(244, 67, 54, .35); } .trade.sell b { color: var(--sell); }
  .tape-empty { color: var(--subtle); font: 12px/32px var(--mono); }
  @keyframes entra-d { from { opacity: 0; transform: translateX(24px); } }
  /* Tabelas */
  .tbl { width: 100%; border-collapse: collapse; font: 12.5px var(--mono); }
  .tbl th, .tbl td { padding: 6px 8px; border-bottom: 1px solid #262626; text-align: right; white-space: nowrap; }
  .tbl th { color: var(--subtle); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }
  .tbl td:first-child, .tbl th:first-child { text-align: left; }
  .tbl .buy { color: var(--buy); } .tbl .sell { color: var(--sell); }
  .scroll { overflow-x: auto; }
  footer { max-width: 1280px; margin: 0 auto; padding: 8px 16px 24px; font: 12px var(--mono); color: var(--subtle); }
  @media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }
</style>
</head>
<body>
<header>
  <div class="brand"><span class="dot" aria-hidden="true"></span>fluxo_server <span class="asset" id="asset">—</span></div>
  <div class="status">
    <span class="pill on" id="conn" role="status">ao vivo</span>
    <span id="clock">—</span>
    <button type="button" class="pause" id="pause" aria-label="Pausar atualização">❚❚</button>
  </div>
</header>

<main>
  <div class="grid g3">
    <section class="card" aria-labelledby="h-sig">
      <span class="h" id="h-sig">Sinal atual</span>
      <div class="sig" id="sig" data-k="WAIT">
        <b class="sig-l" id="sig-l">— WAIT</b>
        <span class="sig-p" id="sig-p">aguardando dados</span>
        <span class="sig-s" id="sig-s"></span>
        <span class="conf"><i id="conf"></i></span>
      </div>
      <p class="reason" id="reason"></p>
    </section>

    <section class="card" aria-labelledby="h-flow">
      <span class="h" id="h-flow">Pressão de fluxo</span>
      <div class="bars">
        <div class="bar buy"><i id="b-buy"></i><span>Compra <b id="p-buy">50,0%</b></span></div>
        <div class="bar sell"><i id="b-sell"></i><span>Venda <b id="p-sell">50,0%</b></span></div>
      </div>
      <dl class="kv">
        <dt>Delta acumulado</dt><dd id="d-cum">0</dd>
        <dt id="d-win-l">Delta 30s</dt><dd id="d-win">0</dd>
        <dt>Ticks processados</dt><dd id="ticks">0</dd>
        <dt>Ativo</dt><dd id="asset2">—</dd>
      </dl>
    </section>

    <section class="card" aria-labelledby="h-pat">
      <span class="h" id="h-pat">Padrões detectados</span>
      <ul class="pats" id="pats"><li class="empty">nenhum padrão ativo</li></ul>
    </section>
  </div>

  <div class="tape" id="tape" aria-label="Últimos negócios"><span class="tape-empty">sem negócios recentes</span></div>

  <div class="grid g2">
    <section class="card" aria-labelledby="h-legs">
      <span class="h" id="h-legs">Últimas pernas</span>
      <div class="scroll">
        <table class="tbl">
          <thead><tr><th>Direção</th><th>De</th><th>Até</th><th>Duração</th><th>Vol a favor</th><th>Contra</th><th>Lote</th><th>Delta fim</th></tr></thead>
          <tbody id="legs"><tr><td colspan="8">sem pernas fechadas</td></tr></tbody>
        </table>
      </div>
    </section>
    <section class="card" aria-labelledby="h-src" id="src-card" hidden>
      <span class="h" id="h-src">Fontes de dados</span>
      <dl class="kv" id="src"></dl>
    </section>
  </div>
</main>
<footer>Fluxo Server · projeto de estudo · não é recomendação de investimento</footer>

<script>
(function () {
  var estadoInicial = __STATE_JSON__;
  var pausado = false, timer = null, ultimoTs = 0, ultimoPadroes = '', ultimoLegs = '', ultimoSrc = '';
  var casas = 2;

  function $(id) { return document.getElementById(id); }
  function num(v, d) { return Number(v || 0).toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function preco(v) { return num(v, casas); }
  function sinal(v) { v = Math.round(v || 0); return (v > 0 ? '+' : '') + v.toLocaleString('pt-BR'); }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function setText(el, t) { if (el.textContent !== t) el.textContent = t; }
  function hora(ts) {
    var d = new Date(ts * 1000);
    return d.toLocaleTimeString('pt-BR', { hour12: false, timeZone: 'America/Sao_Paulo' });
  }

  function render(s) {
    if (!s) return;
    var ativo = s.asset || '—';
    if (document.title !== 'Fluxo Server — ' + ativo) document.title = 'Fluxo Server — ' + ativo;
    setText($('asset'), ativo); setText($('asset2'), ativo);

    // Casas decimais: 2 para ações; futuros com preço alto também usam 2 (5406,50)
    var g = s.signal || {};
    var k = g.signal || 'WAIT';
    $('sig').dataset.k = k;
    setText($('sig-l'), k === 'BUY' ? '▲ BUY' : k === 'SELL' ? '▼ SELL' : k === 'CLOSE' ? '✕ CLOSE' : '— WAIT');
    var ativoSinal = k === 'BUY' || k === 'SELL';
    setText($('sig-p'), ativoSinal ? preco(g.price) + '  ·  ' + (g.pattern || '') : (g.price ? 'último ' + preco(g.price) : 'aguardando dados'));
    setText($('sig-s'), ativoSinal ? 'stop ' + preco(g.stop_price) + '  ·  conf ' + Math.round((g.confidence || 0) * 100) + '%' + (g.broker ? '  ·  ' + g.broker : '') : '');
    $('conf').style.width = (ativoSinal ? (g.confidence || 0) * 100 : 0) + '%';
    setText($('reason'), g.reason || '');

    var pb = s.flow_pct_buy == null ? 50 : s.flow_pct_buy, ps = s.flow_pct_sell == null ? 100 - pb : s.flow_pct_sell;
    $('b-buy').style.width = pb + '%'; $('b-sell').style.width = ps + '%';
    setText($('p-buy'), num(pb, 1) + '%'); setText($('p-sell'), num(ps, 1) + '%');
    var dl = s.delta || {};
    [['d-cum', dl.cumulative], ['d-win', dl.window]].forEach(function (p) {
      var el = $(p[0]); setText(el, sinal(p[1])); el.className = (p[1] || 0) >= 0 ? 'pos' : 'neg';
    });
    setText($('d-win-l'), 'Delta ' + Math.round(dl.window_sec || 30) + 's');
    setText($('ticks'), Number(s.tick_count || 0).toLocaleString('pt-BR'));

    // Padrões
    var li = [];
    (s.icebergs_confirmed || []).forEach(function (ic) {
      li.push('<li class="' + (ic.side === 'compra' ? 'buy' : 'sell') + '"><b>Iceberg ' + esc(ic.role || ic.side) + ' · ' + esc(ic.broker) + '</b>' +
        '@ ' + preco(ic.price) + ' · ' + ic.renewals + ' execuções · vol ' + Number(ic.total_vol || 0).toLocaleString('pt-BR') +
        (ic.weak_heuristic ? ' <span class="tag">heurística fraca</span>' : ' · ' + num(ic.vol_ratio, 1) + 'x lote · ' + Math.round((ic.share || 0) * 100) + '% do nível') + '</li>');
    });
    (s.exhaustions || []).forEach(function (e) {
      var topo = e.exhausted_side === 'compra';
      li.push('<li class="' + (topo ? 'sell' : 'buy') + '"><b>Exaustão ' + (topo ? 'no topo' : 'no fundo') + '</b>@ ' + preco(e.extreme_price) +
        ' · vol ' + Math.round((e.vol_ratio || 0) * 100) + '% da média' + (e.delta_divergence ? ' · divergência de delta' : '') + '</li>');
    });
    (s.absorbed_levels || []).forEach(function (a) {
      li.push('<li><b>Absorção</b>@ ' + preco(a.price) + ' · ' + a.touches + ' toques · vol ' + Number(a.volume || 0).toLocaleString('pt-BR') +
        ' · absorvendo ' + esc(a.absorbed_side) + '</li>');
    });
    (s.urgent_brokers || []).forEach(function (u) {
      li.push('<li class="info"><b>Urgência · ' + esc(u.broker) + '</b>' + esc(u.side) + ' em ' + u.levels + ' níveis</li>');
    });
    if ((s.best_ask_brokers || []).length || (s.best_bid_brokers || []).length) {
      li.push('<li class="info"><b>Best offer</b>' +
        (s.best_bid_brokers || []).map(function (b) { return '▲ ' + esc(b); }).concat(
        (s.best_ask_brokers || []).map(function (b) { return '▼ ' + esc(b); })).join(' · ') + '</li>');
    }
    var html = li.length ? li.join('') : '<li class="empty">nenhum padrão ativo</li>';
    if (html !== ultimoPadroes) { $('pats').innerHTML = html; ultimoPadroes = html; }

    // Fita: entram só os negócios mais novos que o último mostrado
    var rt = s.recent_trades || [], tape = $('tape');
    if (rt.length) {
      var vazio = tape.querySelector('.tape-empty'); if (vazio) tape.removeChild(vazio);
      rt.forEach(function (t) {
        if (t.timestamp <= ultimoTs) return;
        ultimoTs = t.timestamp;
        var c = document.createElement('span');
        var compra = t.side === 'compra';
        c.className = 'trade ' + (compra ? 'buy' : 'sell');
        c.innerHTML = '<b>' + (compra ? '▲' : '▼') + '</b> ' + preco(t.price) + ' <em>' + Number(t.qty).toLocaleString('pt-BR') + '</em> ' +
          esc(t.broker) + (t.passive_broker ? ' → ' + esc(t.passive_broker) : '');
        c.title = hora(t.timestamp);
        tape.appendChild(c);
      });
      while (tape.children.length > 12) tape.removeChild(tape.firstChild);
      setText($('clock'), hora(rt[rt.length - 1].timestamp));
    }

    // Pernas
    var legs = (s.legs || []).slice().reverse().map(function (l) {
      var alta = l.direction === 'compra';
      return '<tr><td class="' + (alta ? 'buy' : 'sell') + '">' + (alta ? '▲ alta' : '▼ baixa') + '</td><td>' + preco(l.start_price) + '</td><td>' +
        preco(l.end_price) + '</td><td>' + num(l.duration_sec, 1) + 's</td><td>' + Number(l.vol_with).toLocaleString('pt-BR') + '</td><td>' +
        Number(l.vol_against).toLocaleString('pt-BR') + '</td><td>' + num(l.avg_lot, 1) + '</td><td>' + sinal(l.cum_delta_end) + '</td></tr>';
    }).join('');
    legs = legs || '<tr><td colspan="8">sem pernas fechadas</td></tr>';
    if (legs !== ultimoLegs) { $('legs').innerHTML = legs; ultimoLegs = legs; }

    // Fontes (RTD / DLL), só quando houver atividade
    var src = '';
    var rotulos = { ticks_emitted: 'RTD: negócios inferidos', aggregated_trades: 'RTD: negócios agrupados', side_by_quote: 'RTD: lado pela cotação',
      side_by_tick: 'RTD: lado pela regra do tick', undetermined: 'RTD: sem lado', trades_recebidos: 'DLL: negócios recebidos',
      trades_ignorados: 'DLL: sem agressão', horarios_fallback: 'DLL: horário local (fallback)', book_atualizacoes: 'DLL: atualizações do book',
      fila_pendente: 'DLL: fila pendente' };
    [s.rtd, s.dll].forEach(function (bloco) {
      if (!bloco) return;
      var algum = Object.keys(bloco).some(function (k2) { return typeof bloco[k2] === 'number' && bloco[k2] > 0; }) || bloco.bid || bloco.ask;
      if (!algum && bloco === s.rtd) return;
      Object.keys(bloco).forEach(function (k2) {
        var v = bloco[k2];
        if (k2 === 'bid' || k2 === 'ask') { src += '<dt>DLL: ' + k2 + '</dt><dd>' + (v ? preco(v[0]) + ' × ' + v[1] : '—') + '</dd>'; return; }
        src += '<dt>' + esc(rotulos[k2] || k2) + '</dt><dd>' + Number(v || 0).toLocaleString('pt-BR') + '</dd>';
      });
    });
    $('src-card').hidden = !src;
    if (src !== ultimoSrc) { $('src').innerHTML = src; ultimoSrc = src; }
  }

  function conexao(ok) {
    var el = $('conn');
    el.className = 'pill ' + (ok ? 'on' : 'off');
    setText(el, ok ? (pausado ? 'pausado' : 'ao vivo') : 'servidor fora do ar');
  }

  function buscar() {
    timer = null;
    if (pausado || document.hidden) return;
    fetch('/state', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (s) { conexao(true); render(s); })
      .catch(function () { conexao(false); })
      .then(function () { if (!timer && !pausado && !document.hidden) timer = setTimeout(buscar, 1000); });
  }

  $('pause').addEventListener('click', function () {
    pausado = !pausado;
    this.textContent = pausado ? '▶' : '❚❚';
    this.setAttribute('aria-label', pausado ? 'Continuar atualização' : 'Pausar atualização');
    conexao(true);
    if (!pausado && !timer) buscar();
  });
  document.addEventListener('visibilitychange', function () { if (!document.hidden && !timer && !pausado) buscar(); });

  render(estadoInicial);
  timer = setTimeout(buscar, 1000);
})();
</script>
</body>
</html>"""


# ──────────────────────────────────────────────────────────────
# HANDLER HTTP
# ──────────────────────────────────────────────────────────────

class FlowHandler(BaseHTTPRequestHandler):
    engine: FlowEngine = None   # referência estática, preenchida no start
    rtd: RTDTradeInferer = None
    dll = None                  # ProfitDLLBridge no modo dll (contadores no /state)

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
            state["rtd"] = self.rtd.stats()
            if self.dll is not None:
                state["dll"] = self.dll.stats()
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
            state["rtd"] = self.rtd.stats()
            if self.dll is not None:
                state["dll"] = self.dll.stats()
            # "</" escapado: um nome de corretora não consegue fechar o <script>
            html  = DASHBOARD_HTML.replace(
                "__STATE_JSON__", json.dumps(state, ensure_ascii=False).replace("</", "<\\/")
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
                tick = self.rtd.update(RTDSnapshot.from_dict(body))
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
