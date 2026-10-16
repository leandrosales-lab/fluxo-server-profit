// Gráfico do Operar: candles, VWAP tracejada, volume por lado e delta acumulado (Lightweight Charts 5.2.1).
import { horaB3, hm, preco, compacto } from "./formato.js";

const LW = window.LightweightCharts;
const LETRA = { "Absorção": "A", "Exaustão": "E", "Iceberg": "I", "Urgência": "U", "BestOffer": "O" };
const cor = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();

function opcoesTema(casas) {
  return {
    layout: {
      background: { type: "solid", color: cor("--bg") }, textColor: cor("--faint"),
      fontFamily: "IBM Plex Mono", fontSize: 11, attributionLogo: true,
      panes: { separatorColor: cor("--rule"), separatorHoverColor: cor("--rule") },
    },
    grid: { vertLines: { color: cor("--grid") }, horzLines: { color: cor("--grid") } },
    rightPriceScale: { borderColor: cor("--rule") },
    timeScale: { borderColor: cor("--rule"), timeVisible: true, secondsVisible: false, tickMarkFormatter: (t) => hm(t) },
    crosshair: {
      vertLine: { color: cor("--accent"), labelBackgroundColor: cor("--accent") },
      horzLine: { color: cor("--accent"), labelBackgroundColor: cor("--accent") },
    },
    // sem priceFormatter global: na v5 ele valeria para todas as séries (volume e delta têm formato próprio)
    localization: { locale: "pt-BR", timeFormatter: (t) => horaB3(t) },
  };
}
/** Formato de preço das séries: casas do tick e passo mínimo = tick do ativo (WDO anda de 0,5 em 0,5). */
const formatoPreco = (casas, tick) => ({ type: "custom", minMove: tick || 10 ** -casas, formatter: (p) => preco(p, casas) });

export function criarGrafico(el, casasIniciais) {
  let casas = casasIniciais;
  const chart = LW.createChart(el, { autoSize: true, ...opcoesTema(casas) });
  const velas = chart.addSeries(LW.CandlestickSeries, { borderVisible: false, priceLineStyle: LW.LineStyle.Dotted,
    priceFormat: formatoPreco(casas) });
  const vwap = chart.addSeries(LW.LineSeries, { lineWidth: 1, lineStyle: LW.LineStyle.Dashed, priceLineVisible: false,
    lastValueVisible: false, crosshairMarkerVisible: false, priceFormat: formatoPreco(casas) });
  const semSinal = (v) => compacto(v).replace("+", "");
  const volume = chart.addSeries(LW.HistogramSeries, { priceLineVisible: false, lastValueVisible: false,
    priceFormat: { type: "custom", formatter: semSinal } }, 1);
  const delta = chart.addSeries(LW.LineSeries, { lineWidth: 1, priceLineVisible: false,
    priceFormat: { type: "custom", formatter: compacto } }, 2);
  const marcas = LW.createSeriesMarkers(velas, []);
  chart.panes()[1].setHeight(110);
  chart.panes()[2].setHeight(190);

  let candles = [];   // ordenados por time
  let sinais = [];
  let tf = 60;

  function desenharMarcas() {
    const tempos = new Set(candles.map((c) => c.time));
    marcas.setMarkers(sinais.map((s) => {
      const t = Math.floor(s.timestamp / tf) * tf;
      const compra = s.signal === "BUY";
      return tempos.has(t) ? { time: t, position: compra ? "belowBar" : "aboveBar", shape: compra ? "arrowUp" : "arrowDown",
        color: cor(compra ? "--buy" : "--sell"), text: LETRA[s.pattern] || "?" } : null;
    }).filter(Boolean).sort((a, b) => a.time - b.time));
  }

  function redesenhar() {
    velas.setData(candles.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
    const vBuy = cor("--vol-buy"), vSell = cor("--vol-sell");
    let fin = 0, vol = 0, acum = 0;
    const vw = [], dl = [], vb = [];
    for (const c of candles) {
      fin += c.financeiro; vol += c.volume; acum += c.buy - c.sell;
      if (vol) vw.push({ time: c.time, value: fin / vol });
      dl.push({ time: c.time, value: acum });
      vb.push({ time: c.time, value: c.volume, color: c.buy >= c.sell ? vBuy : vSell });
    }
    vwap.setData(vw);
    delta.setData(dl);
    volume.setData(vb);
    desenharMarcas();
  }

  function aplicarCores() {
    chart.applyOptions(opcoesTema(casas));
    velas.applyOptions({ upColor: cor("--buy"), downColor: cor("--sell"), wickUpColor: cor("--buy"),
      wickDownColor: cor("--sell"), priceLineColor: cor("--text") });
    vwap.applyOptions({ color: cor("--muted") });
    delta.applyOptions({ color: cor("--text") });
    redesenhar();
  }
  window.addEventListener("tema", aplicarCores);
  aplicarCores();

  return {
    get tf() { return tf; },
    /** Troca o timeframe: limpa; o próximo /candles sem since recarrega o dia. */
    trocarTf(novo) { tf = novo; candles = []; redesenhar(); },
    /** Junta candles novos ou alterados (o since repete o último, que ainda pode mudar). */
    juntar(novos) {
      if (!novos.length) return;
      const porTempo = new Map(candles.map((c) => [c.time, c]));
      for (const c of novos) porTempo.set(c.time, c);
      candles = [...porTempo.values()].sort((a, b) => a.time - b.time);
      redesenhar();
    },
    limpar() { candles = []; sinais = []; redesenhar(); },
    ultimoTempo() { return candles.length ? candles[candles.length - 1].time : null; },
    ultimoCandle() { return candles[candles.length - 1] || null; },
    definirSinais(lista) { sinais = lista; desenharMarcas(); },
    /** Ajusta casas decimais e passo do eixo de preço ao tick do ativo (vem do /health). */
    definirCasas(n, tick) {
      casas = n;
      velas.applyOptions({ priceFormat: formatoPreco(casas, tick) });
      vwap.applyOptions({ priceFormat: formatoPreco(casas, tick) });
    },
  };
}
