# Próximos passos — onde paramos

Última atualização: 16/10/2026. Este arquivo serve para continuar o trabalho de outro computador.

## Prioridade

1. **WDO e WIN pela ProfitDLL.** A licença atual só libera BMF (ver abaixo). Gravar pregões com `--gravar` e calibrar o
   engine no replay. Tick do WDO 0,5 (`--tick-size 0.5`), do WIN 5 (`--tick-size 5`).
2. **Ações (PETR4, BBAS3)** dependem de incluir a Bovespa na licença da DLL (suportecorp@nelogica.com.br). Até lá, ações
   só pelo RTD do Profit. Bolsa `B`, sufixo RTD `_B_0`, tick de R$ 0,01.

## O que já está pronto (no `main`)

- **Engine:** detecta absorção por volume, exaustão, delta acumulado e iceberg pela **corretora passiva**. Usa o horário do negócio, não o relógio do computador.
- **Ponte RTD:**
  - A quantidade vem de `QTT`. O `VOL` do Profit é volume em R$.
  - Os sufixos são `_B_0` para ações e `_F_0` para futuros.
  - O bid/ask vem de `OCP`/`OVD`.
  - O servidor deduz a quantidade e o lado agressor de cada negócio.
- **Modo replay:** `--gravar`, `--modo replay` e `--grid`. Ver [replay.md](replay.md).
- **ProfitDLL (testada com a DLL real em 16/10/2026):**
  - Conecta em ~4 s; negócios com agressor, topo do livro (TinyBook), nome da corretora pela DLL e horário da B3.
  - **A licença atual só libera BMF** (log da DLL: `Exchanges=E,1,0;F,1,0`). Ações (bolsa `B`) são recusadas em
    silêncio: o histórico fica em 0% para sempre.
  - **A DLL não reinicializa no mesmo processo** (Access violation em `CreateDataLoader`): no modo dll ela roda num
    processo filho (`profitdll/processo.py`) e o Reconectar reinicia só o filho.
  - Credenciais: `tools\configurar_profitdll.ps1`; subir: `tools\rodar_dll.ps1 -Asset WDOFUT -TickSize 0.5`.
  - Histórico: `python -m profitdll.historico` (ainda não confirmado com dados reais de BMF).
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
