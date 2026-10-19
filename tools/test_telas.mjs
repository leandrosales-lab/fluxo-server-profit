// Testes das funções puras do frontend (sem navegador). Uso: node tools/test_telas.mjs
import assert from "node:assert/strict";
import * as f from "../api/static/js/formato.js";
import { textoStatus, estadoReconectar } from "../api/static/js/shell.js";
import { tituloSinal, LOTE_GRANDE_PADRAO, textoEvento, duracao, medidaSinal, ordenarDefesas,
  linhasQueCabem, rotuloFonteBook, qtdBook, corretorasBook } from "../api/static/js/operar-paineis.js";
import { textoSituacao, linhaRadar } from "../api/static/js/radar-lista.js";
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
assert.deepEqual(textoStatus(undefined, "exemplo_petr4.csv"), ["fonte: exemplo_petr4.csv", false]);
// fora do pregão a DLL entrega o último negócio do dia: "latência" de 1 h não é latência, não aparece
assert.deepEqual(textoStatus({ ...ok, latencia_ms: 3631402 }, "ProfitDLL"), ["ProfitDLL conectado (2,4)", false]);

assert.equal(tituloSinal({ signal: "BUY", pattern: "Absorção" }), "Absorção compradora");
assert.equal(tituloSinal({ signal: "SELL", pattern: "Iceberg" }), "Iceberg vendedor");
assert.equal(tituloSinal({ signal: "SELL", pattern: "BestOffer" }), "Melhor oferta vendedora");
assert.equal(LOTE_GRANDE_PADRAO, 5000);   // ações: lote grande da fita

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

const ev = (evento, extra = {}) => ({ ts: 0, evento, tipo: "sniper", corretora: "MORGAN", lado: "compra",
  preco: 21.17, detalhe: "", parceiro: "", ...extra });
assert.equal(textoEvento(ev("confirmada")), "Sniper MORGAN segurando a compra @ 21,17");
assert.equal(textoEvento(ev("mudou_nivel", { preco: 21.19, detalhe: "21,17 → 21,19" })), "Sniper MORGAN mudou de nível 21,17 → 21,19");
assert.equal(textoEvento(ev("fila_formada", { tipo: "fantasma", corretora: "TULLETT", lado: "venda", preco: 22.4 })),
  "Fantasma TULLETT: fila formada @ 22,40");
assert.equal(textoEvento(ev("defensor_ausente", { detalhe: "negócio a 4 ticks além" })),
  "Sniper MORGAN sumiu (negócio a 4 ticks além)");
assert.equal(textoEvento(ev("rompida", { tipo: "iceberg", corretora: "JP MORGAN" })), "Iceberg JP MORGAN rompido @ 21,17");
assert.equal(textoEvento(ev("e2_formado", { tipo: "iceberg", corretora: "AGORA", parceiro: "TULLETT", preco: 22.05 })),
  "E2: AGORA + TULLETT @ 22,05");
assert.equal(textoEvento(ev("e2_uma_acabou", { tipo: "iceberg", corretora: "AGORA", parceiro: "MERRILL" })),
  "E2 desfeito: MERRILL acabou, AGORA continua");
assert.equal(duracao(45), "45 s");
assert.equal(duracao(185), "3 min");
assert.equal(duracao(7300), "2 h");

const dd = (preco) => ({ preco });
const dez = [20, 21, 22, 23, 24, 25, 26, 27, 28, 29].map(dd);
assert.deepEqual(ordenarDefesas(dez, 25.1, 3).map((x) => x.preco), [25, 26, 24]);
assert.equal(ordenarDefesas(dez, 25.1).length, 8);
assert.deepEqual(ordenarDefesas(dez, null, 2).map((x) => x.preco), [20, 21]);
assert.deepEqual(ordenarDefesas(undefined, 25, 8), []);
assert.equal(dez[0].preco, 20);   // não altera a lista recebida

// Iceberg mostra o acerto histórico medido; os outros padrões, a força (só ordena)
const acerto = { taxa: 0.408, ganho: 1.044, n: 1217, faixa: "5-10k", base: "RENT3" };
assert.deepEqual(medidaSinal({ pattern: "Iceberg", confidence: 0.84, acerto }), ["acerto", "41% · +1,0 tick", "41%"]);
assert.deepEqual(medidaSinal({ pattern: "Iceberg", confidence: 0.84, acerto: { ...acerto, ganho: -0.07 } }),
  ["acerto", "41% · −0,1 tick", "41%"]);
assert.deepEqual(medidaSinal({ pattern: "Absorção", confidence: 0.84, acerto: null }), ["força", "84%", "84%"]);

// Book: níveis que cabem, rótulo da fonte, quantidade e corretoras
assert.equal(linhasQueCabem(0), 12);
assert.equal(linhasQueCabem(240), 12);
assert.equal(linhasQueCabem(600), 15);   // teto de 15 níveis por lado
assert.equal(linhasQueCabem(30), 3);     // piso de 3
assert.equal(rotuloFonteBook({ depth: "full", fonte: "ofertas" }), "livro completo");
assert.equal(rotuloFonteBook({ depth: "top", fonte: "topo" }), "só topo");
assert.equal(rotuloFonteBook({ depth: "none" }), "sem livro nesta fonte");
assert.equal(rotuloFonteBook({ depth: "full" }), "níveis agregados");   // formato antigo, sem fonte
assert.equal(qtdBook(7900), "7.900");
assert.equal(qtdBook(250000), "250 mil");
assert.equal(qtdBook(1250000), "1,3 mi");
assert.equal(qtdBook(undefined), "—");
assert.equal(corretorasBook([["UBS", 3000], ["XP", 2000], ["BTG", 900], ["ITAU", 10]]), "UBS, XP, BTG");
assert.equal(corretorasBook([["UBS", 3000], ["XP", 2000]], true), "UBS");
assert.equal(corretorasBook(undefined), "—");   // formato antigo {price, qty, broker}
assert.equal(corretorasBook([]), "—");

// Radar: texto da situação de cada iceberg
const reg = { situacao: "segurou", segurou_as: 1792155600, rompeu_as: null, desfecho_as: 1792155600 };
assert.equal(textoSituacao(reg), "segurou às 10:00:00");
assert.equal(textoSituacao({ ...reg, rompeu_as: 1792159200 }), "segurou às 10:00:00, rompeu às 11:00:00");
assert.equal(textoSituacao({ situacao: "rompeu", segurou_as: null, rompeu_as: 1792155600, desfecho_as: 1792155600 }),
  "rompeu às 10:00:00");
assert.equal(textoSituacao({ situacao: "segurando" }), "segurando");
assert.equal(textoSituacao({ situacao: "virou sniper", desfecho_as: 1792155600 }), "virou sniper às 10:00:00");
const lr = linhaRadar({ ativo: "RENT3", corretora: "AGORA", lado: "compra", preco: 50.36, giros: 20, volume: 8500,
  confirmado_as: 1792155600, situacao: "segurando", acerto: { taxa: 0.408 } });
assert.equal(lr.classe, "destaque");
assert.deepEqual(lr.celulas.map((c) => c.t), ["RENT3", "AGORA", "compra", "50,36", "20", "8.500", "10:00:00", "segurando", "41%"]);

console.log("test_telas.mjs: tudo certo");
