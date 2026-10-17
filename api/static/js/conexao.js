// Tela Conexão: estados da ProfitDLL, negócios/s, contadores, configuração, log e Reconectar.
import { getJSON, postJSON, laco } from "./api.js";
import { montarShell, latenciaValida, estadoReconectar } from "./shell.js";
import { atualizarLinhas } from "./tabela.js";
import { inteiro, horaB3, hm } from "./formato.js";

const $ = (id) => document.getElementById(id);
const shell = montarShell("conexao");
const LW = window.LightweightCharts;
const cor = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
const JANELA_S = 15 * 60;
const NIVEL = { INFO: "info", WARNING: "aviso", ERROR: "erro", CRITICAL: "erro" };

// ── Negócios por segundo (só no modo dll), calculado no navegador
let grafico = null, linha = null, faixa = null;
let pontos = [], marcas26 = [], anterior = null;

function criarGrafico() {
  grafico = LW.createChart($("grafico-nps"), { autoSize: true });
  linha = grafico.addSeries(LW.LineSeries, { lineWidth: 1, priceLineVisible: false });
  faixa = grafico.addSeries(LW.HistogramSeries, { priceScaleId: "faixa", priceLineVisible: false, lastValueVisible: false });
  grafico.priceScale("faixa").applyOptions({ visible: false, scaleMargins: { top: 0, bottom: 0 } });
  window.addEventListener("tema", aplicarCores);
  aplicarCores();
}
function aplicarCores() {
  grafico.applyOptions({
    layout: { background: { type: "solid", color: cor("--bg") }, textColor: cor("--faint"), fontFamily: "IBM Plex Mono", fontSize: 11 },
    grid: { vertLines: { color: cor("--grid") }, horzLines: { color: cor("--grid") } },
    rightPriceScale: { borderColor: cor("--rule") },
    timeScale: { borderColor: cor("--rule"), timeVisible: true, secondsVisible: false, tickMarkFormatter: (t) => hm(t) },
    localization: { locale: "pt-BR", timeFormatter: (t) => horaB3(t) },
  });
  linha.applyOptions({ color: cor("--text") });
  faixa.applyOptions({ color: cor("--faixa-26") });
  faixa.setData(marcas26.map((t) => ({ time: t, value: 1 })));
}
function registrarAmostra(dll) {
  const t = Math.floor(Date.now() / 1000);
  if (anterior && t <= anterior.t) return;          // uma amostra por segundo
  if (anterior) {
    pontos.push({ time: t, value: Math.max(0, (dll.trades_recebidos - anterior.recebidos) / (t - anterior.t)) });
    if (dll.avisos_partial > anterior.avisos) {
      marcas26.push(t);
      $("faixa-26").hidden = false;
      $("faixa-26").textContent = `(2,6) callbacks atrasados · ${horaB3(t)} · ${inteiro(dll.avisos_partial)} aviso(s) hoje`;
    }
    pontos = pontos.filter((p) => p.time >= t - JANELA_S);
    marcas26 = marcas26.filter((m) => m >= t - JANELA_S);
    linha.setData(pontos);
    faixa.setData(marcas26.map((m) => ({ time: m, value: 1 })));
  }
  anterior = { t, recebidos: dll.trades_recebidos, avisos: dll.avisos_partial };
}

// ── Faixa de estados e Reconectar
function faixaEstados(dll) {
  const rec = { ...(dll.reconexao || {}) };
  const reconectando = !!rec.em_andamento;
  if (dll.ocupado) rec.em_andamento = true;        // conexão inicial em curso: botão desabilitado também
  const [texto, detalhe] = rec.em_andamento
    ? [reconectando ? "Reconectando…" : "Conectando…", "aguardando login, ativação e market data"]
    : dll.conectado ? ["Conectado", `${dll.ativo} · bolsa ${dll.bolsa}`]
    : ["Desconectado", dll.motivo_falha || "sem conexão com a ProfitDLL"];
  $("c-agregado").textContent = texto;
  $("c-agregado").classList.toggle("ambar", !dll.conectado || !!rec.em_andamento);
  $("c-agregado-det").textContent = detalhe;
  for (const [id, tipo, chave] of [["c-login", 0, "login"], ["c-ativacao", 3, "ativacao"], ["c-market", 2, "market"]]) {
    const e = dll.estados?.[chave];
    $(id).textContent = e ? e.nome : "—";
    $(`${id}-cod`).textContent = ` (${tipo},${e ? e.codigo : "—"})`;
  }
  $("c-latencia").textContent = latenciaValida(dll.latencia_ms) ? `${inteiro(dll.latencia_ms)} ms`
    : dll.latencia_ms != null ? "sem negócio recente" : "—";
  ultimaDll = dll;
  desenharBotao();
}

// Último clique em Reconectar nesta tela: { ate: ms, msg } (ver estadoReconectar no shell.js)
let clique = null, ultimaDll = null;
function desenharBotao() {
  if (!ultimaDll) return;
  const { desabilitado, texto, msg } = estadoReconectar(ultimaDll, clique, Date.now());
  const botao = $("reconectar");
  botao.hidden = false;
  botao.disabled = desabilitado;
  botao.textContent = texto;
  $("reconectar-msg").textContent = msg;
}
$("reconectar").addEventListener("click", async () => {
  clique = { ate: Date.now() + 3000, msg: null };   // até o /state confirmar a reconexão
  desenharBotao();
  try {
    const { status, dados } = await postJSON("/dll/reconectar");
    if (status !== 202) clique = { ate: Date.now() + 5000, msg: dados.error || `falhou: HTTP ${status}` };
  } catch {
    clique = { ate: Date.now() + 5000, msg: "falhou: servidor sem resposta" };
  }
  desenharBotao();
});

function semDll(fonte) {
  $("c-agregado").textContent = "Sem ProfitDLL";
  $("c-agregado").classList.remove("ambar");
  $("c-agregado-det").textContent = `fonte: ${fonte || "—"}`;
  $("reconectar").hidden = true;
  $("grafico-nps").hidden = true;
  $("nps-vazio").hidden = false;
  $("contadores-meta").textContent = "os contadores da DLL só existem no modo dll";
  atualizarLinhas($("contadores"), [], () => ({ celulas: [] }));
}

// ── Contadores, edição e configuração
function contadores(dll) {
  const tipos = Object.entries(dll.ignorados_por_tipo || {}).map(([k, v]) => `${k} ${inteiro(v)}`).join(" · ");
  const linhas = [
    ["Negócios recebidos", dll.trades_recebidos, ""],
    ["Editados (TC_IS_EDIT), descartados", dll.trades_editados, ""],
    ["Ignorados sem agressão", dll.trades_ignorados, tipos],
    ["Horário local (TradeDate ausente)", dll.horarios_fallback, ""],
    ["Quedas do market data", dll.quedas_market, ""],
    ["Avisos (2,6)", dll.avisos_partial, ""],
    ["Fila pendente", dll.fila_pendente, ""],
    ["Atualizações do livro", dll.book_atualizacoes, ""],
  ];
  $("contadores-meta").textContent = "acumulam no dia, inclusive entre reconexões";
  atualizarLinhas($("contadores"), linhas, ([rotulo, valor, nota]) => ({
    celulas: [{ t: rotulo }, { t: inteiro(valor), c: "num" }, { t: nota, c: "faint" }] }));
  $("edicao").hidden = !dll.trades_editados;
  if (dll.trades_editados) $("edicao").textContent = `${inteiro(dll.trades_editados)} correções de negócio hoje — descartadas`;
  atualizarLinhas($("config"), [["PROFITDLL_PATH", dll.dll_path || "padrão"], ["Ativo", dll.ativo], ["Bolsa", dll.bolsa]],
    ([k, v]) => ({ celulas: [{ t: k }, { t: v || "—" }] }));
}

// ── Log (acumula no navegador; o servidor guarda os últimos 500)
let registros = [], ultimoLog = null, filtroLog = "todos";
document.querySelectorAll("#log-filtros [data-nivel]").forEach((b) => b.addEventListener("click", () => {
  filtroLog = b.dataset.nivel;
  document.querySelectorAll("#log-filtros [data-nivel]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  desenharLog();
}));
function desenharLog() {
  const visiveis = registros.filter((x) => filtroLog === "todos" || NIVEL[x.nivel] === filtroLog).reverse();
  atualizarLinhas($("log"), visiveis, (x) => {
    const nivel = NIVEL[x.nivel] || x.nivel.toLowerCase();
    return { classe: nivel === "erro" ? "destaque" : "",
      celulas: [{ t: horaB3(x.ts), c: "faint" }, { t: nivel, c: nivel === "info" ? "muted" : "ambar" },
                { t: x.origem, c: "faint" }, { t: x.msg }] };
  });
  $("log-meta").textContent = `${inteiro(registros.length)} eventos guardados · mais recentes primeiro`;
}
async function buscarLog() {
  // por seq, não por horário: registros com o mesmo instante ou fora de ordem não se perdem
  let r = await getJSON(`/log${ultimoLog != null ? `?apos=${ultimoLog}` : ""}`);
  if (ultimoLog != null && r.ultimo_seq < ultimoLog) {   // servidor reiniciado: o seq recomeçou do 1
    registros = [];
    ultimoLog = null;
    r = await getJSON("/log");
  }
  if (r.registros.length) {
    registros = registros.concat(r.registros).slice(-500);
    ultimoLog = registros[registros.length - 1].seq;
  }
  desenharLog();
}

laco(async () => {
  const estado = await getJSON("/state");
  shell.atualizarStatus(estado);
  if (estado.dll) {
    if (!grafico) criarGrafico();
    faixaEstados(estado.dll);
    registrarAmostra(estado.dll);
    contadores(estado.dll);
  } else {
    semDll(shell.saude.fonte);
  }
  await buscarLog();
}, 500);
