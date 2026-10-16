# ProfitDLL — referência rápida (manual oficial v4.0.0.42)

Resumo do **Manual - ProfitDLL pt_br.pdf** (79 páginas, gerado em 2026-09-04) e dos exemplos oficiais
(Python, C#, C++) do pacote da Nelogica. As páginas citadas (`p.N`) são as do PDF. Os tipos do manual
estão em Delphi. A tabela de conversão está no fim deste documento.

> O pacote oficial **não** está no repositório. Lá estão a DLL, o manual e os exemplos, incluindo o `profitTypes.py`.
> Neste computador ele foi extraído na pasta temporária do Claude. Antes do primeiro uso, copie-o para um local fixo,
> por exemplo `C:\ProfitDLL\`.

---

## 1. Arquivos e plataforma

- O pacote 4.0.0.42 traz `DLLs\Win64\ProfitDLL.dll` e `DLLs\Win32\ProfitDLL.dll`. A p.6 ainda fala em `ProfitDLL64.dll`, nome
  antigo. O arquivo real se chama `ProfitDLL.dll` nas duas pastas.
- **64 bits:** a aplicação também precisa ser 64 bits. Não há problema conhecido com Python e a memória não tem limite (p.79).
- **32 bits:** o Python também precisa ser 32 bits, e o recomendado é o 3.6.2 por causa de um bug do ctypes com argumentos maiores
  que 32 bits. A memória fica limitada a 4 GB (p.79). **Use 64 bits.**
- **Convenção de chamada:** todas as funções e callbacks são `stdcall`, tanto em 32 quanto em 64 bits (p.51, p.79). No Python, isso
  significa `WinDLL` e `WINFUNCTYPE`. No x64 só existe uma convenção, mas `WINFUNCTYPE` continua sendo o correto.
- **Strings:** são `PWideChar`, ou seja, UTF-16. No ctypes, isso é `c_wchar_p`.

## 2. Inicialização (p.17–18, p.24–25, p.77–78)

Há duas funções de inicialização, e as duas retornam `Integer` (`NL_OK` = 0):

| Função | Serviços | Parâmetros, nesta ordem |
|---|---|---|
| `DLLInitializeLogin` | Roteamento e Market Data | `key, user, pass, State, History, OrderChange, Account, NewTrade, NewDaily, PriceBook, OfferBook, HistoryTrade, Progress, TinyBook` (14) |
| `DLLInitializeMarketLogin` | **Só Market Data** (o nosso caso) | `key, user, pass, State, NewTrade, NewDaily, PriceBook, OfferBook, HistoryTrade, Progress, TinyBook` (11) |

- `pwcActivationKey` é a chave de ativação recebida na contratação. `user` e `pass` são o login da conta Nelogica vinculada a essa
  chave (p.24, p.78).
- O manual chama esses callbacks de "obrigatórios" (p.78). Mesmo assim, os exemplos oficiais em Python e C# passam `None` (ou `null`)
  nos que serão trocados depois por `Set*Callback`. Por exemplo, NewTrade (V1) é substituído por `SetTradeCallbackV2` e HistoryTrade
  (V1) por `SetHistoryTradeCallbackV2`.
- Todo `Set*Callback` **substitui** o callback passado na inicialização (p.33–34). Os exemplos oficiais chamam os `Set*` **logo
  depois** de `DLLInitialize*`, sem esperar a conexão.
- O exemplo em C# pede a chave como "Activation Key (Optional)". O manual não diz em lugar nenhum que ela é opcional, então isso
  **não é garantido**.
- `SetServerAndPort` só deve ser usada com orientação da Nelogica e precisa ser chamada antes da inicialização (p.26).
- `SetEnabledLogToDebug(1)` liga o log de debug da DLL (p.31).

### Estado da conexão (TStateCallback, p.15–16, p.57–58)

Assinatura: `TStateCallback(nConnStateType: Integer; nResult: Integer)`, `stdcall`. No ctypes: `WINFUNCTYPE(None, c_int, c_int)`.

| `nConnStateType` | Significado | Valores de `nResult` |
|---|---|---|
| 0 `CONNECTION_STATE_LOGIN` | Servidor de login | 0 conectado · 1 login inválido · 2 senha inválida · 3 senha bloqueada · 4 senha expirada · 200 erro interno |
| 1 `CONNECTION_STATE_ROTEAMENTO` | Roteamento (só com `DLLInitializeLogin`) | 0 desconectado · 1 conectando · 2 conectado · 3 corretora desconectada · 4 corretora conectando · 5 corretora conectada |
| 2 `CONNECTION_STATE_MARKET_DATA` | Market Data | 0 desconectado · 1 conectando · 2 aguardando · 3 não logado · **4 conectado** · 5 `PERFORMANCE_WARNING` (servidor degradado) · 6 `PARTIAL_CONNECTED` |
| 3 `CONNECTION_STATE_MARKET_LOGIN` | **Ativação** | **0 válida** · 1 inválida |

- **A conexão está pronta** quando chegam (0,0), (2,4) e (3,0). Com roteamento, também (1,2) (p.58).
- O estado **(2,6)** quer dizer que o feed do servidor está OK, mas **o cliente não está consumindo os callbacks**. É um aviso
  crítico: dados podem ter atrasado ou se perdido. Quando a situação normaliza, volta (2,4) (p.58, versão 4.0.0.39).
- Desde a 4.0.0.41 existe um *watchdog* das threads internas. `SetHealthCallback` recebe um `TSystemHealthCallback(nState)` com
  0 = responsiva e 1 = travada. `GetHealthStatus(var nState)` faz a mesma consulta sob demanda e responde mesmo com a DLL travada
  (p.1, p.26–27, p.58).
- `SetStateCallback` substitui o callback de estado da inicialização (p.33).
- **Quando chamar `SubscribeTicker`:** o manual não fixa um estado. Os exemplos esperam o market conectado: o Python espera (2,4) e
  o C++ usa `bMarketConnected`. A regra segura é esperar (0,0), (2,4) e (3,0).

## 3. Threading dos callbacks (p.51, p.78)

- Os callbacks rodam na thread interna **ConnectorThread**, que é diferente da thread principal. Para compartilhar dados entre as
  duas, é preciso lock ou fila.
- A DLL coloca todos os dados numa **fila única**. Um callback lento atrasa *tudo*, inclusive trades. A orientação é repassar o dado
  para outra thread e evitar disco e banco de dados dentro do callback (p.78). Callback lento é justamente a causa do estado (2,6).
- **Regra principal (p.78):**
  - **Nunca** chame **funções de requisição** dentro de um callback: envio de ordem, `GetHistoryTrades`, `Subscribe*` etc. Isso causa
    exceções e comportamento indefinido.
  - **Funções acessórias**, que servem para materializar o dado recebido, **devem** ser chamadas de forma síncrona dentro do próprio
    callback. Exemplos: `TranslateTrade`, `GetPriceGroup`, `GetPriceDepthSideCount`, `GetTheoreticalValues`, `GetOrderDetails`.
  - A p.51 diz de forma genérica: "outras funções da DLL não devem ser utilizadas dentro de um callback". A p.78, mais recente
    (4.0.0.39), faz a distinção acima.

## 4. Trades em tempo real (p.35, p.49–50, p.57, p.14)

- `SubscribeTicker(ticker, bolsa)` e `UnsubscribeTicker(ticker, bolsa)`. Ticker inválido dispara o callback de
  `SetInvalidTickerCallback` (p.27).
- **V2, o recomendado:** `SetTradeCallbackV2(TConnectorTradeCallback)`. O callback V1 (`SetTradeCallback`) está **depreciado** (p.33).
  - `TConnectorTradeCallback(const a_Asset: TConnectorAssetIdentifier; const a_pTrade: Pointer; const a_nFlags: Cardinal)`, `stdcall`.
    O exemplo em Python usa `WINFUNCTYPE(None, TConnectorAssetIdentifier, c_size_t, c_uint)` (p.57).
  - O ponteiro `a_pTrade` é opaco. Para lê-lo, chame **`TranslateTrade(a_pTrade, var TConnectorTrade)`** dentro do callback, com
    `Version = 0`. A função retorna `NL_OK` (0) em caso de sucesso (p.22, p.49–50).
  - **Flags** (p.16, p.35): `TC_IS_EDIT = 1`, quando o trade é uma **edição** de um negócio já enviado, e `TC_LAST_PACKET = 2`, só no
    histórico V2.
- **`TConnectorTrade`** (p.14, `profitTypes.py`):

  | Campo | Delphi | ctypes | Observação |
  |---|---|---|---|
  | `Version` | Byte | `c_ubyte` | Enviar 0 |
  | `TradeDate` | TSystemTime | `SystemTime` (8 × `c_ushort`: wYear, wMonth, **wDayOfWeek**, wDay, wHour, wMinute, wSecond, wMilliseconds) | O fuso **não é informado** |
  | `TradeNumber` | Cardinal | `c_uint` | Único por pregão (p.59) |
  | `Price` | Double | `c_double` | Preço de execução |
  | `Quantity` | Int64 | `c_longlong` | Quantidade |
  | `Volume` | Double | `c_double` | Volume financeiro |
  | `BuyAgent` / `SellAgent` | Integer | `c_int` | Código da corretora **compradora** e **vendedora** |
  | `TradeType` | Byte | `c_ubyte` | Ver `TTradeType` abaixo |

- **TTradeType** (p.59, `profitTypes.TTradeType`): 1 cross · **2 agressão de compra** · **3 agressão de venda** · 4 leilão ·
  5 surveillance · 6 expit · 7 exercício de opções · 8 balcão · 9 termo · 10 índice · 11 BTC · 12 on behalf · 13 RLP · 14 BBT ·
  15 RFQ · 16 MPT · 17 TAC · 18 TAA · 32 desconhecido · 33 update · 34 mid · 35 off exchange.
- **Edição de negócio:**
  - No V1, o `bEdit` indica edição, e o identificador do negócio editado é o `pwcDate` (p.59).
  - No V2, a edição chega pela flag `TC_IS_EDIT`.
  - O manual **não descreve cancelamento de negócio**. O único mecanismo documentado é a edição.
- **Callback V1** (`TNewTradeCallback`, p.51 e p.59): data como texto `DD/MM/YYYY HH:mm:SS.ZZZ`, `nQtd` Integer e `bEdit` Char.
  Está depreciado.
- **Correção 4.0.0.38:** o `SetTradeCallbackV2` às vezes parava de receber trades (p.2). Use a versão 4.0.0.38 ou mais nova.

## 5. Histórico de trades (p.20–21, p.30, p.35, p.54, p.66–67)

- `GetHistoryTrades(ticker, bolsa, dtDateStart, dtDateEnd): Integer`. As datas são `PWideChar` no formato
  **`DD/MM/YYYY HH:mm:SS`**, por exemplo `'06/08/2018 09:00:00'` (p.30). É uma **função de requisição**: não pode ser chamada
  dentro de um callback.
- **Limites (p.30):**
  - Se `dtDateStart` for **mais de 30 dias** anterior à data do servidor, a DLL retorna `NL_HISTORY_PERIOD_LIMIT` (0x8000002E = −2147483602).
  - Para tickers que começam com **WIN ou WDO**, o intervalo entre início e fim **não pode chegar a 10 dias**. Se chegar, a DLL
    retorna `NL_INVALID_ARGS`.
  - Para ações (PETR4), o manual **não** define limite de intervalo, só o de 30 dias.
- **Como os dados chegam:**
  - **V1:** `THistoryTradeCallback(rAssetID: TAssetIDRec; pwcDate; nTradeNumber: Cardinal; dPrice, dVol: Double; nQtd, nBuyAgent,
    nSellAgent, nTradeType: Integer)`. Um callback por negócio, com a data em texto `DD/MM/YYYY HH:mm:SS.ZZZ` (p.54, p.66).
    Pode ser registrado na inicialização ou com `SetHistoryTradeCallback` (p.33).
  - **V2:** `SetHistoryTradeCallbackV2(TConnectorTradeCallback)` mais `TranslateTrade`. A flag **`TC_LAST_PACKET` (2)** marca **o
    último trade do histórico** (p.35). É o marcador de fim explícito, e é o que os exemplos oficiais em Python e C# usam.
- **Progresso:** `TProgressCallback(rAssetID: TAssetIDRec; nProgress: Integer)`, de 1 a 100 (p.30, p.66–67). Pode ser registrado
  na inicialização ou com `SetSerieProgressCallback` (p.34).
- **Como saber que terminou:** o mais confiável é `TC_LAST_PACKET` no V2. Progresso 100 também é documentado (p.30). O manual
  **não diz** o que acontece num período sem negócios, como um feriado: não se sabe se chega progresso 100 ou `TC_LAST_PACKET`.
- **Correção 4.0.0.35:** exceção na notificação de download de trades (p.2).

## 6. Livro (book)

### Topo do livro: TinyBook (p.54, p.67)
- Callback `TTinyBookCallback(rAssetID: TAssetIDRec; dPrice: Double; nQtd: Integer; nSide: Integer)`. No ctypes:
  `WINFUNCTYPE(None, TAssetID, c_double, c_int, c_int)`.
- **`nSide`: 0 = compra (bid), 1 = venda (ask)** (p.67).
- O agente não vem no TinyBook. Pode ser registrado na inicialização ou com `SetTinyBookCallback` (p.23).

### Livro de ofertas (offer book)
- `SubscribeOfferBook` e `UnsubscribeOfferBook` (p.28). Use o callback **V2**, registrado com `SetOfferBookCallbackV2` (p.33).
- `TOfferBookCallbackV2` (p.53, p.64–66) recebe estes parâmetros: `rAssetID, nAction, nPosition, Side, nQtd: Int64, nAgent, nOfferID: Int64,
  dPrice, bHasPrice..bHasAgent: Char, pwcDate, pArraySell, pArrayBuy`.
  - Atenção: o exemplo em Python declara `nQtd` como `c_int`, mas o correto é `c_int64`.
  - A tabela da p.65 diz que `nOfferID` é Integer, mas a assinatura e o layout dizem Int64.
- **Ações (`nAction`)** (p.8, p.61): `atAdd = 0`, `atEdit = 1`, `atDelete = 2`, `atDeleteFrom = 3`, `atFullBook = 4`.
  - A posição é contada **a partir do fim da lista**: índice = `size - nPosition - 1` (p.61).
  - `atAdd` insere depois da posição. `atDelete` apaga a posição. `atDeleteFrom` apaga dessa posição em diante. `atEdit` atualiza a
    posição. `atFullBook` reconstrói o livro a partir de `pArrayBuy` e `pArraySell`.
- **Layout do array no FullBook V2** (p.65–66):
  - Cabeçalho: `Q: int32`, `tamanho: int32`.
  - Q entradas de `price: double`, `qty: int64`, `agent: int32`, `offerID: int64`, `T: uint16` e `T bytes` de data.
  - Rodapé no offset `Q*53 + 8`, com `flags: uint32`. O 53 supõe uma data de 23 bytes, em ANSI e não UTF-16. O exemplo oficial lê com
    `struct.unpack('=dqiqH')` e decodifica com `'ansi'`.
  - Flags: `OB_LAST_PACKET = 1` (última página) e `OB_FIRST_PACKET = 2` (adicionada na 4.0.0.36).
  - No V1, cada entrada tem 49 bytes (p.64).

### Livro de preços
- `SubscribePriceBook`, `TPriceBookCallback` e `TPriceBookCallbackV2` estão **depreciados** (p.28, p.33, p.61). Foram substituídos
  por `SubscribePriceDepth` mais `SetPriceDepthCallback` (p.22, p.35, p.50–51).
- `TConnectorPriceDepthCallback(a_AssetID, a_Side: Byte, a_nPosition: Integer, a_UpdateType: Byte)` (p.57). O callback só avisa que
  algo mudou. Os dados são lidos dentro dele, com `GetPriceDepthSideCount` e `GetPriceGroup(asset, side, pos, PConnectorPriceGroup)`.
- `UpdateType` (p.8): 0 add, 1 edit, 2 delete, 3 insert, 4 fullbook, 5 prepare, 6 flush, 7 preço teórico, 8 deleteFrom. Quando há
  várias mudanças seguidas, a DLL manda Prepare antes e Flush depois (p.35).
- No leilão, a posição 0 é a entrada teórica: o preço vem como −INF e o valor real se obtém com `GetTheoreticalValues` (p.50–51).
- `TConnectorPriceGroup` (p.10): `Version: Byte, Price: Double, Count: Cardinal, Quantity: **Int64**, PriceGroupFlags: Cardinal`.
  O **`profitTypes.py` oficial declara `Quantity` como `c_long`**, que tem 32 bits no Windows. Isso **erra o layout**: se for usar o
  PriceDepth, corrija para `c_int64`.

## 7. Código → nome da corretora (p.18, p.29–30)

- `GetAgentNameLength(nAgentID: Integer; nShortName: Cardinal): Integer` retorna o tamanho do nome.
- `GetAgentName(nCount: Integer; nAgentID: Integer; pwcAgent: PWideChar; nShortName: Cardinal): Integer` copia o nome no buffer.
  - O primeiro argumento é o **tamanho**. `nShortName = 1` (`CM_IS_SHORT_NAME`) devolve o nome abreviado.
  - O exemplo em Python faz `create_unicode_buffer(GetAgentNameLength(id, flag))`. Na prática, use **+1 para o terminador**.
  - A 4.0.0.36 corrigiu o tamanho que a função retorna (p.2).
- `GetAgentNameByID` e `GetAgentShortNameByID` retornam `PWideChar` direto, mas estão **depreciadas** (p.29).

## 8. Ticker e bolsa (p.15, p.29)

- O formato é `Ticker: PETR4, Bolsa: B` ou `Ticker: WINFUT, Bolsa: F` (p.29).
- Códigos de bolsa (p.15): A = BCB, **B = Bovespa**, D = câmbio, E = economic, **F = BMF**, K = metrics, M = CME, N = Nasdaq,
  O = OXR, P = Pioneer, X = Dow Jones, Y = NYSE.
- Em `TAssetIDRec` e `TAssetID` (p.7), `nFeed` vale 0 para Nelogica e 255 para outro. Em `TConnectorAssetIdentifier` (p.9–10),
  `FeedType: Byte` também vale 0.
- A 4.0.0.24 retirou o limite de tamanho do ticker (p.4).

## 9. Códigos de erro (p.16–17)

`NL_OK = 0`. Os erros são negativos (0x8000xxxx como int32):

| Código | Hex | Dec | Significado |
|---|---|---|---|
| NL_INTERNAL_ERROR | 0x80000001 | −2147483647 | Erro interno |
| NL_NOT_INITIALIZED | 0x80000002 | −2147483646 | Não inicializado |
| NL_INVALID_ARGS | 0x80000003 | −2147483645 | Argumentos inválidos |
| NL_WAITING_SERVER | 0x80000004 | −2147483644 | Aguardando servidor |
| NL_NO_LOGIN | 0x80000005 | −2147483643 | Nenhum login |
| NL_NO_LICENSE | 0x80000006 | −2147483642 | Nenhuma licença |
| NL_OUT_OF_RANGE | 0x80000009 | −2147483639 | Count maior que o array |
| NL_MARKET_ONLY | 0x8000000A | −2147483638 | Sem roteamento |
| NL_NOT_FOUND | 0x8000000C | −2147483636 | Recurso não encontrado |
| NL_VERSION_NOT_SUPPORTED | 0x8000000D | −2147483635 | Versão de struct não suportada |
| NL_EXCHANGE_UNKNOWN | 0x8000000F | −2147483633 | Bolsa desconhecida |
| NL_LICENSE_NOT_ALLOWED | 0x80000012 | −2147483630 | Recurso não liberado na licença |
| NL_SERIE_NO_HISTORY / NO_DATA / NO_MORE_HISTORY / MAX_COUNT | 0x80000014/16/18/19 | | Séries |
| NL_UNSIGNED_CONTRACT | 0x8000001B | −2147483621 | **Contrato não assinado** |
| NL_NO_PASSWORD / NL_NO_USER | 0x8000001C / 1D | | Senha ou usuário vazio |
| NL_INVALID_TICKER | 0x8000001F | −2147483617 | Ativo inválido |
| NL_HISTORY_PERIOD_LIMIT | 0x8000002E | −2147483602 | Histórico com início a mais de 30 dias |

- Os códigos 0x80000007 e 0x80000008 aparecem só no exemplo em Python, como `NL_PASSWORD_HASH_SHA1` e `NL_PASSWORD_HASH_MD5`.
- O exemplo em Python não tem `NL_HISTORY_PERIOD_LIMIT`.
- O manual às vezes usa nomes antigos (`NL_ERR_INIT`, `NL_ERR_INVALID_ARGS`, p.25 e p.27).

## 10. Finalização (p.18, p.26)

- `DLLFinalize: Integer` encerra os serviços da DLL. Antes, faça os `Unsubscribe*`.
- Os callbacks ctypes precisam continuar vivos (referenciados no Python) até `DLLFinalize` retornar.

## 11. Licença e ativação

- A chave de ativação é recebida na contratação. O login é o usuário e a senha da conta Nelogica (p.78).
- A validade da chave chega pelo callback de estado (3,0) ou (3,1).
- Recursos fora do plano contratado retornam `NL_LICENSE_NOT_ALLOWED`. Contrato não assinado retorna `NL_UNSIGNED_CONTRACT`. A falta
  de licença retorna `NL_NO_LICENSE` (p.16–17).

## 12. Outras funções úteis só para Market Data

- `GetServerClock(var dtDate: Double; var nYear..nMilisec: Integer)` dá o relógio do servidor (TDateTime do Delphi) e só pode ser
  chamada depois da inicialização (p.26). Serve para conferir o fuso e o atraso do `TradeDate`.
- `SetChangeStateTickerCallback` informa o estado do ativo (p.32, p.75): 0 aberto, 2 congelado, 3 inibido, 4 **leilão**,
  6 fechado, 10 pré-fechamento e 13 pré-abertura.
- `SetTheoreticalPriceCallback` e `GetTheoreticalValues` dão o preço teórico no leilão (p.32, p.51).
- `GetLastDailyClose` dá o fechamento anterior. Exige `SubscribeTicker` antes, e a primeira chamada retorna `NL_WAITING_SERVER` (p.27).
- `RequestTickerInfo` mais `SetAssetListInfoCallbackV2` trazem lote, tick mínimo e ISIN (p.31–32, p.54–55).

## 13. Tipos Delphi → ctypes (x64)

| Delphi | ctypes |
|---|---|
| Integer | `c_int` (32) |
| Cardinal | `c_uint` |
| Int64 | `c_int64` / `c_longlong` |
| Byte | `c_ubyte` |
| Double | `c_double` |
| PWideChar | `c_wchar_p` |
| Pointer | `c_void_p` / `c_size_t` |
| Char (callbacks V1) | Unicode Delphi: WideChar (2 bytes). No x64, ocupa um *slot* de 8 bytes de qualquer forma |
| TSystemTime | struct com 8 `c_ushort` |
| record por valor em callback (`TAssetIDRec`, `TConnectorAssetIdentifier`) | Passe a `Structure` por valor no `WINFUNCTYPE`, como no exemplo oficial |
