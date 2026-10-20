// Painéis da coluna direita do Operar: manchete do sinal, 4 anteriores, Times & Trades, defesas e saldo.
import { atualizarLinhas } from "./tabela.js";
import { preco, inteiro, compacto, horaB3, hm, pct } from "./formato.js";

const NOME = { "Absorção": ["Absorção", "f"], "Exaustão": ["Exaustão", "f"], "Iceberg": ["Iceberg", "m"],
               "Urgência": ["Urgência", "f"], "BestOffer": ["Melhor oferta", "f"] };
const SEGUNDOS_NOVO = 60;
const TIPO = { iceberg: "Iceberg", sniper: "Sniper", fantasma: "Fantasma" };
const EVENTOS_NA_TELA = 8;
const DEFESAS_NA_TELA = 8;   // limite de exibição do painel (o servidor já manda só as 30 mais próximas)

/** As `limite` defesas mais próximas de `preco` (empate mantém a ordem recebida). Sem preço, a ordem original. */
export function ordenarDefesas(ativas, preco, limite = DEFESAS_NA_TELA) {
  const lista = [...(ativas || [])];
  if (preco != null) lista.sort((a, b) => Math.abs(a.preco - preco) - Math.abs(b.preco - preco));
  return lista.slice(0, limite);
}

/**
 * O que a tela mostra sobre o sinal: iceberg → acerto histórico medido em pregões reais
 * (taxa de alvo antes do stop e ganho médio em ticks); demais → força (fórmula antiga, só ordena).
 * Devolve [rótulo, texto da manchete, texto curto da lista].
 */
export function medidaSinal(s) {
  if (s.acerto) {
    const taxa = pct(100 * s.acerto.taxa, 0);
    const g = s.acerto.ganho;
    return ["acerto", `${taxa} · ${g < 0 ? "−" : "+"}${preco(Math.abs(g), 1)} tick`, taxa];
  }
  const forca = pct(100 * s.confidence, 0);
  return ["força", forca, forca];
}

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
    case "mudou_nivel": return `${quem} mudou de nível ${ev.detalhe}`;
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

const ALTURA_LINHA_BOOK = 20, NIVEIS_MAX_BOOK = 20, NIVEIS_MIN_BOOK = 3;

/** Quantos níveis cabem num lado do Book (sem rolagem); sem medida ainda (altura 0), 12. */
export function linhasQueCabem(altura) {
  if (!(altura > 0)) return 12;
  return Math.max(NIVEIS_MIN_BOOK, Math.min(NIVEIS_MAX_BOOK, Math.floor(altura / ALTURA_LINHA_BOOK)));
}

/** Rótulo discreto da origem do Book (contrato de /book: depth + fonte). */
export function rotuloFonteBook(b) {
  if (!b || b.depth === "none") return "sem livro nesta fonte";
  if (b.fonte === "ofertas") return "livro completo";
  if (b.fonte === "topo" || b.depth === "top") return "só topo";
  return "níveis agregados";
}

/**
 * Book de ofertas: cada ordem na ordem da fila (melhor preço primeiro; dentro do preço, a mais antiga primeiro).
 * `niveis` = [{price, qty, fila: [[corretora, qtd], …], corretoras}, …]. Nível sem fila (fonte só com topo ou
 * livro antigo) entra como uma linha por corretora agregada. Devolve até `limite` linhas
 * {price, corretora, qty, pos, inicio} (inicio = 1ª linha do preço).
 */
export function linhasOfertas(niveis, limite) {
  const saida = [];
  for (const x of niveis || []) {
    const ordens = x.fila && x.fila.length ? x.fila : (x.corretoras || []);
    ordens.forEach(([corretora, qty], i) => {
      if (saida.length < limite) saida.push({ price: x.price, corretora, qty, pos: i + 1, inicio: i === 0 });
    });
    if (saida.length >= limite) break;
  }
  return saida;
}

/** Quantidade do nível: inteiro até 99.999; acima, "123 mil" / "1,2 mi". */
export function qtdBook(q) {
  if (q == null) return "—";
  return q >= 100000 ? compacto(q).replace(/^\+/, "") : inteiro(q);
}

/** Corretoras do nível ([[nome, qtd], …] da maior para a menor): até 3 nomes, ou só a maior em coluna estreita. */
export function corretorasBook(lista, so1 = false) {
  if (!Array.isArray(lista) || !lista.length) return "—";
  return lista.slice(0, so1 ? 1 : 3).map((c) => c[0]).join(", ");
}

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
  // Padrão: só iceberg — o único com resultado positivo na calibração de 42 pregões (17/10/2026)
  let filtro = "Iceberg";
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
    const [rotuloMedida, valorMedida] = medidaSinal(sinal);
    const a = sinal.acerto;
    det.title = a ? `Acerto histórico: ${inteiro(a.n)} sinais de iceberg com ${a.faixa} ações absorvidas `
      + `(${a.base === "TODOS" ? "todos os papéis medidos" : a.base}); alvo de 4 ticks antes do stop em 5 min, sem custos`
      : "Força: fórmula do motor que só ordena os sinais entre si (não é taxa de acerto)";
    for (const [rotulo, valor] of [[rotuloMedida, valorMedida], ["stop", preco(sinal.stop_price, casas)],
                                   ["VWAP", preco(vwap, casas)], ["vela", hm(vela)], ["hora", horaB3(sinal.timestamp)]]) {
      det.append(rotulo, Object.assign(document.createElement("b"), { textContent: valor }));
    }
  }

  function anteriores(lista, casas) {
    atualizarLinhas($("sinais-anteriores"), lista, (s) => {
      const compra = s.signal === "BUY";
      return { celulas: [{ t: compra ? "▲" : "▼", c: compra ? "compra" : "venda" }, { t: tituloSinal(s) },
        { t: preco(s.price, casas), c: "num" }, { t: medidaSinal(s)[2], c: "num faint" },
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

  // Book: compra (esquerda) e venda (direita), melhor preço na 1ª linha de cada coluna. A quantidade de cada preço
  // fica guardada entre ciclos para piscar só o que mudou.
  const qtdAnterior = new Map();
  const CHAVE_MODO_BOOK = "fluxo.bookModo";
  let modoBook = "niveis";
  try { if (localStorage.getItem(CHAVE_MODO_BOOK) === "ofertas") modoBook = "ofertas"; } catch { /* padrão */ }
  function marcarModoBook() {
    document.querySelectorAll("#book-modos [data-modo]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.modo === modoBook)));
    document.querySelectorAll(".book-th-ord").forEach((th) => { th.textContent = modoBook === "ofertas" ? "Pos" : "Ord"; });
  }
  marcarModoBook();
  document.querySelectorAll("#book-modos [data-modo]").forEach((b) => b.addEventListener("click", () => {
    modoBook = b.dataset.modo;
    marcarModoBook();
    qtdAnterior.clear();
    try { localStorage.setItem(CHAVE_MODO_BOOK, modoBook); } catch { /* vale só nesta visita */ }
  }));
  function painelBook(b, ultimo, casas) {
    const bids = b.bids || [], asks = b.asks || [];
    const total = bids.length + asks.length;
    $("book-fonte").textContent = rotuloFonteBook(b);
    $("book-ultimo").textContent = preco(ultimo, casas);
    $("book-spread").textContent = bids.length && asks.length ? `spread ${preco(asks[0].price - bids[0].price, casas)}` : "spread —";
    const msg = $("book-msg");
    msg.hidden = total > 0;
    msg.textContent = total > 0 ? "" : b.depth === "none" ? "Sem livro nesta fonte." : "Livro vazio.";
    const n = linhasQueCabem($("book-bids").closest(".book-lado").clientHeight);
    const so1 = $("book-bids").closest(".book-col").clientWidth < 230;   // coluna estreita: só a maior corretora
    if (modoBook === "ofertas") return painelOfertas(bids, asks, n, so1, casas);
    const vis = { bids: bids.slice(0, n), asks: asks.slice(0, n) };
    const maior = Math.max(1, ...vis.asks.map((x) => x.qty), ...vis.bids.map((x) => x.qty));
    const novas = new Map();
    for (const [lado, tbody, classe] of [["bids", $("book-bids"), "compra"], ["asks", $("book-asks"), "venda"]]) {
      const niveis = vis[lado];
      const iq = lado === "bids" ? 2 : 1, ic = lado === "bids" ? 0 : 3;   // bids espelhado: corr | ord | qtd | preço
      atualizarLinhas(tbody, niveis, (x) => {
        const chave = `${lado}|${x.price}`;
        novas.set(chave, x.qty);
        const mudou = qtdAnterior.has(chave) && qtdAnterior.get(chave) !== x.qty;
        const cel = [{ t: preco(x.price, casas), c: `num ${classe}` }, { t: qtdBook(x.qty), c: "num qtd" },
          { t: x.ordens == null ? "—" : inteiro(x.ordens), c: "num ord" }, { t: corretorasBook(x.corretoras, so1), c: "corr" }];
        return { classe: `${classe}-n${mudou ? " mudou" : ""}`, celulas: lado === "bids" ? cel.reverse() : cel };
      });
      niveis.forEach((x, i) => {
        const tr = tbody.rows[i];
        const w = `${Math.max(2, Math.round(100 * x.qty / maior))}%`;
        if (tr.cells[iq].style.getPropertyValue("--w") !== w) tr.cells[iq].style.setProperty("--w", w);
        const dica = (x.corretoras || []).map(([c, q]) => `${c} ${inteiro(q)}`).join(" · ");
        if (tr.cells[ic].title !== dica) tr.cells[ic].title = dica;
      });
      const soma = niveis.reduce((t, x) => t + x.qty, 0);
      $(`book-tot-${lado}`).textContent = niveis.length ? `${niveis.length} níveis · ${qtdBook(soma)}` : "";
    }
    qtdAnterior.clear();
    novas.forEach((q, k) => qtdAnterior.set(k, q));
  }

  // Book de ofertas: uma linha por ordem (corretora, posição na fila, quantidade, preço)
  function painelOfertas(bids, asks, n, so1, casas) {
    const novas = new Map();
    const vis = { bids: linhasOfertas(bids, n), asks: linhasOfertas(asks, n) };
    const maior = Math.max(1, ...vis.asks.map((x) => x.qty), ...vis.bids.map((x) => x.qty));
    for (const [lado, tbody, classe] of [["bids", $("book-bids"), "compra"], ["asks", $("book-asks"), "venda"]]) {
      const linhas = vis[lado];
      const iq = lado === "bids" ? 2 : 1;
      atualizarLinhas(tbody, linhas, (x) => {
        const chave = `${lado}|${x.price}|${x.pos}|${x.corretora}`;
        novas.set(chave, x.qty);
        const mudou = qtdAnterior.has(chave) && qtdAnterior.get(chave) !== x.qty;
        const cel = [{ t: preco(x.price, casas), c: `num ${classe}` }, { t: qtdBook(x.qty), c: "num qtd" },
          { t: inteiro(x.pos), c: "num ord" }, { t: x.corretora || "—", c: "corr" }];
        return { classe: `${classe}-n${x.inicio ? " novo-preco" : ""}${mudou ? " mudou" : ""}`, celulas: lado === "bids" ? cel.reverse() : cel };
      });
      linhas.forEach((x, i) => {
        const w = `${Math.max(2, Math.round(100 * x.qty / maior))}%`;
        const td = tbody.rows[i].cells[iq];
        if (td.style.getPropertyValue("--w") !== w) td.style.setProperty("--w", w);
        const ic = lado === "bids" ? 0 : 3;
        if (tbody.rows[i].cells[ic].title) tbody.rows[i].cells[ic].title = "";
      });
      const soma = linhas.reduce((t, x) => t + x.qty, 0);
      $(`book-tot-${lado}`).textContent = linhas.length ? `${linhas.length} ordens · ${qtdBook(soma)}` : "";
    }
    qtdAnterior.clear();
    novas.forEach((q, k) => qtdAnterior.set(k, q));
  }

  function defesas(estado, casas, agora) {
    const d = estado.defesas || {};
    const ativas = d.ativas || [], eventos = d.eventos || [];
    $("defesas-nota").textContent = ativas.length ? `${ativas.length} ativa${ativas.length > 1 ? "s" : ""}` : "nenhuma ativa";
    atualizarLinhas($("defesas"), ordenarDefesas(ativas, estado.resumo?.ultimo), (x) => ({
      celulas: [{ t: (TIPO[x.tipo] || x.tipo) + (x.e2_com ? " · E2" : "") }, { t: x.corretora },
        { t: preco(x.preco, casas), c: `num ${x.lado}` }, { t: duracao(agora - x.desde), c: "num faint" }] }));
    // "alerta" é só candidata; a lista de eventos da tela mostra o que já virou defesa
    atualizarLinhas($("defesas-eventos"), eventos.filter((ev) => ev.evento !== "alerta").reverse().slice(0, EVENTOS_NA_TELA), (ev) => ({
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
    atualizar({ estado, sinais, trades, book: bookDados, casas, agora, tf }) {
      const filtrados = filtro === "todos" ? sinais : sinais.filter((s) => s.pattern === filtro);
      $("sinais-meta").textContent = `${filtrados.length} hoje`;
      manchete(filtrados[filtrados.length - 1], estado.resumo?.vwap, casas, agora, tf);
      anteriores(filtrados.slice(-5, -1).reverse(), casas);
      fita(trades, estado.asset, casas);
      painelBook(bookDados, estado.resumo?.ultimo, casas);
      defesas(estado, casas, agora);
      saldo(estado.resumo?.saldo_corretoras || []);
    },
  };
}
