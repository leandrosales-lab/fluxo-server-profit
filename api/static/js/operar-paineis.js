// Painéis da coluna direita do Operar: manchete do sinal, 4 anteriores, Times & Trades, defesas e saldo.
import { atualizarLinhas } from "./tabela.js";
import { preco, inteiro, compacto, horaB3, hm, pct } from "./formato.js";

const NOME = { "Absorção": ["Absorção", "f"], "Exaustão": ["Exaustão", "f"], "Iceberg": ["Iceberg", "m"],
               "Urgência": ["Urgência", "f"], "BestOffer": ["Melhor oferta", "f"] };
const SEGUNDOS_NOVO = 60;
const TIPO = { iceberg: "Iceberg", sniper: "Sniper", fantasma: "Fantasma" };
const EVENTOS_NA_TELA = 8;

/** "45 s", "3 min", "2 h": há quanto tempo a defesa está ativa. */
export function duracao(seg) {
  const s = Math.max(0, Math.round(seg));
  return s < 60 ? `${s} s` : s < 3600 ? `${Math.floor(s / 60)} min` : `${Math.floor(s / 3600)} h`;
}

/** Texto de um evento de defesa (estado.defesas.eventos). */
export function textoEvento(ev, casas = 2) {
  const quem = `${TIPO[ev.tipo] || "Defesa"} ${ev.corretora}`;
  const p = preco(ev.preco, casas);
  switch (ev.evento) {
    case "confirmada": return `${quem} segurando a ${ev.lado} @ ${p}`;
    case "mudou_nivel": return `${quem} ${ev.lado === "compra" ? "subiu" : "desceu"} ${ev.detalhe}`;
    case "rompida": return `${quem} rompido @ ${p}`;
    case "fila_formada": return `${quem}: fila formada @ ${p}`;
    case "defensor_ausente": return `${quem} sumiu (${ev.detalhe})`;
    case "reclassificada": return `${quem} reclassificado: ${ev.detalhe}`;
    case "e2_formado": return `E2: ${ev.corretora} + ${ev.parceiro} @ ${p}`;
    case "e2_uma_acabou": return `E2 desfeito: ${ev.parceiro} acabou, ${ev.corretora} continua`;
    case "alerta": return `Alerta: ${ev.corretora} @ ${p}`;
    default: return `${quem}: ${ev.evento}`;
  }
}
const $ = (id) => document.getElementById(id);

/** "Absorção compradora", "Iceberg vendedor": padrão + direção, com o gênero do nome. */
export function tituloSinal(s) {
  const [nome, genero] = NOME[s.pattern] || [s.pattern, "m"];
  const compra = s.signal === "BUY";
  const lado = compra ? (genero === "f" ? "compradora" : "comprador") : (genero === "f" ? "vendedora" : "vendedor");
  return `${nome} ${lado}`;
}

/** Lote grande da fita (ações); ajustável por fluxo.loteGrande no localStorage. */
export const LOTE_GRANDE_PADRAO = 5000;
function loteGrande() {
  try { const v = Number(localStorage.getItem("fluxo.loteGrande")); if (v > 0) return v; } catch { /* padrão */ }
  return LOTE_GRANDE_PADRAO;
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
    const limite = loteGrande();
    $("tt-meta").textContent = `≥ ${inteiro(limite)} ações em negrito`;
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

  function topo(book, casas) {
    const bids = book.bids || [], asks = book.asks || [];
    $("spread").textContent = bids.length && asks.length
      ? `spread ${preco(asks[0].price - bids[0].price, casas)}   ${preco(bids[0].price, casas)} × ${preco(asks[0].price, casas)}`
      : book.depth === "none" ? "sem livro nesta fonte" : "—";
  }

  function defesas(estado, casas, agora) {
    const d = estado.defesas || { ativas: [], eventos: [] };
    $("defesas-nota").textContent = d.ativas.length ? `${d.ativas.length} ativa${d.ativas.length > 1 ? "s" : ""}` : "nenhuma ativa";
    atualizarLinhas($("defesas"), d.ativas, (x) => ({
      celulas: [{ t: (TIPO[x.tipo] || x.tipo) + (x.e2_com ? " · E2" : "") }, { t: x.corretora },
        { t: preco(x.preco, casas), c: `num ${x.lado}` }, { t: duracao(agora - x.desde), c: "num faint" }] }));
    atualizarLinhas($("defesas-eventos"), [...d.eventos].reverse().slice(0, EVENTOS_NA_TELA), (ev) => ({
      celulas: [{ t: horaB3(ev.ts), c: "faint" }, { t: textoEvento(ev, casas) }] }));
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
      topo(book, casas);
      defesas(estado, casas, agora);
      saldo(estado.resumo?.saldo_corretoras || []);
    },
  };
}
