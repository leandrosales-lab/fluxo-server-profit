// Linhas da tela Radar: funções puras (testadas em tools/test_telas.mjs).
import { preco, inteiro, horaB3, pct } from "./formato.js";

/** "segurando", "segurou às 10:00:00", "segurou às 10:00:00, rompeu às 11:00:00", "rompeu às …", "virou sniper às …". */
export function textoSituacao(r) {
  if (r.situacao === "segurando") return "segurando";
  if (r.situacao === "segurou") {
    return `segurou às ${horaB3(r.segurou_as)}` + (r.rompeu_as ? `, rompeu às ${horaB3(r.rompeu_as)}` : "");
  }
  return `${r.situacao} às ${horaB3(r.desfecho_as)}`;
}

/** Uma linha da lista: papel, corretora, lado, preço, giros, volume, desde, situação, acerto histórico. */
export function linhaRadar(r) {
  return {
    classe: r.situacao === "segurando" ? "destaque" : "",
    celulas: [
      { t: r.ativo }, { t: r.corretora }, { t: r.lado, c: r.lado },
      { t: preco(r.preco, 2), c: `num ${r.lado}` }, { t: inteiro(r.giros), c: "num" },
      { t: inteiro(r.volume), c: "num" }, { t: horaB3(r.confirmado_as), c: "faint" },
      { t: textoSituacao(r) }, { t: r.acerto ? pct(100 * r.acerto.taxa, 0) : "—", c: "num faint" },
    ],
  };
}
