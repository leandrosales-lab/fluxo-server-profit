# Auditoria de `profitdll/bridge.py` e `profitdll/historico.py` contra o manual oficial

**Data:** 16/10/2026.

**Fonte de comparação:**
- Manual ProfitDLL pt_br, v4.0.0.42 (79 páginas).
- Exemplos oficiais em Python (`main.py`, `profit_dll.py`, `profitTypes.py`), C# (`ProfitDataTypes.cs`, `ProfitFunctions.cs`,
  `CallbackHandler.cs`, `Program.cs`) e C++ (`profit.h`, `main.cpp`).

O resumo do manual está em [profitdll-referencia.md](profitdll-referencia.md).

**Escopo:** só leitura. **Nenhum código foi alterado.** Os patches abaixo são propostas, e a decisão é sua.

**Classificação usada:**
- **CERTO:** confere com o manual e os exemplos.
- **ERRADO:** diverge do manual ou dos exemplos.
- **NÃO VERIFICÁVEL:** o manual e os exemplos não respondem; só o teste real com a DLL confirma.

---

## Resumo

O código foi escrito sem o manual, mas está **estruturalmente correto**:
- Assinaturas, tipos ctypes, convenção `stdcall`, layout das structs, ordem dos parâmetros da inicialização, uso de `TranslateTrade`
  dentro do callback, códigos de estado e códigos de agressão (2 e 3) conferem com o manual.
- Ele usa o **`profitTypes.py` oficial do pacote**, sem cópia própria. O caminho vem de `PROFITDLL_TYPES_DIR`.

**Não há bug que impeça o primeiro teste.** Os problemas encontrados são de robustez e de semântica:

| # | Sev. | Onde | Problema |
|---|---|---|---|
| B1 | **Média** | bridge.py:364-373 | A flag `TC_IS_EDIT` é ignorada. Uma edição de negócio entra no engine como negócio **novo**, o que duplica volume e delta |
| B2 | **Média** | bridge.py:356-362, 400-402 | O callback de estado só grava os "sucessos". Login inválido, senha errada ou ativação inválida esperam 30 s e terminam numa mensagem enganosa ("faltou: login"). Queda posterior do market (2,0), aviso (2,5) e (2,6) não são detectados nem contados |
| H1 | **Média** | historico.py:323-325, 362-372 | O limite de **30 dias** do `GetHistoryTrades` (p.30) não é validado. Um dia antigo falha com −2147483602 e ainda é tentado de novo |
| H2 | **Média** | historico.py:251, 303-306, 329-332 | Um dia sem negócios (feriado) pode nunca receber progresso 100. Nesse caso, o código espera 600 s × 2 tentativas por dia. O comportamento não está documentado |
| H3 | Baixa | historico.py:285-312 | O histórico usa o callback V1 com progresso 100. Funciona pelo manual (p.30), mas o marcador oficial de fim é `TC_LAST_PACKET` no **V2** (p.35), que é o que os exemplos usam |
| B3 | Baixa | bridge.py:319-321 | Põe a pasta "Exemplo Python" inteira no **início** do `sys.path`. Os `main.py` e `profit_dll.py` de terceiros dessa pasta passam a ter precedência de import |
| B4 | Baixa | bridge.py:399, historico.py:311-312 | O retorno de `SetTradeCallbackV2`, `SetHistoryTradeCallback` e `SetSerieProgressCallback` não é verificado |
| B5 | Baixa | bridge.py:268, 278, 396; historico.py:325 | Os erros saem como número cru (−2147483xxx), sem o nome `NL_*` |
| D1 | Info | historico.py:13-14 | A docstring diz "no máximo 10 dias por requisição". Pelo manual, esse limite vale **só para WIN e WDO**, e faltava mencionar o de 30 dias |

---

## 1. `bridge.py`, item por item

### 1.1 Carregamento e convenção de chamada
| Item | Linha | Veredito | Comentário |
|---|---|---|---|
| `WinDLL(dll_path)` | 344 | **CERTO** | O manual exige stdcall (p.51, p.79). O exemplo oficial usa `WinDLL` (`profit_dll.py`) |
| Callbacks com `WINFUNCTYPE` | 337-341 | **CERTO** | Os callbacks são stdcall (p.51). No x64 é igual ao `CFUNCTYPE`, mas `WINFUNCTYPE` é o correto e funciona também em 32 bits |
| Caminho padrão `C:\ProfitDLL\Win64\ProfitDLL.dll` | 318 | **CERTO** (nome do arquivo) | No pacote 4.0.0.42, a DLL de 64 bits fica em `DLLs\Win64\ProfitDLL.dll`. O nome `ProfitDLL64.dll` da p.6 está desatualizado. Defina `PROFITDLL_PATH` ou copie para o caminho padrão |
| Python 64 bits | — | **CERTO** | O Python do sistema é 3.12 64 bits. O manual não aponta problema conhecido em 64 bits (p.79) |

### 1.2 `profitTypes.py`: oficial ou cópia?
| Item | Linha | Veredito | Comentário |
|---|---|---|---|
| `from profitTypes import TConnectorAssetIdentifier, TConnectorTrade` | 326 | **CERTO** | Usa o arquivo **oficial** do pacote, apontado por `PROFITDLL_TYPES_DIR`. Não há cópia no repo |
| Fallback de `TAssetID` | 330-335 | **CERTO** | O `profitTypes.py` oficial **tem** `TAssetID` com os mesmos campos (`ticker`, `bolsa`: `c_wchar_p`; `feed`: `c_int`), que conferem com `TAssetIDRec` (p.7). O fallback nunca será usado |
| `sys.path.insert(0, types_dir)` | 319-321 | **Risco baixo (B3)** | A pasta "Exemplo Python" também tem `main.py` e `profit_dll.py`. Inserida na posição 0, ela passa a ter precedência sobre o resto do `sys.path`. Hoje só importamos `profitTypes`, mas é código de terceiro no caminho de import. Ver P5 |

Conferi o `TConnectorTrade` oficial contra o manual (p.14) e contra o C# (`ProfitDataTypes.cs`). Ordem dos campos e tipos:
`Version c_ubyte`, `TradeDate SystemTime` (8×`c_ushort`), `TradeNumber c_uint`, `Price c_double`, `Quantity c_longlong`,
`Volume c_double`, `BuyAgent c_int`, `SellAgent c_int`, `TradeType c_ubyte`. **Confere.** O `TradeType` também é `byte` no C#
(`enum TradeType : byte`).

### 1.3 Inicialização (`DLLInitializeMarketLogin`)
| Item | Linha | Veredito | Comentário |
|---|---|---|---|
| Ordem e quantidade de parâmetros (11) | 384-394 | **CERTO** | `key, user, pass, State, NewTrade, NewDaily, PriceBook, OfferBook, HistoryTrade, Progress, TinyBook` (p.18, p.25). Igual ao exemplo oficial em Python |
| `None` em NewTrade (V1) e HistoryTrade (V1) | 387, 391 | **CERTO** | Os exemplos oficiais em Python e C# fazem o mesmo ("replaced by SetTradeCallbackV2") |
| Strings sem `argtypes` (str → `wchar_t*`) | 345, 385 | **CERTO** | O ctypes converte `str` em `c_wchar_p` automaticamente. O exemplo oficial chama a função sem `argtypes` e embrulha em `c_wchar_p(...)` |
| `restype = c_int` e teste `ret != 0` | 345, 395 | **CERTO** | Retorna `Integer`, com `NL_OK = 0` |
| `SetTradeCallbackV2` chamado **depois** da inicialização e **antes** de a conexão completar | 399 | **CERTO** | É o mesmo padrão dos exemplos em Python e C#. Todo `Set*` substitui o callback da inicialização (p.33) |
| Retorno de `SetTradeCallbackV2` não verificado | 399 | **Baixo (B4)** | O C# verifica com `EvalNResult` |

### 1.4 Callback de estado
| Item | Linha | Veredito | Comentário |
|---|---|---|---|
| Tipo `WINFUNCTYPE(None, c_int, c_int)` | 337 | **CERTO** | É `TStateCallback(nConnStateType, nResult: Integer)` (p.51). O exemplo oficial usa `c_int32`, que é idêntico no Windows |
| Códigos usados: (0,0) login, (2,4) market, (3,0) ativação | 58-61, 356-362 | **CERTO** | Conferem com a p.15–16 e a p.58. O 3 é `CONNECTION_STATE_MARKET_LOGIN`, cujo resultado 0 é `CONNECTION_ACTIVATE_VALID` |
| Falhas e quedas ignoradas | 356-362 | **ERRADO (B2)** | Login inválido (0,1..4,200) e ativação inválida (3,1) não abortam a espera, o que dá timeout de 30 s com "faltou: login". Os `Event` nunca são limpos, então uma queda depois do start (2,0 / 2,3) passa despercebida. Os estados (2,5) `PERFORMANCE_WARNING` e **(2,6) `PARTIAL_CONNECTED`** (p.58) não são registrados. O (2,6) indica callbacks atrasados ou perdidos. Ver P2 |

### 1.5 Quando chamar `SubscribeTicker`
| Item | Linha | Veredito | Comentário |
|---|---|---|---|
| Esperar login, market e ativação antes do `SubscribeTicker` | 400-402, 276 | **CERTO** (conservador) | O manual não fixa um estado. O exemplo em Python espera só (2,4) e o C++ usa `bMarketConnected`. Esperar os três estados válidos da p.58 é o mais seguro |
| Chamado na thread principal, fora de callback | 276 | **CERTO** | `Subscribe*` é **função de requisição** e não pode ser chamada dentro de um callback (p.78) |
| `argtypes [c_wchar_p, c_wchar_p]`, `restype c_int` e ticker/bolsa `PETR4`/`B` | 347-348, 75-80 | **CERTO** | p.18, p.29. B = Bovespa, F = BMF (p.15) |

### 1.6 Trade V2 e `TranslateTrade`
| Item | Linha | Veredito | Comentário |
|---|---|---|---|
| `WINFUNCTYPE(None, TConnectorAssetIdentifier, c_size_t, c_uint)` | 339 | **CERTO** | Idêntico ao `tradeCallback` do `main.py` oficial. A p.57 dá `(const a_Asset: TConnectorAssetIdentifier; const a_pTrade: Pointer; const a_nFlags: Cardinal)`. O `profitTypes.py` oficial também oferece `TConnectorAssetIdentifierSafe`, com `c_void_p` no lugar de `c_wchar_p`, que o exemplo usa no histórico. Como não lemos o ativo, tanto faz |
| `TranslateTrade.argtypes = [c_size_t, POINTER(TConnectorTrade)]`, `restype c_int` | 353-354 | **CERTO** | Idêntico ao `profit_dll.py` oficial. p.22 |
| `TranslateTrade` chamada **dentro** do callback | 368 | **CERTO** | É função acessória e deve ser síncrona dentro do callback (p.78). O ponteiro não vale depois do callback |
| `trade.Version = 0` | 367 | **CERTO** | Igual aos exemplos em Python e C# |
| Teste de sucesso `!= 0` | 368 | **CERTO** | O manual diz que retorna `Integer`/`NL_OK`. O exemplo oficial de tempo real usa `if TranslateTrade(...):`, que testa veracidade e é **bug do exemplo**. O nosso está certo e coincide com o exemplo de histórico (`== NL_OK`) |
| Campos `BuyAgent`, `SellAgent`, `Quantity`, `Price` e `TradeType` | 371-373 | **CERTO** | p.14. `BuyAgent` é a corretora **compradora** e `SellAgent` a **vendedora** (p.59) |
| Agressão: 2 = compra, 3 = venda; o resto é ignorado | 54-55, 174-179 | **CERTO** | p.59 e `TTradeType` oficial (`AggressorBuyer = 2`, `AggressorSeller = 3`). O agressor na compra é o `BuyAgent` e na venda o `SellAgent`, o que confere com `trade_para_tick` |
| **Flag `TC_IS_EDIT` ignorada** | 364-373 | **ERRADO (B1)** | A p.35 diz que `a_nFlags` pode vir com `TC_IS_EDIT = 1` quando o trade é **uma edição**. Hoje uma edição entra como negócio novo, o que duplica volume, delta e possivelmente sinais. O manual não descreve como casar a edição com o original no V2: no V1, o identificador é o `pwcDate` (p.59). O `TradeNumber` é o candidato natural, mas isso é **NÃO VERIFICÁVEL**. Ver P1 |
| Cancelamento de negócio | — | **NÃO VERIFICÁVEL** | O manual não documenta cancelamento. Existe o `TradeType` 33 "Update", sem descrição. Hoje ele cai em "ignorado", o que está ok |
| Unidade de `Quantity` em ações (ações ou lotes) | — | **NÃO VERIFICÁVEL** | O manual só diz "Quantidade". Confira no teste: um negócio de PETR4 costuma ser múltiplo de 100 |
| Unidade de `Price` | — | **CERTO** | Double, preço de execução (p.59). Para ações, em R$ |
| Conversão do horário na thread da DLL | 373 | **CERTO** | É barata, e a struct não sobrevive ao callback |

### 1.7 `TradeDate` e formato de data
| Item | Linha | Veredito | Comentário |
|---|---|---|---|
| `TradeDate` é `SystemTime` (não texto) | 133-146 | **CERTO** | p.14 e `profitTypes.SystemTime`. `horario_negocio()` detecta `wYear` e usa `systemtime_para_epoch`. O ramo de texto fica para o V1 e o histórico |
| Campos usados (wYear, wMonth, wDay, wHour, wMinute, wSecond, wMilliseconds) | 112-130 | **CERTO** | O `SystemTime` oficial tem `wDayOfWeek` na 3ª posição. Como acessamos por nome, não há problema |
| **Fuso** do `TradeDate` (supomos Brasília, UTC−3) | 67-69 | **NÃO VERIFICÁVEL** | O manual não informa o fuso. Os exemplos só imprimem o valor cru. Confirmar no primeiro teste, comparando com `time.time()` ou `GetServerClock` (p.26) |
| Formato texto `DD/MM/YYYY HH:mm:SS.ZZZ` | 87 | **CERTO** | É o formato das datas do V1 e do histórico (p.59, p.66) |

### 1.8 TinyBook
| Item | Linha | Veredito | Comentário |
|---|---|---|---|
| `WINFUNCTYPE(None, TAssetID, c_double, c_int, c_int)` | 341 | **CERTO** | p.54 e igual ao `tinyBookCallBack` oficial |
| Lado 0 = bid, 1 = ask | 63-65 | **CERTO** | p.67: "Compra=0, Venda=1". Fecha a pendência do PROXIMOS-PASSOS |
| Posição 8 na inicialização | 393 | **CERTO** | p.18 |
| Preço ou quantidade ≤ 0 = lado vazio | 452 | **NÃO VERIFICÁVEL** | O manual não diz como vem o lado vazio, por exemplo no leilão. A heurística é razoável |
| O TinyBook exige `SubscribeTicker`? | — | **NÃO VERIFICÁVEL** | Provavelmente sim, já que o tick vem da assinatura. Confirmar no teste |

### 1.9 Threading
| Item | Linha | Veredito | Comentário |
|---|---|---|---|
| Callbacks só fazem `Queue.put` | 364-377 | **CERTO** | Segue a orientação da p.78 (repassar o dado e não fazer I/O). Também é o que evita o estado (2,6) |
| Fila única para trade e book (ordem preservada) | 232 | **CERTO** | Todos os callbacks vêm da mesma ConnectorThread (p.51, p.78), na ordem de entrega |
| Nenhuma função de requisição dentro de callbacks | — | **CERTO** | — |

### 1.10 Risco de o GC coletar callbacks ctypes
| Item | Linha | Veredito | Comentário |
|---|---|---|---|
| `self._callbacks += [cb_estado, cb_trade, cb_tiny]` | 234, 382 | **CERTO** | As referências duram enquanto a `ProfitDLLBridge` existir. `stop()` não limpa a lista, então elas ficam vivas mesmo depois do `DLLFinalize`. **Condição:** o objeto da bridge não pode ser descartado antes do `stop()`. No `main.py` ele é mantido como `data_source`. As closures (`on_trade` captura `dll` e `self`) não criam problema |

### 1.11 Finalização
| Item | Linha | Veredito | Comentário |
|---|---|---|---|
| `UnsubscribeTicker` e depois `DLLFinalize` | 284-296 | **CERTO** | p.18, p.26 |
| Inicialização falha (`ret != 0`) sem `DLLFinalize` | 395-397 | **Ok** | `self.dll` não é atribuído. O manual não diz se é preciso finalizar depois de uma inicialização que falhou |

---

## 2. `historico.py`, item por item

| Item | Linha | Veredito | Comentário |
|---|---|---|---|
| `GetHistoryTrades.argtypes = [c_wchar_p]*4`, `restype c_int` | 290-291 | **CERTO** | Idêntico ao `profit_dll.py` oficial. p.20–21 |
| Formato da requisição `%d/%m/%Y %H:%M:%S` via `strftime` | 55, 113-124 | **CERTO** | p.30: `DD/MM/YYYY HH:mm:SS`. Igual ao exemplo oficial |
| Chamada na thread principal | 323 | **CERTO** | Função de requisição, fora de callback (p.78) |
| `THistoryTradeCallback = WINFUNCTYPE(None, TAssetID, c_wchar_p, c_uint, c_double, c_double, c_int, c_int, c_int, c_int)` | 285-286 | **CERTO** | Confere com a p.54 e a p.66, e com o `THistoryTradeCallback` em C# e C++ |
| `TProgressCallback = WINFUNCTYPE(None, TAssetID, c_int)` | 287 | **CERTO** | p.51, p.66–67. Igual ao `progressCallBack` oficial |
| `SetHistoryTradeCallback` e `SetSerieProgressCallback` depois da inicialização | 311-312 | **CERTO** | p.33–34: substituem os da inicialização. O V1 de histórico **não** está marcado como depreciado (só o `SetTradeCallback` de tempo real está) |
| Retorno dos `Set*` não verificado | 311-312 | **Baixo (B4)** | — |
| Callbacks só acumulam sob lock | 297-306 | **CERTO** | p.78 |
| **Detecção de fim por progresso ≥ 100** | 303-306 | **CERTO, com ressalva (H3)** | O manual diz que o progresso vai de 1 a 100 (p.30), então o critério é válido. Como o progresso e os trades vêm da mesma fila (p.78), o 100 deve chegar depois do último trade, mas a ordem **não está documentada**. O marcador explícito do manual é **`TC_LAST_PACKET` no V2** (p.35), e é o que os exemplos oficiais usam. Ver P4 |
| **Dia sem negócios** (feriado) | 251, 329-332 | **NÃO VERIFICÁVEL / risco (H2)** | Não está documentado se chega progresso 100 ou `TC_LAST_PACKET` quando não há dados. Se não chegar, o código espera 600 s × 2 tentativas por feriado. Ver P4: abortar se não houver nenhum progresso nem trade em N segundos |
| **Limite de 30 dias** | 323-325, 362-372 | **ERRADO (H1)** | A p.30 diz que um início com mais de 30 dias retorna `NL_HISTORY_PERIOD_LIMIT` (−2147483602). Não validamos isso, e o laço de tentativas repete o erro. Ver P3 |
| Limite de 10 dias | 13-14 | **Doc imprecisa (D1)** | Vale **só para WIN e WDO** (p.30). Pedir dia a dia já respeita o limite |
| Filtro `fora_do_dia` e duplicados por `TradeNumber` | 159-188 | **CERTO** | Também protege contra trades atrasados de uma requisição anterior que deu timeout. O `TradeNumber` é único por pregão (p.59) |
| Data do callback `DD/MM/YYYY HH:mm:SS.ZZZ` → `data_b3_para_epoch` | 173 | **CERTO** | p.66. O fuso tem a mesma ressalva do item 1.7 |
| Reaproveitar `bridge._conectar()` | 265-269 | **CERTO** | Também registra o trade V2 e o TinyBook. Sem `SubscribeTicker`, eles não disparam, então é inofensivo |
| GC: `self._callbacks += [cb_hist, cb_prog]` | 259, 310 | **CERTO** | Ficam vivos enquanto o `BaixadorHistorico` existir. O `fechar()` chama `DLLFinalize` antes de o objeto sair de escopo |

---

## 3. Patches propostos (P1–P3 aplicados; P4–P7 pendentes)

### P1 — Tratar `TC_IS_EDIT` (B1) — ✅ aplicado em 16/10/2026
Em `bridge.py`, dentro de `on_trade`, passe `flags` para a fila. No consumidor, **não** mande a edição ao engine como negócio
novo: conte num contador novo, `trades_editados` em `stats()`. Até confirmar no teste real como a edição se relaciona com o original,
o mais seguro é descartá-la e contar.
```python
TC_IS_EDIT = 1
# on_trade:
self.fila.put(("trade", ..., horario_negocio(trade.TradeDate), int(flags), int(trade.TradeNumber)))
# _processar_trade(self, buy, sell, qty, price, ttype, ts, flags=0, numero=None):
if flags & TC_IS_EDIT:
    self.trades_editados += 1
    logger.info(f"Edição de negócio #{numero}: {qty} @ {price} (tipo {ttype}) — ignorada")
    return
```
Os testes atuais que chamam `_processar_evento(("trade", ...))` com 7 campos continuam funcionando, porque os novos parâmetros têm
valor padrão.

### P2 — Estado de conexão completo (B2) — ✅ aplicado em 16/10/2026 (sem SetHealthCallback)
- Guardar o último `(tipo, resultado)` de cada `nConnStateType`.
- Criar um `Event` de falha que é disparado em (0, 1..4 ou 200) e em (3,1). O laço de espera aborta na hora com uma mensagem legível,
  como "senha inválida" ou "ativação inválida".
- Depois do start, registrar (2,≠4) como **queda** e (2,6) como **aviso crítico**, e expor no `stats()` os campos `estado_market`,
  `quedas_market` e `avisos_partial`.
- Opcionalmente, ligar `SetHealthCallback` (p.33) e expor o `shsFrozen`.

### P3 — Validar a janela de 30 dias no histórico (H1) — ✅ aplicado em 16/10/2026
- Em `main()` de `historico.py`, recusar `inicio < hoje - 30 dias` (ou avisar e cortar), com mensagem citando o limite da DLL.
- Em `baixar_periodo`, **não** tentar de novo quando o retorno for `NL_HISTORY_PERIOD_LIMIT` (−2147483602) ou `NL_INVALID_ARGS`
  (−2147483645). Por exemplo, lançar `ValueError` e tratar fora do laço de tentativas.
- Corrigir a docstring nas linhas 13–14.

### P4 — Histórico pelo V2, com fim por `TC_LAST_PACKET` (H2, H3)
- Registrar `SetHistoryTradeCallbackV2` com `WINFUNCTYPE(None, TConnectorAssetIdentifierSafe, c_size_t, c_uint)`, como no exemplo
  oficial.
- Dentro do callback, chamar `TranslateTrade` e acumular `(TradeDate como SystemTime → texto ou epoch, TradeNumber, Price, Volume,
  Quantity, BuyAgent, SellAgent, TradeType)`.
- Marcar `_pronto` quando `flags & 2`. Manter o progresso 100 como segundo critério.
- **Ociosidade:** se não chegar nenhum trade nem progresso em 60 s depois do `GetHistoryTrades`, considerar o dia vazio em vez de
  esperar 600 s.
- Ajustar `converter_trades` para aceitar data em epoch, além de texto, sem quebrar os testes atuais.

### P5 — Não depender da pasta "Exemplo Python" no `sys.path` (B3)
Há duas opções:
- **(a)** Copiar só o `profitTypes.py` para uma pasta dedicada, por exemplo `C:\ProfitDLL\py\`, e apontar `PROFITDLL_TYPES_DIR` para ela.
  Não exige mudar código.
- **(b)** Definir no próprio repositório as 4 structs que usamos (`SystemTime`, `TConnectorTrade`, `TConnectorAssetIdentifier` e `TAssetID`),
  já conferidas contra a p.7, a p.9–10 e a p.14. Isso elimina a dependência. Como o pacote é proprietário, confirme antes se a
  licença permite.

Em qualquer caso, usar `sys.path.append` em vez de `insert(0, ...)`.

### P6 — Nomes dos códigos de erro e verificação dos `Set*` (B4, B5)
- Criar um dicionário `NL_NOMES = {-2147483647: "NL_INTERNAL_ERROR", ...}` com a tabela da p.16–17, incluindo `NL_HISTORY_PERIOD_LIMIT`.
- Usar o dicionário nos logs de falha.
- Verificar o retorno de `SetTradeCallbackV2`, `SetHistoryTradeCallback` e `SetSerieProgressCallback`.

### P7 — Nome das corretoras pela DLL (melhoria, fecha pendência do registro de 14/10)
- Em vez de exigir `agentes.json`, montar um cache sob demanda **na thread consumidora**, fora do callback da DLL. Para cada código
  ainda não visto, chamar:
  `n = GetAgentNameLength(id, 1)` → `buf = create_unicode_buffer(n + 1)` → `GetAgentName(n + 1, id, buf, 1)`.
  - `argtypes`: `[c_int, c_uint]` e `[c_int, c_int, c_wchar_p, c_uint]` (p.18).
  - O `profit_dll.py` oficial declara `c_int` no último argumento, o que dá no mesmo.
- O nome abreviado (flag 1) é o candidato a bater com `high_relevance_brokers`. Gravar o resultado em `agentes.json` para o replay.
- O manual não diz se `GetAgentName*` é segura fora da ConnectorThread. O exemplo oficial em Python a chama na thread principal,
  então provavelmente é. **NÃO VERIFICÁVEL.**

---

## 4. Divergências encontradas nos próprios exemplos oficiais (para não copiar)

- `main.py`, `tradeCallback`: `if profit_dll.TranslateTrade(...):` testa veracidade, mas sucesso é 0 (`NL_OK`). O certo é `== 0`.
- `profitTypes.TConnectorPriceGroup.Quantity` é `c_long` (32 bits no Windows), mas o manual diz **Int64** (p.10). O layout fica errado.
- `profitTypes.TTheoreticalPriceCallback.nTheoreticalQtd` é `c_uint`, mas o manual diz **Int64** (p.55).
- `main.py`, `offerBookCallbackV2`: declara `nQtd` como `c_int`, mas é **Int64** (p.53, p.65).
- `main.py`, `assetListInfoCallback`: `nMinOrderQtd`, `nMaxOrderQtd` e `nLote` estão como `c_int`, mas são **Int64** desde a 4.0.0.38 (p.2).
- A p.6 do manual cita `ProfitDLL64.dll`, mas o pacote traz `DLLs\Win64\ProfitDLL.dll`.

---

## 5. Itens que só o teste real confirma

1. O **fuso do `TradeDate`**. Compare `horario_negocio(...)` com `time.time()` durante o pregão: a diferença deve ser de
   milissegundos a poucos segundos, nunca de cerca de 3 horas.
2. A **unidade de `Quantity`** para PETR4 (ações).
3. Se `TC_IS_EDIT` aparece no pregão, com que frequência, e como identificar o negócio original.
4. Se o TinyBook só dispara depois do `SubscribeTicker` e como chega o lado vazio no leilão.
5. Se o `SubscribeTicker` reenvia os negócios do dia já ocorridos, como snapshot, ou só os novos.
6. Histórico: a ordem entre o progresso 100 e o último trade, e o comportamento num dia sem negócios.
7. A chave de ativação, que o C# chama de "Optional". Não conte com isso: use a chave recebida.
