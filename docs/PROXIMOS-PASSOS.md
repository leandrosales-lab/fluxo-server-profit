# Próximos passos — onde paramos

Última atualização: 17/10/2026. Este arquivo serve para continuar o trabalho de outro computador.

## Prioridade

**O sistema trabalha só com ações** (decisão de 17/10/2026). Contratos futuros (WIN, WDO, DOL, IND... ou terminados em
`FUT`) são recusados na linha de comando, na ponte da DLL e no histórico. Bolsa sempre `B`, sufixo RTD `_B_0`, tick R$ 0,01.

1. ~~Incluir a Bovespa na licença da ProfitDLL~~ — **liberada em 17/10/2026** (ver abaixo).
2. **PETR4 ao vivo pela DLL** (primeiro pregão após a liberação): conferir assinatura, histórico (`profitdll.historico`)
   e gravar pregões com `--gravar` para calibrar no replay.
3. **Estratégias do curso — subprojeto 2 (escora × rompimento)**: sinais a partir das defesas, com gatilho e stop por
   tipo. Depois: subprojetos 3 (condução e saída) e 4 (players e algoritmos).

## O que já está pronto (no `main`)

- **Engine:** detecta absorção por volume, exaustão, delta acumulado e iceberg pela **corretora passiva**. Usa o horário do negócio, não o relógio do computador.
- **Radar de fluxo (17/10/2026):** `--radar` assina as ações de `config/acoes_b3.txt` (cadastro da B3,
  `tools/acoes_b3.py`) e lista os icebergs do dia com giros, volume e desfecho (segurou a 4 ticks / rompeu / virou
  sniper) na tela Radar (F3). Clique troca o papel da Operar. Falta confirmar ao vivo quantos papéis a licença
  aceita (tela Conexão mostra assinados e recusados).
- **Defesas (17/10/2026):** `core/defesas.py` reconhece iceberg (pela passiva), sniper, fantasma e E2 pelas regras do
  professor, com eventos de fim (rompida, fila formada, defensor ausente). Painel "Defesas" no Operar. Spec:
  `docs/superpowers/specs/2026-10-17-defesas-design.md`.
- **Ponte RTD:**
  - A quantidade vem de `QTT`. O `VOL` do Profit é volume em R$.
  - O sufixo é `_B_0` (ações).
  - O bid/ask vem de `OCP`/`OVD`.
  - O servidor deduz a quantidade e o lado agressor de cada negócio.
- **Modo replay:** `--gravar`, `--modo replay` e `--grid`. Ver [replay.md](replay.md).
- **ProfitDLL (testada com a DLL real em 16/10/2026):**
  - Conecta em ~4 s; negócios com agressor, topo do livro (TinyBook), nome da corretora pela DLL e horário da B3.
  - **Bovespa liberada em 17/10/2026:** o log da DLL passou a mostrar `Exchanges=#, A, B, D, E, F, V` (antes `E, F`).
    Histórico de PETR4 de 16/10 (10:00–10:05) baixado: 432 negócios, 283 com agressor, todos com corretora passiva.
    Falta conferir o tempo real num pregão aberto.
  - **A DLL não reinicializa no mesmo processo** (Access violation em `CreateDataLoader`): no modo dll ela roda num
    processo filho (`profitdll/processo.py`) e o Reconectar reinicia só o filho.
  - Credenciais: `tools\configurar_profitdll.ps1`; subir: `tools\rodar_dll.ps1 -Asset PETR4`.
  - Histórico: `python -m profitdll.historico` (ainda não confirmado com dados reais).
- **Telas (design v3):** `http://127.0.0.1:5000/operar` (F1) e `/conexao` (F2), tema escuro/claro (T), Reconectar
  da DLL na Conexão. Testes: `node tools/test_telas.mjs` e `node tools/qa_telas.js` (QA no navegador com Playwright).

O detalhe do que foi feito está em [registro-2026-10-14.md](registro-2026-10-14.md).

## Próximo passo: PETR4 com dados reais

Dá para fazer uma das duas opções, ou as duas. Fazer as duas permite comparar quantos negócios o RTD perde.

### Opção 1: exportar o Times & Trades do Profit
1. No Profit, abra o Times & Trades da PETR4 e carregue o dia inteiro.
2. Clique com o botão direito e procure a opção de exportar em CSV. O nome do menu ainda não foi confirmado.
3. Salve em `historico/` e rode:
   ```
   python main.py --asset PETR4 --modo replay --arquivo historico\ARQUIVO.csv --sem-servidor
   ```
4. Coisas a conferir:
   - Se o leitor entende o arquivo do Profit. Ele **ainda não foi testado com uma exportação real**.
   - O relatório de acerto.
   - Depois, a calibração com `--grid`.

### Opção 2: gravar ao vivo pela ponte RTD
1. Rode o servidor:
   ```
   python main.py --asset PETR4 --modo rtd --gravar historico\petr4_AAAA-MM-DD.csv
   ```
2. No Excel, remova o módulo antigo, importe `excel\FLUXO_BRIDGE_RTD.bas` (versão nova) e rode `InserirFormulasRTD` com PETR4.
3. Confira se as células E1:K1 mostram valores:
   - G1/H1 (`ACP`/`AVD`): ainda não confirmados via RTD, porque só aparecem na lista do DDE.
   - J1/K1 (`OCP`/`OVD`).
4. Rode `IniciarBridge` e acompanhe em http://127.0.0.1:5000/state, no bloco `rtd`.

### Depois da primeira calibração
- Ajustar os parâmetros de iceberg e absorção para o lote e a liquidez da PETR4: `iceberg_vol_ratio`, `iceberg_min_share`, `absorption_vol_ratio`, `exhaustion_*`.
- Preencher `high_relevance_brokers` com os nomes das corretoras **exatamente como aparecem no RTD**.

## Pendências gerais

- [ ] Confirmar no Profit que `ACP`/`AVD` funcionam via RTD.
- [ ] Testar o RTD ligado à janela de Times & Trades, que dá o agressor real sem precisar inferir.
- [ ] Conferir o leitor do replay com uma exportação real do Times & Trades.
- [ ] Esperar a resposta da Nelogica sobre teste, preço e o pacote com o `profitTypes.py` e o manual. Quando chegar, conferir:
  - o tipo de `TradeDate`;
  - os nomes dos campos do `TConnectorTrade`;
  - se no TinyBook o lado 0 é bid e o 1 é ask.
- [ ] Conferir a conta da Vercel com `vercel login` e `vercel project ls`. O repo não publica nada, só falta confirmar que não existe projeto antigo na conta.

## Como montar o ambiente em outro computador

1. Clone o repo e rode os testes:
   ```
   git clone https://github.com/leandrosales-lab/fluxo-server-profit.git
   cd fluxo-server-profit
   set PYTHONIOENCODING=utf-8
   python test_engine.py
   ```
2. Coisas a saber:
   - O núcleo usa só a biblioteca padrão do Python. O `requirements.txt` lista apenas as dependências dos modos OCR e DDE.
   - No Windows, sem `PYTHONIOENCODING=utf-8`, os testes quebram ao imprimir as bordas do relatório (console cp1252).
   - A captura de dados (RTD, DDE e DLL) precisa rodar **no Windows, na mesma máquina do Profit**.
   - A pasta `historico/` está no `.gitignore`. Para levar um pregão gravado para outro computador, copie o CSV ou force a inclusão com `git add -f historico\ARQUIVO.csv`.
   - As credenciais da DLL (`PROFITDLL_*`) ficam só em variáveis de ambiente e nunca vão para o repositório.
