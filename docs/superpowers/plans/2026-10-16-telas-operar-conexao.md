# Telas Operar e Conexão — plano de implementação

> **Para agentes:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou
> superpowers:executing-plans para executar este plano tarefa por tarefa. Os passos usam caixas (`- [ ]`) para
> acompanhamento.

**Objetivo:** trocar o `api/static/dashboard.html` por duas telas, **Operar** e **Conexão**, no design v3
"Terminal + manchete", com o backend que elas precisam (resumo do pregão, log em memória e reconexão da ProfitDLL).

**Arquitetura:**
- **Backend:** Python puro, sem dependências novas. Ganha:
  - o bloco `resumo` no engine;
  - um handler de log em memória;
  - a rota `POST /dll/reconectar`, que reaproveita a mesma `ProfitDLLBridge`;
  - rotas e estáticos com subpastas.
- **Frontend:** HTML, CSS e JS puros com ES modules, sem build. Cada tela consulta a API a cada 500 ms. Os gráficos
  usam a Lightweight Charts 5.2.1, que já está no repositório.

**Stack:** Python 3.12 (`http.server`, `logging`, `ctypes`), HTML/CSS/JS (ES2022, sem framework), Lightweight Charts
5.2.1, IBM Plex Sans/Mono (OFL), Node 24 (testes JS) e Playwright 1.x do `urnalytics-marcelo` (QA no navegador).

**Spec:** `docs/superpowers/specs/2026-10-16-telas-operar-conexao-design.md`. Leia junto com este plano.

## Restrições globais

- Sem build, sem npm e sem nenhuma dependência nova no Python. Bibliotecas e fontes ficam dentro de `api/static/`.
- Cores **exatamente** como em `docs/design/v3/tokens-v3.md`:
  - **escuro:** bg `#0F0F0D`, raise `#1A1915`, rule `#2C2A25`, grid `#1C1B18`, text `#ECE7DC`, muted `#A39D90`,
    faint `#928C80`, accent `#E3A33B`, buy `#4FBF7F`, sell `#E8604C`, volBuy `#357951`, volSell `#A74839`, inv `#0F0F0D`;
  - **claro:** bg `#F3F0E8`, raise `#E8E3D7`, rule `#D2CBBC`, grid `#E5E0D4`, text `#1C1B18`, muted `#57534A`,
    faint `#66615A`, accent `#8A5000`, buy `#176C40`, sell `#B0352A`, volBuy `#50936E`, volSell `#C46D63`, inv `#F3F0E8`;
  - a linha de lote grande usa buy ou sell a 13% no escuro e a 10% no claro.
- Proibido: card arredondado, sombra, glow, gradiente, pílula, chip, badge, ícone decorativo, sparkline decorativa,
  CAIXA ALTA espaçada e ciano. Raio de 0 a 2px. A estrutura vem de fios de 1px.
- Verde e vermelho só para compra e venda. **Âmbar só para estado e seleção.** O estado de conexão é sempre âmbar
  mais texto: quadrado cheio quando OK, quadrado vazado mais texto âmbar quando há problema.
  - O §9 da especificação fala em "status vermelho" para a DLL caída. As regras visuais obrigatórias do §2 e do
    tokens-v3 vencem: vermelho nunca indica estado.
- Tipografia: IBM Plex Sans (interface, com `font-variant-numeric: tabular-nums`) e IBM Plex Mono (tabelas, eixos,
  horas e log).
- Grade de 1920×1080: barra de 32px, faixa de 80px, corpo e rodapé de 28px. Divisão em x = 1180 (coluna direita de
  740px). Gutter de 16px.
- Chave, usuário e senha da ProfitDLL nunca aparecem em `/state`, `/log`, `/health` ou na tela.
- Atualização a cada 500 ms. Aviso "sem resposta do servidor" depois de 3 s sem resposta.
- Commit direto no `main`. Push só com o OK do dono.
- Testes Python: `PYTHONIOENCODING=utf-8 python -X utf8 test_engine.py`, no mesmo estilo de `ok()`/`err()`. A suíte
  precisa terminar com "TODOS OS TESTES PASSARAM!".
- Desvio consciente da especificação: além de `tokens.css` e `base.css`, cada tela tem um CSS próprio pequeno
  (`css/operar.css`, `css/conexao.css`), para o `base.css` não virar depósito.

## Foco da revisão

Situações que a especificação implica e que nenhum teste "natural" cobriria. Cada uma ganhou um teste na tarefa dona:

1. **Credenciais vazando** por `/state`, `/log` ou mensagem de log. Esperado: nunca aparecem. Coberto pelos testes 9e
   (stats) e 23 (log mascarado), nas tarefas 1 e 3.
2. **Reconectar clicado duas vezes**, ou durante uma conexão que demora até 30 s. Esperado: o segundo pedido recebe
   409 e o botão fica desabilitado. Teste 25 (tarefa 5).
3. **Negócio fora de ordem** (comum no replay e na DLL). Esperado: a abertura e o último preço seguem o horário do
   negócio, não a ordem de chegada. Teste 22 (tarefa 2).
4. **`POST /reset` ou virada do dia com a tela aberta.** Esperado: faixa, gráfico e manchete voltam para "—" e
   "Nenhum sinal ainda hoje", sem recarregar a página. QA "operar: reset" (tarefa 9).
5. **O servidor cai e volta com a tela aberta.** Esperado: aviso âmbar "parado há N s", dados congelados, e o aviso
   some sozinho quando o servidor volta. QA final (tarefa 7).

---

## Estrutura de arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `profitdll/bridge.py` | Modificar | `start()` depois de `stop()`, estados com nome, latência, caminho mascarado |
| `core/engine.py` | Modificar | bloco `resumo`, timeframes 900 e 3600, `financeiro` nos candles |
| `api/log_memoria.py` | Criar | `logging.Handler` em memória com máscara de credenciais |
| `api/server.py` | Modificar | páginas, `/static` com subpastas, `/health` com modo/fonte, `/log`, `/dll/reconectar` |
| `main.py` | Modificar | passa `modo` e `fonte` ao `FlowServer`; mensagens com `/operar` |
| `api/static/fonts/*.woff2`, `OFL.txt` | Criar | IBM Plex Sans e Mono 400/500/600 |
| `api/static/VENDOR.md` | Modificar | origem e sha256 das fontes |
| `api/static/css/tokens.css` | Criar | fontes e variáveis dos 2 temas |
| `api/static/css/base.css` | Criar | reset, grade, barra, faixa, tabelas, botões |
| `api/static/css/operar.css`, `conexao.css` | Criar | ajustes de cada tela |
| `api/static/js/formato.js` | Criar | números e horas em pt-BR (puro) |
| `api/static/js/api.js` | Criar | `getJSON`/`postJSON` com timeout, laço de consulta, "sem resposta" |
| `api/static/js/tabela.js` | Criar | tabela que reaproveita `<tr>` |
| `api/static/js/shell.js` | Criar | barra, rodapé, tema, atalhos, status da fonte |
| `api/static/operar.html` + `js/operar.js` | Criar | tela Operar e o laço dela |
| `api/static/js/operar-grafico.js` | Criar | candles, VWAP, volume, delta e marcas de sinal |
| `api/static/js/operar-paineis.js` | Criar | manchete, sinais anteriores, T&T, livro e saldo |
| `api/static/conexao.html` + `js/conexao.js` | Criar | tela Conexão |
| `api/static/dashboard.html` | Remover | substituído (continua no histórico do git) |
| `tools/test_telas.mjs` | Criar | testes Node das funções puras do frontend |
| `tools/qa_telas.js` | Criar | QA no navegador (Playwright) contra o replay de exemplo |
| `test_engine.py` | Modificar | testes 9e, 22, 23, 24 e 25, e o 21 ajustado |
| `.gitignore` | Modificar | `qa-telas/` (capturas do QA) |
| `docs/replay.md`, `docs/PROXIMOS-PASSOS.md` | Modificar | rotas e atalhos novos, licença só BMF |

---

### Tarefa 1: a ponte da ProfitDLL volta a conectar depois de `stop()`

**Arquivos:**
- Modificar: `profitdll/bridge.py` (constantes no topo, `__init__`, `stats()`, `start()`, `stop()`, `_conectar()`,
  `_on_estado()`, `_processar_trade()`)
- Teste: `test_engine.py` (nova `test_profitdll_reconexao`, registrada em `main()`)

**Interfaces:**
- Produz:
  - `ProfitDLLBridge._resetar_conexao() -> None`;
  - `stats()` ganha estas chaves:
    - `motivo_falha: str|None`;
    - `estados: {"login"|"ativacao"|"market": {"codigo": int, "nome": str} | None}`;
    - `latencia_ms: int|None`, `ativo: str`, `bolsa: str` e `dll_path: str|None` (mascarado);
  - `mascarar_caminho(caminho) -> str|None`;
  - `CAMINHO_PADRAO_DLL`, `NOMES_LOGIN` e `NOMES_ATIVACAO`;
  - `start()` devolve `False` com `motivo_falha` preenchido quando falha.

- [ ] **Passo 1: escrever o teste que falha.** Em `test_engine.py`, logo antes de `def test_profitdll_correcoes():`:

```python
def test_profitdll_reconexao():
    print(f"\n{AMARELO}═══ TESTE 9e: ProfitDLL — start() depois de stop() e stats da tela Conexão ═══{RESET}")

    import json as _json
    from profitdll.bridge import ProfitDLLBridge, AGRESSAO_COMPRA, mascarar_caminho

    class DLLFalsa:
        def SubscribeTicker(self, *a): return 0
        def UnsubscribeTicker(self, *a): return 0
        def DLLFinalize(self): return 0

    b = ProfitDLLBridge("WDOFUT", timeout=0.5)
    falhar = {"login": False}

    def conectar_falso():
        if falhar["login"]:
            b._on_estado(0, 2)                    # (0,2) senha inválida
        else:
            b._on_estado(0, 0); b._on_estado(3, 0); b._on_estado(2, 4)
        b.dll = DLLFalsa()
        b._aguardar_conexao()

    b._conectar = conectar_falso
    if b.start() and b.stats()["conectado"]:
        ok("start() conecta com login, ativação e market OK")
    else:
        err(f"start() inicial falhou: {b.stats()}")
    b.stop()
    if b.stats()["conectado"] is False:
        ok("stop() marca conectado = False no /state")
    else:
        err("stop() deixou conectado = True")

    # Uma falha antiga não pode abortar a próxima tentativa
    b._registrar_falha("senha inválida")
    if b.start() and b.motivo_falha is None:
        ok("start() depois de stop() limpa a falha antiga e reconecta")
    else:
        err(f"falha antiga travou a reconexão: {b.motivo_falha}")
    b.stop()

    # O estado antigo não pode declarar "conectada" antes de a DLL responder
    b._resetar_conexao()
    if not b._conectado_agora() and all(not e.is_set() for e in b._estado.values()):
        ok("_resetar_conexao() zera login, ativação e market")
    else:
        err("estado antigo sobreviveu ao reset")

    # Falha nova: start() devolve False com motivo e código legíveis
    falhar["login"] = True
    if not b.start() and b.motivo_falha == "senha inválida" \
            and b.stats()["estados"]["login"] == {"codigo": 2, "nome": "senha inválida"}:
        ok("Falha na reconexão devolve False com motivo e código do login")
    else:
        err(f"falha não reportada: {b.motivo_falha} {b.stats()['estados']}")

    # Latência e campos da tela Conexão
    falhar["login"] = False
    b.start()
    b._processar_evento(("trade", 3, 8, 1, 5078.5, AGRESSAO_COMPRA, time.time() - 0.05))
    st = b.stats()
    if st["latencia_ms"] is not None and 30 <= st["latencia_ms"] < 2000 \
            and st["estados"]["market"] == {"codigo": 4, "nome": "conectado"} \
            and st["ativo"] == "WDOFUT" and st["bolsa"] == "F":
        ok(f"stats() com latência ({st['latencia_ms']} ms), estados com nome, ativo e bolsa")
    else:
        err(f"stats() incompleto: {st}")
    b.stop()

    caminho = mascarar_caminho(r"C:\ProfitDLL\Win64\ProfitDLL.dll")
    if caminho == "C:\\…\\ProfitDLL.dll" and mascarar_caminho("") is None:
        ok("Caminho da DLL mascarado")
    else:
        err(f"máscara do caminho: {caminho}")

    segredos = {"PROFITDLL_KEY": "chave-secreta-123", "PROFITDLL_USER": "eu@exemplo.com",
                "PROFITDLL_PASS": "s3nh@Forte"}
    antigos = {k: os.environ.get(k) for k in segredos}
    os.environ.update(segredos)
    try:
        texto = _json.dumps(b.stats(), ensure_ascii=False)
        if not any(v in texto for v in segredos.values()):
            ok("stats() nunca contém chave, usuário ou senha")
        else:
            err("stats() vazou credencial")
    finally:
        for k, v in antigos.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
```

Em `main()`, depois de `test_profitdll_nomes_e_descartes()`, acrescente `test_profitdll_reconexao()`.

- [ ] **Passo 2: rodar e ver falhar.**
  - Comando: `cd C:\Users\Usuário\fluxo-server-profit && PYTHONIOENCODING=utf-8 python -X utf8 test_engine.py`
  - Esperado: falha no 9e com `ImportError: cannot import name 'mascarar_caminho'`.

- [ ] **Passo 3: implementar em `profitdll/bridge.py`.**

  1. Nos imports, acrescente `import ntpath` depois de `import os`.
  2. Depois do dicionário `NOMES_MARKET`, acrescente:

```python
NOMES_LOGIN    = {0: "conectado", **_FALHAS_LOGIN}
NOMES_ATIVACAO = {0: "válida", 1: "inválida"}

CAMINHO_PADRAO_DLL = r"C:\ProfitDLL\Win64\ProfitDLL.dll"


def mascarar_caminho(caminho: Optional[str]) -> Optional[str]:
    """C:\\ProfitDLL\\Win64\\ProfitDLL.dll → C:\\…\\ProfitDLL.dll (a tela não mostra a pasta inteira)."""
    if not caminho:
        return None
    drive, _ = ntpath.splitdrive(caminho)
    nome = ntpath.basename(caminho)
    return f"{drive}\\…\\{nome}" if drive else f"…\\{nome}"


def _estado_nomeado(codigo: Optional[int], nomes: dict) -> Optional[dict]:
    """(código, nome) de um estado do TStateCallback, ou None se ainda não chegou."""
    if codigo is None:
        return None
    return {"codigo": codigo, "nome": nomes.get(codigo, f"código {codigo}")}
```

  3. Em `__init__`, depois de `self.resultado_market: Optional[int] = None`:

```python
        self.resultado_login: Optional[int] = None
        self.resultado_ativacao: Optional[int] = None
        self.latencia_ms: Optional[int] = None   # chegada ao consumidor − horário do negócio
```

  4. Em `stats()`, depois de `"ask": ...`, ainda dentro do dicionário:

```python
            "motivo_falha":      self.motivo_falha,
            "estados": {
                "login":    _estado_nomeado(self.resultado_login, NOMES_LOGIN),
                "ativacao": _estado_nomeado(self.resultado_ativacao, NOMES_ATIVACAO),
                "market":   _estado_nomeado(self.resultado_market, NOMES_MARKET),
            },
            "latencia_ms":       self.latencia_ms,
            "ativo":             self.asset,
            "bolsa":             self.exchange,
            "dll_path":          mascarar_caminho(os.getenv("PROFITDLL_PATH", CAMINHO_PADRAO_DLL)),
```

  5. Troque o começo de `start()` (até o `return False` do `except`) por:

```python
    def start(self) -> bool:
        self._resetar_conexao()
        try:
            self._conectar()
        except Exception as e:
            self.motivo_falha = self.motivo_falha or str(e)
            logger.error(f"Falha ao conectar na ProfitDLL: {e}")
            self.stop()
            return False
```

  6. Em `stop()`:
     - logo depois de `self._parar.set()`, acrescente `self._conectado = False`;
     - logo antes do `logger.info(f"ProfitDLL encerrada ...`, acrescente `self._consumidor = None`. Esse ponto fica
       depois do bloco `if self.dll is not None:`, que ainda usa `self._consumidor` para decidir o
       `UnsubscribeTicker`.
  7. Depois do método `stop()`, acrescente:

```python
    def _resetar_conexao(self):
        """
        Zera o estado de CONEXÃO antes de cada start(): eventos de login/ativação/market,
        falha anterior, topo do livro e a fila antiga. Os contadores continuam acumulando
        (a tela Conexão mostra o dia inteiro, com as reconexões).
        """
        for evento in self._estado.values():
            evento.clear()
        self._falha.clear()
        self.motivo_falha = None
        self._conectado = False
        self.resultado_market = self.resultado_login = self.resultado_ativacao = None
        self.bid = self.ask = None
        while True:
            try:
                self.fila.get_nowait()
            except Empty:
                break
```

  8. Em `_conectar()`, troque `dll_path  = os.getenv("PROFITDLL_PATH", r"C:\ProfitDLL\Win64\ProfitDLL.dll")` por
     `dll_path  = os.getenv("PROFITDLL_PATH", CAMINHO_PADRAO_DLL)`.
  9. Em `_on_estado()`:
     - na primeira linha do ramo `if tipo == _LOGIN:`, acrescente `self.resultado_login = resultado`;
     - na primeira linha do ramo `elif tipo == _ATIVACAO:`, acrescente `self.resultado_ativacao = resultado`.
  10. Em `_processar_trade()`, troque o bloco `if ts is None:` por:

```python
        if ts is None:
            self.horarios_fallback += 1
            ts = time.time()
        else:
            self.latencia_ms = max(0, round((time.time() - ts) * 1000))
```

- [ ] **Passo 4: rodar e ver passar.**
  - Comando: `PYTHONIOENCODING=utf-8 python -X utf8 test_engine.py`
  - Esperado: o 9e passa com 9 ✓ e a suíte termina com "TODOS OS TESTES PASSARAM!".

- [ ] **Passo 5: commit.**

```bash
git add profitdll/bridge.py test_engine.py
git commit -m "fix(profitdll): start() funciona depois de stop(); stats com estados, latência e caminho mascarado"
```

---

### Tarefa 2: resumo do pregão no engine e timeframes de 15 e 60 min

**Arquivos:**
- Modificar: `core/engine.py` (`CANDLE_TFS`, `__init__`, `add_tick`, `_update_candles`, `get_candles`, `get_state`,
  `reset` e métodos novos)
- Teste: `test_engine.py` (nova `test_resumo_pregao`)

**Interfaces:**
- Produz:
  - `FlowEngine.get_resumo() -> dict` com as chaves `abertura`, `maxima`, `minima`, `ultimo`, `volume_financeiro`,
    `vwap`, `agressao_compra_pct`, `negocios_por_min` e `saldo_corretoras: list[[str, int]]`. Sem negócios, todas
    são `None` e o saldo é `[]`;
  - `get_state()["resumo"]`;
  - `CANDLE_TFS = (15, 60, 300, 900, 3600)`;
  - cada candle ganha `"financeiro"` (soma de preço × quantidade).

- [ ] **Passo 1: escrever o teste que falha.** Em `test_engine.py`, antes de `def main():`:

```python
def test_resumo_pregao():
    print(f"\n{AMARELO}═══ TESTE 22: Resumo do pregão (faixa do Operar) ═══{RESET}")

    e = FlowEngine("PETR4", EngineConfig())
    r0 = e.get_state()["resumo"]
    if r0["ultimo"] is None and r0["saldo_corretoras"] == [] and r0["negocios_por_min"] is None:
        ok("Sem negócios: resumo vazio (a tela mostra —)")
    else:
        err(f"resumo inicial: {r0}")

    e.add_tick(Tick(1000, 10.0, 100, "A", Side.BUY, passive_broker="B"))
    e.add_tick(Tick(1060, 12.0, 300, "B", Side.SELL, passive_broker="C"))
    e.add_tick(Tick(1030, 9.0, 100, "C", Side.BUY))            # chega fora de ordem, sem passiva
    r = e.get_state()["resumo"]
    esperado = {"abertura": 10.0, "maxima": 12.0, "minima": 9.0, "ultimo": 12.0,
                "volume_financeiro": 5500.0, "vwap": 11.0, "agressao_compra_pct": 40.0,
                "negocios_por_min": 3.0}
    if all(r[k] == v for k, v in esperado.items()):
        ok("Abertura/último pelo horário do negócio; máx, mín, financeiro, VWAP e agressão certos")
    else:
        err(f"resumo: {r}")
    if r["saldo_corretoras"] == [["C", 400], ["A", 100], ["B", -400]]:
        ok("Saldo soma a ponta agressora e a passiva, do maior ao menor")
    else:
        err(f"saldo: {r['saldo_corretoras']}")

    e.add_tick(Tick(1500, 11.0, 100, "D", Side.BUY))
    if e.get_resumo()["negocios_por_min"] == 0.2:
        ok("Negócios/min = últimos 5 min de horário de negócio")
    else:
        err(f"negocios_por_min: {e.get_resumo()['negocios_por_min']}")

    for i in range(12):
        e.add_tick(Tick(1501 + i, 11.0, 10 * (i + 1), f"X{i}", Side.BUY if i % 2 else Side.SELL))
    s = e.get_resumo()["saldo_corretoras"]
    valores = [v for _, v in s]
    if len(s) == 10 and valores == sorted(valores, reverse=True):
        ok("Com mais de 10 corretoras: as 5 maiores e as 5 menores")
    else:
        err(f"saldo com muitas corretoras: {s}")

    c900, c3600 = e.get_candles(900), e.get_candles(3600)
    if [c["time"] for c in c900] == [900] and [c["time"] for c in c3600] == [0] \
            and c900[0]["volume"] == 1380 and c900[0]["financeiro"] == 15180.0:
        ok("Candles de 15 e 60 min, com financeiro para a VWAP")
    else:
        err(f"candles 900/3600: {c900} {c3600}")

    e.reset()
    if e.get_resumo()["ultimo"] is None and e.get_resumo()["saldo_corretoras"] == []:
        ok("reset zera o resumo")
    else:
        err(f"resumo depois do reset: {e.get_resumo()}")
```

Em `main()`, depois de `test_api_grafico_tt_book()`, acrescente `test_resumo_pregao()`.

- [ ] **Passo 2: rodar e ver falhar.**
  - Comando: `PYTHONIOENCODING=utf-8 python -X utf8 test_engine.py`
  - Esperado: o teste 22 falha com `KeyError: 'resumo'`.

- [ ] **Passo 3: implementar em `core/engine.py`.**

  1. Troque `CANDLE_TFS = (15, 60, 300)` por `CANDLE_TFS = (15, 60, 300, 900, 3600)`.
  2. Em `__init__`, depois de `self._last_signal_key: Optional[tuple] = None`:

```python
        # ── Resumo do pregão (faixa do Operar), incremental: nada aqui varre o pregão
        self._zerar_resumo()
```

  3. Em `add_tick`, logo depois de `self._update_candles(tick)`, acrescente `self._atualizar_resumo(tick)`.
  4. Em `_update_candles`:
     - no dicionário do candle novo, acrescente `"financeiro": 0.0,` depois de `"sell": 0,`;
     - logo depois de `c["volume"] += tick.qty`, acrescente `c["financeiro"] += tick.price * tick.qty`.
  5. Em `get_candles`, troque a tupla `campos` por
     `("time", "open", "high", "low", "close", "volume", "buy", "sell", "financeiro")`.
  6. Antes de `def _registrar_sinal(self):`, acrescente:

```python
    JANELA_NEGOCIOS_SEC = 300   # negócios/min = média dos últimos 5 min de horário de negócio

    def _zerar_resumo(self):
        self._r_abertura: Optional[tuple] = None   # (horário, preço) do 1º negócio pelo horário
        self._r_ultimo: Optional[tuple] = None     # (horário, preço) do último pelo horário
        self._r_max: Optional[float] = None
        self._r_min: Optional[float] = None
        self._r_qtd = 0
        self._r_qtd_compra = 0
        self._r_financeiro = 0.0
        self._r_recentes: deque = deque()           # horários dos negócios na janela de 5 min
        self._r_saldo: dict[str, int] = defaultdict(int)

    def _atualizar_resumo(self, tick: Tick):
        """
        Atualiza o resumo do dia com um negócio. Regras:
        - abertura e último seguem o HORÁRIO do negócio (um negócio atrasado não vira "último");
        - volume financeiro = Σ preço × quantidade (sem multiplicador de contrato);
        - saldo da corretora = compras − vendas em quantidade, contando a ponta agressora e,
          quando a fonte informa, a passiva (agressão de compra: agressora +q, passiva −q).
        """
        p, q, ts = tick.price, tick.qty, tick.timestamp
        if self._r_abertura is None or ts < self._r_abertura[0]:
            self._r_abertura = (ts, p)
        if self._r_ultimo is None or ts >= self._r_ultimo[0]:
            self._r_ultimo = (ts, p)
        self._r_max = p if self._r_max is None else max(self._r_max, p)
        self._r_min = p if self._r_min is None else min(self._r_min, p)
        self._r_qtd += q
        self._r_financeiro += p * q
        if tick.side == Side.BUY:
            self._r_qtd_compra += q
        self._r_recentes.append(ts)
        limite = self._r_ultimo[0] - self.JANELA_NEGOCIOS_SEC
        while self._r_recentes and self._r_recentes[0] <= limite:
            self._r_recentes.popleft()
        sinal = 1 if tick.side == Side.BUY else -1 if tick.side == Side.SELL else 0
        if sinal:
            self._r_saldo[tick.broker] += sinal * q
            if tick.passive_broker:
                self._r_saldo[tick.passive_broker] -= sinal * q

    def get_resumo(self) -> dict:
        """Resumo do pregão para GET /state (bloco "resumo"). Sem negócios, tudo None."""
        with self._lock:
            if not self._r_qtd:
                return {"abertura": None, "maxima": None, "minima": None, "ultimo": None,
                        "volume_financeiro": None, "vwap": None, "agressao_compra_pct": None,
                        "negocios_por_min": None, "saldo_corretoras": []}
            # janela real: até 5 min, mas nunca menos de 1 min (começo do pregão)
            janela = min(self.JANELA_NEGOCIOS_SEC, max(60.0, self._r_ultimo[0] - self._r_abertura[0]))
            saldo = sorted(((b, s) for b, s in self._r_saldo.items() if b),
                           key=lambda x: x[1], reverse=True)
            if len(saldo) > 10:
                saldo = saldo[:5] + saldo[-5:]
            return {
                "abertura":            self._r_abertura[1],
                "maxima":              self._r_max,
                "minima":              self._r_min,
                "ultimo":              self._r_ultimo[1],
                "volume_financeiro":   round(self._r_financeiro, 2),
                "vwap":                round(self._r_financeiro / self._r_qtd, 6),
                "agressao_compra_pct": round(100.0 * self._r_qtd_compra / self._r_qtd, 1),
                "negocios_por_min":    round(len(self._r_recentes) / (janela / 60.0), 1),
                "saldo_corretoras":    [[b, s] for b, s in saldo],
            }
```

  7. Em `get_state()`, no dicionário devolvido, acrescente antes de `"signal":` a linha
     `"resumo":             self.get_resumo(),`. O `RLock` permite chamar de dentro do `with self._lock`.
  8. Em `reset()`, dentro do `with self._lock:`, depois de `self._signals_log.clear()`, acrescente
     `self._zerar_resumo()`.

- [ ] **Passo 4: rodar e ver passar.**
  - Comando: `PYTHONIOENCODING=utf-8 python -X utf8 test_engine.py`
  - Esperado: o 22 passa com 7 ✓; o 21 (`/candles?tf=42` → 400) e o de desempenho continuam verdes.

- [ ] **Passo 5: commit.**

```bash
git add core/engine.py test_engine.py
git commit -m "feat(engine): resumo do pregão no /state e candles de 15 e 60 min"
```

---

### Tarefa 3: log em memória e `GET /log`

**Arquivos:**
- Criar: `api/log_memoria.py`
- Modificar: `api/server.py` (import, `FlowHandler.log`, rota `/log`, `FlowServer.__init__`, docstring)
- Teste: `test_engine.py` (nova `test_log_memoria`)

**Interfaces:**
- Produz:
  - `LogMemoria(capacidade=500, nivel=logging.INFO)`;
  - `LogMemoria.registros(since: float|None = None, nivel: str = "INFO") -> list[dict]`, com cada registro no
    formato `{"ts": float, "nivel": "WARNING", "origem": "ProfitDLL", "msg": str}`. Um nível inválido gera
    `ValueError`;
  - `instalar() -> LogMemoria`, idempotente, que instala no logger raiz;
  - `GET /log?since=T&nivel=INFO` → `{"registros": [...]}`, do mais antigo ao mais novo e só com `ts > since`.
    Um `nivel` ou `since` inválido devolve 400.

- [ ] **Passo 1: escrever o teste que falha.** Em `test_engine.py`, antes de `def main():`:

```python
def test_log_memoria():
    print(f"\n{AMARELO}═══ TESTE 23: Log em memória (GET /log) ═══{RESET}")

    import json
    import logging
    import urllib.error
    import urllib.request
    from api.log_memoria import LogMemoria
    from api.server import FlowServer

    h = LogMemoria(capacidade=3)
    lg = logging.getLogger("TesteLog")
    lg.propagate = False
    lg.setLevel(logging.INFO)
    lg.addHandler(h)
    antigo = os.environ.get("PROFITDLL_PASS")
    os.environ["PROFITDLL_PASS"] = "s3nh@Teste"
    try:
        lg.info("primeiro")
        lg.warning("login falhou com s3nh@Teste")
        t_meio = time.time()
        time.sleep(0.01)
        lg.error("market caiu")
        lg.info("quarto")                         # capacidade 3: "primeiro" sai
    finally:
        if antigo is None:
            os.environ.pop("PROFITDLL_PASS", None)
        else:
            os.environ["PROFITDLL_PASS"] = antigo
        lg.removeHandler(h)

    regs = h.registros()
    if [r["msg"] for r in regs] == ["login falhou com •••", "market caiu", "quarto"] \
            and regs[0]["nivel"] == "WARNING" and regs[0]["origem"] == "TesteLog":
        ok("Guarda os últimos N registros e mascara a senha")
    else:
        err(f"registros: {regs}")
    if [r["msg"] for r in h.registros(since=t_meio)] == ["market caiu", "quarto"]:
        ok("since devolve só os registros posteriores")
    else:
        err(f"since: {h.registros(since=t_meio)}")
    if [r["msg"] for r in h.registros(nivel="ERROR")] == ["market caiu"]:
        ok("nivel=ERROR filtra do nível pedido para cima")
    else:
        err(f"nivel: {h.registros(nivel='ERROR')}")
    try:
        h.registros(nivel="XYZ")
        err("nível inválido aceito")
    except ValueError:
        ok("Nível inválido → ValueError")

    porta = 15573
    base = f"http://127.0.0.1:{porta}"
    server = FlowServer(FlowEngine("PETR4", EngineConfig()), host="127.0.0.1", port=porta)
    server.start()
    time.sleep(0.3)
    try:
        logging.getLogger("API").warning("aviso para a tela")
        with urllib.request.urlopen(base + "/log?nivel=WARNING", timeout=3) as r:
            corpo = json.loads(r.read())
        if any(x["msg"] == "aviso para a tela" and x["origem"] == "API" for x in corpo["registros"]):
            ok("GET /log devolve o log do servidor")
        else:
            err(f"/log: {corpo}")
        for rota in ("/log?nivel=XYZ", "/log?since=abc"):
            try:
                urllib.request.urlopen(base + rota, timeout=3)
                err(f"{rota} aceito")
            except urllib.error.HTTPError as e:
                if e.code != 400:
                    err(f"{rota} devolveu {e.code}")
        ok("/log com nivel ou since inválidos → 400")
    finally:
        server.stop()
```

Em `main()`, depois de `test_resumo_pregao()`, acrescente `test_log_memoria()`.

- [ ] **Passo 2: rodar e ver falhar.**
  - Esperado: `ModuleNotFoundError: No module named 'api.log_memoria'`.

- [ ] **Passo 3: criar `api/log_memoria.py`.**

```python
"""
LOG EM MEMÓRIA PARA A TELA CONEXÃO (GET /log)
=============================================
Um logging.Handler que guarda os últimos N registros (INFO ou mais) num deque,
thread-safe. Instalado no logger raiz pelo FlowServer, capta ProfitDLL,
ProfitDLLHistorico, API, Main etc.

Antes de guardar, troca por "•••" qualquer trecho igual ao valor atual de
PROFITDLL_KEY, PROFITDLL_USER ou PROFITDLL_PASS: credencial nunca sai do servidor.
"""
import os
import logging
import threading
from collections import deque
from typing import Optional

VARIAVEIS_SECRETAS = ("PROFITDLL_KEY", "PROFITDLL_USER", "PROFITDLL_PASS")
NIVEIS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def mascarar(texto: str, segredos) -> str:
    """Troca cada segredo (com 4+ caracteres, para não mascarar letra solta) por •••."""
    for s in segredos:
        if s and len(s) >= 4:
            texto = texto.replace(s, "•••")
    return texto


class LogMemoria(logging.Handler):
    def __init__(self, capacidade: int = 500, nivel: int = logging.INFO):
        super().__init__(nivel)
        self._registros: deque = deque(maxlen=capacidade)
        self._trava = threading.Lock()

    def emit(self, record: logging.LogRecord):
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        if record.exc_info:
            msg += " | " + logging.Formatter().formatException(record.exc_info).splitlines()[-1]
        segredos = [os.environ.get(n, "") for n in VARIAVEIS_SECRETAS]
        registro = {"ts": record.created, "nivel": record.levelname,
                    "origem": record.name, "msg": mascarar(msg, segredos)}
        with self._trava:
            self._registros.append(registro)

    def registros(self, since: Optional[float] = None, nivel: str = "INFO") -> list[dict]:
        """Registros com ts > since e nível >= nivel, do mais antigo ao mais novo."""
        minimo = NIVEIS.get(str(nivel).upper())
        if minimo is None:
            raise ValueError(f"nível inválido: {nivel} (use {', '.join(NIVEIS)})")
        with self._trava:
            copia = list(self._registros)
        return [dict(r) for r in copia
                if (since is None or r["ts"] > since) and NIVEIS.get(r["nivel"], 0) >= minimo]


_instalado: Optional[LogMemoria] = None


def instalar() -> LogMemoria:
    """Instala (uma vez só) o LogMemoria no logger raiz e o devolve."""
    global _instalado
    if _instalado is None:
        _instalado = LogMemoria()
        logging.getLogger().addHandler(_instalado)
    return _instalado
```

- [ ] **Passo 4: ligar no `api/server.py`.**

  1. Depois de `from core.rtd import RTDTradeInferer, RTDSnapshot`, acrescente `from api import log_memoria`.
  2. Na classe `FlowHandler`, depois de `dll = None ...`, acrescente
     `log: "log_memoria.LogMemoria" = None   # GET /log (tela Conexão)`.
  3. Em `do_GET`, antes do `else:` final, acrescente:

```python
        elif path == "/log":
            try:
                since = num("since")
                registros = self.log.registros(since, qs.get("nivel", ["INFO"])[0])
            except ValueError as e:
                self._send_json({"error": str(e)}, 400)
                return
            self._send_json({"registros": registros})
```

  4. Em `FlowServer.__init__`, depois de `FlowHandler.dll = None`, acrescente
     `FlowHandler.log = log_memoria.instalar()`.
  5. Na docstring do módulo, depois da linha do `GET  /book`, acrescente
     `  GET  /log?since=T&nivel=INFO → log do servidor em memória (credenciais mascaradas)`.

- [ ] **Passo 5: rodar e ver passar.**
  - Esperado: o 23 passa com 6 ✓ e a suíte continua toda verde.

- [ ] **Passo 6: commit.**

```bash
git add api/log_memoria.py api/server.py test_engine.py
git commit -m "feat(api): log em memória com credenciais mascaradas (GET /log)"
```

---

### Tarefa 4: páginas novas, `/static` com subpastas e `/health` com modo e fonte

**Arquivos:**
- Modificar:
  - `api/server.py` (`_TIPOS`, `caminho_estatico`, `PAGINAS`, rotas de página, `/health`, `FlowServer.__init__`,
    `FlowServer.start`, docstring);
  - `main.py` (`fonte_da_captura`, as duas criações de `FlowServer`, mensagens);
  - `test_engine.py` (trecho de estáticos e `/dashboard` do teste 21; nova `test_api_health_modo`).

**Interfaces:**
- Produz:
  - `FlowServer(engine, host, port, modo="manual", fonte=None)`;
  - `GET /health` com as chaves `modo`, `fonte` e `tick_size`, além das que já existiam;
  - `/`, `/dashboard` e `/operar` servem `operar.html`; `/conexao` serve `conexao.html`. Sem o arquivo, devolvem 503;
  - `/static/<css|js|fonts>/<arquivo>`;
  - `main.fonte_da_captura(args) -> str`.
- Observação: até a tarefa 7, `/operar` devolve 503, porque `operar.html` ainda não existe. O `dashboard.html` antigo
  sai na tarefa 11.

- [ ] **Passo 1: ajustar o teste 21 (falha esperada).**
  1. Em `test_api_grafico_tt_book`, troque o trecho que vai de `# Estáticos: travessia recusada` até a linha
     `srv.STATIC_DIR = original`, inclusive, pelo bloco abaixo.
  2. Remova o `post("/tick", ... "</script><b>" ...)`: o estado não é mais injetado no HTML.

```python
        # Estáticos: travessia recusada, subpasta fora de css/js/fonts e inexistente → 404
        for rota in ("/static/../server.py", "/static/..%2Fserver.py", "/static/sub/x.js",
                     "/static/js/../server.py", "/static/js/sub/x.js", "/static/.oculto.js",
                     "/static/naoexiste.js"):
            cod, _, _ = get(rota)
            if cod != 404:
                err(f"{rota} devolveu {cod} (esperado 404)")
        ok("/static recusa '..', subpastas fora de css/js/fonts e arquivos inexistentes")

        # Páginas: sem o arquivo → 503; com os arquivos → HTML puro (estado vem do /state)
        original = srv.STATIC_DIR
        with tempfile.TemporaryDirectory() as tmp:
            srv.STATIC_DIR = tmp
            cod, _, _ = get("/operar")
            if cod == 503:
                ok("/operar sem api/static/operar.html → 503")
            else:
                err(f"/operar sem arquivo devolveu {cod}")
            arquivos = {"operar.html": "<p>operar</p>", "conexao.html": "<p>conexao</p>",
                        "x.js": "var x = 1;", "css/a.css": "body{}",
                        "js/m.js": "export const m = 1;", "fonts/f.woff2": "wOF2"}
            for nome, conteudo in arquivos.items():
                caminho = os.path.join(tmp, *nome.split("/"))
                os.makedirs(os.path.dirname(caminho), exist_ok=True)
                with open(caminho, "w", encoding="utf-8") as f:
                    f.write(conteudo)
            for rota in ("/", "/dashboard", "/operar"):
                cod, corpo, tipo = get(rota)
                if not (cod == 200 and corpo == b"<p>operar</p>" and "text/html" in tipo):
                    err(f"{rota} não serviu operar.html: {cod} {corpo[:60]}")
            ok("/, /dashboard e /operar servem operar.html")
            cod, corpo, _ = get("/conexao")
            if cod == 200 and corpo == b"<p>conexao</p>":
                ok("/conexao serve conexao.html")
            else:
                err(f"/conexao: {cod} {corpo[:60]}")
            tipos = {"/static/x.js": "application/javascript", "/static/css/a.css": "text/css",
                     "/static/js/m.js": "application/javascript", "/static/fonts/f.woff2": "font/woff2"}
            for rota, esperado in tipos.items():
                cod, _, tipo = get(rota)
                if cod != 200 or not tipo.startswith(esperado):
                    err(f"{rota}: {cod} {tipo}")
            ok("/static serve css/, js/ e fonts/ com o content-type certo")
        srv.STATIC_DIR = original
```

  3. Antes de `def main():`, crie:

```python
def test_api_health_modo():
    print(f"\n{AMARELO}═══ TESTE 24: /health com modo, fonte e tick ═══{RESET}")

    import json
    import urllib.request
    from api.server import FlowServer

    porta = 15574
    for kwargs, esperado in (({}, ("manual", None)),
                             ({"modo": "replay", "fonte": "exemplo_wdo.csv"}, ("replay", "exemplo_wdo.csv"))):
        engine = FlowEngine("WDOFUT", EngineConfig(tick_size=0.5))
        server = FlowServer(engine, host="127.0.0.1", port=porta, **kwargs)
        server.start()
        time.sleep(0.3)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/health", timeout=3) as r:
                h = json.loads(r.read())
        finally:
            server.stop()
        if (h["modo"], h["fonte"]) == esperado and h["tick_size"] == 0.5 and h["asset"] == "WDOFUT":
            ok(f"/health → modo {h['modo']}, fonte {h['fonte']}, tick {h['tick_size']}")
        else:
            err(f"/health: {h}")
        porta += 1
```

  4. Em `main()`, depois de `test_log_memoria()`, acrescente `test_api_health_modo()`.

- [ ] **Passo 2: rodar e ver falhar.**
  - Esperado: o teste 21 falha em `/static/css/a.css` com 404, ou o `/operar` devolve 404 em vez de 503.

- [ ] **Passo 3: implementar no `api/server.py`.**
  1. Em `_TIPOS`, acrescente `".mjs": "application/javascript; charset=utf-8",` e
     `".txt": "text/plain; charset=utf-8",`.
  2. Troque o comentário `# api/static/dashboard.html: __STATE_JSON__ ...` por
     `# Páginas e arquivos das telas (api/static/). As páginas buscam o estado no GET /state.`.
  3. Troque a função `caminho_estatico` por:

```python
_SUBPASTAS = ("css", "js", "fonts")

# Rota → página em STATIC_DIR
PAGINAS = {"/": "operar.html", "/dashboard": "operar.html", "/operar": "operar.html",
           "/conexao": "conexao.html"}


def caminho_estatico(nome: str):
    """
    Caminho de um arquivo de STATIC_DIR ou de uma subpasta css/, js/ ou fonts/.
    None para '..', caminho absoluto, arquivo oculto, outra subpasta, tipo não servido ou inexistente.
    """
    if not nome or "\\" in nome or nome.startswith("/"):
        return None
    partes = nome.split("/")
    if len(partes) > 2 or (len(partes) == 2 and partes[0] not in _SUBPASTAS):
        return None
    if any(not p or p.startswith(".") or ":" in p for p in partes):
        return None
    if os.path.splitext(nome)[1].lower() not in _TIPOS:
        return None
    caminho = os.path.join(STATIC_DIR, *partes)
    return caminho if os.path.isfile(caminho) else None
```

  4. Na classe `FlowHandler`, acrescente `modo = "manual"` e `fonte = None`, cada um com um comentário curto
     (`# GET /health: modo do main.py e nome da fonte`).
  5. Em `/health`, acrescente ao dicionário as chaves `"modo": self.modo`, `"fonte": self.fonte` e
     `"tick_size": self.engine.cfg.tick_size`.
  6. Troque o bloco inteiro `elif path == "/dashboard":` por:

```python
        elif path in PAGINAS:
            arquivo = os.path.join(STATIC_DIR, PAGINAS[path])
            try:
                with open(arquivo, "rb") as f:
                    corpo = f.read()
            except OSError:
                self._send_bytes(f"Tela indisponível: api/static/{PAGINAS[path]} não encontrado.\n"
                                 .encode(), "text/plain; charset=utf-8", code=503)
                return
            self._send_bytes(corpo, "text/html; charset=utf-8")
```

  7. No ramo `/static/`, troque o cache: `cache = "max-age=86400" if ext == ".woff2" or "lightweight-charts" in caminho
     else "no-cache"`. Assim, JS e CSS das telas nunca ficam velhos no navegador depois de uma atualização. Passe
     `cache` para `_send_bytes`.
  8. Remova o método `_send_html` se nada mais o usar. Confira com `grep -n "_send_html" api/server.py`.
  9. Troque a assinatura de `FlowServer.__init__` por
     `def __init__(self, engine: FlowEngine, host: str = "127.0.0.1", port: int = 5000, modo: str = "manual", fonte=None):`
     e, depois de `FlowHandler.dll = None`, acrescente `FlowHandler.modo = modo` e `FlowHandler.fonte = fonte`.
  10. Em `FlowServer.start`, troque a linha `Dashboard:` por
      `logger.info(f"Telas: http://{self.host}:{self.port}/operar  (F2 = Conexão)")`.
  11. Na docstring, troque a linha do `/dashboard` por estas duas e acrescente o `/conexao`:
      - `  GET  / , /operar      → tela Operar (api/static/operar.html; /dashboard também abre)`
      - `  GET  /conexao        → tela Conexão (api/static/conexao.html)`
      - e a do `/static/<nome>` por `  GET  /static/[css|js|fonts/]<nome> → arquivos de api/static/`.
      Na linha do `/health`, acrescente "(modo, fonte e tick do ativo)".
  12. Na linha do `/candles`, troque "(15, 60 ou 300)" por "(15, 60, 300, 900 ou 3600)".

- [ ] **Passo 4: `main.py`.**
  1. Antes de `def rodar_modo_replay`, acrescente:

```python
def fonte_da_captura(args) -> str:
    """Nome curto da fonte para o cabeçalho das telas (GET /health)."""
    if args.modo == "replay":
        return os.path.basename(args.arquivo or "")
    return {"dll": "ProfitDLL", "rtd": "rtd", "dde": "dde", "ocr": "ocr"}.get(args.modo, "manual")
```

  2. Em `rodar_modo_replay`:
     - troque `server = FlowServer(engine, host=args.host, port=args.port)` por
       `server = FlowServer(engine, host=args.host, port=args.port, modo="replay", fonte=fonte_da_captura(args))`;
     - troque o `print` do "Dashboard do replay" por
       `print(f"  Telas do replay: http://{args.host}:{args.port}/operar  (F2 = Conexão)")`.
  3. Em `main()`, troque `server = FlowServer(engine, host=args.host, port=args.port)` por
     `server = FlowServer(engine, host=args.host, port=args.port, modo=args.modo, fonte=fonte_da_captura(args))`.
  4. Na mensagem de boas-vindas, troque as duas linhas do Dashboard por
     `print(f"  Telas:    http://{args.host}:{args.port}/operar  (F2 = Conexão)")`.

- [ ] **Passo 5: rodar e ver passar.**
  - Esperado: o 21 e o 24 passam e a suíte continua verde.
  - Conferência manual rápida: `python -X utf8 main.py --modo manual --port 5091`. Em seguida, `curl -s
    127.0.0.1:5091/health` mostra `"modo": "manual"` e `curl -s -o NUL -w "%{http_code}" 127.0.0.1:5091/operar`
    devolve 503. Encerre com Ctrl+C.

- [ ] **Passo 6: commit.**

```bash
git add api/server.py main.py test_engine.py
git commit -m "feat(api): rotas das telas, /static com css/js/fonts e /health com modo e fonte"
```

---

### Tarefa 5: `POST /dll/reconectar`

**Arquivos:**
- Modificar: `api/server.py` (`FlowHandler.reconexao`, `_trava_reconexao`, `_reconectar`, `do_POST`,
  `_estado_completo`, `FlowServer.__init__`, docstring)
- Teste: `test_engine.py` (nova `test_api_reconectar`)

**Interfaces:**
- Consome: `bridge.stop()`, `bridge.start() -> bool`, `bridge.motivo_falha` e `bridge.stats()` (tarefa 1).
- Produz:
  - `POST /dll/reconectar` devolve 202 com `{"ok": true, "reconexao": {...}}`; 409 se já houver uma reconexão em
    andamento; 404 sem ponte;
  - `GET /state` ganha `dll.reconexao = {"em_andamento": bool, "ultima": float|None, "resultado": "ok" |
    "falhou: <motivo>" | None}`.

- [ ] **Passo 1: escrever o teste que falha.** Antes de `def main():`:

```python
def test_api_reconectar():
    print(f"\n{AMARELO}═══ TESTE 25: POST /dll/reconectar ═══{RESET}")

    import json
    import threading
    import urllib.error
    import urllib.request
    from api.server import FlowServer

    class PonteFalsa:
        def __init__(self):
            self.ok, self.motivo_falha, self.chamadas = True, None, []
            self.liberar = threading.Event()

        def stop(self):
            self.chamadas.append("stop")

        def start(self):
            self.chamadas.append("start")
            self.liberar.wait(3)
            if not self.ok:
                self.motivo_falha = "senha inválida"
            return self.ok

        def stats(self):
            return {"conectado": self.ok}

    porta = 15576
    base = f"http://127.0.0.1:{porta}"

    def post(rota):
        req = urllib.request.Request(base + rota, data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def reconexao():
        with urllib.request.urlopen(base + "/state", timeout=3) as r:
            return json.loads(r.read())["dll"]["reconexao"]

    def esperar_fim():
        for _ in range(80):
            rec = reconexao()
            if not rec["em_andamento"]:
                return rec
            time.sleep(0.05)
        err("reconexão não terminou")

    server = FlowServer(FlowEngine("WDOFUT", EngineConfig(tick_size=0.5)),
                        host="127.0.0.1", port=porta, modo="dll", fonte="ProfitDLL")
    server.start()
    time.sleep(0.3)
    try:
        cod, _ = post("/dll/reconectar")
        if cod == 404:
            ok("Sem ponte registrada → 404")
        else:
            err(f"sem ponte devolveu {cod}")

        ponte = PonteFalsa()
        server.registrar_dll(ponte)
        cod, corpo = post("/dll/reconectar")
        cod2, _ = post("/dll/reconectar")
        if cod == 202 and corpo["reconexao"]["em_andamento"] and cod2 == 409:
            ok("202 ao pedir; 409 enquanto a reconexão anterior roda")
        else:
            err(f"reconectar: {cod} {cod2} {corpo}")
        if reconexao()["em_andamento"]:
            ok("/state mostra a reconexão em andamento")
        else:
            err("/state não mostrou em_andamento")

        ponte.liberar.set()
        rec = esperar_fim()
        if rec["resultado"] == "ok" and ponte.chamadas == ["stop", "start"] and rec["ultima"]:
            ok("Reconexão chama stop() e start() na mesma ponte; resultado ok")
        else:
            err(f"reconexão: {rec} {ponte.chamadas}")

        ponte.ok = False
        post("/dll/reconectar")
        rec = esperar_fim()
        if rec["resultado"] == "falhou: senha inválida":
            ok("Falha aparece com o motivo vindo de motivo_falha")
        else:
            err(f"falha: {rec}")
    finally:
        server.stop()
```

Em `main()`, depois de `test_api_health_modo()`, acrescente `test_api_reconectar()`.

- [ ] **Passo 2: rodar e ver falhar.**
  - Esperado: `KeyError: 'reconexao'`, ou 404 no lugar de 202.

- [ ] **Passo 3: implementar no `api/server.py`.**
  1. Na classe `FlowHandler`, depois de `fonte = None`:

```python
    # Reconexão da ProfitDLL pedida pela tela Conexão (uma de cada vez)
    reconexao = {"em_andamento": False, "ultima": None, "resultado": None}
    _trava_reconexao = threading.Lock()

    @staticmethod
    def _reconectar(bridge):
        """Roda numa thread: stop() + start() na MESMA ponte (o engine continua ligado em on_tick)."""
        logger.info("ProfitDLL: reconectando (pedido pela tela Conexão)")
        try:
            bridge.stop()
            ok = bridge.start()
            resultado = "ok" if ok else f"falhou: {bridge.motivo_falha or 'veja o log'}"
        except Exception as e:
            resultado = f"falhou: {e}"
        with FlowHandler._trava_reconexao:
            FlowHandler.reconexao = {"em_andamento": False, "ultima": time.time(), "resultado": resultado}
        (logger.info if resultado == "ok" else logger.error)(f"ProfitDLL: reconexão {resultado}")
```

  2. Em `_estado_completo`, troque `state["dll"] = self.dll.stats()` por:

```python
            state["dll"] = self.dll.stats()
            state["dll"]["reconexao"] = dict(FlowHandler.reconexao)
```

  3. Em `do_POST`, antes do `else:` final:

```python
        elif path == "/dll/reconectar":
            if self.dll is None:
                self._send_json({"error": "reconectar só existe no modo dll"}, 404)
                return
            with FlowHandler._trava_reconexao:
                if FlowHandler.reconexao["em_andamento"]:
                    self._send_json({"error": "reconexão já em andamento"}, 409)
                    return
                FlowHandler.reconexao = {"em_andamento": True, "ultima": time.time(), "resultado": None}
            threading.Thread(target=FlowHandler._reconectar, args=(self.dll,), daemon=True).start()
            self._send_json({"ok": True, "reconexao": dict(FlowHandler.reconexao)}, 202)
```

  4. Em `FlowServer.__init__`, depois de `FlowHandler.fonte = fonte`, acrescente
     `FlowHandler.reconexao = {"em_andamento": False, "ultima": None, "resultado": None}`.
  5. Na docstring, depois do `POST /reset`, acrescente
     `  POST /dll/reconectar → stop()+start() da ProfitDLL numa thread (202; 409 se já reconectando; 404 fora do modo dll)`.
  6. Confira que `main.py` já chama `server.registrar_dll(data_source)` antes de `start()` e mantém a ponte registrada
     mesmo quando o `start()` falha. Hoje ele mantém, e é isso que permite o Reconectar depois de uma falha na subida.
     Não mude essa ordem.

- [ ] **Passo 4: rodar e ver passar.**
  - Esperado: o 25 passa com 5 ✓ e a suíte continua verde.

- [ ] **Passo 5: commit.**

```bash
git add api/server.py test_engine.py
git commit -m "feat(api): POST /dll/reconectar com estado da reconexão no /state"
```

---

### Tarefa 6: fontes IBM Plex, `tokens.css` e `base.css`

**Arquivos:**
- Criar:
  - `api/static/fonts/IBMPlexSans-{Regular,Medium,SemiBold}.woff2`;
  - `api/static/fonts/IBMPlexMono-{Regular,Medium,SemiBold}.woff2`;
  - `api/static/fonts/OFL.txt`;
  - `api/static/css/tokens.css` e `api/static/css/base.css`.
- Modificar: `api/static/VENDOR.md`

**Interfaces:**
- Produz:
  - variáveis CSS `--bg --raise --rule --grid --text --muted --faint --accent --buy --sell --vol-buy --vol-sell --inv
    --lote-buy --lote-sell --faixa-26`, em `:root[data-tema="escuro"|"claro"]`;
  - classes de `base.css`:
    - grade e barra: `.tela .topo .marca .aba .direita .modo .status .quadrado(.vazio) .relogio .tema .aviso
      .rodape .atalhos`;
    - faixa: `.faixa .metrica .rotulo .valor .heroi`;
    - cores: `.compra .venda .muted .faint .ambar`;
    - seções: `.corpo .secao .cab .meta .acoes .seletor`;
    - tabelas e botões: `.num .lote-compra .lote-venda .destaque .rolagem .barra .botao(.primario) .vazio-msg`.

- [ ] **Passo 1: baixar as fontes (versão fixa) e conferir.**

```bash
cd C:/Users/Usuário/fluxo-server-profit/api/static
mkdir -p fonts
for p in Sans Mono; do
  for w in Regular Medium SemiBold; do
    curl -sSfL -o "fonts/IBMPlex$p-$w.woff2" \
      "https://cdn.jsdelivr.net/npm/@ibm/plex-$(echo $p | tr A-Z a-z)@1.1.0/fonts/complete/woff2/IBMPlex$p-$w.woff2"
  done
done
curl -sSfL -o fonts/OFL.txt "https://cdn.jsdelivr.net/npm/@ibm/plex-sans@1.1.0/LICENSE.txt"
for f in fonts/*.woff2; do printf '%s ' "$f"; head -c4 "$f"; echo; done   # cada linha termina em wOF2
sha256sum fonts/*.woff2 fonts/OFL.txt
```

Esperado: 6 arquivos `.woff2`, cada um começando com `wOF2`, e um `OFL.txt` com "SIL OPEN FONT LICENSE". Guarde a
saída do `sha256sum` para o passo 2.

- [ ] **Passo 2: registrar no `VENDOR.md`.** Acrescente no fim:

```markdown
## IBM Plex Sans e IBM Plex Mono

| campo | valor |
| --- | --- |
| versão | @ibm/plex-sans 1.1.0 e @ibm/plex-mono 1.1.0 (npm) |
| arquivos | `fonts/IBMPlexSans-{Regular,Medium,SemiBold}.woff2`, `fonts/IBMPlexMono-{Regular,Medium,SemiBold}.woff2` |
| origem | https://cdn.jsdelivr.net/npm/@ibm/plex-sans@1.1.0/fonts/complete/woff2/ (idem plex-mono) |
| licença | SIL Open Font License 1.1 — texto em `fonts/OFL.txt` (LICENSE.txt do pacote) |
| sha256 | (colar aqui a saída do sha256sum do passo 1, um arquivo por linha) |

As telas carregam as fontes de `/static/fonts/` (funciona offline, sem Google Fonts).
```

Troque a linha "(colar aqui...)" pelas 7 linhas reais do `sha256sum`. Não deixe o texto entre parênteses.

- [ ] **Passo 3: criar `api/static/css/tokens.css`.**

```css
/* Tokens do design v3 "Terminal + manchete" — valores de docs/design/v3/tokens-v3.md.
   Não alterar sem refazer a tabela de contraste. O tema vem de data-tema no <html>. */
@font-face { font-family: "IBM Plex Sans"; font-weight: 400; font-display: swap; src: url("../fonts/IBMPlexSans-Regular.woff2") format("woff2"); }
@font-face { font-family: "IBM Plex Sans"; font-weight: 500; font-display: swap; src: url("../fonts/IBMPlexSans-Medium.woff2") format("woff2"); }
@font-face { font-family: "IBM Plex Sans"; font-weight: 600; font-display: swap; src: url("../fonts/IBMPlexSans-SemiBold.woff2") format("woff2"); }
@font-face { font-family: "IBM Plex Mono"; font-weight: 400; font-display: swap; src: url("../fonts/IBMPlexMono-Regular.woff2") format("woff2"); }
@font-face { font-family: "IBM Plex Mono"; font-weight: 500; font-display: swap; src: url("../fonts/IBMPlexMono-Medium.woff2") format("woff2"); }
@font-face { font-family: "IBM Plex Mono"; font-weight: 600; font-display: swap; src: url("../fonts/IBMPlexMono-SemiBold.woff2") format("woff2"); }

:root, :root[data-tema="escuro"] {
  --bg: #0F0F0D; --raise: #1A1915; --rule: #2C2A25; --grid: #1C1B18;
  --text: #ECE7DC; --muted: #A39D90; --faint: #928C80;
  --accent: #E3A33B; --buy: #4FBF7F; --sell: #E8604C;
  --vol-buy: #357951; --vol-sell: #A74839; --inv: #0F0F0D;
  --lote-buy: rgba(79, 191, 127, 0.13); --lote-sell: rgba(232, 96, 76, 0.13);
  --faixa-26: rgba(227, 163, 59, 0.22);
  color-scheme: dark;
}
:root[data-tema="claro"] {
  --bg: #F3F0E8; --raise: #E8E3D7; --rule: #D2CBBC; --grid: #E5E0D4;
  --text: #1C1B18; --muted: #57534A; --faint: #66615A;
  --accent: #8A5000; --buy: #176C40; --sell: #B0352A;
  --vol-buy: #50936E; --vol-sell: #C46D63; --inv: #F3F0E8;
  --lote-buy: rgba(23, 108, 64, 0.10); --lote-sell: rgba(176, 53, 42, 0.10);
  --faixa-26: rgba(138, 80, 0, 0.18);
  color-scheme: light;
}
```

- [ ] **Passo 4: criar `api/static/css/base.css`.**

```css
/* Base comum às telas: grade 32/80/corpo/28, fios de 1px, tipografia Plex, tabelas e botões retos. */
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%; background: var(--bg); color: var(--text); }
body { font: 400 13px/18px "IBM Plex Sans", system-ui, sans-serif; font-variant-numeric: tabular-nums; overflow: hidden; }
button { font: inherit; }
.mono { font-family: "IBM Plex Mono", ui-monospace, monospace; }

.tela { display: grid; grid-template-rows: 32px 80px minmax(0, 1fr) 28px; height: 100vh; min-width: 1280px; }

/* Barra de 32px */
.topo { display: flex; align-items: stretch; padding: 0 16px; border-bottom: 1px solid var(--rule); white-space: nowrap; }
.topo .marca { display: flex; align-items: center; font-weight: 600; padding-right: 16px; margin-right: 4px; border-right: 1px solid var(--rule); }
.topo nav { display: flex; }
.aba { display: flex; align-items: center; padding: 0 12px; color: var(--muted); text-decoration: none; border-bottom: 2px solid transparent; }
.aba[aria-current="page"] { color: var(--text); border-bottom-color: var(--accent); }
.aba[aria-disabled="true"] { color: var(--faint); cursor: default; }
.topo .direita { margin-left: auto; display: flex; align-items: center; gap: 24px; }
.modo b { font-weight: 500; padding: 7px 0; border-bottom: 2px solid var(--accent); }
.status { display: flex; align-items: center; gap: 8px; color: var(--muted); }
.status.alerta { color: var(--accent); }
.quadrado { width: 7px; height: 7px; background: var(--accent); }
.quadrado.vazio { background: transparent; box-shadow: inset 0 0 0 1px var(--accent); }
.relogio { font: 500 15px/20px "IBM Plex Mono", monospace; }
.tema { color: var(--muted); }
.tema button { background: none; border: 0; color: var(--muted); cursor: pointer; padding: 0 4px; }
.tema button[aria-pressed="true"] { color: var(--text); font-weight: 500; }
.aviso { color: var(--accent); }

/* Rodapé de 28px */
.rodape { display: flex; align-items: center; padding: 0 16px; border-top: 1px solid var(--rule); color: var(--faint); font-size: 12px; }
.rodape .atalhos { margin: 0 auto; display: flex; gap: 20px; font-family: "IBM Plex Mono", monospace; }

/* Faixa de 80px: rótulo 12px + valor, separados por fio vertical */
.faixa { display: flex; align-items: stretch; padding: 0 16px; border-bottom: 1px solid var(--rule); overflow: hidden; }
.metrica { display: flex; flex-direction: column; justify-content: center; gap: 2px; padding: 0 20px; margin: 12px 0; border-left: 1px solid var(--rule); white-space: nowrap; }
.metrica:first-child { border-left: 0; padding-left: 0; }
.metrica .rotulo { font-size: 12px; color: var(--muted); }
.metrica .valor { font: 500 23px/28px "IBM Plex Sans", sans-serif; }
.metrica .valor small { font: 400 12px/16px "IBM Plex Sans", sans-serif; color: var(--muted); margin-left: 8px; }
.heroi { font: 500 56px/60px "IBM Plex Sans", sans-serif; }

.compra { color: var(--buy); }
.venda { color: var(--sell); }
.muted { color: var(--muted); }
.faint { color: var(--faint); }
.ambar { color: var(--accent); }

/* Corpo: conteúdo principal | coluna de apoio de 740px (x = 1180 em 1920) */
.corpo { display: grid; grid-template-columns: minmax(0, 1fr) 740px; min-height: 0; }
.secao { display: flex; flex-direction: column; min-height: 0; border-left: 1px solid var(--rule); }
.corpo > .secao:first-child { border-left: 0; }
.cab { display: flex; align-items: baseline; gap: 16px; height: 36px; padding: 9px 16px 0; flex: 0 0 auto; }
.cab h2 { font: 600 13px/18px "IBM Plex Sans", sans-serif; }
.meta { font-size: 12px; color: var(--faint); }
.cab .acoes { margin-left: auto; display: flex; gap: 16px; }
.seletor { background: none; border: 0; border-bottom: 2px solid transparent; color: var(--muted); cursor: pointer; padding: 0 0 2px; }
.seletor[aria-pressed="true"] { color: var(--text); border-bottom-color: var(--accent); }

/* Tabelas densas: Mono 13, números à direita */
table { border-collapse: collapse; width: 100%; table-layout: fixed; font: 400 13px/21px "IBM Plex Mono", monospace; }
th { font: 400 12px/20px "IBM Plex Sans", sans-serif; color: var(--muted); text-align: left; padding: 0 8px; border-bottom: 1px solid var(--rule); }
td { padding: 0 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
th:first-child, td:first-child { padding-left: 16px; }
th:last-child, td:last-child { padding-right: 16px; }
.num { text-align: right; }
tr.lote-compra { background: var(--lote-buy); font-weight: 600; }
tr.lote-venda { background: var(--lote-sell); font-weight: 600; }
tr.destaque { background: var(--raise); }
.rolagem { flex: 1; min-height: 0; overflow-y: auto; }
.barra { display: block; height: 3px; }
.barra.compra { background: var(--vol-buy); }
.barra.venda { background: var(--vol-sell); }

/* Botões retos: primário (um por área), secundário e desabilitado */
.botao { font: 500 13px/18px "IBM Plex Sans", sans-serif; color: var(--text); background: none; border: 1px solid var(--faint); border-radius: 0; padding: 6px 14px; cursor: pointer; }
.botao.primario { background: var(--text); color: var(--inv); border-color: var(--text); }
.botao:disabled { background: none; color: var(--faint); border-color: var(--rule); cursor: default; }
.vazio-msg { color: var(--muted); padding: 16px; }
```

- [ ] **Passo 5: conferir os tipos e as subpastas.**
  - Comando: `python -X utf8 main.py --modo manual --port 5091`.
  - Em outro terminal:

```bash
curl -s -o NUL -w "%{http_code} %{content_type}\n" 127.0.0.1:5091/static/css/tokens.css
curl -s -o NUL -w "%{http_code} %{content_type}\n" 127.0.0.1:5091/static/fonts/IBMPlexSans-Regular.woff2
```

  - Esperado: `200 text/css; charset=utf-8` e `200 font/woff2`. Encerre o servidor.
  - Contraste: os tokens são cópia literal do `tokens-v3.md`, então não há par novo para medir.

- [ ] **Passo 6: commit.**

```bash
git add api/static/fonts api/static/css/tokens.css api/static/css/base.css api/static/VENDOR.md
git commit -m "feat(telas): fontes IBM Plex embutidas, tokens v3 e CSS base"
```

---

### Tarefa 7: módulos JS comuns, páginas mínimas e QA da barra

**Arquivos:**
- Criar:
  - `api/static/js/formato.js`, `api/static/js/api.js`, `api/static/js/tabela.js`, `api/static/js/shell.js`;
  - `api/static/operar.html` e `api/static/conexao.html` (versões mínimas, completadas nas tarefas 8 e 10);
  - `tools/test_telas.mjs` e `tools/qa_telas.js`.
- Modificar: `.gitignore`

**Interfaces:**
- Produz:
  - **`formato.js`:**
    - `casasDoTick(tick)`;
    - `preco(v, casas=2)`, `inteiro(v)`, `comSinal(v, fmt=inteiro)`;
    - `financeiro(v)`, `compacto(v)`, `pct(v, casas=1)`;
    - `horaB3(epoch)` e `hm(epoch)`.
    - Valores nulos viram "—".
  - **`api.js`:** `getJSON(url, timeoutMs=2500)`, `postJSON(url, corpo={}, timeoutMs=5000) -> {status, dados}`,
    `laco(passo, intervalo=500) -> parar()` e `segundosSemResposta()`.
  - **`tabela.js`:** `atualizarLinhas(tbody, linhas, montar)`, em que `montar(dado)` devolve
    `{classe?, celulas: [{t?, c?, barra?: {pct, lado}}]}`.
  - **`shell.js`:** `montarShell(telaAtiva) -> {saude, atualizarStatus(estado)}`,
    `textoStatus(dll, fonte) -> [texto, alerta]`, `aplicarTema(tema, salvar)`, `temaAtual()` e o evento
    `window "tema"`.
  - **`qa_telas.js`:** o array `verificacoes`, a que as tarefas 8 a 10 acrescentam itens, e os helpers `checar`,
    `esperar` e `esperarFimReplay`.

- [ ] **Passo 1: escrever o teste JS que falha (`tools/test_telas.mjs`).**

```js
// Testes das funções puras do frontend (sem navegador). Uso: node tools/test_telas.mjs
import assert from "node:assert/strict";
import * as f from "../api/static/js/formato.js";
import { textoStatus } from "../api/static/js/shell.js";

assert.equal(f.preco(38.47), "38,47");
assert.equal(f.preco(5078.5, 1), "5.078,5");
assert.equal(f.preco(null), "—");
assert.equal(f.inteiro(184300), "184.300");
assert.equal(f.comSinal(184300), "+184.300");
assert.equal(f.comSinal(-0.48, (v) => f.preco(v)), "-0,48");
assert.equal(f.compacto(92000), "+92 mil");
assert.equal(f.compacto(-61000), "-61 mil");
assert.equal(f.compacto(-1234567), "-1,2 mi");
assert.equal(f.compacto(950), "+950");
assert.equal(f.financeiro(412000000), "R$ 412,0 mi");
assert.equal(f.financeiro(2.5e9), "R$ 2,5 bi");
assert.equal(f.pct(57), "57,0%");
assert.equal(f.casasDoTick(0.5), 1);
assert.equal(f.casasDoTick(0.01), 2);
assert.equal(f.casasDoTick(0.25), 2);
assert.equal(f.casasDoTick(5), 0);
assert.equal(f.horaB3(1792183666.518), "17:47:46");   // 16/10/2026 20:47:46 UTC = 17:47:46 em Brasília
assert.equal(f.hm(1792183666.518), "17:47");
assert.equal(f.horaB3(null), "—");

const ok = { conectado: true, latencia_ms: 12, estados: { market: { codigo: 4, nome: "conectado" } }, reconexao: {} };
assert.deepEqual(textoStatus(ok, "ProfitDLL"), ["ProfitDLL conectado (2,4) · 12 ms", false]);
assert.deepEqual(textoStatus({ ...ok, estados: { market: { codigo: 6 } } }, "ProfitDLL"),
  ["ProfitDLL conectado (2,6) · callbacks atrasados", true]);
assert.deepEqual(textoStatus({ conectado: false, motivo_falha: "senha inválida", estados: {} }, "ProfitDLL"),
  ["desconectado — senha inválida", true]);
assert.deepEqual(textoStatus({ ...ok, reconexao: { em_andamento: true } }, "ProfitDLL"), ["reconectando…", true]);
assert.deepEqual(textoStatus(undefined, "exemplo_wdo.csv"), ["fonte: exemplo_wdo.csv", false]);

console.log("test_telas.mjs: tudo certo");
```

- [ ] **Passo 2: rodar e ver falhar.**
  - Comando: `cd C:\Users\Usuário\fluxo-server-profit && node tools/test_telas.mjs`
  - Esperado: `ERR_MODULE_NOT_FOUND` para `formato.js`.

- [ ] **Passo 3: criar `api/static/js/formato.js`.**

```js
// Formatação pt-BR de números e horários das telas (puro: testado em tools/test_telas.mjs).
const FUSO = "America/Sao_Paulo";
const formatos = new Map();
function nf(casas) {
  if (!formatos.has(casas)) {
    formatos.set(casas, new Intl.NumberFormat("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas }));
  }
  return formatos.get(casas);
}
const vazio = (v) => v === null || v === undefined || Number.isNaN(v);

/** Casas decimais do tick do ativo: 0,5 → 1; 0,01 → 2; 0,25 → 2; 5 → 0. */
export function casasDoTick(tick) {
  if (!tick) return 2;
  const decimais = String(tick).split(".")[1];
  return decimais ? Math.min(4, decimais.length) : 0;
}
export function preco(v, casas = 2) { return vazio(v) ? "—" : nf(casas).format(v); }
export function inteiro(v) { return vazio(v) ? "—" : nf(0).format(Math.round(v)); }
/** +184.300 / -0,48: o sinal fica explícito; fmt formata o valor absoluto. */
export function comSinal(v, fmt = inteiro) {
  if (vazio(v)) return "—";
  return (v > 0 ? "+" : v < 0 ? "-" : "") + fmt(Math.abs(v));
}
export function financeiro(v) {
  if (vazio(v)) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return `R$ ${nf(1).format(v / 1e9)} bi`;
  if (a >= 1e6) return `R$ ${nf(1).format(v / 1e6)} mi`;
  if (a >= 1e3) return `R$ ${nf(1).format(v / 1e3)} mil`;
  return `R$ ${nf(0).format(v)}`;
}
/** Saldo em lotes, com sinal: +92 mil, -1,2 mi, +950. */
export function compacto(v) {
  if (vazio(v)) return "—";
  const a = Math.abs(v);
  const s = v > 0 ? "+" : v < 0 ? "-" : "";
  if (a >= 1e6) return `${s}${nf(1).format(a / 1e6)} mi`;
  if (a >= 1e3) return `${s}${nf(0).format(Math.round(a / 1e3))} mil`;
  return `${s}${nf(0).format(a)}`;
}
export function pct(v, casas = 1) { return vazio(v) ? "—" : `${nf(casas).format(v)}%`; }

const fmtHora = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
const fmtHM = new Intl.DateTimeFormat("pt-BR", { timeZone: FUSO, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
/** Hora de Brasília (B3) de um epoch em segundos. */
export function horaB3(epoch) { return vazio(epoch) ? "—" : fmtHora.format(new Date(epoch * 1000)); }
export function hm(epoch) { return vazio(epoch) ? "—" : fmtHM.format(new Date(epoch * 1000)); }
```

- [ ] **Passo 4: criar `api/static/js/api.js`.**

```js
// Acesso à API do Fluxo Server: JSON com timeout, laço de consulta e o relógio do "sem resposta".
let ultimoSucesso = Date.now();

/** Segundos desde a última resposta do servidor (qualquer status HTTP conta como resposta). */
export function segundosSemResposta() { return (Date.now() - ultimoSucesso) / 1000; }

async function pedir(url, opcoes, timeoutMs) {
  const controle = new AbortController();
  const relogio = setTimeout(() => controle.abort(), timeoutMs);
  try {
    const r = await fetch(url, { ...opcoes, signal: controle.signal, cache: "no-store" });
    ultimoSucesso = Date.now();
    const dados = await r.json().catch(() => ({}));
    return { status: r.status, dados };
  } finally {
    clearTimeout(relogio);
  }
}

export async function getJSON(url, timeoutMs = 2500) {
  const { status, dados } = await pedir(url, {}, timeoutMs);
  if (status >= 400) throw new Error(dados.error || `HTTP ${status}`);
  return dados;
}

export function postJSON(url, corpo = {}, timeoutMs = 5000) {
  return pedir(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corpo) }, timeoutMs);
}

/** Chama `passo` a cada `intervalo` ms, um de cada vez (nunca sobrepõe). Falha de rede não para o laço. */
export function laco(passo, intervalo = 500) {
  let parado = false;
  async function rodar() {
    if (parado) return;
    const inicio = performance.now();
    try {
      await passo();
    } catch (e) {
      // rede fora/servidor parado: o aviso "sem resposta" do cabeçalho já informa
      if (!(e instanceof TypeError) && e.name !== "AbortError") console.warn(e.message);
    }
    setTimeout(rodar, Math.max(0, intervalo - (performance.now() - inicio)));
  }
  rodar();
  return () => { parado = true; };
}
```

- [ ] **Passo 5: criar `api/static/js/tabela.js`.**

```js
// Tabela que reaproveita as linhas <tr> e só reescreve as células que mudaram (rolagem estável, pouco reflow).

/**
 * linhas: dados na ordem de exibição.
 * montar(dado) → { classe: "classe da <tr>", celulas: [{ t: "texto", c: "classe da <td>", barra: { pct, lado } }] }
 * Uma célula com `barra` desenha um <span class="barra compra|venda"> com largura pct% (sem texto).
 */
export function atualizarLinhas(tbody, linhas, montar) {
  while (tbody.rows.length > linhas.length) tbody.deleteRow(-1);
  linhas.forEach((dado, i) => {
    const tr = tbody.rows[i] || tbody.insertRow();
    const { classe = "", celulas } = montar(dado);
    if (tr.className !== classe) tr.className = classe;
    while (tr.cells.length > celulas.length) tr.deleteCell(-1);
    celulas.forEach((cel, j) => {
      const td = tr.cells[j] || tr.insertCell();
      const c = cel.c || "";
      if (td.className !== c) td.className = c;
      if (cel.barra) {
        let s = td.firstElementChild;
        if (!s) { td.textContent = ""; s = td.appendChild(document.createElement("span")); }
        const largura = `${Math.max(1, Math.min(100, cel.barra.pct))}%`;
        if (s.style.width !== largura) s.style.width = largura;
        const cls = `barra ${cel.barra.lado}`;
        if (s.className !== cls) s.className = cls;
      } else if (td.textContent !== cel.t) {
        td.textContent = cel.t;
      }
    });
  });
}
```

- [ ] **Passo 6: criar `api/static/js/shell.js`.**

```js
// Cabeçalho, rodapé, tema e atalhos comuns às telas (Operar, Conexão).
import { getJSON, segundosSemResposta } from "./api.js";
import { horaB3 } from "./formato.js";

const CHAVE_TEMA = "fluxo.tema";
const ABAS = [["operar", "Operar", "/operar"], ["conexao", "Conexão", "/conexao"],
              ["replay", "Replay", null], ["calibracao", "Calibração", null]];

function temaSalvo() {
  try { const t = localStorage.getItem(CHAVE_TEMA); return t === "claro" || t === "escuro" ? t : null; }
  catch { return null; }
}
function temaDoSistema() { return matchMedia("(prefers-color-scheme: light)").matches ? "claro" : "escuro"; }
export function temaAtual() { return document.documentElement.dataset.tema || temaDoSistema(); }

/** Aplica o tema; com salvar=true guarda a escolha manual. Dispara window "tema" (os gráficos recolorem). */
export function aplicarTema(tema, salvar = false) {
  document.documentElement.dataset.tema = tema;
  if (salvar) { try { localStorage.setItem(CHAVE_TEMA, tema); } catch { /* sem armazenamento: vale nesta visita */ } }
  document.querySelectorAll(".tema button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tema === tema)));
  window.dispatchEvent(new CustomEvent("tema", { detail: tema }));
}

/** Texto do status da ProfitDLL (ou da fonte fora do modo dll) e se é alerta (âmbar vazado). */
export function textoStatus(dll, fonte) {
  if (!dll) return [`fonte: ${fonte || "—"}`, false];
  if (dll.reconexao?.em_andamento) return ["reconectando…", true];
  const market = dll.estados?.market;
  if (dll.conectado && market?.codigo === 6) return ["ProfitDLL conectado (2,6) · callbacks atrasados", true];
  if (dll.conectado) {
    const lat = dll.latencia_ms != null ? ` · ${dll.latencia_ms} ms` : "";
    return [`ProfitDLL conectado (2,${market?.codigo ?? 4})${lat}`, false];
  }
  if (dll.motivo_falha) return [`desconectado — ${dll.motivo_falha}`, true];
  return [`desconectado${market ? ` (2,${market.codigo})` : ""}`, true];
}

export function montarShell(telaAtiva) {
  const topo = document.getElementById("topo");
  topo.className = "topo";
  topo.innerHTML = `
    <span class="marca">Fluxo Server</span>
    <nav>${ABAS.map(([id, nome, href]) => href
      ? `<a class="aba" href="${href}"${id === telaAtiva ? ' aria-current="page"' : ""}>${nome}</a>`
      : `<span class="aba" aria-disabled="true" title="em breve">${nome}</span>`).join("")}</nav>
    <div class="direita">
      <span class="aviso" id="sem-resposta" hidden></span>
      <span class="modo" id="modo"></span>
      <span class="status" id="status"><span class="quadrado" id="status-quadrado"></span><span id="status-texto">—</span></span>
      <span class="relogio" id="relogio">—</span>
      <span class="tema">tema <button data-tema="escuro">escuro</button> / <button data-tema="claro">claro</button></span>
    </div>`;
  const rodape = document.getElementById("rodape");
  rodape.className = "rodape";
  rodape.innerHTML = `<span id="aviso-exemplo"></span>
    <span class="atalhos"><span>F1 Operar</span><span>F2 Conexão</span><span>T tema</span></span>
    <span>B3 · horário de Brasília</span>`;

  topo.querySelectorAll(".tema button").forEach((b) => b.addEventListener("click", () => aplicarTema(b.dataset.tema, true)));
  aplicarTema(temaSalvo() || temaDoSistema());
  matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => { if (!temaSalvo()) aplicarTema(temaDoSistema()); });

  document.addEventListener("keydown", (ev) => {
    const alvo = ev.target;
    if (alvo.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(alvo.tagName)) return;
    if (ev.ctrlKey || ev.altKey || ev.metaKey) return;
    if (ev.key === "F1") { ev.preventDefault(); if (telaAtiva !== "operar") location.href = "/operar"; }
    else if (ev.key === "F2") { ev.preventDefault(); if (telaAtiva !== "conexao") location.href = "/conexao"; }
    else if (ev.key === "F3" || ev.key === "F4") ev.preventDefault();   // reservados: Replay e Calibração
    else if (ev.key === "t" || ev.key === "T") aplicarTema(temaAtual() === "escuro" ? "claro" : "escuro", true);
  });

  const saude = { modo: null, fonte: null, tick_size: null };
  let ultimoNegocio = null;
  getJSON("/health").then((h) => {
    Object.assign(saude, h);
    document.getElementById("modo").innerHTML = h.modo === "replay" ? "<b>replay</b>" : "<b>ao vivo</b>";
    document.getElementById("aviso-exemplo").textContent = h.fonte === "exemplo_wdo.csv"
      ? "Dados de exemplo — pregão gravado para demonstração, não é negociação de hoje" : "";
  }).catch(() => { /* o aviso "sem resposta" cobre */ });

  setInterval(() => {
    const parado = segundosSemResposta();
    const aviso = document.getElementById("sem-resposta");
    aviso.hidden = parado <= 3;
    if (!aviso.hidden) aviso.textContent = `sem resposta do servidor · parado há ${Math.floor(parado)} s`;
    document.getElementById("relogio").textContent =
      saude.modo === "replay" ? horaB3(ultimoNegocio) : horaB3(Date.now() / 1000);
  }, 1000);

  return {
    saude,
    /** Atualiza o status da fonte com o GET /state mais recente. */
    atualizarStatus(estado) {
      const ultimo = estado.recent_trades?.at(-1);
      if (ultimo) ultimoNegocio = ultimo.timestamp;
      const [texto, alerta] = textoStatus(estado.dll, saude.fonte || saude.modo);
      document.getElementById("status-texto").textContent = texto;
      document.getElementById("status").classList.toggle("alerta", alerta);
      document.getElementById("status-quadrado").classList.toggle("vazio", alerta);
    },
  };
}
```

- [ ] **Passo 7: rodar o teste JS e ver passar.**
  - Comando: `node tools/test_telas.mjs`
  - Esperado: `test_telas.mjs: tudo certo`.

- [ ] **Passo 8: páginas mínimas.**
  1. Crie `api/static/operar.html`. A tarefa 8 troca o conteúdo do `<main>` e da faixa:

```html
<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fluxo Server · Operar</title>
<script>/* tema antes da 1ª pintura (sem piscar) */ try { var t = localStorage.getItem("fluxo.tema"); } catch (e) {} document.documentElement.dataset.tema = (t === "claro" || t === "escuro") ? t : (matchMedia("(prefers-color-scheme: light)").matches ? "claro" : "escuro");</script>
<link rel="stylesheet" href="/static/css/tokens.css">
<link rel="stylesheet" href="/static/css/base.css">
</head>
<body>
<div class="tela">
  <header id="topo"></header>
  <section class="faixa" id="faixa"></section>
  <main class="corpo"><section class="secao"></section><section class="secao"></section></main>
  <footer id="rodape"></footer>
</div>
<script type="module">
  import { montarShell } from "/static/js/shell.js";
  import { getJSON, laco } from "/static/js/api.js";
  const shell = montarShell("operar");
  laco(async () => shell.atualizarStatus(await getJSON("/state")));
</script>
</body>
</html>
```

  2. Crie `api/static/conexao.html` igual, com `<title>Fluxo Server · Conexão</title>` e `montarShell("conexao")`.

- [ ] **Passo 9: criar `tools/qa_telas.js`.**

```js
// QA no navegador das telas Operar e Conexão contra o replay de exemplo.
// Usa o Playwright já instalado em C:/Projetos/urnalytics-marcelo (nada é instalado neste repositório).
// Uso: node tools/qa_telas.js   → sobe o replay na porta 5077 e salva as capturas em qa-telas/
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const { chromium } = require(process.env.PLAYWRIGHT_DIR || "C:/Projetos/urnalytics-marcelo/node_modules/playwright");

const RAIZ = path.resolve(__dirname, "..");
const PORTA = 5077;
const BASE = `http://127.0.0.1:${PORTA}`;
const SAIDA = path.join(RAIZ, "qa-telas");
const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

function subirServidor() {
  return spawn("python", ["-X", "utf8", "main.py", "--asset", "WDOFUT", "--modo", "replay",
    "--arquivo", "replay/exemplo_wdo.csv", "--tick-size", "0.5", "--velocidade", "6", "--port", String(PORTA)],
    { cwd: RAIZ, env: { ...process.env, PYTHONIOENCODING: "utf-8" }, stdio: "ignore" });
}
async function esperarSaude() {
  for (let i = 0; i < 80; i++) {
    try { if ((await fetch(`${BASE}/health`)).ok) return; } catch { /* ainda subindo */ }
    await esperar(250);
  }
  throw new Error("servidor não respondeu /health");
}
/** Espera o replay acabar: o último negócio fica igual por 6 s seguidos (máx. 2 min). */
async function esperarFimReplay() {
  let anterior = null, iguais = 0;
  for (let i = 0; i < 240 && iguais < 12; i++) {
    const r = await (await fetch(`${BASE}/trades?limit=1`)).json();
    const ts = r.trades.at(-1)?.timestamp ?? null;
    iguais = ts !== null && ts === anterior ? iguais + 1 : 0;
    anterior = ts;
    await esperar(500);
  }
}
function checar(condicao, msg) {
  if (!condicao) throw new Error(msg);
  console.log(`  ✓ ${msg}`);
}

const verificacoes = [];   // [nome, async (page) => {}] — as tarefas de cada tela acrescentam as suas

verificacoes.push(["barra e atalhos", async (page) => {
  await page.goto(`${BASE}/operar`);
  // o /health chega em paralelo ao 1º /state: espera o status já com o nome da fonte
  await page.waitForFunction(() => document.getElementById("status-texto").textContent.includes("exemplo_wdo.csv"));
  checar(await page.locator('.aba[aria-current="page"]').textContent() === "Operar", "aba Operar marcada");
  checar(true, "status mostra a fonte do replay");
  checar((await page.textContent("#modo")).includes("replay"), "modo replay no cabeçalho");
  checar((await page.textContent("#aviso-exemplo")).startsWith("Dados de exemplo"), "rodapé avisa que são dados de exemplo");
  await page.keyboard.press("F2");
  await page.waitForURL("**/conexao");
  checar(true, "F2 abre a Conexão");
  await page.keyboard.press("F1");
  await page.waitForURL("**/operar");
  checar(true, "F1 volta ao Operar");
  const antes = await page.evaluate(() => document.documentElement.dataset.tema);
  await page.keyboard.press("t");
  const depois = await page.evaluate(() => document.documentElement.dataset.tema);
  checar(antes !== depois, `T alterna o tema (${antes} → ${depois})`);
  await page.reload();
  checar(await page.evaluate(() => document.documentElement.dataset.tema) === depois, "tema persiste ao recarregar");
}]);

// ── as tarefas 8, 9 e 10 acrescentam verificações acima desta linha ──

async function main() {
  fs.mkdirSync(SAIDA, { recursive: true });
  let servidor = subirServidor();
  const navegador = await chromium.launch();
  const erros = [];
  try {
    await esperarSaude();
    const contexto = await navegador.newContext({ viewport: { width: 1920, height: 1080 }, colorScheme: "dark" });
    const page = await contexto.newPage();
    page.on("console", (m) => { if (m.type() === "error") erros.push(m.text()); });
    page.on("pageerror", (e) => erros.push(String(e)));
    for (const [nome, verificar] of verificacoes) {
      console.log(`→ ${nome}`);
      await verificar(page);
    }
    checar(erros.length === 0, `nenhum erro no console${erros.length ? ": " + erros.join(" | ") : ""}`);

    // Por último (gera erros de rede de propósito): servidor cai → aviso; volta → aviso some
    console.log("→ servidor parado e de volta");
    await page.goto(`${BASE}/operar`);
    await page.waitForFunction(() => document.getElementById("status-texto").textContent !== "—");
    servidor.kill();
    await page.waitForSelector("#sem-resposta:not([hidden])", { timeout: 8000 });
    checar((await page.textContent("#sem-resposta")).includes("sem resposta do servidor"), "aviso de servidor parado aparece");
    servidor = subirServidor();
    await esperarSaude();
    await page.waitForSelector("#sem-resposta[hidden]", { state: "attached", timeout: 8000 });
    checar(true, "aviso some quando o servidor volta");
    console.log(`\nQA das telas: tudo certo. Capturas em ${SAIDA}`);
  } finally {
    await navegador.close();
    servidor.kill();
  }
}
main().catch((e) => { console.error(`✗ ${e.message}`); process.exitCode = 1; });
```

- [ ] **Passo 10: `.gitignore`.** No fim, acrescente:

```
# Capturas do QA no navegador (node tools/qa_telas.js)
qa-telas/
```

- [ ] **Passo 11: rodar o QA e ver passar.**
  - Comando: `node tools/qa_telas.js`
  - Esperado: cada linha com ✓ e, no fim, `QA das telas: tudo certo`.
  - Se `chromium.launch` reclamar de navegador ausente, rode uma vez
    `node C:/Projetos/urnalytics-marcelo/node_modules/playwright/cli.js install chromium`.

- [ ] **Passo 12: commit.**

```bash
git add api/static/js api/static/operar.html api/static/conexao.html tools/test_telas.mjs tools/qa_telas.js .gitignore
git commit -m "feat(telas): módulos comuns (formato, api, tabela, shell), páginas mínimas e QA da barra"
```

---

### Tarefa 8: Operar — faixa de cotação e gráfico

**Arquivos:**
- Criar: `api/static/css/operar.css`, `api/static/js/operar-grafico.js` e `api/static/js/operar.js`
- Modificar: `api/static/operar.html` (layout completo) e `tools/qa_telas.js` (+1 verificação)

**Interfaces:**
- Consome:
  - `GET /state` (`resumo`, `delta.cumulative`, `recent_trades`, `dll`);
  - `GET /candles?tf&since`, com `financeiro` (tarefa 2);
  - `GET /signals?since`;
  - `montarShell` e `formato.js`.
- Produz:
  - `criarGrafico(el, casas)`, que devolve:
    - `tf`, `trocarTf(tf)`, `juntar(candles)` e `limpar()`;
    - `ultimoTempo()` e `ultimoCandle()`;
    - `definirSinais(lista)` e `definirCasas(n)`;
  - em `operar.js`: as variáveis de módulo `sinais`, `casas` e `shell`. A tarefa 9 acrescenta os painéis.

- [ ] **Passo 1: acrescentar a verificação no QA (falha esperada).** Em `tools/qa_telas.js`, logo acima da linha
  `// ── as tarefas 8, 9 e 10 ...`:

```js
verificacoes.push(["operar: faixa e gráfico", async (page) => {
  await page.goto(`${BASE}/operar`);
  await page.waitForFunction(() => document.getElementById("f-ultimo")?.textContent !== "—", null, { timeout: 30000 });
  checar(/\d/.test(await page.textContent("#f-ultimo")), `faixa mostra o último preço (${await page.textContent("#f-ultimo")})`);
  checar(/mi|mil|R\$/.test(await page.textContent("#f-fin")), "volume financeiro formatado");
  checar(await page.locator("#grafico canvas").count() > 0, "gráfico desenhado");
  await page.click('#tfs [data-tf="300"]');
  checar(await page.getAttribute('#tfs [data-tf="300"]', "aria-pressed") === "true", "timeframe de 5 min selecionado");
  await page.click('#tfs [data-tf="60"]');
  for (const tema of ["escuro", "claro"]) {
    await page.evaluate((t) => localStorage.setItem("fluxo.tema", t), tema);
    await page.reload();
    await page.waitForFunction(() => document.getElementById("f-ultimo").textContent !== "—");
    await esperar(1500);
    await page.screenshot({ path: path.join(SAIDA, `operar-${tema}.png`) });
  }
  checar(true, "capturas operar-escuro.png e operar-claro.png salvas");
}]);
```

Rode `node tools/qa_telas.js`. Esperado: falha em "operar: faixa e gráfico", porque `#f-ultimo` não existe.

- [ ] **Passo 2: layout completo do `operar.html`.**
  1. No `<head>`, depois de `base.css`, acrescente:

```html
<link rel="stylesheet" href="/static/css/operar.css">
<script src="/static/lightweight-charts.standalone.production.js"></script>
```

  2. Troque tudo entre `<header id="topo"></header>` e `<footer id="rodape"></footer>`:

```html
  <section class="faixa" id="faixa">
    <div class="metrica ativo"><span class="valor" id="f-ativo">—</span><span class="rotulo" id="f-fonte"></span></div>
    <div class="metrica sem-fio"><span class="heroi" id="f-ultimo">—</span></div>
    <div class="metrica sem-fio"><span class="valor" id="f-var">—</span><span class="rotulo" id="f-var-pct">desde a abertura</span></div>
    <div class="metrica"><span class="rotulo">Delta acumulado</span><span class="valor" id="f-delta">—</span></div>
    <div class="metrica"><span class="rotulo">Volume financeiro</span><span class="valor" id="f-fin">—</span></div>
    <div class="metrica"><span class="rotulo">VWAP</span><span class="valor"><span id="f-vwap">—</span><small id="f-vwap-dist"></small></span></div>
    <div class="metrica"><span class="rotulo">Agressão compra × venda</span><span class="valor" id="f-agr">—</span></div>
    <div class="metrica"><span class="rotulo">Negócios</span><span class="valor" id="f-npm">—</span></div>
    <div class="metrica"><span class="rotulo">Máxima · mínima</span><span class="valor" id="f-maxmin">—</span></div>
    <div class="metrica"><span class="rotulo">Abertura · ajuste ant.</span><span class="valor" id="f-abert">—</span></div>
  </section>
  <main class="corpo">
    <section class="secao">
      <div class="cab"><h2>Candles</h2>
        <span id="tfs"><button class="seletor mono" data-tf="60">1 min</button><button class="seletor mono" data-tf="300">5</button><button class="seletor mono" data-tf="900">15</button><button class="seletor mono" data-tf="3600">60</button></span>
        <span class="meta mono" id="ohlc"></span>
        <span class="acoes meta"><span>- - - VWAP</span><span>▲▼ direção</span><span>A absorção</span><span>E exaustão</span><span>I iceberg</span><span>U urgência</span></span>
      </div>
      <div id="grafico" class="grafico"></div>
    </section>
    <section class="secao direita">
      <div class="bloco-sinais">
        <div class="cab"><h2>Sinais</h2><span class="meta" id="sinais-meta"></span>
          <span class="acoes" id="filtros"><button class="seletor" data-filtro="todos" aria-pressed="true">todos</button><button class="seletor" data-filtro="Absorção">absorção</button><button class="seletor" data-filtro="Exaustão">exaustão</button><button class="seletor" data-filtro="Iceberg">iceberg</button><button class="seletor" data-filtro="Urgência">urgência</button></span>
        </div>
        <article class="manchete vazia" id="manchete">
          <div class="m-topo"><span class="ambar">Sinal ativo</span> <span class="faint" id="m-idade"></span></div>
          <h1 id="m-titulo">Nenhum sinal ainda hoje</h1>
          <div class="m-preco" id="m-preco"></div>
          <p class="m-frase" id="m-frase"></p>
          <p class="m-det mono" id="m-det"></p>
        </article>
        <table class="anteriores"><colgroup><col style="width:36px"><col style="width:190px"><col style="width:80px"><col style="width:56px"><col><col style="width:86px"></colgroup><tbody id="sinais-anteriores"></tbody></table>
      </div>
      <div class="bloco-baixo">
        <section class="secao">
          <div class="cab"><h2>Times &amp; Trades</h2><span class="acoes meta" id="tt-meta"></span></div>
          <table><colgroup><col style="width:92px"><col style="width:76px"><col style="width:64px"><col style="width:32px"><col><col></colgroup>
            <thead><tr><th>Hora</th><th class="num">Preço</th><th class="num">Qtd</th><th>Ag</th><th>Compra</th><th>Venda</th></tr></thead></table>
          <div class="rolagem"><table><colgroup><col style="width:92px"><col style="width:76px"><col style="width:64px"><col style="width:32px"><col><col></colgroup><tbody id="tt"></tbody></table></div>
        </section>
        <section class="secao">
          <div class="cab"><h2>Livro</h2><span class="meta" id="livro-nota"></span></div>
          <table><colgroup><col><col style="width:72px"><col style="width:80px"><col style="width:86px"></colgroup>
            <thead><tr><th>Corretora</th><th class="num">Qtd</th><th class="num">Preço</th><th></th></tr></thead>
            <tbody id="livro-asks"></tbody>
            <tbody><tr class="spread"><td colspan="4" id="spread">—</td></tr></tbody>
            <tbody id="livro-bids"></tbody></table>
          <div class="cab"><h2>Saldo das corretoras</h2><span class="acoes meta">lotes, dia</span></div>
          <div class="rolagem"><table><colgroup><col><col style="width:90px"><col style="width:96px"></colgroup><tbody id="saldo"></tbody></table></div>
        </section>
      </div>
    </section>
  </main>
```

  3. Troque o `<script type="module">…</script>` inline por
     `<script type="module" src="/static/js/operar.js"></script>`.

- [ ] **Passo 3: criar `api/static/css/operar.css`.**

```css
/* Ajustes da tela Operar (layout de docs/design/v3/operar-escuro.png). */
.faixa .ativo .valor { font-size: 20px; font-weight: 600; }
.faixa .sem-fio { border-left: 0; padding-left: 4px; }
#tfs { display: flex; gap: 14px; }
.grafico { flex: 1; min-height: 0; }

.secao.direita { display: grid; grid-template-rows: auto minmax(0, 1fr); }
.manchete { margin: 2px 0 8px; padding: 4px 16px 8px 14px; border-left: 2px solid var(--rule); }
.manchete.compra-dir { border-left-color: var(--buy); }
.manchete.venda-dir { border-left-color: var(--sell); }
.manchete h1 { font: 600 38px/44px "IBM Plex Sans", sans-serif; }
.manchete.vazia h1 { font: 400 15px/22px "IBM Plex Sans", sans-serif; color: var(--muted); }
.manchete.vazia .m-topo { display: none; }
.m-preco { font: 400 38px/44px "IBM Plex Sans", sans-serif; }
.m-frase { font: 400 15px/22px "IBM Plex Sans", sans-serif; color: var(--muted); margin-top: 6px; }
.m-det { font-size: 12px; color: var(--faint); margin-top: 6px; }
.m-det b { color: var(--text); font-weight: 500; margin: 0 14px 0 6px; }
.anteriores td { line-height: 23px; }
.anteriores td:nth-child(5) { font-family: "IBM Plex Sans", sans-serif; color: var(--muted); }

.bloco-baixo { display: grid; grid-template-columns: 380px 360px; min-height: 0; border-top: 1px solid var(--rule); }
.bloco-baixo > .secao:first-child { border-left: 0; }
.bloco-baixo td { line-height: 21px; }
tr.spread td { color: var(--faint); font-size: 12px; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
td.barra-cel span { display: block; height: 3px; }
```

- [ ] **Passo 4: criar `api/static/js/operar-grafico.js`.**

```js
// Gráfico do Operar: candles, VWAP tracejada, volume por lado e delta acumulado (Lightweight Charts 5.2.1).
import { horaB3, hm, preco, compacto } from "./formato.js";

const LW = window.LightweightCharts;
const LETRA = { "Absorção": "A", "Exaustão": "E", "Iceberg": "I", "Urgência": "U", "BestOffer": "O" };
const cor = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();

function opcoesTema(casas) {
  return {
    layout: {
      background: { type: "solid", color: cor("--bg") }, textColor: cor("--faint"),
      fontFamily: "IBM Plex Mono", fontSize: 11, attributionLogo: true,
      panes: { separatorColor: cor("--rule"), separatorHoverColor: cor("--rule") },
    },
    grid: { vertLines: { color: cor("--grid") }, horzLines: { color: cor("--grid") } },
    rightPriceScale: { borderColor: cor("--rule") },
    timeScale: { borderColor: cor("--rule"), timeVisible: true, secondsVisible: false, tickMarkFormatter: (t) => hm(t) },
    crosshair: {
      vertLine: { color: cor("--accent"), labelBackgroundColor: cor("--accent") },
      horzLine: { color: cor("--accent"), labelBackgroundColor: cor("--accent") },
    },
    localization: { locale: "pt-BR", timeFormatter: (t) => horaB3(t), priceFormatter: (p) => preco(p, casas) },
  };
}

export function criarGrafico(el, casasIniciais) {
  let casas = casasIniciais;
  const chart = LW.createChart(el, { autoSize: true, ...opcoesTema(casas) });
  const velas = chart.addSeries(LW.CandlestickSeries, { borderVisible: false, priceLineStyle: LW.LineStyle.Dotted });
  const vwap = chart.addSeries(LW.LineSeries, { lineWidth: 1, lineStyle: LW.LineStyle.Dashed, priceLineVisible: false,
    lastValueVisible: false, crosshairMarkerVisible: false });
  const semSinal = (v) => compacto(v).replace("+", "");
  const volume = chart.addSeries(LW.HistogramSeries, { priceLineVisible: false, lastValueVisible: false,
    priceFormat: { type: "custom", formatter: semSinal } }, 1);
  const delta = chart.addSeries(LW.LineSeries, { lineWidth: 1, priceLineVisible: false,
    priceFormat: { type: "custom", formatter: compacto } }, 2);
  const marcas = LW.createSeriesMarkers(velas, []);
  chart.panes()[1].setHeight(110);
  chart.panes()[2].setHeight(190);

  let candles = [];   // ordenados por time
  let sinais = [];
  let tf = 60;

  function desenharMarcas() {
    const tempos = new Set(candles.map((c) => c.time));
    marcas.setMarkers(sinais.map((s) => {
      const t = Math.floor(s.timestamp / tf) * tf;
      const compra = s.signal === "BUY";
      return tempos.has(t) ? { time: t, position: compra ? "belowBar" : "aboveBar", shape: compra ? "arrowUp" : "arrowDown",
        color: cor(compra ? "--buy" : "--sell"), text: LETRA[s.pattern] || "?" } : null;
    }).filter(Boolean).sort((a, b) => a.time - b.time));
  }

  function redesenhar() {
    velas.setData(candles.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));
    const vBuy = cor("--vol-buy"), vSell = cor("--vol-sell");
    let fin = 0, vol = 0, acum = 0;
    const vw = [], dl = [], vb = [];
    for (const c of candles) {
      fin += c.financeiro; vol += c.volume; acum += c.buy - c.sell;
      if (vol) vw.push({ time: c.time, value: fin / vol });
      dl.push({ time: c.time, value: acum });
      vb.push({ time: c.time, value: c.volume, color: c.buy >= c.sell ? vBuy : vSell });
    }
    vwap.setData(vw);
    delta.setData(dl);
    volume.setData(vb);
    desenharMarcas();
  }

  function aplicarCores() {
    chart.applyOptions(opcoesTema(casas));
    velas.applyOptions({ upColor: cor("--buy"), downColor: cor("--sell"), wickUpColor: cor("--buy"),
      wickDownColor: cor("--sell"), priceLineColor: cor("--text") });
    vwap.applyOptions({ color: cor("--muted") });
    delta.applyOptions({ color: cor("--text") });
    redesenhar();
  }
  window.addEventListener("tema", aplicarCores);
  aplicarCores();

  return {
    get tf() { return tf; },
    /** Troca o timeframe: limpa; o próximo /candles sem since recarrega o dia. */
    trocarTf(novo) { tf = novo; candles = []; redesenhar(); },
    /** Junta candles novos ou alterados (o since repete o último, que ainda pode mudar). */
    juntar(novos) {
      if (!novos.length) return;
      const porTempo = new Map(candles.map((c) => [c.time, c]));
      for (const c of novos) porTempo.set(c.time, c);
      candles = [...porTempo.values()].sort((a, b) => a.time - b.time);
      redesenhar();
    },
    limpar() { candles = []; sinais = []; redesenhar(); },
    ultimoTempo() { return candles.length ? candles[candles.length - 1].time : null; },
    ultimoCandle() { return candles[candles.length - 1] || null; },
    definirSinais(lista) { sinais = lista; desenharMarcas(); },
    definirCasas(n) { casas = n; chart.applyOptions(opcoesTema(casas)); },
  };
}
```

- [ ] **Passo 5: criar `api/static/js/operar.js`.**

```js
// Tela Operar: laço de 500 ms que alimenta a faixa de cotação, o gráfico e (tarefa 9) os painéis.
import { getJSON, laco } from "./api.js";
import { montarShell } from "./shell.js";
import { criarGrafico } from "./operar-grafico.js";
import { casasDoTick, preco, comSinal, inteiro, financeiro, pct } from "./formato.js";

const $ = (id) => document.getElementById(id);
const shell = montarShell("operar");
const CHAVE_TF = "fluxo.tf";
let casas = 2;
const grafico = criarGrafico($("grafico"), casas);

let sinais = [];
let vistos = new Set();
let ultimoSinalTs = null;
let tinhaDados = false;
const chaveSinal = (s) => `${s.timestamp}|${s.signal}|${s.pattern}|${s.stop_price}`;

function tfSalvo() {
  try { const v = Number(localStorage.getItem(CHAVE_TF)); return [60, 300, 900, 3600].includes(v) ? v : 60; }
  catch { return 60; }
}
function marcarTf(tf) {
  document.querySelectorAll("#tfs [data-tf]").forEach((b) => b.setAttribute("aria-pressed", String(Number(b.dataset.tf) === tf)));
}
grafico.trocarTf(tfSalvo());
marcarTf(grafico.tf);
document.querySelectorAll("#tfs [data-tf]").forEach((b) => b.addEventListener("click", () => {
  const tf = Number(b.dataset.tf);
  grafico.trocarTf(tf);
  grafico.definirSinais(sinais);
  marcarTf(tf);
  try { localStorage.setItem(CHAVE_TF, String(tf)); } catch { /* vale só nesta visita */ }
}));

function atualizarFaixa(e) {
  const r = e.resumo || {};
  $("f-ativo").textContent = e.asset;
  $("f-fonte").textContent = shell.saude.fonte || "";
  $("f-ultimo").textContent = preco(r.ultimo, casas);
  const variacao = r.ultimo != null && r.abertura ? r.ultimo - r.abertura : null;
  $("f-var").className = `valor ${variacao > 0 ? "compra" : variacao < 0 ? "venda" : ""}`;
  $("f-var").textContent = comSinal(variacao, (v) => preco(v, casas));
  $("f-var-pct").textContent = variacao == null ? "desde a abertura"
    : `${comSinal(100 * variacao / r.abertura, (v) => pct(v, 2))} desde a abertura`;
  const d = r.ultimo == null ? null : e.delta?.cumulative;
  $("f-delta").className = `valor ${d > 0 ? "compra" : d < 0 ? "venda" : ""}`;
  $("f-delta").textContent = comSinal(d);
  $("f-fin").textContent = financeiro(r.volume_financeiro);
  $("f-vwap").textContent = preco(r.vwap, casas);
  $("f-vwap-dist").textContent = r.vwap && r.ultimo != null
    ? `preço ${pct(Math.abs(100 * (r.ultimo - r.vwap) / r.vwap), 2)} ${r.ultimo >= r.vwap ? "acima" : "abaixo"}` : "";
  const compra = r.agressao_compra_pct == null ? null : Math.round(r.agressao_compra_pct);
  $("f-agr").textContent = compra == null ? "—" : `${compra}/${100 - compra}`;
  $("f-npm").textContent = r.negocios_por_min == null ? "—" : `${inteiro(r.negocios_por_min)}/min`;
  $("f-maxmin").textContent = r.maxima == null ? "—" : `${preco(r.maxima, casas)} · ${preco(r.minima, casas)}`;
  $("f-abert").textContent = `${preco(r.abertura, casas)} · —`;   // ajuste anterior: sem fonte ainda
}

async function passo() {
  const estado = await getJSON("/state");
  shell.atualizarStatus(estado);
  const novasCasas = shell.saude.tick_size ? casasDoTick(shell.saude.tick_size) : casas;
  if (novasCasas !== casas) { casas = novasCasas; grafico.definirCasas(casas); }

  const temDados = estado.resumo?.ultimo != null;
  if (tinhaDados && !temDados) {           // POST /reset ou virada do dia: começa do zero sem recarregar
    grafico.limpar();
    sinais = []; vistos = new Set(); ultimoSinalTs = null;
  }
  tinhaDados = temDados;
  atualizarFaixa(estado);

  const tfPedido = grafico.tf;
  const since = grafico.ultimoTempo();
  const c = await getJSON(`/candles?tf=${tfPedido}${since != null ? `&since=${since}` : ""}`);
  if (tfPedido === grafico.tf) grafico.juntar(c.candles);   // troca de tf no meio do pedido: descarta
  const u = grafico.ultimoCandle();
  $("ohlc").textContent = u ? `A ${preco(u.open, casas)}   M ${preco(u.high, casas)}   m ${preco(u.low, casas)}   F ${preco(u.close, casas)}` : "";

  const s = await getJSON(`/signals${ultimoSinalTs != null ? `?since=${ultimoSinalTs}` : ""}`);
  const novos = s.signals.filter((x) => !vistos.has(chaveSinal(x)));
  if (novos.length) {
    novos.forEach((x) => vistos.add(chaveSinal(x)));
    sinais = sinais.concat(novos);
    ultimoSinalTs = sinais[sinais.length - 1].timestamp;
    grafico.definirSinais(sinais);
  }
  return estado;
}

laco(passo, 500);
```

- [ ] **Passo 6: rodar o QA e ver passar.**
  - Comando: `node tools/qa_telas.js`
  - Esperado: "operar: faixa e gráfico" passa e o console fica sem erros.
  - Abra `qa-telas/operar-escuro.png` e `operar-claro.png` ao lado de `docs/design/v3/operar-*.png`. Confira:
    - a faixa de 80px com fios verticais;
    - candles verde e vermelho, a VWAP tracejada e os subpainéis de volume e delta;
    - nada de cards, sombras ou caixa alta.
  - Corrija desvios de espaçamento no `operar.css` antes do commit.

- [ ] **Passo 7: commit.**

```bash
git add api/static/operar.html api/static/css/operar.css api/static/js/operar.js api/static/js/operar-grafico.js tools/qa_telas.js
git commit -m "feat(telas): Operar com faixa de cotação e gráfico (candles, VWAP, volume, delta, marcas)"
```

---

### Tarefa 9: Operar — manchete, sinais anteriores, Times & Trades, livro e saldo

**Arquivos:**
- Criar: `api/static/js/operar-paineis.js`
- Modificar: `api/static/js/operar.js`, `tools/test_telas.mjs` e `tools/qa_telas.js`

**Interfaces:**
- Consome:
  - `GET /trades?limit=40` e `GET /book` (`depth`, `bids`, `asks`);
  - o `resumo.saldo_corretoras` e o `resumo.vwap`;
  - a lista `sinais` de `operar.js`.
- Produz:
  - `tituloSinal(sinal) -> str` (ex.: "Absorção compradora", "Iceberg vendedor");
  - `loteGrandePadrao(ativo) -> number` (50 para WDO, DOL, WIN e IND; 5.000 nos demais);
  - `criarPaineis() -> {atualizar({estado, sinais, trades, book, casas, agora, tf})}`.

- [ ] **Passo 1: testes JS que falham.** Em `tools/test_telas.mjs`:
  1. Junto dos outros imports, acrescente:

```js
import { tituloSinal, loteGrandePadrao } from "../api/static/js/operar-paineis.js";
```

  2. Antes do `console.log` final, acrescente:

```js
assert.equal(tituloSinal({ signal: "BUY", pattern: "Absorção" }), "Absorção compradora");
assert.equal(tituloSinal({ signal: "SELL", pattern: "Iceberg" }), "Iceberg vendedor");
assert.equal(tituloSinal({ signal: "SELL", pattern: "BestOffer" }), "Melhor oferta vendedora");
assert.equal(loteGrandePadrao("WDOFUT"), 50);
assert.equal(loteGrandePadrao("PETR4"), 5000);
```

  Rode `node tools/test_telas.mjs`. Esperado: `ERR_MODULE_NOT_FOUND` para `operar-paineis.js`.

- [ ] **Passo 2: criar `api/static/js/operar-paineis.js`.**

```js
// Painéis da coluna direita do Operar: manchete do sinal, 4 anteriores, Times & Trades, livro e saldo.
import { atualizarLinhas } from "./tabela.js";
import { preco, inteiro, compacto, horaB3, hm, pct } from "./formato.js";

const NOME = { "Absorção": ["Absorção", "f"], "Exaustão": ["Exaustão", "f"], "Iceberg": ["Iceberg", "m"],
               "Urgência": ["Urgência", "f"], "BestOffer": ["Melhor oferta", "f"] };
const SEGUNDOS_NOVO = 60;
const $ = (id) => document.getElementById(id);

/** "Absorção compradora", "Iceberg vendedor": padrão + direção, com o gênero do nome. */
export function tituloSinal(s) {
  const [nome, genero] = NOME[s.pattern] || [s.pattern, "m"];
  const compra = s.signal === "BUY";
  const lado = compra ? (genero === "f" ? "compradora" : "comprador") : (genero === "f" ? "vendedora" : "vendedor");
  return `${nome} ${lado}`;
}

/** Lote grande da fita: contratos para futuros de índice/dólar, ações em lotes de 100. */
export function loteGrandePadrao(ativo) { return /^(WDO|DOL|WIN|IND)/.test(ativo || "") ? 50 : 5000; }
function loteGrande(ativo) {
  try { const v = Number(localStorage.getItem("fluxo.loteGrande")); if (v > 0) return v; } catch { /* padrão */ }
  return loteGrandePadrao(ativo);
}

export function criarPaineis() {
  let filtro = "todos";
  document.querySelectorAll("#filtros [data-filtro]").forEach((b) => b.addEventListener("click", () => {
    filtro = b.dataset.filtro;
    document.querySelectorAll("#filtros [data-filtro]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  }));

  function manchete(sinal, vwap, casas, agora, tf) {
    const art = $("manchete");
    if (!sinal) {
      art.className = "manchete vazia";
      $("m-titulo").textContent = "Nenhum sinal ainda hoje";
      for (const id of ["m-idade", "m-preco", "m-frase", "m-det"]) $(id).textContent = "";
      return;
    }
    const compra = sinal.signal === "BUY";
    art.className = `manchete ${compra ? "compra-dir" : "venda-dir"}`;
    const idade = Math.max(0, Math.round(agora - sinal.timestamp));
    $("m-idade").textContent = idade <= SEGUNDOS_NOVO ? `novo · há ${idade} s` : `às ${horaB3(sinal.timestamp)}`;
    $("m-titulo").textContent = tituloSinal(sinal);
    $("m-preco").className = `m-preco ${compra ? "compra" : "venda"}`;
    $("m-preco").textContent = `em ${preco(sinal.price, casas)}`;
    $("m-frase").textContent = sinal.reason || "";
    const det = $("m-det");
    det.textContent = "";
    const vela = Math.floor(sinal.timestamp / tf) * tf;
    for (const [rotulo, valor] of [["força", pct(100 * sinal.confidence, 0)], ["stop", preco(sinal.stop_price, casas)],
                                   ["VWAP", preco(vwap, casas)], ["vela", hm(vela)], ["hora", horaB3(sinal.timestamp)]]) {
      det.append(rotulo, Object.assign(document.createElement("b"), { textContent: valor }));
    }
  }

  function anteriores(lista, casas) {
    atualizarLinhas($("sinais-anteriores"), lista, (s) => {
      const compra = s.signal === "BUY";
      return { celulas: [{ t: compra ? "▲" : "▼", c: compra ? "compra" : "venda" }, { t: tituloSinal(s) },
        { t: preco(s.price, casas), c: "num" }, { t: pct(100 * s.confidence, 0), c: "num faint" },
        { t: s.reason || "" }, { t: horaB3(s.timestamp), c: "num faint" }] };
    });
  }

  function fita(trades, ativo, casas) {
    const limite = loteGrande(ativo);
    $("tt-meta").textContent = `lotes ≥ ${inteiro(limite)} em negrito`;
    atualizarLinhas($("tt"), [...trades].reverse(), (t) => {
      const compra = t.side === "compra";
      const comprador = compra ? t.broker : t.passive_broker;
      const vendedor = compra ? t.passive_broker : t.broker;
      return {
        classe: t.qty >= limite ? (compra ? "lote-compra" : "lote-venda") : "",
        celulas: [{ t: horaB3(t.timestamp), c: "faint" }, { t: preco(t.price, casas), c: "num" },
          { t: inteiro(t.qty), c: "num" }, { t: compra ? "C" : "V", c: compra ? "compra" : "venda" },
          { t: comprador || "—" }, { t: vendedor || "—" }],
      };
    });
  }

  function livro(book, casas) {
    const asks = book.asks.slice(0, 10).reverse();
    const bids = book.bids.slice(0, 10);
    const maior = Math.max(1, ...asks.map((l) => l.qty), ...bids.map((l) => l.qty));
    const linha = (lado) => (l) => ({ celulas: [{ t: l.broker || "—" }, { t: l.qty ? inteiro(l.qty) : "—", c: "num" },
      { t: preco(l.price, casas), c: `num ${lado}` }, { barra: { pct: 100 * l.qty / maior, lado }, c: "barra-cel" }] });
    atualizarLinhas($("livro-asks"), asks, linha("venda"));
    atualizarLinhas($("livro-bids"), bids, linha("compra"));
    $("livro-nota").textContent = book.depth === "top" ? "topo do livro"
      : book.depth === "none" ? "sem livro nesta fonte" : `${Math.max(asks.length, bids.length)} níveis`;
    $("spread").textContent = bids.length && book.asks.length
      ? `spread ${preco(book.asks[0].price - bids[0].price, casas)}   ${preco(bids[0].price, casas)} × ${preco(book.asks[0].price, casas)}`
      : "—";
  }

  function saldo(lista) {
    const maior = Math.max(1, ...lista.map(([, v]) => Math.abs(v)));
    atualizarLinhas($("saldo"), lista, ([nome, v]) => {
      const lado = v >= 0 ? "compra" : "venda";
      return { celulas: [{ t: nome }, { t: compacto(v), c: `num ${lado}` },
        { barra: { pct: 100 * Math.abs(v) / maior, lado }, c: "barra-cel" }] };
    });
  }

  return {
    atualizar({ estado, sinais, trades, book, casas, agora, tf }) {
      const filtrados = filtro === "todos" ? sinais : sinais.filter((s) => s.pattern === filtro);
      $("sinais-meta").textContent = `${sinais.length} hoje`;
      manchete(filtrados[filtrados.length - 1], estado.resumo?.vwap, casas, agora, tf);
      anteriores(filtrados.slice(-5, -1).reverse(), casas);
      fita(trades, estado.asset, casas);
      livro(book, casas);
      saldo(estado.resumo?.saldo_corretoras || []);
    },
  };
}
```

- [ ] **Passo 3: ligar os painéis em `operar.js`.**
  1. Acrescente o import `import { criarPaineis } from "./operar-paineis.js";`.
  2. Depois de `const grafico = criarGrafico(...)`, acrescente `const paineis = criarPaineis();`.
  3. Em `passo()`, troque o `return estado;` final por:

```js
  const [tr, book] = await Promise.all([getJSON("/trades?limit=40"), getJSON("/book")]);
  // "agora": no replay é a hora do último negócio; ao vivo, o relógio
  const ultimo = estado.recent_trades?.at(-1);
  const agora = shell.saude.modo === "replay" && ultimo ? ultimo.timestamp : Date.now() / 1000;
  paineis.atualizar({ estado, sinais, trades: tr.trades, book, casas, agora, tf: grafico.tf });
```

- [ ] **Passo 4: verificações no QA.** Acima da linha `// ── as tarefas 8, 9 e 10 ...`:

```js
verificacoes.push(["operar: painéis", async (page) => {
  await page.goto(`${BASE}/operar`);
  await page.waitForFunction(() => document.getElementById("m-titulo").textContent !== "Nenhum sinal ainda hoje",
    null, { timeout: 60000 });
  const titulo = await page.textContent("#m-titulo");
  checar(/(compradora?|vendedora?|comprador|vendedor)$/.test(titulo), `manchete do sinal: ${titulo}`);
  checar((await page.textContent("#m-preco")).startsWith("em "), "manchete mostra \"em {preço}\"");
  const n1 = await page.locator("#tt tr").count();
  await esperar(2000);
  const n2 = await page.locator("#tt tr").count();
  checar(n2 > 0 && n2 >= n1, `Times & Trades com ${n2} linhas`);
  checar((await page.textContent("#livro-nota")).length > 0, `livro: ${await page.textContent("#livro-nota")}`);
  checar(await page.locator("#saldo tr").count() > 0, "saldo das corretoras preenchido");
  await page.screenshot({ path: path.join(SAIDA, "operar-com-sinal.png") });
}]);

verificacoes.push(["operar: reset com a tela aberta", async (page) => {
  await esperarFimReplay();
  await page.goto(`${BASE}/operar`);
  await page.waitForFunction(() => document.getElementById("f-ultimo").textContent !== "—");
  await page.evaluate(() => fetch("/reset", { method: "POST" }));
  await page.waitForFunction(() => document.getElementById("f-ultimo").textContent === "—", null, { timeout: 5000 });
  checar(await page.textContent("#m-titulo") === "Nenhum sinal ainda hoje", "reset limpa faixa e manchete sem recarregar");
}]);
```

- [ ] **Passo 5: rodar os dois testes e ver passar.**
  - Comandos: `node tools/test_telas.mjs` e depois `node tools/qa_telas.js`.
  - Esperado: os dois passam.
  - Compare `qa-telas/operar-com-sinal.png` com `docs/design/v3/operar-escuro.png`:
    - manchete com fio lateral de 2px na cor da direção;
    - lotes grandes em negrito com fundo tingido;
    - livro com barras finas.

- [ ] **Passo 6: commit.**

```bash
git add api/static/js/operar-paineis.js api/static/js/operar.js tools/test_telas.mjs tools/qa_telas.js
git commit -m "feat(telas): Operar com manchete, sinais anteriores, Times & Trades, livro e saldo"
```

---

### Tarefa 10: tela Conexão

**Arquivos:**
- Criar: `api/static/css/conexao.css` e `api/static/js/conexao.js`
- Modificar: `api/static/conexao.html` (layout completo) e `tools/qa_telas.js`

**Interfaces:**
- Consome:
  - de `GET /state`, o `dll`: `conectado`, `estados`, `motivo_falha`, `latencia_ms`, `ativo`, `bolsa`, `dll_path`,
    `reconexao` e os contadores;
  - `GET /log?since`;
  - `POST /dll/reconectar`.
- Produz: a tela, sem API nova.

- [ ] **Passo 1: verificação no QA (falha esperada).** Acima da linha `// ── as tarefas 8, 9 e 10 ...`:

```js
verificacoes.push(["conexão", async (page) => {
  await page.goto(`${BASE}/conexao`);
  await page.waitForFunction(() => document.querySelectorAll("#log tr").length > 0, null, { timeout: 10000 });
  checar(true, `log com ${await page.locator("#log tr").count()} eventos`);
  checar(await page.isHidden("#reconectar"), "sem botão Reconectar fora do modo dll");
  checar((await page.textContent("#c-agregado")).includes("Sem ProfitDLL"), "faixa explica a fonte sem DLL");
  await page.click('#log-filtros [data-nivel="aviso"]');
  await esperar(700);
  const niveis = await page.locator("#log tr td:nth-child(2)").allTextContents();
  checar(niveis.every((n) => n === "aviso"), `filtro "aviso" mostra só avisos (${niveis.length})`);
  await page.click('#log-filtros [data-nivel="todos"]');
  for (const tema of ["escuro", "claro"]) {
    await page.evaluate((t) => localStorage.setItem("fluxo.tema", t), tema);
    await page.reload();
    await page.waitForFunction(() => document.querySelectorAll("#log tr").length > 0);
    await page.screenshot({ path: path.join(SAIDA, `conexao-${tema}.png`) });
  }
  checar(true, "capturas conexao-escuro.png e conexao-claro.png salvas");
}]);
```

Rode `node tools/qa_telas.js`. Esperado: falha em "conexão", porque `#log` não existe.

- [ ] **Passo 2: layout completo do `conexao.html`.**
  1. No `<head>`, depois de `base.css`, acrescente:

```html
<link rel="stylesheet" href="/static/css/conexao.css">
<script src="/static/lightweight-charts.standalone.production.js"></script>
```

  2. Troque tudo entre `<header id="topo"></header>` e `<footer id="rodape"></footer>`:

```html
  <section class="faixa">
    <div class="metrica primeira"><span class="rotulo">ProfitDLL</span><span class="valor grande" id="c-agregado">—</span><span class="rotulo" id="c-agregado-det"></span></div>
    <div class="metrica"><span class="rotulo">Login</span><span class="valor"><span id="c-login">—</span><small class="mono" id="c-login-cod"></small></span></div>
    <div class="metrica"><span class="rotulo">Ativação</span><span class="valor"><span id="c-ativacao">—</span><small class="mono" id="c-ativacao-cod"></small></span></div>
    <div class="metrica"><span class="rotulo">Market Data</span><span class="valor"><span id="c-market">—</span><small class="mono" id="c-market-cod"></small></span></div>
    <div class="metrica"><span class="rotulo">Roteamento</span><span class="valor faint">não usado<small class="mono">(1,—)</small></span></div>
    <div class="metrica"><span class="rotulo">Latência</span><span class="valor" id="c-latencia">—</span></div>
    <div class="metrica acao"><span class="ambar" id="reconectar-msg"></span><button class="botao primario" id="reconectar" hidden>Reconectar</button></div>
  </section>
  <main class="corpo">
    <section class="secao">
      <div class="cab"><h2>Negócios por segundo</h2><span class="meta" id="nps-meta">últimos 15 min · diferença de negócios recebidos a cada segundo</span></div>
      <div class="aviso-26 mono" id="faixa-26" hidden></div>
      <div class="grafico" id="grafico-nps"></div>
      <p class="vazio-msg" id="nps-vazio" hidden>Sem ProfitDLL nesta fonte: negócios por segundo só existem no modo dll.</p>
    </section>
    <section class="secao direita">
      <div class="cab"><h2>Contadores</h2><span class="meta" id="contadores-meta"></span></div>
      <table class="chave-valor"><colgroup><col style="width:300px"><col style="width:110px"><col></colgroup><tbody id="contadores"></tbody></table>
      <div class="edicao" id="edicao" hidden></div>
      <div class="cab"><h2>Configuração</h2><span class="meta">chave, usuário e senha nunca saem do servidor</span></div>
      <table class="chave-valor"><colgroup><col style="width:300px"><col></colgroup><tbody id="config"></tbody></table>
      <div class="cab"><h2>Log de eventos</h2><span class="acoes" id="log-filtros"><button class="seletor" data-nivel="todos" aria-pressed="true">todos</button><button class="seletor" data-nivel="info">info</button><button class="seletor" data-nivel="aviso">aviso</button><button class="seletor" data-nivel="erro">erro</button></span></div>
      <table><colgroup><col style="width:92px"><col style="width:64px"><col style="width:150px"><col></colgroup><thead><tr><th>Hora</th><th>Nível</th><th>Origem</th><th>Mensagem</th></tr></thead></table>
      <div class="rolagem"><table class="log"><colgroup><col style="width:92px"><col style="width:64px"><col style="width:150px"><col></colgroup><tbody id="log"></tbody></table></div>
      <div class="cab"><span class="meta" id="log-meta"></span></div>
    </section>
  </main>
```

  3. Troque o `<script type="module">…</script>` inline por
     `<script type="module" src="/static/js/conexao.js"></script>`.

- [ ] **Passo 3: criar `api/static/css/conexao.css`.**

```css
/* Ajustes da tela Conexão (layout de docs/design/v3/conexao-escuro.png). */
.faixa .primeira { min-width: 260px; }
.faixa .grande { font: 500 30px/36px "IBM Plex Sans", sans-serif; }
.faixa .acao { margin-left: auto; border-left: 0; flex-direction: row; align-items: center; gap: 16px; }
.metrica .valor small.mono { font-family: "IBM Plex Mono", monospace; }
.grafico { flex: 1; min-height: 0; }
.aviso-26 { color: var(--accent); font-size: 12px; padding: 0 16px 6px; }
.secao.direita { overflow: hidden; }
.chave-valor td:first-child { font-family: "IBM Plex Sans", sans-serif; color: var(--muted); }
.chave-valor td { line-height: 24px; }
.edicao { margin: 8px 0 4px; padding: 10px 16px; border-left: 2px solid var(--accent); background: var(--raise); font-weight: 600; }
.log td { font-size: 12px; line-height: 26px; }
```

- [ ] **Passo 4: criar `api/static/js/conexao.js`.**

```js
// Tela Conexão: estados da ProfitDLL, negócios/s, contadores, configuração, log e Reconectar.
import { getJSON, postJSON, laco } from "./api.js";
import { montarShell } from "./shell.js";
import { atualizarLinhas } from "./tabela.js";
import { inteiro, horaB3, hm } from "./formato.js";

const $ = (id) => document.getElementById(id);
const shell = montarShell("conexao");
const LW = window.LightweightCharts;
const cor = (nome) => getComputedStyle(document.documentElement).getPropertyValue(nome).trim();
const JANELA_S = 15 * 60;
const NIVEL = { INFO: "info", WARNING: "aviso", ERROR: "erro", CRITICAL: "erro" };

// ── Negócios por segundo (só no modo dll), calculado no navegador
let grafico = null, linha = null, faixa = null;
let pontos = [], marcas26 = [], anterior = null;

function criarGrafico() {
  grafico = LW.createChart($("grafico-nps"), { autoSize: true });
  linha = grafico.addSeries(LW.LineSeries, { lineWidth: 1, priceLineVisible: false });
  faixa = grafico.addSeries(LW.HistogramSeries, { priceScaleId: "faixa", priceLineVisible: false, lastValueVisible: false });
  grafico.priceScale("faixa").applyOptions({ visible: false, scaleMargins: { top: 0, bottom: 0 } });
  window.addEventListener("tema", aplicarCores);
  aplicarCores();
}
function aplicarCores() {
  grafico.applyOptions({
    layout: { background: { type: "solid", color: cor("--bg") }, textColor: cor("--faint"), fontFamily: "IBM Plex Mono", fontSize: 11 },
    grid: { vertLines: { color: cor("--grid") }, horzLines: { color: cor("--grid") } },
    rightPriceScale: { borderColor: cor("--rule") },
    timeScale: { borderColor: cor("--rule"), timeVisible: true, secondsVisible: false, tickMarkFormatter: (t) => hm(t) },
    localization: { locale: "pt-BR", timeFormatter: (t) => horaB3(t) },
  });
  linha.applyOptions({ color: cor("--text") });
  faixa.applyOptions({ color: cor("--faixa-26") });
  faixa.setData(marcas26.map((t) => ({ time: t, value: 1 })));
}
function registrarAmostra(dll) {
  const t = Math.floor(Date.now() / 1000);
  if (anterior && t <= anterior.t) return;          // uma amostra por segundo
  if (anterior) {
    pontos.push({ time: t, value: Math.max(0, (dll.trades_recebidos - anterior.recebidos) / (t - anterior.t)) });
    if (dll.avisos_partial > anterior.avisos) {
      marcas26.push(t);
      $("faixa-26").hidden = false;
      $("faixa-26").textContent = `(2,6) callbacks atrasados · ${horaB3(t)} · ${inteiro(dll.avisos_partial)} aviso(s) hoje`;
    }
    pontos = pontos.filter((p) => p.time >= t - JANELA_S);
    marcas26 = marcas26.filter((m) => m >= t - JANELA_S);
    linha.setData(pontos);
    faixa.setData(marcas26.map((m) => ({ time: m, value: 1 })));
  }
  anterior = { t, recebidos: dll.trades_recebidos, avisos: dll.avisos_partial };
}

// ── Faixa de estados e Reconectar
function faixaEstados(dll) {
  const rec = dll.reconexao || {};
  const [texto, detalhe] = rec.em_andamento ? ["Reconectando…", "aguardando login, ativação e market data"]
    : dll.conectado ? ["Conectado", `${dll.ativo} · bolsa ${dll.bolsa}`]
    : ["Desconectado", dll.motivo_falha || "sem conexão com a ProfitDLL"];
  $("c-agregado").textContent = texto;
  $("c-agregado").classList.toggle("ambar", !dll.conectado || !!rec.em_andamento);
  $("c-agregado-det").textContent = detalhe;
  for (const [id, tipo, chave] of [["c-login", 0, "login"], ["c-ativacao", 3, "ativacao"], ["c-market", 2, "market"]]) {
    const e = dll.estados?.[chave];
    $(id).textContent = e ? e.nome : "—";
    $(`${id}-cod`).textContent = ` (${tipo},${e ? e.codigo : "—"})`;
  }
  $("c-latencia").textContent = dll.latencia_ms == null ? "—" : `${inteiro(dll.latencia_ms)} ms`;
  const botao = $("reconectar");
  botao.hidden = false;
  botao.disabled = !!rec.em_andamento;
  botao.textContent = rec.em_andamento ? "reconectando…" : "Reconectar";
  if (!rec.em_andamento) $("reconectar-msg").textContent = rec.resultado?.startsWith("falhou") ? rec.resultado : "";
}
$("reconectar").addEventListener("click", async () => {
  const botao = $("reconectar");
  botao.disabled = true;
  botao.textContent = "reconectando…";
  try {
    const { status, dados } = await postJSON("/dll/reconectar");
    if (status !== 202) $("reconectar-msg").textContent = dados.error || `falhou: HTTP ${status}`;
  } catch {
    $("reconectar-msg").textContent = "falhou: servidor sem resposta";
  }
});

function semDll(fonte) {
  $("c-agregado").textContent = "Sem ProfitDLL";
  $("c-agregado").classList.remove("ambar");
  $("c-agregado-det").textContent = `fonte: ${fonte || "—"}`;
  $("reconectar").hidden = true;
  $("grafico-nps").hidden = true;
  $("nps-vazio").hidden = false;
  $("contadores-meta").textContent = "os contadores da DLL só existem no modo dll";
  atualizarLinhas($("contadores"), [], () => ({ celulas: [] }));
}

// ── Contadores, edição e configuração
function contadores(dll) {
  const tipos = Object.entries(dll.ignorados_por_tipo || {}).map(([k, v]) => `${k} ${inteiro(v)}`).join(" · ");
  const linhas = [
    ["Negócios recebidos", dll.trades_recebidos, ""],
    ["Editados (TC_IS_EDIT), descartados", dll.trades_editados, ""],
    ["Ignorados sem agressão", dll.trades_ignorados, tipos],
    ["Horário local (TradeDate ausente)", dll.horarios_fallback, ""],
    ["Quedas do market data", dll.quedas_market, ""],
    ["Avisos (2,6)", dll.avisos_partial, ""],
    ["Fila pendente", dll.fila_pendente, ""],
    ["Atualizações do livro", dll.book_atualizacoes, ""],
  ];
  $("contadores-meta").textContent = "acumulam no dia, inclusive entre reconexões";
  atualizarLinhas($("contadores"), linhas, ([rotulo, valor, nota]) => ({
    celulas: [{ t: rotulo }, { t: inteiro(valor), c: "num" }, { t: nota, c: "faint" }] }));
  $("edicao").hidden = !dll.trades_editados;
  if (dll.trades_editados) $("edicao").textContent = `${inteiro(dll.trades_editados)} correções de negócio hoje — descartadas`;
  atualizarLinhas($("config"), [["PROFITDLL_PATH", dll.dll_path || "padrão"], ["Ativo", dll.ativo], ["Bolsa", dll.bolsa]],
    ([k, v]) => ({ celulas: [{ t: k }, { t: v || "—" }] }));
}

// ── Log (acumula no navegador; o servidor guarda os últimos 500)
let registros = [], ultimoLog = null, filtroLog = "todos";
document.querySelectorAll("#log-filtros [data-nivel]").forEach((b) => b.addEventListener("click", () => {
  filtroLog = b.dataset.nivel;
  document.querySelectorAll("#log-filtros [data-nivel]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  desenharLog();
}));
function desenharLog() {
  const visiveis = registros.filter((x) => filtroLog === "todos" || NIVEL[x.nivel] === filtroLog).reverse();
  atualizarLinhas($("log"), visiveis, (x) => {
    const nivel = NIVEL[x.nivel] || x.nivel.toLowerCase();
    return { classe: nivel === "erro" ? "destaque" : "",
      celulas: [{ t: horaB3(x.ts), c: "faint" }, { t: nivel, c: nivel === "info" ? "muted" : "ambar" },
                { t: x.origem, c: "faint" }, { t: x.msg }] };
  });
  $("log-meta").textContent = `${inteiro(registros.length)} eventos guardados · mais recentes primeiro`;
}
async function buscarLog() {
  const r = await getJSON(`/log${ultimoLog != null ? `?since=${ultimoLog}` : ""}`);
  if (r.registros.length) {
    registros = registros.concat(r.registros).slice(-500);
    ultimoLog = registros[registros.length - 1].ts;
  }
  desenharLog();
}

laco(async () => {
  const estado = await getJSON("/state");
  shell.atualizarStatus(estado);
  if (estado.dll) {
    if (!grafico) criarGrafico();
    faixaEstados(estado.dll);
    registrarAmostra(estado.dll);
    contadores(estado.dll);
  } else {
    semDll(shell.saude.fonte);
  }
  await buscarLog();
}, 500);
```

- [ ] **Passo 5: rodar o QA e ver passar.**
  - Comandos: `node tools/qa_telas.js` e `node tools/test_telas.mjs`.
  - Esperado: os dois passam.
  - Compare `qa-telas/conexao-*.png` com `docs/design/v3/conexao-*.png`. Nesta fonte não há DLL, então a faixa mostra
    "Sem ProfitDLL", o log tem a cor certa por nível e não há botão.

- [ ] **Passo 6: conferência manual no modo dll.**
  - Comando: `powershell -ExecutionPolicy Bypass -File tools\rodar_dll.ps1 -Asset WDOFUT -TickSize 0.5`.
  - **A licença atual só libera BMF**, então use WDO ou WIN, nunca ações. Rode em horário de pregão.
  - Abra `http://127.0.0.1:5000/conexao` e confira:
    - a faixa com Login, Ativação e Market Data com nome e código, e a latência em ms;
    - o gráfico de negócios/s andando;
    - os contadores subindo e o tipo RLP nos ignorados;
    - o botão **Reconectar**: mostra "reconectando…" desabilitado e volta para "Conectado" em poucos segundos;
    - o log com "ProfitDLL: reconexão ok".
  - Se a DLL não aceitar `DLLFinalize` seguido de um novo login no mesmo processo, anote o erro do log da DLL
    (`C:\ProfitDLL\Win64\Logs\LogDesktop_*.log`, mascarando o e-mail) e **pare para avisar o dono**. Nesse caso o
    plano B é reiniciar o processo, e isso muda a especificação.

- [ ] **Passo 7: commit.**

```bash
git add api/static/conexao.html api/static/css/conexao.css api/static/js/conexao.js tools/qa_telas.js
git commit -m "feat(telas): Conexão com estados da DLL, negócios/s, contadores, log e Reconectar"
```

---

### Tarefa 11: remover o dashboard antigo e atualizar a documentação

**Arquivos:**
- Remover: `api/static/dashboard.html`
- Modificar: `docs/replay.md`, `docs/PROXIMOS-PASSOS.md` e `api/static/VENDOR.md` (só a frase que cita o
  `dashboard.html`)

- [ ] **Passo 1: procurar referências.**
  - Comando: `grep -rn "dashboard" --include=*.py --include=*.md --include=*.js --include=*.html . | grep -v "^./docs/superpowers"`.
  - Toda referência que restar a `dashboard.html` ou "Dashboard" como tela deve ser trocada por "telas
    (`/operar`, `/conexao`)". A rota `/dashboard` continua existindo como apelido do Operar.

- [ ] **Passo 2: remover o arquivo.**

```bash
git rm api/static/dashboard.html
```

- [ ] **Passo 3: `docs/replay.md`.**
  1. Troque a seção "### Assistir no dashboard" pelo texto abaixo.
  2. Na tabela de opções, troque "servidor/dashboard" por "servidor/telas".

```markdown
### Assistir nas telas

Sem `--sem-servidor`, o servidor sobe normalmente e as telas ficam em `http://127.0.0.1:5000/operar`
(F2 abre a Conexão, T alterna o tema escuro/claro). Use uma velocidade maior que zero para ver o pregão andar:
```

  3. Mantenha o bloco de código de exemplo que já vinha depois do título.

- [ ] **Passo 4: `docs/PROXIMOS-PASSOS.md`.**
  1. Troque "Última atualização: 14/10/2026" por "Última atualização: 16/10/2026".
  2. Em "O que já está pronto", troque o item **ProfitDLL** inteiro por:

```markdown
- **ProfitDLL (testada com a DLL real em 16/10/2026):**
  - Conecta em ~4 s; negócios com agressor, topo do livro, nome da corretora pela DLL e horário da B3 corretos.
  - **A licença atual só libera BMF** (log da DLL: `Exchanges=E,1,0;F,1,0`). Ações (bolsa `B`) são recusadas em
    silêncio: o histórico fica em 0%. Para PETR4/BBAS3 é preciso pedir a Bovespa à Nelogica (suportecorp@nelogica.com.br).
  - Credenciais: `tools\configurar_profitdll.ps1`; subir: `tools\rodar_dll.ps1 -Asset WDOFUT -TickSize 0.5`.
- **Telas novas (design v3):** `http://127.0.0.1:5000/operar` (F1) e `/conexao` (F2), tema escuro/claro (T),
  Reconectar da DLL na Conexão. QA: `node tools/test_telas.mjs` e `node tools/qa_telas.js`.
```

  3. Na lista "## Prioridade", troque o item 1 por um que diga que ações dependem da licença Bovespa e que, até lá,
     o foco é **WDO/WIN**, calibrando com os pregões gravados por `--gravar`.

- [ ] **Passo 5: `VENDOR.md`.** Na seção da Lightweight Charts, troque "revisar a API usada em `dashboard.html`" por
  "revisar a API usada em `js/operar-grafico.js` e `js/conexao.js`".

- [ ] **Passo 6: verificação final completa.**
  - `PYTHONIOENCODING=utf-8 python -X utf8 test_engine.py` → "TODOS OS TESTES PASSARAM!".
  - `node tools/test_telas.mjs` → "tudo certo".
  - `node tools/qa_telas.js` → "QA das telas: tudo certo".
  - Rode `python -X utf8 main.py --asset WDOFUT --modo replay --arquivo replay/exemplo_wdo.csv --tick-size 0.5
    --velocidade 4` e abra `http://127.0.0.1:5000/`. Ele abre direto no Operar novo (critério de pronto 4).
  - Coloque lado a lado as 4 capturas de `qa-telas/` e as 4 de `docs/design/v3/` e confira os critérios de pronto 1
    a 3. Diferenças só de conteúdo (ativo, valores) são esperadas. Diferenças de estrutura, cor ou tipografia não.

- [ ] **Passo 7: commit.**

```bash
git add -A docs/replay.md docs/PROXIMOS-PASSOS.md api/static/VENDOR.md api/static/dashboard.html
git commit -m "docs: telas Operar/Conexão no lugar do dashboard; licença da DLL só BMF"
```

Não faça push. O dono revisa e autoriza.

---

### Tarefa 10b (adendo de 16/10): ProfitDLL em processo filho

Motivo e decisão no §12 da especificação. Arquivos: criar `profitdll/processo.py`; modificar `main.py`
(`setup_dll_mode`) e `test_engine.py` (teste 26 com um filho falso que fala o mesmo protocolo).
Testes: ida e volta tick/book ↔ JSON; start ok entrega ticks e stats; start com falha devolve False com o motivo;
filho que morre vira `conectado: false`; contadores somam entre reinícios; log do filho chega ao `logging` do pai.
Conferência manual: modo dll real, Reconectar duas vezes seguidas volta a "Conectado" sem perder o gráfico.
