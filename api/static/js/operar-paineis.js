// Painéis da coluna direita do Operar: manchete do sinal, 4 anteriores, Times & Trades, livro e saldo.
import { atualizarLinhas } from "./tabela.js";
import { preco, inteiro, compacto, horaB3, hm, pct } from "./formato.js";

const NOME = { "Absorção": ["Absorção", "f"], "Exaustão": ["Exaustão", "f"], "Iceberg": ["Iceberg", "m"],
               "Urgência": ["Urgência", "f"], "BestOffer": ["Melhor oferta", "f"] };
const SEGUNDOS_NOVO = 60;
const $ = (id) => document.getElementById(id);

/** "Absorção compradora", "Iceberg vendedor": padrão + direção, com o gênero do nome. */
export function tituloSinal(s) {
  const [nome, genero] = NOME[s.pattern] || [s.pattern, "m"];
  const compra = s.signal === "BUY";
  const lado = compra ? (genero === "f" ? "compradora" : "comprador") : (genero === "f" ? "vendedora" : "vendedor");
  return `${nome} ${lado}`;
}

/** Lote grande da fita: contratos para futuros de índice/dólar, ações em lotes de 100. */
export function loteGrandePadrao(ativo) { return /^(WDO|DOL|WIN|IND)/.test(ativo || "") ? 50 : 5000; }
function loteGrande(ativo) {
  try { const v = Number(localStorage.getItem("fluxo.loteGrande")); if (v > 0) return v; } catch { /* padrão */ }
  return loteGrandePadrao(ativo);
}

export function criarPaineis() {
  let filtro = "todos";
  document.querySelectorAll("#filtros [data-filtro]").forEach((b) => b.addEventListener("click", () => {
    filtro = b.dataset.filtro;
    document.querySelectorAll("#filtros [data-filtro]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  }));

  function manchete(sinal, vwap, casas, agora, tf) {
    const art = $("manchete");
    if (!sinal) {
      art.className = "manchete vazia";
      $("m-titulo").textContent = "Nenhum sinal ainda hoje";
      for (const id of ["m-idade", "m-preco", "m-frase", "m-det"]) $(id).textContent = "";
      return;
    }
    const compra = sinal.signal === "BUY";
    art.className = `manchete ${compra ? "compra-dir" : "venda-dir"}`;
    const idade = Math.max(0, Math.round(agora - sinal.timestamp));
    $("m-idade").textContent = idade <= SEGUNDOS_NOVO ? `novo · há ${idade} s` : `às ${horaB3(sinal.timestamp)}`;
    $("m-titulo").textContent = tituloSinal(sinal);
    $("m-preco").className = `m-preco ${compra ? "compra" : "venda"}`;
    $("m-preco").textContent = `em ${preco(sinal.price, casas)}`;
    $("m-frase").textContent = sinal.reason || "";
    const det = $("m-det");
    det.textContent = "";
    const vela = Math.floor(sinal.timestamp / tf) * tf;
    for (const [rotulo, valor] of [["força", pct(100 * sinal.confidence, 0)], ["stop", preco(sinal.stop_price, casas)],
                                   ["VWAP", preco(vwap, casas)], ["vela", hm(vela)], ["hora", horaB3(sinal.timestamp)]]) {
      det.append(rotulo, Object.assign(document.createElement("b"), { textContent: valor }));
    }
  }

  function anteriores(lista, casas) {
    atualizarLinhas($("sinais-anteriores"), lista, (s) => {
      const compra = s.signal === "BUY";
      return { celulas: [{ t: compra ? "▲" : "▼", c: compra ? "compra" : "venda" }, { t: tituloSinal(s) },
        { t: preco(s.price, casas), c: "num" }, { t: pct(100 * s.confidence, 0), c: "num faint" },
        { t: s.reason || "" }, { t: horaB3(s.timestamp), c: "num faint" }] };
    });
  }

  function fita(trades, ativo, casas) {
    const limite = loteGrande(ativo);
    $("tt-meta").textContent = `lotes ≥ ${inteiro(limite)} em negrito`;
    atualizarLinhas($("tt"), [...trades].reverse(), (t) => {
      const compra = t.side === "compra";
      const comprador = compra ? t.broker : t.passive_broker;
      const vendedor = compra ? t.passive_broker : t.broker;
      return {
        classe: t.qty >= limite ? (compra ? "lote-compra" : "lote-venda") : "",
        celulas: [{ t: horaB3(t.timestamp), c: "faint" }, { t: preco(t.price, casas), c: "num" },
          { t: inteiro(t.qty), c: "num" }, { t: compra ? "C" : "V", c: compra ? "compra" : "venda" },
          { t: comprador || "—" }, { t: vendedor || "—" }],
      };
    });
  }

  function livro(book, casas) {
    const asks = book.asks.slice(0, 10).reverse();
    const bids = book.bids.slice(0, 10);
    const maior = Math.max(1, ...asks.map((l) => l.qty), ...bids.map((l) => l.qty));
    const linha = (lado) => (l) => ({ celulas: [{ t: l.broker || "—" }, { t: l.qty ? inteiro(l.qty) : "—", c: "num" },
      { t: preco(l.price, casas), c: `num ${lado}` }, { barra: { pct: 100 * l.qty / maior, lado }, c: "barra-cel" }] });
    atualizarLinhas($("livro-asks"), asks, linha("venda"));
    atualizarLinhas($("livro-bids"), bids, linha("compra"));
    $("livro-nota").textContent = book.depth === "top" ? "topo do livro"
      : book.depth === "none" ? "sem livro nesta fonte" : `${Math.max(asks.length, bids.length)} níveis`;
    $("spread").textContent = bids.length && book.asks.length
      ? `spread ${preco(book.asks[0].price - bids[0].price, casas)}   ${preco(bids[0].price, casas)} × ${preco(book.asks[0].price, casas)}`
      : "—";
  }

  function saldo(lista) {
    const maior = Math.max(1, ...lista.map(([, v]) => Math.abs(v)));
    atualizarLinhas($("saldo"), lista, ([nome, v]) => {
      const lado = v >= 0 ? "compra" : "venda";
      return { celulas: [{ t: nome }, { t: compacto(v), c: `num ${lado}` },
        { barra: { pct: 100 * Math.abs(v) / maior, lado }, c: "barra-cel" }] };
    });
  }

  return {
    atualizar({ estado, sinais, trades, book, casas, agora, tf }) {
      const filtrados = filtro === "todos" ? sinais : sinais.filter((s) => s.pattern === filtro);
      $("sinais-meta").textContent = `${sinais.length} hoje`;
      manchete(filtrados[filtrados.length - 1], estado.resumo?.vwap, casas, agora, tf);
      anteriores(filtrados.slice(-5, -1).reverse(), casas);
      fita(trades, estado.asset, casas);
      livro(book, casas);
      saldo(estado.resumo?.saldo_corretoras || []);
    },
  };
}
