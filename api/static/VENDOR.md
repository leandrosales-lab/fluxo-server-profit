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

## IBM Plex Sans e IBM Plex Mono

| campo | valor |
| --- | --- |
| versão | @ibm/plex-sans 1.1.0 e @ibm/plex-mono 1.1.0 (npm) |
| arquivos | `fonts/IBMPlexSans-{Regular,Medium,SemiBold}.woff2`, `fonts/IBMPlexMono-{Regular,Medium,SemiBold}.woff2` |
| origem | https://cdn.jsdelivr.net/npm/@ibm/plex-sans@1.1.0/fonts/complete/woff2/ (idem plex-mono) |
| licença | SIL Open Font License 1.1 — texto em `fonts/OFL.txt` (LICENSE.txt do pacote) |

sha256:

```
8c2c290cbd998fa1f647e4572aca6ebbd72589551b0f3f9f8bb8628fbb8219d5  fonts/IBMPlexMono-Medium.woff2
49ce58b41a0e1cb921c0f58d9a5b8b96a2cc21437c7066f3ba4f24873076d131  fonts/IBMPlexMono-Regular.woff2
ed5eaca7522336959d6c3810bd9bb78424f0d964082d581bfbea169ee08d14e3  fonts/IBMPlexMono-SemiBold.woff2
5660f8a658f8bb50dbc005232f885eadffd2bc1c235c4f6fbb63469d1f9cde6d  fonts/IBMPlexSans-Medium.woff2
ba711a3085ff9f27440b6b9c4550cfc47c97bf36591d5da958b975bb3add8c1a  fonts/IBMPlexSans-Regular.woff2
f78048030eab62e860efa39a0df79e2e5581bf122eb95b9bc42c0b8a4988d205  fonts/IBMPlexSans-SemiBold.woff2
7e6b2818edbd8f6a01ae80641cc8f16a51080d08fb4e532be3a0b6f74adb07da  fonts/OFL.txt
```

As telas carregam as fontes de `/static/fonts/` (funciona offline, sem Google Fonts).
