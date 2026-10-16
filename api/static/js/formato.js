// Formatação pt-BR de números e horários das telas (puro: testado em tools/test_telas.mjs).
const FUSO = "America/Sao_Paulo";
const formatos = new Map();
function nf(casas) {
  if (!formatos.has(casas)) {
    formatos.set(casas, new Intl.NumberFormat("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas }));
  }
  return formatos.get(casas);
}
const vazio = (v) => v === null || v === undefined || Number.isNaN(v);

/** Casas decimais do tick do ativo: 0,5 → 1; 0,01 → 2; 0,25 → 2; 5 → 0. */
export function casasDoTick(tick) {
  if (!tick) return 2;
  const decimais = String(tick).split(".")[1];
  return decimais ? Math.min(4, decimais.length) : 0;
}
export function preco(v, casas = 2) { return vazio(v) ? "—" : nf(casas).format(v); }
export function inteiro(v) { return vazio(v) ? "—" : nf(0).format(Math.round(v)); }
/** +184.300 / -0,48: o sinal fica explícito; fmt formata o valor absoluto. */
export function comSinal(v, fmt = inteiro) {
  if (vazio(v)) return "—";
  return (v > 0 ? "+" : v < 0 ? "-" : "") + fmt(Math.abs(v));
}
export function financeiro(v) {
  if (vazio(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `R$ ${nf(1).format(v / 1e9)} bi`;
  if (a >= 1e6) return `R$ ${nf(1).format(v / 1e6)} mi`;
  if (a >= 1e3) return `R$ ${nf(1).format(v / 1e3)} mil`;
  return `R$ ${nf(0).format(v)}`;
}
/** Saldo em lotes, com sinal: +92 mil, -1,2 mi, +950. */
export function compacto(v) {
  if (vazio(v)) return "—";
  const a = Math.abs(v);
  const s = v > 0 ? "+" : v < 0 ? "-" : "";
  if (a >= 1e6) return `${s}${nf(1).format(a / 1e6)} mi`;
  if (a >= 1e3) return `${s}${nf(0).format(Math.round(a / 1e3))} mil`;
  return `${s}${nf(0).format(a)}`;
}
export function pct(v, casas = 1) { return vazio(v) ? "—" : `${nf(casas).format(v)}%`; }

const fmtHora = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
const fmtHM = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
/** Hora de Brasília (B3) de um epoch em segundos. */
export function horaB3(epoch) { return vazio(epoch) ? "—" : fmtHora.format(new Date(epoch * 1000)); }
export function hm(epoch) { return vazio(epoch) ? "—" : fmtHM.format(new Date(epoch * 1000)); }
