# Bibliotecas de terceiros embutidas

O dashboard funciona sem internet, então as bibliotecas ficam dentro do repositório.

## TradingView Lightweight Charts

| campo | valor |
| --- | --- |
| versão | 5.2.1 (publicada em 2026-08-12) |
| arquivo | `lightweight-charts.standalone.production.js` |
| origem | https://unpkg.com/lightweight-charts@5.2.1/dist/lightweight-charts.standalone.production.js |
| sha256 | `e21cc5caa0226ef30bd8549c50b9ef926615f2a4ee6b4e486353477a55f598cf` |
| licença | Apache License 2.0 — texto em `LICENSE-lightweight-charts.txt` (copiado do pacote) |
| projeto | https://github.com/tradingview/lightweight-charts |

O cabeçalho do arquivo mantém o aviso de copyright e a licença. A Apache 2.0 pede que o aviso
de atribuição ("TradingView Lightweight Charts™, Copyright TradingView, Inc.") continue visível
na distribuição; o dashboard mostra o logo/atribuição padrão da biblioteca (`attributionLogo`).

Para atualizar: baixar a nova versão exata do unpkg, conferir o cabeçalho, recalcular o sha256
e revisar a API usada em `dashboard.html` (v5: `chart.addSeries(CandlestickSeries, …)`,
`createSeriesMarkers`).
