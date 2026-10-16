# Fluxo Server · tokens v3 (Terminal + manchete)

Valores tirados de `_gerador-v3.py` (dicionário `PAL`). A tabela de contraste é gerada pelo próprio gerador (`python _gerador-v3.py tokens - saida.md`), com a fórmula de luminância relativa do WCAG 2.x. Os limites são 4,5:1 para texto e 3:1 para elementos gráficos que carregam informação. Hairlines e grade não carregam informação sozinhas (a estrutura também vem do alinhamento), então ficam como decorativas.

## Cores: escuro × claro

| Token | Uso | Escuro | Contraste no fundo | Claro | Contraste no fundo | Mínimo |
|---|---|---|---|---|---|---|
| `text` | Texto principal, números | `#ECE7DC` | 15.56:1 ok | `#1C1B18` | 15.12:1 ok | 4.5:1 (texto) |
| `muted` | Rótulos, texto secundário | `#A39D90` | 7.11:1 ok | `#57534A` | 6.73:1 ok | 4.5:1 (texto) |
| `faint` | Metadados, eixos, hora em tabela | `#928C80` | 5.74:1 ok | `#66615A` | 5.39:1 ok | 4.5:1 (texto) |
| `accent` | Estado e seleção (âmbar) | `#E3A33B` | 8.74:1 ok | `#8A5000` | 5.71:1 ok | 4.5:1 (texto) |
| `buy` | Compra (texto e candle) | `#4FBF7F` | 8.31:1 ok | `#176C40` | 5.66:1 ok | 4.5:1 (texto) |
| `sell` | Venda (texto e candle) | `#E8604C` | 5.67:1 ok | `#B0352A` | 5.44:1 ok | 4.5:1 (texto) |
| `volBuy` | Barras de volume/livro/saldo, compra | `#357951` | 3.66:1 ok | `#50936E` | 3.21:1 ok | 3.0:1 (gráfico) |
| `volSell` | Barras de volume/livro/saldo, venda | `#A74839` | 3.32:1 ok | `#C46D63` | 3.23:1 ok | 3.0:1 (gráfico) |
| `rule` | Hairline estrutural 1px | `#2C2A25` | 1.34:1 | `#D2CBBC` | 1.42:1 | decorativo |
| `grid` | Grade do gráfico | `#1C1B18` | 1.11:1 | `#E5E0D4` | 1.16:1 | decorativo |
| `raise` | Fundo de linha destacada | `#1A1915` | 1.09:1 | `#E8E3D7` | 1.12:1 | superfície |

Contraste sobre superfícies destacadas (pior caso):

| Par | Escuro | Claro |
|---|---|---|
| `muted` sobre `raise` | 6.52:1 | 5.98:1 |
| `faint` sobre `raise` | 5.26:1 | 4.79:1 |
| `accent` sobre `raise` | 8.01:1 | 5.08:1 |
| `buy` sobre `raise` | 7.62:1 | 5.04:1 |
| `sell` sobre `raise` | 5.20:1 | 4.84:1 |
| `text` sobre linha de lote grande (`buy` a 13% no escuro, 10% no claro) | 12.80:1 | 13.16:1 |
| `text` sobre linha de lote grande (`sell` a 13% no escuro, 10% no claro) | 13.50:1 | 13.02:1 |
| `muted` sobre linha de lote grande (`buy` a 13% no escuro, 10% no claro) | 5.85:1 | 5.85:1 |
| `muted` sobre linha de lote grande (`sell` a 13% no escuro, 10% no claro) | 6.17:1 | 5.79:1 |
| `buy` sobre linha de lote grande (`buy` a 13% no escuro, 10% no claro) | 6.83:1 | 4.93:1 |
| `sell` sobre linha de lote grande (`sell` a 13% no escuro, 10% no claro) | 4.92:1 | 4.68:1 |
| `inv` sobre botão primário (`text`) | 15.56:1 | 15.12:1 |

### Ajustes de acessibilidade em relação à v2
- `faint` passou de `#6F6A60` (3,57:1) para `#928C80` no escuro, e de `#8A8578` (3,23:1) para `#66615A` no claro. Antes, metadados e eixos ficavam abaixo de 4,5:1.
- O âmbar `#E3A33B` fica só no escuro. No papel ele dá 1,93:1, então o claro usa `#8A5000` (5,71:1), o mesmo matiz escurecido.
- O verde do claro passou para `#176C40`, porque o `#1A7445` dava 4,46:1 sobre a linha de lote grande.
- As barras de volume, livro e saldo deixaram de usar alfa e ganharam tokens sólidos próprios (`volBuy`/`volSell`), com pelo menos 3:1 nos dois temas. Isso corrige as barras fracas do claro na v2, que usavam alfa de 45% e ficavam em torno de 1,9:1.

## Regras de uso

### Âmbar (`accent`): só estado e seleção
- Tela ativa, modo ativo (ao vivo/replay), timeframe, filtro, ordenação e velocidade selecionados: sublinhado de 2px.
- Estado de conexão: quadrado de 6 a 8px ao lado do texto. Nunca use círculo com brilho.
- Rótulo "Sinal ativo", linha selecionada (fio de 3px à esquerda + fundo `raise`), "reproduzindo", "baixando", "repetindo", "aguardando".
- Avisos e erros do log (`aviso`, `erro`), janela (2,6) no gráfico e TC_IS_EDIT.
- Valor proposto que difere do atual na Calibração.
- **Nunca** use âmbar como cor de série, em barra grande, em fundo de bloco ou em texto decorativo. Em gráficos, a série "proposta" usa `text` e a "atual" usa `faint`.

### Verde e vermelho (`buy`/`sell`): só compra e venda
- Candles, ▲/▼, letras A/E/I das marcas, preço do sinal na manchete ("em 38,40"), agressor C/V, preço no livro, saldo positivo e negativo, delta, variação do dia.
- Não use verde para "conectado/ok" nem vermelho para "erro/desconectar". Estado é âmbar + texto, e ação destrutiva é botão neutro com rótulo claro.
- O fundo de linha de lote grande é `buy`/`sell` a 13% no escuro e 10% no claro, e o texto em cima continua com `text`.

### Botões e campos
- São retos (raio 0) e usam contorno de 1px. Há três tipos: **primário** (fundo `text`, rótulo `inv`, só um por área: "Aplicar ao vivo", "Baixar 10 dias úteis", "pausar"), **secundário** (contorno `faint`, rótulo `text`) e **desabilitado** (contorno `rule`, rótulo `faint`).
- Link de ação ("+ Assinar ativo", "Ver no log", "Reproduzir", "Calibrar", "Cancelar") é texto Medium, sem caixa.
- Campos de formulário têm contorno `rule` de 1px, valor em Mono 13 e rótulo à esquerda em `muted`, como numa tabela de chave e valor.

## Tipografia

| Papel | Família | Tamanho/peso | Onde |
|---|---|---|---|
| Número-herói | Plex Sans Medium, `tnum` | 56 (cotação, hora do replay), 44 (progresso do grid), 30 (estado da DLL) | um por tela, na faixa do topo |
| Manchete do sinal | Plex Sans SemiBold + Regular | 38/44 (tipo + "em preço" na cor da direção) | Operar, topo da coluna direita |
| Métrica da faixa | Plex Sans Medium | 23/28 (Operar), 16 a 20/28 (telas de apoio) | colunas da faixa de 80px |
| Frase explicativa | Plex Sans Regular | 15/22 `muted` | sob a manchete |
| Título de seção | Plex Sans SemiBold | 13/18 | sem caixa alta, sem tracking |
| Corpo e rótulo | Plex Sans Regular | 13 (tabela), 12 (rótulo de coluna e metadado) | caixa normal |
| Tabela, eixo, hora, log, código | Plex Mono Regular/Medium/SemiBold | 13 (linhas), 12 (log, caminhos), 11 (eixos, chaves de config) | números alinhados à direita |

- Só duas coisas são grandes por tela: o número-herói e, no Operar, a manchete. O resto fica entre 11 e 15px.
- SemiBold em tabela marca exceção (lote grande, linha proposta), nunca decoração.
- Nada de caixa alta espaçada. Siglas reais (PETR4, DLL, VWAP, TC_IS_EDIT) ficam como são.

## Grade e espaçamento
- O quadro tem 1920×1080 e usa estas faixas: barra de topo de **32px** (0 a 32), faixa-resumo de **80px** (32 a 112), corpo de **940px** (112 a 1052) e rodapé de **28px** (1052 a 1080, com atalhos F1 a F4 e T).
- Gutter lateral de **16px**. As colunas são separadas por hairline de 1px, sem gap nem card.
- Divisão principal em **x = 1180** (gráfico ou conteúdo principal | coluna de apoio de 740px) no Operar, na Conexão e no Replay. A Calibração usa três colunas: 0–600 | 600–1380 | 1380–1920.
- Cabeçalho de seção: título no topo da seção + 9px. A linha de rótulos de coluna fica 36px abaixo do início da seção, com hairline 20px abaixo dela.
- Alturas de linha: 19 a 23px nas tabelas densas (fita, livro, log do Operar), 26 a 27px no log e na fila, 36 a 44px nas tabelas de leitura (resultados, biblioteca), 46px no formulário de parâmetros.
- Na faixa de 80px, cada métrica tem rótulo de 12px em y=44 e valor em y=64, separados por fio vertical de 56px.
- Gráficos: grade em `grid`, eixo em Mono 11 `faint` à direita, VWAP tracejado 5/4 em `muted`, cursor e janelas em âmbar de 1 a 3px.

## Proibido (motivo da v1 ser rejeitada)
Card arredondado, sombra, glow, gradiente, pílula/chip/badge, ícone decorativo, sparkline decorativa, CAIXA ALTA espaçada, ciano.
