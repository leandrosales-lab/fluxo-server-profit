// Tela Leilão: papéis do leilão de abertura (GET /api/leilao) e o book do papel escolhido.
import { getJSON, laco } from "./api.js";
import { montarShell } from "./shell.js";
import { atualizarLinhas } from "./tabela.js";
import { inteiro, pct, preco } from "./formato.js";
import { linhaLeilao, filtrarLeilao, linhasEscada, linhaEvento, contagem, seta, qtdCurta } from "./leilao-lista.js";

const $ = (id) => document.getElementById(id);
const shell = montarShell("leilao");

// Filtros e papel escolhido: conveniência desta visita (sem armazenamento, valem os padrões)
const CHAVE = "fluxo.leilao";
let pref = { filtro: "", liq: "0", visao: "sobra", ativo: "" };
try { pref = { ...pref, ...JSON.parse(localStorage.getItem(CHAVE) || "{}") }; } catch { /* padrões */ }
function salvar() { try { localStorage.setItem(CHAVE, JSON.stringify(pref)); } catch { /* vale só nesta visita */ } }

function grupo(sel, attr, chave) {
  const botoes = document.querySelectorAll(`${sel} [data-${attr}]`);
  const marcar = () => botoes.forEach((b) => b.setAttribute("aria-pressed", String(b.dataset[attr] === pref[chave])));
  botoes.forEach((b) => b.addEventListener("click", () => { pref[chave] = b.dataset[attr]; marcar(); salvar(); passo(); }));
  marcar();
}
grupo("#filtros", "filtro", "filtro");
grupo("#liquidez", "liq", "liq");
grupo("#visoes", "visao", "visao");

let visiveis = [];
$("lista").addEventListener("click", (ev) => {
  const tr = ev.target.closest("tr");
  const r = tr && visiveis[tr.rowIndex];
  if (!r) return;
  pref.ativo = r.ativo;
  salvar();
  passo();
});

let ativoDaEscada = null;
function escada(book) {
  const corpo = $("escada");
  const linhas = linhasEscada(book?.niveis);
  corpo.innerHTML = "";
  for (const l of linhas) {
    const tr = corpo.insertRow();
    tr.className = l.classe;
    tr.innerHTML = `<td class="corr"></td><td class="num q c" style="--w:${l.wCompra}%"></td><td class="preco mono"></td>`
      + `<td class="num q v" style="--w:${l.wVenda}%"></td><td class="corr dir"></td>`;
    [l.corrCompra, l.compra, l.preco, l.venda, l.corrVenda].forEach((t, i) => { tr.cells[i].textContent = t; });
  }
  // Papel novo: centraliza o teórico (depois a rolagem fica com quem está olhando)
  if (book && book.ativo !== ativoDaEscada) {
    ativoDaEscada = book.ativo;
    const t = corpo.querySelector("tr.teorico");
    const caixa = $("escada-rolagem");
    if (t) caixa.scrollTop = t.offsetTop - caixa.clientHeight / 2;
  }
}

function resumoBook(b) {
  $("book-titulo").textContent = b ? `Book · ${b.ativo}` : "Book";
  const s = seta(b?.pressao ?? 0);
  $("b-seta").textContent = s.t;
  $("b-seta").className = `seta-grande ${s.c}`;
  $("b-teorico").textContent = b ? preco(b.teorico) : "—";
  $("b-qtd").textContent = b?.qtd_teorica ? `${qtdCurta(b.qtd_teorica)} casados` : "";
  $("b-sobra").textContent = b?.sobra_lado ? `${qtdCurta(b.sobra_qtd)} ${b.sobra_lado}` : "—";
  $("b-sobra").className = `mono ${b?.sobra_lado || ""}`;
  $("b-banda").textContent = b ? `${qtdCurta(b.banda_compra)} × ${qtdCurta(b.banda_venda)}` : "—";
  $("book-meta").textContent = b ? `${b.fase} · ${inteiro(b.ordens)} ordens · tendência ${b.tendencia}` : "";
}

let rodando = false;
async function passo() {
  if (rodando) return;
  rodando = true;
  try {
    const params = new URLSearchParams({ visao: pref.visao });
    if (pref.ativo) params.set("ativo", pref.ativo);
    const [dados, estado] = await Promise.all([getJSON(`/api/leilao?${params}`), getJSON("/state")]);
    shell.atualizarStatus(estado);
    const desligado = dados.resumo === null;
    const r = dados.resumo || {};
    $("l-abre").textContent = contagem(dados.agora, dados.abertura_prevista);
    $("l-fase").textContent = dados.agora != null && dados.abertura_prevista != null && dados.agora < dados.abertura_prevista
      ? "Abre em" : "Abertura";
    for (const [id, chave] of [["l-em-leilao", "em_leilao"], ["l-desbal-c", "desbal_compra"], ["l-desbal-v", "desbal_venda"], ["l-perfil", "no_perfil"]]) {
      $(id).textContent = r[chave] == null ? "—" : inteiro(r[chave]);
    }
    $("l-regra").textContent = desligado ? "—" : `${String(dados.razao_min).replace(".", ",")}× · banda ±${pct(100 * dados.banda, 0)}`;
    $("l-fonte").textContent = desligado ? "—" : dados.fonte === "simulado" ? "simulado" : "ProfitDLL";
    $("l-fonte").className = `valor ${dados.fonte === "simulado" ? "ambar" : ""}`;
    $("rodape").querySelector("#aviso-exemplo").textContent = dados.fonte === "simulado"
      ? "Leilão SIMULADO — ordens inventadas para testar a tela, não é o leilão de hoje" : "";

    visiveis = filtrarLeilao(dados.lista, pref.filtro, Number(pref.liq));
    const escolhido = dados.book?.ativo;
    atualizarLinhas($("lista"), visiveis, (x) => linhaLeilao(x, x.ativo === escolhido));
    $("lista-meta").textContent = desligado ? "" : `${inteiro(visiveis.length)} de ${inteiro(dados.lista.length)} · clique abre o book`;
    $("lista-vazio").hidden = !desligado && visiveis.length > 0;
    $("lista-vazio").textContent = desligado
      ? "Leilão desligado — suba o servidor com --modo dll --leilao (ou --leilao-demo para a simulação)"
      : dados.lista.length ? "Nenhum papel com esse filtro"
      : "Nenhum papel em leilão ainda — o livro chega na pré-abertura (9:45 às 10:00)";

    resumoBook(dados.book);
    escada(dados.book);
    atualizarLinhas($("eventos"), dados.book?.eventos || [], (ev) => linhaEvento(ev));
  } finally {
    rodando = false;
  }
}

laco(passo, 1000);
