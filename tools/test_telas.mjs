// Testes das funções puras do frontend (sem navegador). Uso: node tools/test_telas.mjs
import assert from "node:assert/strict";
import * as f from "../api/static/js/formato.js";
import { textoStatus, estadoReconectar } from "../api/static/js/shell.js";
import { tituloSinal, loteGrandePadrao } from "../api/static/js/operar-paineis.js";
import { sinceCandles, juntarCandles, precisaLimpar } from "../api/static/js/candles.js";

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
// fora do pregão a DLL entrega o último negócio do dia: "latência" de 1 h não é latência, não aparece
assert.deepEqual(textoStatus({ ...ok, latencia_ms: 3631402 }, "ProfitDLL"), ["ProfitDLL conectado (2,4)", false]);

assert.equal(tituloSinal({ signal: "BUY", pattern: "Absorção" }), "Absorção compradora");
assert.equal(tituloSinal({ signal: "SELL", pattern: "Iceberg" }), "Iceberg vendedor");
assert.equal(tituloSinal({ signal: "SELL", pattern: "BestOffer" }), "Melhor oferta vendedora");
assert.equal(loteGrandePadrao("WDOFUT"), 50);
assert.equal(loteGrandePadrao("PETR4"), 5000);

// conexão inicial ainda em curso (ponte ocupada): alerta, não "desconectado"
assert.deepEqual(textoStatus({ conectado: false, ocupado: true, estados: {}, reconexao: {} }, "ProfitDLL"),
  ["conectando…", true]);

// negócio atrasado muda o candle anterior: o since volta um candle e o juntar substitui por time
assert.equal(sinceCandles(1020, 60), 960);
assert.equal(sinceCandles(null, 60), null);
const juntos = juntarCandles([{ time: 960, volume: 5 }, { time: 1020, volume: 1 }],
                             [{ time: 960, volume: 7 }, { time: 1020, volume: 2 }, { time: 1080, volume: 1 }]);
assert.deepEqual(juntos.map((c) => [c.time, c.volume]), [[960, 7], [1020, 2], [1080, 1]]);

// sem mudança real, juntarCandles devolve o MESMO array (o gráfico não redesenha à toa)
const base = [{ time: 960, open: 1, high: 2, low: 1, close: 2, volume: 5, buy: 3, sell: 2, financeiro: 9 }];
assert.equal(juntarCandles(base, [{ ...base[0] }]), base);
assert.notEqual(juntarCandles(base, [{ ...base[0], volume: 6 }]), base);

// reset: a tela limpa quando a geração muda, mesmo que o /state já traga negócios novos
assert.equal(precisaLimpar(null, 0), false);   // 1ª leitura
assert.equal(precisaLimpar(0, 0), false);
assert.equal(precisaLimpar(0, 1), true);

// botão Reconectar
const agora = 100000;
const livre = { conectado: true, reconexao: { em_andamento: false, resultado: null } };
// um /state que saiu antes do clique ainda diz "livre": o botão continua desabilitado
assert.deepEqual(estadoReconectar(livre, { ate: agora + 2000, msg: null }, agora),
  { desabilitado: true, texto: "reconectando…", msg: "" });
// 409 do clique: a mensagem fica 5 s mesmo com /state dizendo "livre"
assert.deepEqual(estadoReconectar(livre, { ate: agora + 5000, msg: "reconexão já em andamento" }, agora),
  { desabilitado: false, texto: "Reconectar", msg: "reconexão já em andamento" });
// depois do prazo vale o servidor: resultado da última tentativa
assert.deepEqual(estadoReconectar({ ...livre, reconexao: { em_andamento: false, resultado: "falhou: senha inválida" } },
  { ate: agora - 1, msg: "x" }, agora), { desabilitado: false, texto: "Reconectar", msg: "falhou: senha inválida" });
assert.deepEqual(estadoReconectar({ conectado: false, ocupado: true, reconexao: {} }, null, agora),
  { desabilitado: true, texto: "conectando…", msg: "" });

console.log("test_telas.mjs: tudo certo");
