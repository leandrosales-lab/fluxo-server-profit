// Tela Operar: laço de 500 ms que alimenta a faixa de cotação, o gráfico e (tarefa 9) os painéis.
import { getJSON, laco } from "./api.js";
import { montarShell } from "./shell.js";
import { criarGrafico } from "./operar-grafico.js";
import { criarPaineis } from "./operar-paineis.js";
import { sinceCandles, precisaLimpar } from "./candles.js";
import { casasDoTick, preco, comSinal, inteiro, financeiro, pct } from "./formato.js";

const $ = (id) => document.getElementById(id);
const shell = montarShell("operar");
const CHAVE_TF = "fluxo.tf";
let casas = 2;
let tickAplicado = null;
const grafico = criarGrafico($("grafico"), casas);
const paineis = criarPaineis();

let sinais = [];
let vistos = new Set();
let ultimoSinalTs = null;
let geracaoVista = null;     // geração do engine na última leitura (muda a cada reset)
const chaveSinal = (s) => `${s.timestamp}|${s.signal}|${s.pattern}|${s.stop_price}`;

function tfSalvo() {
  try { const v = Number(localStorage.getItem(CHAVE_TF)); return [60, 300, 900, 3600].includes(v) ? v : 60; }
  catch { return 60; }
}
function marcarTf(tf) {
  document.querySelectorAll("#tfs [data-tf]").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.tf) === tf)));
}
grafico.trocarTf(tfSalvo());
marcarTf(grafico.tf);
document.querySelectorAll("#tfs [data-tf]").forEach((b) => b.addEventListener("click", () => {
  const tf = Number(b.dataset.tf);
  grafico.trocarTf(tf);
  marcarTf(tf);
  try { localStorage.setItem(CHAVE_TF, String(tf)); } catch { /* vale só nesta visita */ }
}));

function atualizarFaixa(e) {
  const r = e.resumo || {};
  $("f-ativo").textContent = e.asset;
  $("f-fonte").textContent = shell.saude.fonte || "";
  $("f-ultimo").textContent = preco(r.ultimo, casas);
  const variacao = r.ultimo != null && r.abertura ? r.ultimo - r.abertura : null;
  $("f-var").className = `valor ${variacao > 0 ? "compra" : variacao < 0 ? "venda" : ""}`;
  $("f-var").textContent = comSinal(variacao, (v) => preco(v, casas));
  $("f-var-pct").textContent = variacao == null ? "desde a abertura"
    : `${comSinal(100 * variacao / r.abertura, (v) => pct(v, 2))} desde a abertura`;
  const d = r.ultimo == null ? null : e.delta?.cumulative;
  $("f-delta").className = `valor ${d > 0 ? "compra" : d < 0 ? "venda" : ""}`;
  $("f-delta").textContent = comSinal(d);
  $("f-fin").textContent = financeiro(r.volume_financeiro);
  $("f-vwap").textContent = preco(r.vwap, casas);
  $("f-vwap-dist").textContent = r.vwap && r.ultimo != null
    ? `preço ${pct(Math.abs(100 * (r.ultimo - r.vwap) / r.vwap), 2)} ${r.ultimo >= r.vwap ? "acima" : "abaixo"}` : "";
  const compra = r.agressao_compra_pct == null ? null : Math.round(r.agressao_compra_pct);
  $("f-agr").textContent = compra == null ? "—" : `${compra}/${100 - compra}`;
  $("f-npm").textContent = r.negocios_por_min == null ? "—" : `${inteiro(r.negocios_por_min)}/min`;
  $("f-maxmin").textContent = r.maxima == null ? "—" : `${preco(r.maxima, casas)} · ${preco(r.minima, casas)}`;
  $("f-abert").textContent = `${preco(r.abertura, casas)} · —`;   // ajuste anterior: sem fonte ainda
}

async function passo() {
  const estado = await getJSON("/state");
  shell.atualizarStatus(estado);
  const tick = shell.saude.tick_size;
  if (tick && tick !== tickAplicado) {     // o /health chega depois do 1º /state
    tickAplicado = tick;
    casas = casasDoTick(tick);
    grafico.definirCasas(casas, tick);
  }

  // POST /reset ou virada do dia: começa do zero sem recarregar. Pela geração, e não por "ficou vazio":
  // com o mercado rodando, o /state seguinte ao reset já chega com negócios novos.
  if (precisaLimpar(geracaoVista, estado.geracao)) {
    grafico.limpar();
    sinais = []; vistos = new Set(); ultimoSinalTs = null;
  }
  geracaoVista = estado.geracao;
  atualizarFaixa(estado);

  const tfPedido = grafico.tf;
  const since = sinceCandles(grafico.ultimoTempo(), tfPedido);
  const c = await getJSON(`/candles?tf=${tfPedido}${since != null ? `&since=${since}` : ""}`);
  if (tfPedido === grafico.tf) grafico.juntar(c.candles);   // troca de tf no meio do pedido: descarta
  const u = grafico.ultimoCandle();
  $("ohlc").textContent = u ? `A ${preco(u.open, casas)}   M ${preco(u.high, casas)}   m ${preco(u.low, casas)}   F ${preco(u.close, casas)}` : "";

  const s = await getJSON(`/signals${ultimoSinalTs != null ? `?since=${ultimoSinalTs}` : ""}`);
  const novos = s.signals.filter((x) => !vistos.has(chaveSinal(x)));
  if (novos.length) {
    novos.forEach((x) => vistos.add(chaveSinal(x)));
    sinais = sinais.concat(novos);
    ultimoSinalTs = sinais[sinais.length - 1].timestamp;
  }

  const [tr, book] = await Promise.all([getJSON("/trades?limit=40"), getJSON("/book")]);
  // "agora": no replay é a hora do último negócio; ao vivo, o relógio
  const ultimo = estado.recent_trades?.at(-1);
  const agora = shell.saude.modo === "replay" && ultimo ? ultimo.timestamp : Date.now() / 1000;
  paineis.atualizar({ estado, sinais, trades: tr.trades, book, casas, agora, tf: grafico.tf });
}

laco(passo, 500);
