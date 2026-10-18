# Radar de fluxo (icebergs em todas as ações) — design

Data: 17/10/2026. Usa o detector de defesas (spec `2026-10-17-defesas-design.md`) e a calibração do iceberg
(`config/calibracao_iceberg.json`). Só ações à vista (bolsa B, tick R$ 0,01).

## 1. Objetivo

Ao vivo, ler **todas as ações à vista** da B3 ao mesmo tempo e montar uma lista com cada iceberg do dia: papel,
corretora, lado, preço, quantos giros e quanto volume absorveu, e como terminou — **segurou o preço** ou **rompeu**.
O radar aponta onde olhar; não gera sinal de entrada. A operação continua na tela Operar.

## 2. Viabilidade (medida em 17/10/2026)

- O detector de defesas sozinho processa **45–55 mil negócios/s** num núcleo (≈ 20 µs por negócio; pregão inteiro de
  PETR4 de 05/10, 180 mil negócios, em 4 s). A bolsa inteira fica bem abaixo disso, mesmo no pico.
- O motor completo (gráfico, exaustão, urgência…) é ~100× mais pesado: fica só no papel aberto na tela Operar.
- A DLL não lista os papéis (só `RequestTickerInfo` por papel) e o manual não cita limite de `SubscribeTicker`.
  Quantos papéis a licença aceita ao mesmo tempo só se confirma num pregão aberto.

## 3. Universo de papéis

- **Ações à vista do lote padrão:** ON, PN e UNIT (ex.: PETR4, VALE3, RENT3, TAEE11). Sem fracionário, BDR, FII, ETF.
- Fonte: cadastro público de instrumentos da B3 (arquivo diário). `tools/acoes_b3.py` baixa, filtra e grava
  `config/acoes_b3.txt` (um ticker por linha, versionado). O dono roda quando quiser atualizar.
- Ao conectar, cada papel é assinado na DLL; papel recusado vai para o log e para a tela Conexão.

## 4. Arquitetura

### 4.1 Uma conexão da DLL para tudo
- O processo filho da DLL (`profitdll/processo.py`) assina a lista inteira. Uma conexão só: a DLL não reinicializa no
  mesmo processo e dois logins com a mesma conta tendem a derrubar um ao outro.
- O callback de negócio já identifica o papel (`TConnectorAssetIdentifier`). A mensagem de negócio do protocolo
  filho → pai ganha o campo `ativo`.
- Contadores da conexão ganham: papéis pedidos, assinados e recusados (tela Conexão).

### 4.2 `core/radar.py` (novo)
- `Radar(cfg)`: um `DefesaDetector` por papel, criado no primeiro negócio dele. `on_tick(tick)` entrega ao do papel.
- **Evento novo `segurou`** (no detector de defesas): iceberg confirmado e o preço anda **4 ticks a favor** do nível
  sem negócio além (suporte: negócio a nível + 4; resistência: nível − 4). Parâmetro `defesa_segurou_ticks = 4`,
  comentado como calibração (mesmo alvo dos 42 pregões), não regra do professor. Depois de `segurou` a defesa segue
  acompanhada; se romper depois, as duas coisas ficam registradas.
- **Lista do dia:** um registro por iceberg confirmado — papel, corretora, lado, preço, giros, volume absorvido,
  confirmado às, situação (`segurando`, `segurou`, `rompeu`, `virou sniper`), hora do desfecho, `segurou_as` e
  `rompeu_as`, e o acerto histórico da faixa de volume (`core/calibracao.py`, quando houver).
- Ordem: primeiro os que estão **segurando agora** (maior volume primeiro); depois os resolvidos, do mais recente.
- `reset()` na troca de dia. Memória limitada aos icebergs do dia (registros pequenos).

### 4.3 Servidor
- `main.py` no modo dll (e no replay com `--radar`) cria o `Radar` e entrega **todo** negócio a ele; o negócio do
  papel aberto na Operar também vai para o `FlowEngine` desse papel.
- **Trocar o papel da Operar** (`POST /operar/ativo`): o `FlowEngine` zera e passa a receber o papel novo dali em
  diante. Carregar o histórico do dia do papel novo fica para depois.
- `GET /radar?situacao=…` → resumo (segurando, seguraram, romperam, papéis com negócio) + lista.

### 4.4 Tela "Radar" (F3)
- Faixa de cima com o resumo; lista com as colunas de §4.2; filtro por situação; clique no papel troca a Operar e
  abre a tela Operar.
- Mesmo estilo e mesma adaptação ao notebook (1536×864 e 1280×720) e ao monitor de 24".

### 4.5 Replay de vários papéis
- `python main.py --modo replay --radar historico/petr4_2026-10-16.csv historico/rent3_2026-10-16.csv …`: junta os
  negócios dos arquivos em ordem de horário (o papel vem do nome do arquivo) e alimenta o radar. Serve para testar e
  para ver o radar sem pregão aberto.

## 5. Testes
- Unitários: `segurou` exatamente a 4 ticks (não a 3); suporte e resistência; segurou e depois rompeu; papel novo
  criado no primeiro negócio; ordem da lista.
- Multi-ativo: replay de PETR4 + RENT3 juntos dá, por papel, os mesmos icebergs que cada papel sozinho.
- Desempenho: um pregão inteiro de PETR4 + RENT3 no radar em menos de 1 minuto.
- `tools/acoes_b3.py`: filtro de lote padrão sobre um trecho de cadastro de exemplo (sem rede no teste).
- QA da tela Radar em 1920×1080, 1536×864 e 1280×720.

## 6. Fora desta etapa
Sinais de entrada no radar; histórico do dia ao trocar o papel da Operar; calibração em lote de todos os papéis
(continua por `tools/calibrar_iceberg.py`); snipers/fantasmas na lista (o radar lista icebergs; os outros tipos
seguem no painel Defesas da Operar).
