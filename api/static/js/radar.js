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
  const [dados, estado] = await Promise.all([
    getJSON(`/api/radar${situacao ? `?situacao=${encodeURIComponent(situacao)}` : ""}`), getJSON("/state")]);
  shell.atualizarStatus(estado);
  const desligado = dados.resumo === null;
  $("radar-vazio").hidden = !desligado && dados.lista.length > 0;
  $("radar-vazio").textContent = desligado ? "Radar desligado — suba o servidor com --radar"
    : "Nenhum iceberg ainda hoje";
  const r = dados.resumo || {};
  for (const [id, chave] of [["r-segurando", "segurando"], ["r-seguraram", "seguraram"], ["r-romperam", "romperam"],
                             ["r-sniper", "viraram_sniper"], ["r-papeis", "papeis"], ["r-negocios", "negocios"]]) {
    $(id).textContent = r[chave] == null ? "—" : inteiro(r[chave]);
  }
  $("radar-meta").textContent = desligado ? "" : `${inteiro(dados.lista.length)} na lista · clique abre o papel na Operar`;
  linhas = dados.lista;
  atualizarLinhas($("lista"), linhas, linhaRadar);
}, 1000);
