// Testes das funções puras do frontend (sem navegador). Uso: node tools/test_telas.mjs
import assert from "node:assert/strict";
import * as f from "../api/static/js/formato.js";
import { textoStatus } from "../api/static/js/shell.js";
import { tituloSinal, loteGrandePadrao } from "../api/static/js/operar-paineis.js";

assert.equal(f.preco(38.47), "38,47");
assert.equal(f.preco(5078.5, 1), "5.078,5");
assert.equal(f.preco(null), "—");
assert.equal(f.inteiro(184300), "184.300");
assert.equal(f.comSinal(184300), "+184.300");
assert.equal(f.comSinal(-0.48, (v) => f.preco(v)), "-0,48");
assert.equal(f.compacto(92000), "+92 mil");
assert.equal(f.compacto(-61000), "-61 mil");
assert.equal(f.compacto(-1234567), "-1,2 mi");
assert.equal(f.compacto(950), "+950");
assert.equal(f.financeiro(412000000), "R$ 412,0 mi");
assert.equal(f.financeiro(2.5e9), "R$ 2,5 bi");
assert.equal(f.pct(57), "57,0%");
assert.equal(f.casasDoTick(0.5), 1);
assert.equal(f.casasDoTick(0.01), 2);
assert.equal(f.casasDoTick(0.25), 2);
assert.equal(f.casasDoTick(5), 0);
assert.equal(f.horaB3(1792183666.518), "17:47:46");   // 16/10/2026 20:47:46 UTC = 17:47:46 em Brasília
assert.equal(f.hm(1792183666.518), "17:47");
assert.equal(f.horaB3(null), "—");

const ok = { conectado: true, latencia_ms: 12, estados: { market: { codigo: 4, nome: "conectado" } }, reconexao: {} };
assert.deepEqual(textoStatus(ok, "ProfitDLL"), ["ProfitDLL conectado (2,4) · 12 ms", false]);
assert.deepEqual(textoStatus({ ...ok, estados: { market: { codigo: 6 } } }, "ProfitDLL"),
  ["ProfitDLL conectado (2,6) · callbacks atrasados", true]);
assert.deepEqual(textoStatus({ conectado: false, motivo_falha: "senha inválida", estados: {} }, "ProfitDLL"),
  ["desconectado — senha inválida", true]);
assert.deepEqual(textoStatus({ ...ok, reconexao: { em_andamento: true } }, "ProfitDLL"), ["reconectando…", true]);
assert.deepEqual(textoStatus(undefined, "exemplo_wdo.csv"), ["fonte: exemplo_wdo.csv", false]);

assert.equal(tituloSinal({ signal: "BUY", pattern: "Absorção" }), "Absorção compradora");
assert.equal(tituloSinal({ signal: "SELL", pattern: "Iceberg" }), "Iceberg vendedor");
assert.equal(tituloSinal({ signal: "SELL", pattern: "BestOffer" }), "Melhor oferta vendedora");
assert.equal(loteGrandePadrao("WDOFUT"), 50);
assert.equal(loteGrandePadrao("PETR4"), 5000);

console.log("test_telas.mjs: tudo certo");
