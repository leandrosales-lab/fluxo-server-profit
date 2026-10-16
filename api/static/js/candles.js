// Busca incremental de candles (puro: testado em tools/test_telas.mjs).

/**
 * `since` do próximo GET /candles: volta UM candle antes do último já visto.
 * Um negócio atrasado (comum na DLL e no replay) muda o candle anterior; sem essa volta,
 * ele ficaria velho na tela e a VWAP/delta do gráfico se afastariam dos da faixa.
 */
export function sinceCandles(ultimoTempo, tf) {
  return ultimoTempo == null ? null : ultimoTempo - tf;
}

/** Junta candles novos ou alterados aos que já existem, substituindo pelo `time`, em ordem. */
export function juntarCandles(existentes, novos) {
  const porTempo = new Map(existentes.map((c) => [c.time, c]));
  for (const c of novos) porTempo.set(c.time, c);
  return [...porTempo.values()].sort((a, b) => a.time - b.time);
}
