// Linhas da tela Leilão: funções puras (testadas em tools/test_telas.mjs).
import { preco, pct, horaB3, financeiro, comSinal, inteiro } from "./formato.js";

const nf1 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

/** Quantidade curta sem sinal: 950, 92 mil, 1,2 mi. */
export function qtdCurta(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e6) return `${nf1.format(a / 1e6)} mi`;
  if (a >= 1e3) return `${inteiro(a / 1e3)} mil`;
  return inteiro(a);
}

/** Seta da pressão: +2 ▲▲, +1 ▲, 0 —, −1 ▼, −2 ▼▼. */
export function seta(pressao) {
  if (pressao > 0) return { t: pressao > 1 ? "▲▲" : "▲", c: "compra" };
  if (pressao < 0) return { t: pressao < -1 ? "▼▼" : "▼", c: "venda" };
  return { t: "—", c: "faint" };
}

/** "3,0× venda", "só compra" (o outro lado vazio), "1,4×" (abaixo da regra) ou "—" sem sobra. */
export function textoDesequilibrio(r) {
  if (!r.banda_compra && !r.banda_venda) return { t: "—", c: "faint" };
  const lado = r.banda_compra > r.banda_venda ? "compra" : r.banda_venda > r.banda_compra ? "venda" : null;
  if (r.razao == null) return { t: `só ${lado}`, c: r.desbalanceado ? lado : "" };
  if (!r.desbalanceado) return { t: `${nf1.format(r.razao)}×`, c: "faint" };
  return { t: `${nf1.format(r.razao)}× ${r.desbalanceado}`, c: r.desbalanceado };
}

/** Escora: preço na tabela; quantidade, dono e distância no title. */
export function textoEscora(e, casas = 2) {
  if (!e) return { t: "—", c: "num faint", title: "" };
  return { t: preco(e.preco, casas), c: "num",
    title: `${qtdCurta(e.qtd)} parados · ${e.corretora} com ${pct(100 * e.fatia, 0)} · ${e.dist_ticks} ticks do teórico` };
}

/** "A mercado" da lista: compra × venda a mercado + agressivas (as duas casam em qualquer teórico). */
export function textoMercado(r) {
  const c = (r.mercado_compra || 0) + (r.agressiva_compra || 0);
  const v = (r.mercado_venda || 0) + (r.agressiva_venda || 0);
  if (!c && !v) return { t: "—", c: "num faint", title: "" };
  return { t: `${c ? qtdCurta(c) : "—"} × ${v ? qtdCurta(v) : "—"}`, c: `num ${c > v ? "compra" : v > c ? "venda" : ""}`,
    title: `compra: ${qtdCurta(r.mercado_compra || 0)} a mercado + ${qtdCurta(r.agressiva_compra || 0)} agressiva · `
      + `venda: ${qtdCurta(r.mercado_venda || 0)} a mercado + ${qtdCurta(r.agressiva_venda || 0)} agressiva` };
}

export function textoTendencia(t) {
  return { t: t || "—", c: t === "alta" ? "compra" : t === "baixa" ? "venda" : "faint" };
}

/** Uma linha da lista de papéis. */
export function linhaLeilao(r, selecionado = false, casas = 2) {
  const s = seta(r.pressao);
  const d = textoDesequilibrio(r);
  const tend = textoTendencia(r.tendencia);
  const ea = textoEscora(r.escora_abaixo, casas), ec = textoEscora(r.escora_acima, casas);
  return {
    classe: r.no_perfil ? "perfil" : "",
    selecionado,
    celulas: [
      { t: r.ativo }, { t: s.t, c: `seta ${s.c}` },
      { t: preco(r.teorico, casas), c: "num" },
      { t: r.var_pct == null ? "—" : comSinal(r.var_pct, (v) => pct(v, 2)), c: `num opc ${r.var_pct > 0 ? "compra" : r.var_pct < 0 ? "venda" : "faint"}` },
      { t: r.delta_ticks == null ? "—" : comSinal(r.delta_ticks), c: `num ${r.delta_ticks > 0 ? "compra" : r.delta_ticks < 0 ? "venda" : "faint"}` },
      { t: `${r.cruzou_acima ?? 0} ▲ ${r.cruzou_abaixo ?? 0} ▼`, c: `num ${r.cruzou_acima || r.cruzou_abaixo ? "" : "faint"}`,
        title: `O teórico passou ${r.cruzou_acima ?? 0}× para cima e ${r.cruzou_abaixo ?? 0}× para baixo do preço de partida` },
      { t: qtdCurta(r.banda_compra), c: "num" }, { t: qtdCurta(r.banda_venda), c: "num" },
      textoMercado(r), d, tend, ea, ec,
      { t: r.liquidez == null ? "—" : financeiro(r.liquidez), c: "num opc faint" },
    ],
  };
}

/** Filtro da lista: "" todos, "desbalanceados", "perfil"; liqMin em R$ (0 = qualquer). */
export function filtrarLeilao(lista, filtro = "", liqMin = 0) {
  return (lista || []).filter((r) => (
    (!filtro || (filtro === "perfil" ? r.no_perfil : !!r.desbalanceado))
    && (!liqMin || (r.liquidez || 0) >= liqMin)));
}

/** Escada do book: largura da barra relativa ao maior nível visível. */
export function linhasEscada(niveis, casas = 2) {
  const maior = Math.max(1, ...(niveis || []).map((n) => Math.max(n.compra, n.venda)));
  return (niveis || []).map((n) => ({
    classe: [n.teorico ? "teorico" : "", n.mercado ? "mercado" : "", n.agressiva ? "agressiva" : "",
      n.escora === "compra" ? "lote-compra" : n.escora === "venda" ? "lote-venda" : ""].filter(Boolean).join(" "),
    corrCompra: (n.corretora_compra || "") + (n.agressiva === "compra" ? " · agressiva" : ""),
    corrVenda: (n.agressiva === "venda" ? "agressiva · " : "") + (n.corretora_venda || ""),
    compra: n.compra ? qtdCurta(n.compra) : "", venda: n.venda ? qtdCurta(n.venda) : "",
    wCompra: Math.round((100 * n.compra) / maior), wVenda: Math.round((100 * n.venda) / maior),
    preco: n.mercado ? "a mercado" : preco(n.preco, casas),
  }));
}

const VERBO = { entrou: "entrou na", saiu: "saiu da", aumentou: "aumentou a", reduziu: "reduziu a", cancelou: "cancelou na" };

/**
 * "entrou na compra · 25 mil a 45,60", "… · 300 mil a mercado", "… · 50 mil a 39,50 (agressiva)" e o teórico
 * "45,39 → 45,41" (ou só "45,39" se não mexeu).
 */
export function linhaEvento(ev, casas = 2) {
  const mexeu = ev.teorico_antes !== ev.teorico_depois;
  const subiu = mexeu && (ev.teorico_depois ?? 0) > (ev.teorico_antes ?? 0);
  return {
    classe: "",
    celulas: [
      { t: horaB3(ev.ts), c: "faint" }, { t: ev.corretora, c: ev.tipo === "entrou" ? "ambar" : "" },
      { t: `${VERBO[ev.tipo] || ev.tipo} ${ev.lado} · ${qtdCurta(ev.qtd)} `
          + (ev.preco == null ? "a mercado" : `a ${preco(ev.preco, casas)}${ev.agressiva ? " (agressiva)" : ""}`), c: ev.lado },
      { t: mexeu ? `${preco(ev.teorico_antes, casas)} → ${preco(ev.teorico_depois, casas)}` : preco(ev.teorico_depois, casas),
        c: `num ${mexeu ? (subiu ? "compra" : "venda") : "faint"}` },
    ],
  };
}

/** Contagem até o fim do leilão: "04:12" (mm:ss); depois dele, "aberto" (ou o texto dado, ex. "encerrado"). */
export function contagem(agora, abertura, depois = "aberto") {
  if (agora == null || abertura == null) return "—";
  const s = Math.floor(abertura - agora);
  if (s <= 0) return depois;
  return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
