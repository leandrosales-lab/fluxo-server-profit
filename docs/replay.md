# Modo replay — rodar um pregão gravado

O modo replay pega um pregão salvo num arquivo CSV e passa negócio por negócio pelo engine, do mesmo jeito que aconteceria ao vivo. Serve para:

- ver quais sinais o engine teria dado naquele dia;
- medir se esses sinais funcionaram (um backtest simples);
- testar vários valores de parâmetros e escolher os melhores para cada ativo (calibração).

Não precisa do Profit aberto, nem da DLL, nem de internet.

---

## 1. Gravar um pregão

Acrescente `--gravar arquivo.csv` em qualquer modo. Cada negócio que chega ao engine também é salvo no arquivo:

```
python main.py --asset WDOFUT --modo dll --tick-size 0.5 --gravar wdo_2026-10-14.csv
python main.py --asset PETR4 --modo rtd --gravar petr4_hoje.csv
```

- Se o arquivo já existir, os negócios novos entram no final (nada é apagado).
- O arquivo é atualizado a cada negócio. Se o programa fechar de repente, o que já chegou fica salvo.

Para pegar **dias passados** sem ter gravado ao vivo, baixe o histórico pela ProfitDLL (seção 7).

### Formato do arquivo

```
timestamp,preco,quantidade,agressor,corretora_agressora,corretora_passiva
1791986400.000,5400,2,S,UBS,ORAMA
1791986402.000,5400.5,2,B,XP INC,INTER
```

| Coluna | O que é |
|---|---|
| `timestamp` | Hora do negócio. Pode ser em segundos desde 1970 com milissegundos (`1791986400.125`), no padrão ISO (`2026-10-14T10:00:00.125`) ou `14/10/2026 10:00:00.125` |
| `preco` | Preço do negócio |
| `quantidade` | Contratos ou ações |
| `agressor` | `B` = comprador agrediu, `S` = vendedor agrediu (também aceita `C`/`V`, Compra/Venda, Comprador/Vendedor) |
| `corretora_agressora` | Corretora que agrediu |
| `corretora_passiva` | Corretora que estava no book (opcional, pode ficar vazia) |

### Usar a exportação do Times & Trades do Profit

Também dá para usar o CSV exportado do Times & Trades do Profit. O leitor se adapta sozinho a:

- separador `;` ou `,`;
- números com vírgula (`5.123,50`) e milhar com ponto (`1.000`);
- cabeçalhos em português, com ou sem acento: `Data`, `Hora`, `Preço`, `Quantidade`, `Agressor`, `Compradora`, `Vendedora`, `Corretora`...;
- data e hora juntas numa coluna ou em colunas separadas;
- arquivo do mais novo para o mais antigo (como o Profit mostra) — ele inverte a ordem;
- linhas de título antes do cabeçalho.

Quando o arquivo tem `Compradora` e `Vendedora`, a corretora agressora é a compradora nos negócios de compra e a vendedora nos de venda. A outra vira a passiva. Negócios sem agressor (leilão, direto) são ignorados e contados no log.

Se o arquivo tiver só a hora, sem a data, o replay usa 01/01/2000 como data. Isso não muda os sinais.

---

## 2. Rodar o replay

```
python main.py --asset WDOFUT --modo replay --arquivo replay/exemplo_wdo.csv --tick-size 0.5 --sem-servidor
```

| Opção | Para que serve |
|---|---|
| `--arquivo` | O CSV do pregão (obrigatório) |
| `--tick-size` | Tamanho do tick do ativo (WDO = 0.5, WIN = 5, ações = 0.01). **Importante:** os resultados são medidos em ticks |
| `--velocidade` | `0` = o mais rápido possível (padrão). `1` = tempo real. `10` = 10 vezes mais rápido |
| `--sem-servidor` | Roda direto, sem abrir o servidor/dashboard (modo lote) |
| `--alvo-ticks` | Quantos ticks a favor contam como acerto (padrão 4) |
| `--horizonte` | Por quantos segundos depois do sinal o resultado é medido (padrão 300) |
| `--saida` | Salva a lista de sinais num CSV |

Os outros parâmetros do engine (`--flow-window`, `--flow-pct`, `--min-confidence` etc.) funcionam igual ao modo ao vivo.

### Assistir no dashboard

Sem `--sem-servidor`, o servidor sobe normalmente e dá para acompanhar em `http://127.0.0.1:5000/dashboard`. Use uma velocidade maior que zero para ver o pregão andar:

```
python main.py --asset WDOFUT --modo replay --arquivo wdo_2026-10-14.csv --tick-size 0.5 --velocidade 20
```

Quando o arquivo termina, o relatório aparece e o servidor continua no ar com o estado final até você apertar Ctrl+C.

### Vários dias no mesmo arquivo

Quando a data dos negócios muda, o engine é zerado, igual ao reset da meia-noite ao vivo.

---

## 3. O relatório

```
  Padrão       Sinais   Alvo   Stop  Nenhum   Acerto  MFE méd  MAE méd
  Absorção         10      5      2       3      50%      8.6     11.0
  Urgência          7      3      4       0      43%     4.29    34.71
  Exaustão          2      2      0       0     100%     20.5      0.0
  TOTAL            19     10      6       3      53%     8.26    18.58
```

Para cada sinal novo de compra ou venda, o replay olha os negócios seguintes, até o fim do horizonte:

- **Alvo**: o preço andou `--alvo-ticks` a favor **antes** de tocar o stop do sinal.
- **Stop**: o preço tocou o stop do sinal antes de chegar ao alvo. Se o sinal vier sem stop válido, usa `stop_ticks_behind` ticks.
- **Nenhum**: não chegou nem no alvo nem no stop dentro do horizonte.
- **Acerto**: alvos divididos pelo total de sinais.
- **MFE**: o máximo que o preço andou a favor, em ticks, dentro do horizonte.
- **MAE**: o máximo que o preço andou contra, em ticks, dentro do horizonte.

A entrada é o preço do negócio que gerou o sinal. Não há custo, nem escorregamento, nem fila no book. É uma medida para **comparar parâmetros**, e não uma promessa de resultado.

Um sinal conta como "novo" quando muda o lado, o padrão ou o stop em relação ao sinal anterior. Um sinal que fica ativo por vários negócios conta uma vez só.

---

## 4. Calibrar parâmetros (grid)

Com `--grid`, o replay roda uma vez para cada combinação de valores e mostra quantos sinais saíram e a taxa de acerto de cada uma:

```
python main.py --asset WDOFUT --modo replay --arquivo wdo_2026-10-14.csv --tick-size 0.5 ^
    --grid exhaustion_vol_ratio=0.5,0.6,0.7 exhaustion_reversal_ticks=2,3,4 ^
    --saida grid_wdo.csv
```

(No Linux/macOS, troque `^` por `\`.)

- Cada item é `nome_do_parametro=valor1,valor2,...`. O nome é o mesmo do `EngineConfig` em `core/engine.py`.
- O exemplo acima testa 3 x 3 = 9 combinações. Cuidado: o número de combinações cresce rápido.
- A tabela mostra as melhores primeiro. O CSV (`--saida`, padrão `grid_resultado.csv`) traz todas, com nº de sinais por padrão (`n_exaustao`, `n_absorcao`...), alvos, stops, acerto, MFE e MAE médios.
- O grid sempre roda no modo lote, na velocidade máxima.

Parâmetros que normalmente valem a pena calibrar por ativo:

| Parâmetro | O que muda |
|---|---|
| `exhaustion_reversal_ticks` | Tamanho do recuo que fecha uma perna |
| `exhaustion_vol_ratio` | Quão menor a última perna precisa ser para virar exaustão |
| `exhaustion_min_legs` | Quantas pernas seguidas são comparadas |
| `absorption_min_touches` / `absorption_vol_ratio` | Quantos toques e quanto volume caracterizam absorção |
| `flow_pct_threshold` | % de fluxo dominante exigido |
| `min_confidence` | Confiança mínima para emitir sinal |

Dica: calibre com alguns dias e confira o resultado em **outros** dias. Um parâmetro ótimo para um único pregão costuma ser sorte.

---

## 5. Arquivo de exemplo

`replay/exemplo_wdo.csv` é um pregão **inventado** de WDO (tick 0,5), com uns 7 minutos e 235 negócios. Ele tem:

1. três pernas de alta com cada vez menos compra → exaustão no topo;
2. vendedores batendo várias vezes no mesmo preço até o nível ceder → absorção;
3. três pernas de baixa com cada vez menos venda → exaustão no fundo.

Serve para conferir se tudo funciona. Não serve para calibrar nada.

---

## 6. Tempo do pregão (detalhe técnico)

O engine mede todas as janelas (fluxo, absorção, urgência, best offer, exaustão) pelo **horário dos negócios**, e não pelo relógio do computador. O "agora" do engine é o horário do último negócio ou book recebido. Antes do primeiro negócio, ele usa o relógio do computador.

Por isso o mesmo arquivo dá sempre os mesmos sinais, em qualquer velocidade. Ao vivo, o horário dos negócios é praticamente o do relógio, então nada muda. A única diferença ao vivo: se o mercado parar, as janelas só "andam" quando chega o próximo negócio.

---

## 7. Baixar histórico pela ProfitDLL

Com a ProfitDLL dá para baixar os negócios de dias que já passaram, tick a tick, direto no formato do replay. Assim a calibração usa pregões reais, sem precisar ter gravado ao vivo. A Nelogica guarda cerca de 30 dias de histórico tick a tick.

Precisa das mesmas coisas do modo `dll`: Windows, a `ProfitDLL.dll`, o `profitTypes.py` e as variáveis `PROFITDLL_*` (veja `docs/registro-2026-10-14.md`, seção 3).

### O fluxo: baixar → replay → grid

**1. Baixar** (um arquivo por dia, na pasta `historico/`):

```
python -m profitdll.historico --asset WDOFUT --inicio 2026-10-01 --fim 2026-10-10 ^
    --saida historico/wdo_{data}.csv --agentes agentes.json
```

Isso gera `historico/wdo_2026-10-01.csv`, `historico/wdo_2026-10-02.csv`, `historico/wdo_2026-10-05.csv`...

**2. Ver um dia no replay:**

```
python main.py --asset WDOFUT --modo replay --arquivo historico/wdo_2026-10-01.csv --tick-size 0.5 --sem-servidor
```

**3. Calibrar com o grid:**

```
python main.py --asset WDOFUT --modo replay --arquivo historico/wdo_2026-10-01.csv --tick-size 0.5 ^
    --grid exhaustion_vol_ratio=0.5,0.6,0.7 exhaustion_reversal_ticks=2,3,4 --saida grid_0110.csv
```

Faça o grid em alguns dias e confira os melhores valores nos **outros** dias baixados. Para rodar vários dias de uma vez no replay, baixe tudo num arquivo só (sem `{data}` no nome, veja abaixo): o engine é zerado quando a data muda.

### Opções

| Opção | Para que serve |
|---|---|
| `--asset` | Ticker (`WDOFUT`, `WINZ26`, `PETR4`...) — obrigatório |
| `--inicio` | Primeiro dia, `2026-10-01` ou `01/10/2026` — obrigatório |
| `--fim` | Último dia (se faltar, baixa só o dia do `--inicio`) |
| `--saida` | Onde gravar. Padrão: `historico/{asset}_{data}.csv` |
| `--bolsa` | `F` (BMF) ou `B` (Bovespa). Se faltar, é deduzida do ticker |
| `--agentes` | JSON `{"codigo": "NOME"}` com o nome das corretoras (igual ao modo `dll`) |
| `--hora-inicio` / `--hora-fim` | Janela de cada dia. Padrão `09:00:00` a `18:35:00` |
| `--timeout-dia` | Quantos segundos esperar cada dia terminar (padrão 600) |
| `--tentativas` | Quantas vezes tentar um dia que deu erro (padrão 2) |
| `--refazer` | Baixa de novo os dias que já têm arquivo |

### Um arquivo por dia ou um arquivo só

- **Com `{data}` no nome** (o padrão): um arquivo por dia. `{data}` vira `AAAA-MM-DD` e `{asset}` vira o ticker. Se o download parar no meio, rode o mesmo comando de novo: os dias que já têm arquivo são pulados. Cada arquivo só aparece quando o dia termina inteiro, então um arquivo que existe nunca está pela metade.
- **Sem `{data}` no nome** (ex.: `--saida historico/wdo_outubro.csv`): todos os dias no mesmo arquivo, um depois do outro. Se o arquivo já existir, o programa para e avisa; use `--refazer` para apagar e baixar de novo.

### Como funciona por dentro

- O programa entra com o mesmo login do modo `dll`, mas **não assina** o ativo: só pede o histórico.
- Pede **um dia de cada vez** (a DLL aceita até 10 dias por pedido, mas a Nelogica recomenda dia a dia: WDO e WIN têm centenas de milhares de negócios por dia). Sábados e domingos são pulados. Feriados não são conhecidos: a DLL não devolve nada e o dia fica sem arquivo.
- Espera a DLL avisar que chegou a 100%. Cada dia é gravado assim que termina.
- Converte cada negócio com a mesma regra do tempo real: tipo 2 = compra agressora, tipo 3 = venda agressora. A corretora agressora vai em `corretora_agressora` e a outra em `corretora_passiva`. Os outros tipos (leilão, cross, RLP...) ficam de fora e são contados no log.
- O horário vem da DLL como horário de Brasília (`14/10/2026 10:00:00.125`) e vira o `timestamp` em segundos, com milissegundos. A conversão usa UTC-3 fixo, então não depende do fuso do computador.
- Antes de gravar, os negócios do dia são postos em ordem de horário (e, no mesmo milissegundo, pelo número do negócio). Número de negócio repetido é gravado uma vez só e aparece no log como duplicado.

No fim de cada dia o log mostra algo como:

```
01/10/2026: 412530 negócios recebidos, 398112 gravados, 14418 sem agressão
```

A pasta `historico/` está no `.gitignore`: os pregões baixados não vão para o repositório.

**Status:** a parte de conversão, ordem, dias úteis e gravação tem testes (`python test_engine.py`, teste 16). O download em si **não foi testado com a DLL real** ainda.
