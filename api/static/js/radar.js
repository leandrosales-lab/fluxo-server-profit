// Tela Radar: icebergs do dia em todas as ações (GET /api/radar); clique na linha troca o papel da Operar.
import { getJSON, postJSON, laco } from "./api.js";
import { montarShell } from "./shell.js";
import { atualizarLinhas } from "./tabela.js";
import { inteiro } from "./formato.js";
import { linhaRadar } from "./radar-lista.js";

const $ = (id) => document.getElementById(id);
const shell = montarShell("radar");

let situacao = "";
let linhas = [];
let agora = null;     // relógio dos dados (hora do último negócio/giro visto pelo radar)
const CHAVE_JANELA = "fluxo.radarJanela";
let janela = "";      // segundos como texto: "120" (2 min), "300" (5 min) ou "" (dia inteiro)
try { const v = localStorage.getItem(CHAVE_JANELA); if (v === "120" || v === "300") janela = v; } catch { /* padrão: dia */ }
function marcarJanela() {
  document.querySelectorAll("#janelas [data-janela]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.janela === janela)));
}
marcarJanela();
document.querySelectorAll("#janelas [data-janela]").forEach((b) => b.addEventListener("click", () => {
  janela = b.dataset.janela;
  marcarJanela();
  try { localStorage.setItem(CHAVE_JANELA, janela); } catch { /* vale só nesta visita */ }
}));
document.querySelectorAll("#filtros [data-sit]").forEach((b) => b.addEventListener("click", () => {
  situacao = b.dataset.sit;
  document.querySelectorAll("#filtros [data-sit]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
}));

$("lista").addEventListener("click", async (ev) => {
  const tr = ev.target.closest("tr");
  const r = tr && linhas[tr.rowIndex];
  if (!r) return;
  const { status } = await postJSON("/operar/ativo", { ativo: r.ativo });
  if (status < 400) location.href = "/operar";
});

laco(async () => {
  const params = new URLSearchParams();
  if (situacao) params.set("situacao", situacao);
  if (janela) params.set("janela", janela);
  const [dados, estado] = await Promise.all([
    getJSON(`/api/radar${params.size ? `?${params}` : ""}`), getJSON("/state")]);
  shell.atualizarStatus(estado);
  const desligado = dados.resumo === null;
  $("radar-vazio").hidden = !desligado && dados.lista.length > 0;
  $("radar-vazio").textContent = desligado ? "Radar desligado — suba o servidor com --radar"
    : janela ? `Nenhum iceberg com giro nos últimos ${janela === "120" ? 2 : 5} min` : "Nenhum iceberg ainda hoje";
  const r = dados.resumo || {};
  for (const [id, chave] of [["r-segurando", "segurando"], ["r-seguraram", "seguraram"], ["r-romperam", "romperam"],
                             ["r-sniper", "viraram_sniper"], ["r-papeis", "papeis"], ["r-negocios", "negocios"]]) {
    $(id).textContent = r[chave] == null ? "—" : inteiro(r[chave]);
  }
  $("radar-meta").textContent = desligado ? "" : `${inteiro(dados.lista.length)} na lista · clique abre o papel na Operar`;
  linhas = dados.lista;
  agora = dados.agora || null;
  atualizarLinhas($("lista"), linhas, (x) => linhaRadar(x, agora));
}, 1000);
