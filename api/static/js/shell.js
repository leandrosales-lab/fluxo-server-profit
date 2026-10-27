// Cabeçalho, rodapé, tema e atalhos comuns às telas (Operar, Conexão, Radar, Leilão).
import { getJSON, segundosSemResposta } from "./api.js";
import { horaB3 } from "./formato.js";

const CHAVE_TEMA = "fluxo.tema";
const ABAS = [["operar", "Operar", "/operar"], ["conexao", "Conexão", "/conexao"], ["radar", "Radar", "/radar"],
              ["leilao", "Leilão", "/leilao"], ["replay", "Replay", null], ["calibracao", "Calibração", null]];

function temaSalvo() {
  try { const t = localStorage.getItem(CHAVE_TEMA); return t === "claro" || t === "escuro" ? t : null; }
  catch { return null; }
}
function temaDoSistema() { return matchMedia("(prefers-color-scheme: light)").matches ? "claro" : "escuro"; }
export function temaAtual() { return document.documentElement.dataset.tema || temaDoSistema(); }

/** Aplica o tema; com salvar=true guarda a escolha manual. Dispara window "tema" (os gráficos recolorem). */
export function aplicarTema(tema, salvar = false) {
  document.documentElement.dataset.tema = tema;
  if (salvar) { try { localStorage.setItem(CHAVE_TEMA, tema); } catch { /* sem armazenamento: vale nesta visita */ } }
  document.querySelectorAll(".tema button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tema === tema)));
  window.dispatchEvent(new CustomEvent("tema", { detail: tema }));
}

/**
 * Latência = chegada − horário do negócio. Acima de 1 min não é atraso de rede: é um negócio antigo
 * (fora do pregão a DLL entrega o último do dia ao assinar), então não se mostra como latência.
 */
export function latenciaValida(ms) { return ms != null && ms < 60000; }

/**
 * Estado do botão Reconectar.
 * clique = { ate: ms, msg } do último clique nesta tela (ou null). Até `ate`, ele vale mais que o /state:
 * um /state que saiu antes do clique ainda diz "livre", e uma resposta 409 precisa ficar visível.
 */
export function estadoReconectar(dll, clique, agora) {
  const rec = dll.reconexao || {};
  const servidorOcupado = !!rec.em_andamento || !!dll.ocupado;
  const cliqueVale = !!clique && agora < clique.ate;
  const desabilitado = servidorOcupado || (cliqueVale && !clique.msg);
  const texto = !desabilitado ? "Reconectar" : dll.ocupado && !rec.em_andamento ? "conectando…" : "reconectando…";
  const msg = cliqueVale && clique.msg ? clique.msg
    : !servidorOcupado && rec.resultado?.startsWith("falhou") ? rec.resultado : "";
  return { desabilitado, texto, msg };
}

/** Texto do status da ProfitDLL (ou da fonte fora do modo dll) e se é alerta (âmbar vazado). */
export function textoStatus(dll, fonte) {
  if (!dll) return [`fonte: ${fonte || "—"}`, false];
  if (dll.reconexao?.em_andamento) return ["reconectando…", true];
  if (dll.ocupado) return ["conectando…", true];        // conexão inicial ainda em curso
  const market = dll.estados?.market;
  if (dll.conectado && market?.codigo === 6) return ["ProfitDLL conectado (2,6) · callbacks atrasados", true];
  if (dll.conectado) {
    const lat = latenciaValida(dll.latencia_ms) ? ` · ${dll.latencia_ms} ms` : "";
    return [`ProfitDLL conectado (2,${market?.codigo ?? 4})${lat}`, false];
  }
  if (dll.motivo_falha) return [`desconectado — ${dll.motivo_falha}`, true];
  return [`desconectado${market ? ` (2,${market.codigo})` : ""}`, true];
}

export function montarShell(telaAtiva) {
  const topo = document.getElementById("topo");
  topo.className = "topo";
  topo.innerHTML = `
    <span class="marca">Fluxo Server</span>
    <nav>${ABAS.map(([id, nome, href]) => href
      ? `<a class="aba" href="${href}"${id === telaAtiva ? ' aria-current="page"' : ""}>${nome}</a>`
      : `<span class="aba" aria-disabled="true" title="em breve">${nome}</span>`).join("")}</nav>
    <div class="direita">
      <span class="aviso" id="sem-resposta" hidden></span>
      <span class="modo" id="modo"></span>
      <span class="status" id="status"><span class="quadrado" id="status-quadrado"></span><span id="status-texto">—</span></span>
      <span class="relogio" id="relogio">—</span>
      <span class="tema">tema <button data-tema="escuro">escuro</button> / <button data-tema="claro">claro</button></span>
    </div>`;
  const rodape = document.getElementById("rodape");
  rodape.className = "rodape";
  rodape.innerHTML = `<span id="aviso-exemplo"></span>
    <span class="atalhos"><span>F1 Operar</span><span>F2 Conexão</span><span>F3 Radar</span><span>F4 Leilão</span><span>T tema</span></span>
    <span>B3 · horário de Brasília</span>`;

  topo.querySelectorAll(".tema button").forEach((b) => b.addEventListener("click", () => aplicarTema(b.dataset.tema, true)));
  aplicarTema(temaSalvo() || temaDoSistema());
  matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => { if (!temaSalvo()) aplicarTema(temaDoSistema()); });

  document.addEventListener("keydown", (ev) => {
    const alvo = ev.target;
    if (alvo.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(alvo.tagName)) return;
    if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
    if (ev.key === "F1") { ev.preventDefault(); if (telaAtiva !== "operar") location.href = "/operar"; }
    else if (ev.key === "F2") { ev.preventDefault(); if (telaAtiva !== "conexao") location.href = "/conexao"; }
    else if (ev.key === "F3") { ev.preventDefault(); if (telaAtiva !== "radar") location.href = "/radar"; }
    else if (ev.key === "F4") { ev.preventDefault(); if (telaAtiva !== "leilao") location.href = "/leilao"; }
    else if (ev.key === "t" || ev.key === "T") aplicarTema(temaAtual() === "escuro" ? "claro" : "escuro", true);
  });

  const saude = { modo: null, fonte: null, tick_size: null };
  let ultimoNegocio = null;
  getJSON("/health").then((h) => {
    Object.assign(saude, h);
    document.getElementById("modo").innerHTML = h.modo === "replay" ? "<b>replay</b>" : "<b>ao vivo</b>";
    document.getElementById("aviso-exemplo").textContent = h.fonte === "exemplo_petr4.csv"
      ? "Dados de exemplo — pregão gravado para demonstração, não é negociação de hoje" : "";
  }).catch(() => { /* o aviso "sem resposta" cobre */ });

  setInterval(() => {
    const parado = segundosSemResposta();
    const aviso = document.getElementById("sem-resposta");
    aviso.hidden = parado <= 3;
    if (!aviso.hidden) aviso.textContent = `sem resposta do servidor · parado há ${Math.floor(parado)} s`;
    document.getElementById("relogio").textContent =
      saude.modo === "replay" ? horaB3(ultimoNegocio) : horaB3(Date.now() / 1000);
  }, 1000);

  return {
    saude,
    /** Atualiza o status da fonte com o GET /state mais recente. */
    atualizarStatus(estado) {
      const ultimo = estado.recent_trades?.at(-1);
      if (ultimo) ultimoNegocio = ultimo.timestamp;
      const [texto, alerta] = textoStatus(estado.dll, saude.fonte || saude.modo);
      document.getElementById("status-texto").textContent = texto;
      document.getElementById("status").classList.toggle("alerta", alerta);
      document.getElementById("status-quadrado").classList.toggle("vazio", alerta);
    },
  };
}
