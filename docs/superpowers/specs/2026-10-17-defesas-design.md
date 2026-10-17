# Defesas no motor (iceberg, sniper, fantasma, E2) — design

Data: 17/10/2026. Subprojeto 1 de 4 da leitura de fluxo do curso (2 = escora × rompimento, 3 = condução e saída,
4 = players e algoritmos). Só ações (bolsa B, tick R$ 0,01).

## 1. Objetivo

O motor passa a reconhecer **quem está segurando um preço** e de que jeito, como o professor ensina: iceberg, sniper,
fantasma e duas defesas juntas (E2). Também corrige dois erros do detector de iceberg atual:
- um único negócio 1 tick além do nível apaga a defesa, mesmo confirmada (mata todo sniper);
- duas corretoras dividindo o nível (`iceberg_min_share = 0.5`) se anulam ou fazem o sinal piscar.

O sistema continua só de **sinais para operação manual** na tela Operar. Nada é enviado à corretora.

## 2. Regra de origem: só o professor

Toda regra e todo número vêm do que o professor disse ou mostrou nas aulas. Cada parâmetro novo no `EngineConfig`
leva um comentário com a origem (`aula <id> mm:ss` ou `aula <id> quadro q_NNNNN`). Onde as aulas não dão medida, a
regra é escrita por **acontecimento** (ex.: "o fluxo atravessou o nível e o defensor não apareceu"), nunca por um
número estimado. O material de apoio (medidas e sequências transcritas dos quadros) fica só no computador do dono, em
`Documents\fluxo-cursos\estrategias\medidas\`, fora do git.

Os intervalos foram medidos pelo horário do Times & Trades (horário do mercado), porque os replays das aulas estão
acelerados. Resolução real: 10 ms (o 3º dígito dos milissegundos está cortado nas telas).

## 3. Entradas

- Cada negócio: horário (ms), preço, quantidade, lado agressor, corretora agressora, corretora passiva.
- Cada atualização do topo do book: melhor compra e melhor venda com quantidade, **sem corretora** (TinyBook da DLL).

Só fontes com corretora passiva (DLL, RTD, POST /tick) alimentam o módulo. Sem passiva (OCR, DDE, manual), continua o
iceberg simplificado de hoje, marcado como heurística fraca.

Negócios sem lado agressor (leilão, cross, RLP) são ignorados, como hoje.

## 4. Ordem original

Antes de classificar, o módulo junta os pedaços da mesma agressão: **mesma corretora agressora, mesmo lado e mesmo
horário até o milissegundo** viram uma ordem só (quantidade somada, preço do primeiro e do último pedaço). É o que a
aba "Ordem Original" do Profit mostrou em 9 de 10 ordens medidas (aula 9393818, LREN3; a exceção, UBS 3.200 com 111 ms
entre pedaços, não é coberta). "N agressões" em todo este documento significa N ordens originais.

## 5. Classificação

Unidade: uma **candidata** por (corretora, lado defendido, preço). Lado defendido: compra (suporte) ou venda
(resistência). Uma corretora pode ter candidatas em preços diferentes.

### 5.1 Iceberg
- **Assinatura:** a mesma corretora é a **passiva** de execuções repetidas no mesmo preço. O que conta é a repetição
  do nome no preço; o lote pode variar (Ágora 1.200 a 7.800, aula 9393840 08:45).
- **Lote:** a soma executada contra ela no preço precisa chegar a **1.000** ações (mínimo dito para ações, aula-02
  03:43–04:09).
- **Alerta / confirmação:** 1 giro alerta, 2 giros confirmam (aula 9393845 05:52). Giro = uma ordem original
  executada contra a candidata no preço.
- **Nenhum negócio além do nível** enquanto existir: 0 negócios além em todos os 5 exemplos medidos (CM Capital,
  Merrill, Santander, Itaú, Ágora).
- **Iceberg × absorção:** várias passivas com tamanhos diferentes no mesmo preço é absorção (padrão já existente), não
  iceberg (aula 9393840 03:58–04:16, Itaú × BTG). Duas passivas que repetem cada uma é E2 (5.4).
- **Fim — `rompida`:** primeiro negócio 1 tick além do nível (aula-02 24:15; aula 9393831).

### 5.2 Sniper
- **Assinatura:** a corretora defende o preço como passiva **e** agride do mesmo lado no mesmo preço contra quem tenta
  formar fila (aula-02 12:20–13:12; aula 9393841 11:39 "absorve e boleta de volta"). Reação medida: 0–30 ms entre a
  agressão contrária e a agressão do sniper (aula 9393841, 21,17 / 21,19 / 21,30 / 21,34). (ver §9, item 9: só por reação)
- Também vira sniper a candidata que **continua defendendo o preço depois de negócios além do nível** (aula-02 16:01). (ver §9, item 9: só quem já era defesa)
- **Agressão do mesmo lado:** a mesma corretora agredindo o lado oposto são clientes diferentes e não conta
  (aula-02 09:18; aula 9393831 07:18).
- **Tolera negócios além:** até 3 ticks além com o sniper ativo (máximo observado: 1–2 ticks em aula-02, 9393834 e
  9393841; 1–3 ticks em 9393833).
- **Muda de nível:** quando a mesma corretora passa a defender outro preço do mesmo lado, é a mesma defesa que mudou
  de nível (saltos observados +1, +2, +4, +12 ticks; aula 9393841). Recuo de 2 ticks com o defensor ainda no book não
  encerra (21,30 → 21,28 → 21,30, aula 9393841 13:44–13:54).
- **Fim:**
  - `fila_formada`: o topo do lado oposto fica no preço do sniper e o próximo negócio contra essa fila não é agressão
    dele (aula-02 17:45–18:46).
  - `defensor_ausente`: negócio a 4 ticks ou mais além do nível sem o sniper aparecer. No "cadê ele" o último sinal do
    Morgan foi 10:14:11,96 e o rompimento veio às 10:14:14,10 a 4 ticks (21,34 → 21,30); na perda do 21,03 o preço caiu
    5 ticks (aula 9393841).

### 5.3 Fantasma
- **Assinatura:** a mesma corretora **agressora** em 3 ordens no mesmo preço, com o book do lado dela vazio naquele
  preço (spread de 2–3 ticks: 35,14/35,16; 35,13/35,16; 22,39/22,42). O fantasma é agressor nos 3 exemplos
  (aula-02 25:09–25:35; aula 9393835; aula 9393842).
- **Tolera negócios além:** até 3 ticks (22,43 contra 22,40; 35,13/35,14 contra 35,15).
- **Fim:** `fila_formada` (o topo do lado oposto fica no preço e o próximo negócio contra essa fila não é dele) ou
  `defensor_ausente` (negócio a 4 ticks ou mais além). Medido: última agressão da Tullett 11:09:03,57; fila da Clear
  logo depois; varrida a +7 ticks 2,00 s depois (aula 9393842).

### 5.4 E2
- Duas defesas confirmadas (iceberg, sniper ou fantasma) de **corretoras diferentes**, do mesmo lado, no mesmo preço
  (0 tick) ou a 1 tick (Ágora 1.500 + Tullett 1.000 no 22,05, aula 9393845; Morgan iceberg 44,00 + Merrill sniper
  44,01, aula 9393844). (ver §9, item 5: uma confirmada + outra ao menos em alerta)
- Eventos: `e2_formado`; `e2_uma_acabou` quando uma das duas termina e a outra continua (regra dita em 9393845
  07:00–07:35 e 9393844 12:32–14:18; sem exemplo com horário).
- O E2 substitui a regra de fatia mínima: duas passivas repetindo no mesmo preço não se anulam mais.

### 5.5 Reclassificação, nunca descarte
- Iceberg que agride do mesmo lado no próprio preço → sniper (`reclassificada`).
- Iceberg com negócio além → `rompida`. Se a mesma corretora voltar a defender o mesmo preço, a defesa é reclassificada
  como sniper e o histórico é mantido.

### 5.6 Fora deste subprojeto (sem medida ou sem dado)
- Lotão: sem número de corte do professor (o "100 mil contra 10 mil" é hipotético, aula 9393817 01:12).
- Market maker: precisa de book completo com corretoras (aula 9393855); a DLL só manda o topo.
- Urgência numérica, camaleões, saldo por corretora: subprojeto 4.
- Instante exato em que uma das defesas do E2 acaba: nenhum exemplo com horário.

## 6. Arquitetura

### 6.1 `core/defesas.py` (novo)
- `DefesaDetector(cfg)` com estado próprio: candidatas, defesas ativas, ordem original em montagem, último topo do book.
- `on_tick(tick, agora)` e `on_book(compra, venda, agora)` — chamados pelo `FlowEngine`.
- `ativas() -> list[Defesa]`, `eventos(desde) -> list[EventoDefesa]`, `reset()`.
- `Defesa`: tipo (`iceberg` | `sniper` | `fantasma`), corretora, lado defendido, preço, desde, última atividade,
  volume absorvido, volume agredido, giros, níveis anteriores, `e2_com` (corretora parceira ou vazio).
- `EventoDefesa`: horário, tipo do evento (`alerta`, `confirmada`, `reclassificada`, `mudou_nivel`, `rompida`,
  `fila_formada`, `defensor_ausente`, `e2_formado`, `e2_uma_acabou`), defesa, preço, detalhe.
- Usa o relógio do engine (`_now()`), não `tick.timestamp` isolado.
- Guarda só candidatas e defesas ativas e os eventos recentes (janela limitada), para o teste de desempenho.

### 6.2 `FlowEngine`
- `add_tick`: chama `defesas.on_tick` em todo negócio com agressor (a parte passiva só conta com a passiva presente); sem passiva, o iceberg simplificado de hoje continua para OCR/DDE/manual.
- `update_book`: chama `defesas.on_book`.
- **Sinal de iceberg:** passa a vir das defesas do tipo iceberg confirmadas. Preço = nível. **Stop = 1 tick além do
  nível** (é onde o professor diz que o iceberg acabou; escora em iceberg com stop 1 tick atrás, aula 9393840 /
  9393845 06:30). O `stop_ticks_behind = 2` continua só para os outros padrões.
- Sniper, fantasma e E2 **não geram sinal** neste subprojeto: aparecem no estado e no log.
- Confluência da exaustão: passa a aceitar qualquer defesa confirmada do lado oposto (hoje só iceberg).
- `get_state()` ganha `"defesas": {"ativas": [...], "eventos": [...]}`; `icebergs_confirmed` e
  `icebergs_weak_heuristic` continuam.
- `reset()` chama `defesas.reset()`.
- Parâmetros novos no `EngineConfig` com prefixo `defesa_`, cada um com o comentário de origem.

### 6.3 Log
- Cada evento vira uma linha INFO: `Defesa <tipo> <corretora> <lado> @ <preço>: <evento> (<detalhe>)`.

### 6.4 Tela Operar
- Painel **"Defesas"** no lugar do "Livro" (que fica vazio com a DLL, que só manda o topo):
  - lista das ativas: tipo, corretora, lado, preço, há quanto tempo;
  - últimos eventos com horário ("Sniper MORGAN subiu 21,17 → 21,19", "Fantasma TULLETT: fila formada").
- O topo do book continua na linha de cima. A tela lê `state.defesas`.

## 7. Testes

### 7.1 Cenários das aulas (locais)
- Os testes leem as sequências transcritas de `FLUXO_CENARIOS_AULAS` (padrão
  `%USERPROFILE%\Documents\fluxo-cursos\estrategias\medidas\cenarios`). Sem a pasta, o teste é **pulado com aviso**,
  nunca dá falso verde nem falso vermelho.
- Na tela do professor o Times & Trades mostra só a corretora agressora (o passivo aparece como "-"); só
  `e2_9393845_0411.csv` tem a passiva. Os testes verificam apenas o que a sequência mostra:

| Sequência | O motor tem de |
|---|---|
| `sniper_9393841_1113` | marcar sniper MORGAN no 21,17 pela agressão do mesmo lado no mesmo preço |
| `sniper_9393841_1327` | mudança de nível 21,19 → 21,30 (o recuo virou teste unitário, ver §9 item 6) |
| `sniper_9393841_1429` | `defensor_ausente` no negócio de 10:14:14,10 (4 ticks além), não antes |
| `sniper_9393841_0545` | não encerrar o sniper com negócios 1–2 ticks além |
| `fantasma_9393842_*` | marcar fantasma TULLETT no 22,40 na 3ª agressão; terminar após 11:09:03,57 |
| `iceberg_9393840_0403` / `_0845` | nenhum `rompida` enquanto não houver negócio além do nível |
| `e2_9393845_0411` | `e2_formado` com ÁGORA + TULLETT no 22,05 |
| `leitura-tt_9393818_*_negocios` | juntar os pedaços nas ordens que o Profit mostrou (ex.: Ativa 20.000 em 27 pedaços) |

O horário exato de cada marcação esperada vem dos arquivos de medidas (`sniper.md`, `fantasma.md`, `e2.md`,
`iceberg.md`, `leitura-tt.md`) e é copiado para o teste.

### 7.2 Testes unitários (no repositório)
Sequências curtas montadas no próprio teste para cada regra de 5.1–5.5 (assinatura, tolerância, fim, reclassificação,
E2, ordem original), mesma corretora nos dois lados, negócio sem agressor, fonte sem passiva, `reset()` e troca de dia.

### 7.3 Regressão
- Testes de iceberg existentes (1, 2, 12–15) ajustados só onde a regra mudou de propósito: stop 1 tick além do nível;
  negócio além não apaga um sniper; fatia mínima substituída pelo E2 no caminho com passiva.
- Replay do `replay/exemplo_petr4.csv` continua determinístico e com exaustão e absorção.
- Teste de desempenho (20) cobre o módulo novo.
- `node tools/test_telas.mjs` e `node tools/qa_telas.js` cobrem o painel Defesas.

## 8. Fora de escopo
Sinais de escora × rompimento (subprojeto 2), condução e saída (3), saldo por corretora, POV, camaleões, urgência
(4), book completo, market maker, lotão.

## 9. Decisões tomadas no plano (17/10/2026)
Estas decisões prevalecem sobre §5, §6 e §7 onde divergirem (as seções anteriores trazem "ver §9" nesses pontos).

1. Sem tempo de expiração (decisão do dono): defesa só termina por acontecimento; o sinal de iceberg só sai com o
   último negócio no próprio nível.
2. O módulo recebe todo negócio com agressor; a parte passiva só conta com a passiva presente.
3. Passiva desconhecida não contradiz a reação do sniper; com a DLL a regra fica estrita.
4. "Lado vazio" do fantasma inferido pelos negócios (compra agressora executa na melhor venda, venda na melhor compra)
   e sem outra corretora agredindo do mesmo lado no preço.
5. E2 = uma defesa confirmada + outra ao menos em alerta (o professor chama o setup com o player novo, 9393845 04:49).
6. Teste do recuo 21,30 → 21,28 virou teste unitário: na sequência transcrita o recuo vem antes do reconhecimento.
7. Confiança do sinal de iceberg = fórmula antiga do motor (só ordena sinais; não é regra do curso).
8. Limitação conhecida: nas sequências das aulas (sem passiva nem book) aparecem classificações extras que o professor
   não comentou (ex.: outros "snipers" por reação com passiva desconhecida). A validação de quem defende fica para os
   dados reais da DLL quando a Bovespa estiver liberada.
9. Sniper só por reação ("absorve e boleta de volta" em ≤ defesa_reacao_ms, com a passiva da agressão contrária igual
   à corretora ou vazia); "continua defendendo depois de negócio além" só para defesa confirmada ou rompida (≥2 giros),
   e só com nova absorção passiva no preço (agressão não conta). Passiva + agressão espaçadas não fazem sniper.
10. Fila formada (sniper e fantasma) só se decide no negócio contra a fila (agressão do lado da defesa, no próprio preço); outros negócios
    não encerram a defesa.
11. Reclassificação para sniper também funde o sniper antigo da mesma corretora e lado (uma defesa só).
12. Reação só com 0 ≤ Δ ≤ defesa_reacao_ms; com fonte sem passiva (OCR/DDE/manual), sniper e fantasma aparecem na tela
    mas não entram na confluência de sinal.
