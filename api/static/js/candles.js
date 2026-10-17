// Busca incremental de candles (puro: testado em tools/test_telas.mjs).

/**
 * `since` do próximo GET /candles: volta UM candle antes do último já visto.
 * Um negócio atrasado (comum na DLL e no replay) muda o candle anterior; sem essa volta,
 * ele ficaria velho na tela e a VWAP/delta do gráfico se afastariam dos da faixa.
 */
export function sinceCandles(ultimoTempo, tf) {
  return ultimoTempo == null ? null : ultimoTempo - tf;
}

const CAMPOS = ["open", "high", "low", "close", "volume", "buy", "sell", "financeiro"];
const igual = (a, b) => CAMPOS.every((k) => a[k] === b[k]);

/**
 * Junta candles novos ou alterados aos que já existem, substituindo pelo `time`, em ordem.
 * Sem mudança real devolve o MESMO array: o gráfico compara a referência e não redesenha à toa
 * (o since repete os dois últimos candles a cada consulta de 500 ms).
 */
export function juntarCandles(existentes, novos) {
  const porTempo = new Map(existentes.map((c) => [c.time, c]));
  let mudou = false;
  for (const c of novos) {
    const atual = porTempo.get(c.time);
    if (!atual || !igual(atual, c)) { porTempo.set(c.time, c); mudou = true; }
  }
  return mudou ? [...porTempo.values()].sort((a, b) => a.time - b.time) : existentes;
}

/** O engine foi zerado (POST /reset ou virada do dia) desde a última leitura? */
export function precisaLimpar(geracaoVista, geracaoAtual) {
  return geracaoVista != null && geracaoAtual !== geracaoVista;
}
