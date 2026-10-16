# Telas novas, subprojeto 1: base, Operar e Conexão

Data: 16/10/2026 · Status: aprovado em conversa, aguardando revisão desta especificação

## 1. Objetivo

Trocar o `api/static/dashboard.html` atual por uma interface de duas telas, **Operar** e **Conexão**, no design
**v3 "Terminal + manchete"** aprovado. Ela é usada só pelo dono, ao vivo, num 2º monitor de 24" (1920×1080), por horas
seguidas. O que mais importa é ler de relance e cansar pouco a vista.

**Fora deste subprojeto:** as telas Replay e Calibração (subprojetos 2 e 3), o livro completo (`SubscribeOfferBook`) e
as correções P4–P7 da ProfitDLL.

## 2. Referências

- Mockups: `docs/design/v3/operar-escuro.png`, `operar-claro.png`, `conexao-escuro.png` e `conexao-claro.png`.
  Os originais editáveis estão em `~/figcraft/designs/fluxo-server/v3/`.
- Cores, contraste e regras de uso: `docs/design/v3/tokens-v3.md`. Os tokens CSS vêm **exatamente** dessa tabela.
- Estados da ProfitDLL: `docs/profitdll-referencia.md` e os campos de `ProfitDLLBridge.stats()` (P2, commit `da0be48`).

### Regras visuais obrigatórias (o que foi rejeitado na versão A não volta)
- A estrutura vem de fios de 1px e alinhamento, com raio de 0–2px. Não há cards, sombras, glow nem gradientes.
- Nada de pílulas, chips, ícones decorativos ou sparklines. Rótulos em caixa normal.
- Verde e vermelho só para compra e venda. O âmbar só para estado e seleção.
- Tipografia: IBM Plex Sans para a interface e os números grandes, com algarismos tabulares. IBM Plex Mono para tabelas,
  eixos, horas e o log.

## 3. Decisões tomadas

| Tema | Decisão | Motivo |
|---|---|---|
| Tecnologia | HTML, CSS e JS puros com ES modules, sem build e sem dependência nova | O projeto é Python, roda offline e segue o padrão do dashboard atual |
| Atualização | Consulta a cada **500 ms**, incremental com `since` | Reaproveita os endpoints que já existem; o atual usa 1 s |
| Ciclo de vida da DLL | **Opção C**: o servidor sobe já no modo dll, e a tela mostra o estado e tem **Reconectar** | Cobre o caso real (queda no pregão) sem virar um gerenciador de conexões |
| Tema | Segue o sistema (`prefers-color-scheme`); a escolha manual (T ou seletor) fica no `localStorage` | Só a preferência do próprio usuário fica no navegador |
| Dashboard antigo | Removido; `/dashboard` passa a abrir o Operar | Uma só interface. O antigo continua no histórico do git |
| Fontes | IBM Plex Sans e Mono (OFL) em `api/static/fonts/`, com as licenças | Funciona offline, sem Google Fonts |

## 4. Estrutura de arquivos

```
api/static/
  operar.html            conexao.html
  css/tokens.css         ← variáveis dos 2 temas: [data-tema="escuro"|"claro"]
  css/base.css           ← reset, grade, fios, tipografia, tabelas, botões retos, utilitários
  js/shell.js            ← monta cabeçalho/rodapé, abas, relógio B3, status DLL, tema, atalhos
  js/api.js              ← getJSON/postJSON com timeout, estado "sem resposta", laço de consulta
  js/formato.js          ← pt-BR: preço (38,47), inteiro (184.300), financeiro (R$ 412,0 mi), hora B3
  js/tabela.js           ← tabela que reaproveita <tr> e só reescreve células que mudaram
  js/operar.js           ← gráfico (Lightweight Charts), manchete, sinais, fita, livro, saldo, faixa de cotação
  js/conexao.js          ← faixa de estados, gráfico de negócios/s, log, Reconectar
  fonts/IBMPlexSans-*.woff2, IBMPlexMono-*.woff2, OFL.txt
  lightweight-charts.standalone.production.js   (já existe)
```
Cada módulo JS tem uma responsabilidade só e fica abaixo de ~400 linhas. `operar.js` pode se dividir em `operar-grafico.js`
e `operar-paineis.js` se passar disso.

## 5. Cabeçalho e rodapé (`shell.js`, comuns às telas)

- **Barra de 32px**, da esquerda para a direita:
  - "Fluxo Server";
  - abas Operar · Conexão · Replay · Calibração. Replay e Calibração aparecem desabilitadas, com o título "em breve";
  - o modo, "ao vivo" ou "replay", conforme `/health`;
  - o status da ProfitDLL, com o ponto na cor do estado e o texto: "ProfitDLL conectado (2,4) · 12 ms", "reconectando…" ou
    "desconectado — senha inválida". Nos modos que não são dll, aparece "fonte: rtd" (ou "replay", "manual");
  - o relógio B3, ou a hora do último negócio no replay;
  - "tema escuro / claro".
- **Rodapé:** "Dados de exemplo…" só quando a fonte é replay de exemplo; os atalhos `F1 Operar  F2 Conexão  T tema`; e
  "B3 · horário de Brasília".
- **Atalhos:** F1 e F2 navegam (F3 e F4 ficam reservados); T alterna o tema. Os atalhos ficam desligados enquanto o foco
  está num campo de texto. O F1 do navegador é cancelado com `preventDefault`.
- **Sem resposta do servidor** por mais de 3 s: o cabeçalho mostra "sem resposta do servidor · parado há N s" em âmbar.
  As telas mantêm os últimos dados, sem limpar nada.

## 6. Tela Operar

O layout é o de `operar-escuro.png`.
- **Faixa de cotação (80px):** ativo e descrição, último preço grande, variação absoluta e %, delta acumulado, volume
  financeiro, VWAP (e a distância do preço), agressão compra × venda (%), negócios/min, máxima · mínima,
  abertura · ajuste anterior. O ajuste anterior aparece como "—" enquanto não houver fonte para ele.
- **Gráfico (coluna esquerda, x < 1180):** candles de 1 min (alternando 1/5/15/60 min), VWAP tracejada, linha de preço,
  marcas tipográficas ▲/▼ com A/E/I nos candles dos sinais, volume por candle colorido pelo lado e subpainel de delta
  acumulado.
  - Os timeframes aceitos hoje são 15/60/300 s. Este subprojeto acrescenta 900 e 3600 s em `/candles`.
- **Coluna direita:**
  1. **Sinais**, com filtros por tipo;
  2. **Manchete do sinal ativo**: "Sinal ativo · novo, há N s" em âmbar; título (padrão + direção, ex.: "Absorção
     compradora"); "em {preço}" na cor da direção; frase (`reason` do sinal); linha de detalhes (força = confiança,
     mínima, VWAP, vela, hora); fio lateral de 2px na cor da direção;
  3. os 4 sinais anteriores, em linhas;
  4. **Times & Trades**, com lotes grandes (≥ limite configurável, padrão 5.000) em negrito e fundo `raise`;
  5. **Livro de 10 níveis**: até haver o livro completo, mostra o que `/book` informar (`depth`). Com `top`, mostra só
     o melhor bid/ask e a nota "topo do livro";
  6. **Saldo das corretoras** (lotes no dia).
- **Sinal "novo":** durante 60 s, a manchete mostra "novo". Não há brilho nem som neste subprojeto.

## 7. Tela Conexão

O layout é o de `conexao-escuro.png`.
- **Faixa de estados:** login (0,·), ativação (3,·), market data (2,·), roteamento ("não usado") e o estado agregado.
  Cada coluna mostra o código e o nome (`NOMES_MARKET`).
- **Negócios por segundo por ativo assinado:** gráfico de linha fina com os últimos 15 min, calculado no navegador a
  partir da diferença de `trades_recebidos` entre consultas. Faixa âmbar anotada nos períodos com `avisos_partial` subindo.
- **Contadores:** recebidos, editados (TC_IS_EDIT), ignorados, horários de fallback, quedas do market, avisos (2,6),
  fila pendente.
  - Quando houver editados, aparece uma linha destacada com fio âmbar: "N correções de negócio hoje — descartadas".
- **Configuração:** caminho da DLL mascarado (`C:\…\ProfitDLL.dll`), versão (quando houver) e ativo e bolsa. **Chave,
  usuário e senha nunca aparecem nem saem do servidor.**
- **Log:** tabela mono com hora, nível e mensagem, a mais nova em cima, com filtro por nível e rolagem própria.
- **Reconectar:** botão reto. Mostra "reconectando…" e fica desabilitado até a resposta; uma falha aparece em linha com
  o motivo. Só existe no modo dll.

## 8. Backend (mudanças no Python)

### 8.1 `GET /state` ganha o bloco `resumo`
Calculado no engine, incremental, sem varrer o pregão a cada consulta:
```json
"resumo": {"abertura": 38.02, "maxima": 38.57, "minima": 37.88, "ultimo": 38.47,
           "volume_financeiro": 412000000.0, "negocios_por_min": 412,
           "agressao_compra_pct": 57.0, "vwap": 38.31,
           "saldo_corretoras": [["BTG", 92000], ["ITAU", 38000], ["XP", -61000]]}
```
- `negocios_por_min` é a média dos últimos 5 min de horário de negócio (não do relógio local).
- `saldo_corretoras` é o saldo líquido em quantidade (compras − vendas como agressora **e** como passiva, quando a fonte
  informa a passiva). Traz as 5 maiores e as 5 menores. A regra fica documentada no código.
- `reset` zera o resumo.

### 8.2 `GET /log?since=T&nivel=INFO`
- Um `logging.Handler` em memória (`deque` de 500 registros, thread-safe), instalado em `main.py`, capta os loggers
  `ProfitDLL`, `ProfitDLLHistorico`, `API` e a raiz no nível INFO ou maior.
- Resposta: `[{"ts": epoch, "nivel": "ERROR", "origem": "ProfitDLL", "msg": "..."}]`.
- Antes de guardar, as mensagens passam por um filtro que mascara valores iguais aos de `PROFITDLL_KEY`, `PROFITDLL_USER` e
  `PROFITDLL_PASS`, por segurança.

### 8.3 `POST /dll/reconectar`
- Existe só no modo dll; nos outros modos devolve 404.
- Responde 202 e roda numa thread: `bridge.stop()` e depois `bridge.start()`. Os callbacks antigos são substituídos e a
  ponte é a mesma instância, então o engine continua recebendo de `on_tick`/`on_book`.
- Se já houver uma reconexão em andamento, devolve 409. O estado da tarefa sai em `/state` → `dll.reconexao`:
  `{"em_andamento": bool, "ultima": epoch, "resultado": "ok" | "falhou: <motivo>"}`.
- **Pré-requisito a verificar no código:** `ProfitDLLBridge.start()` precisa funcionar depois de um `stop()`, zerando os
  `Event` de estado, `_falha` e `motivo_falha`. Os contadores continuam acumulando. Se não funcionar, ajustar e testar.

### 8.4 Rotas
- `GET /`, `/dashboard` e `/operar` servem `operar.html`; `GET /conexao` serve `conexao.html`.
- `/static/` passa a aceitar as subpastas `css/`, `js/` e `fonts/`, com a mesma proteção contra `..` e caminhos absolutos.
  Tipos novos: `.css`, `.woff2`, `.mjs`.
- O estado inicial deixa de ser injetado no HTML (o `__STATE_JSON__` sai): as páginas buscam `/state` ao carregar.
- `GET /health` passa a informar `modo` e `fonte`.

## 9. Erros e casos-limite

| Situação | Comportamento |
|---|---|
| Servidor não responde | Aviso âmbar no cabeçalho com "parado há N s"; dados congelados; volta sozinho |
| DLL cai (2,≠4) | Status vermelho "desconectado"; Operar mantém o último estado; Conexão destaca a queda |
| (2,6) | Status âmbar "callbacks atrasados"; contador e faixa no gráfico da Conexão |
| Reconexão falha | Linha com o motivo vindo de `motivo_falha` (ex.: "senha inválida") |
| Sem sinais ainda | A manchete mostra "Nenhum sinal ainda hoje" em `muted`, sem área vazia quebrada |
| Livro só com o topo | Mostra 1 nível por lado com a nota "topo do livro" |
| Antes da abertura / sem negócios | Faixa com "—" e gráfico vazio com o eixo de horário do pregão |

## 10. Testes

- **Python** (`test_engine.py`, mesmo estilo):
  - `resumo`: valores certos num pregão sintético, reset e desempenho sem varrer tudo;
  - `/log`: captura, `since`, nível e máscara de credenciais;
  - `/dll/reconectar` com uma ponte falsa: 202, 409 em andamento, 404 fora do modo dll e o resultado no `/state`;
  - `start()` depois de `stop()` com estados falsos;
  - rotas novas, `/static` com subpastas (recusa `..`), tipos `.css` e `.woff2`, `/candles` com 900 e 3600.
- **Navegador** (Playwright já instalado em `C:/Projetos/urnalytics-marcelo/node_modules/playwright`, script em
  `tools/qa_telas.js`, sem entrar no repositório de dependências): sobe `main.py --modo replay` com
  `replay/exemplo_wdo.csv`, abre as duas telas em 1920×1080 e confere:
  - nenhum erro no console;
  - as abas, F1/F2 e T funcionam, e o tema persiste ao recarregar;
  - a manchete aparece quando sai um sinal;
  - a tabela de T&T cresce;
  - o aviso "sem resposta" surge quando o servidor para;
  - as capturas dos dois temas ficam salvas para comparar com a v3, no olho.
- **Contraste:** o mesmo critério do `tokens-v3.md`. Nenhum par novo de texto abaixo de 4,5:1.

## 11. Critérios de pronto

1. Operar e Conexão batem com a v3 nos dois temas, conferido por capturas lado a lado.
2. A suíte Python continua toda verde e tem os testes novos.
3. O QA no navegador passa sem erro no console.
4. `python main.py --modo replay --arquivo replay/exemplo_wdo.csv` abre direto no Operar novo.
5. A docstring de `api/server.py` (lista de endpoints), `docs/replay.md` e `docs/PROXIMOS-PASSOS.md` foram atualizados
   com as rotas e os atalhos novos (o repositório não tem README).

## 12. Adendo (16/10/2026): a ProfitDLL roda num processo filho

**Motivo:** testado com a DLL real, um segundo `DLLInitializeMarketLogin` no mesmo processo (depois de `DLLFinalize`)
dá *Access violation* dentro da `ProfitDLL.dll` (`CreateDataLoader Failed`). Reconectar exige um processo novo.
O dono escolheu isolar a DLL num processo filho, para o Reconectar não perder o estado do engine.

- `profitdll/processo.py`:
  - **filho** (`python -m profitdll.processo --asset X [--bolsa B] [--agentes J]`): roda a `ProfitDLLBridge` e escreve
    no stdout uma linha JSON por evento: `inicio` (ok/motivo), `tick`, `book`, `stats` (a cada 0,5 s) e `log`
    (os registros de log do filho). Lê `stop` no stdin para encerrar com `DLLFinalize`. Nada mais vai para o stdout.
  - **pai** (`PonteDLLProcesso`): mesma interface que o `main.py` e o `server.py` usam da ponte (`on_tick`, `on_book`,
    `start() -> bool`, `stop()`, `stats()`, `motivo_falha`). Repassa ticks e book ao engine, os logs ao `logging`
    (então aparecem no `/log`, com a máscara de credenciais), e soma os contadores entre processos (eles acumulam no dia).
  - Se o filho morrer, `stats()` mostra `conectado: false` com o motivo "processo da ProfitDLL encerrou".
- `main.py --modo dll` usa a `PonteDLLProcesso`. O `POST /dll/reconectar` não muda: `stop()` + `start()` agora reiniciam
  só o filho. O histórico (`profitdll.historico`) continua usando a ponte direta.
