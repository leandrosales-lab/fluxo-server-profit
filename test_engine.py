"""
TESTE DO MOTOR DE FLUXO
========================
Simula um setup completo de Iceberg comprador:
  1. Injeta ticks de venda (fluxo vendedor > 65%)
  2. Injeta renovações de lote no mesmo preço (Iceberg comprador)
  3. Injeta snapshot do Book com Iceberg na melhor oferta de compra
  4. Verifica se o motor emite sinal BUY com confiança >= 0.60
  5. Simula o Iceberg sumindo → verifica sinal CLOSE

Execução:
  python test_engine.py
"""

import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.engine import FlowEngine, Tick, BookLevel, Side, Signal, EngineConfig

VERDE  = "\033[92m"
VERMELHO = "\033[91m"
AMARELO  = "\033[93m"
AZUL   = "\033[94m"
RESET  = "\033[0m"

def ok(msg):  print(f"  {VERDE}✓{RESET} {msg}")
def err(msg): print(f"  {VERMELHO}✗{RESET} {msg}"); sys.exit(1)
def info(msg): print(f"  {AZUL}→{RESET} {msg}")


def test_iceberg_buy():
    print(f"\n{AMARELO}═══ TESTE 1: Iceberg Comprador ═══{RESET}")

    cfg = EngineConfig(
        flow_window_sec      = 10.0,
        flow_pct_threshold   = 60.0,
        iceberg_min_renewals = 3,
        iceberg_lot_tolerance = 20.0,
        tick_size            = 0.01,
        min_confidence       = 0.50,
        defesa_iceberg_vol_sinal        = {},   # testes antigos: sem corte de volume do sinal
        defesa_iceberg_vol_sinal_padrao = 0,
    )
    engine = FlowEngine("PETR4", cfg)

    # Cenário real: JP MORGAN fica no Bid 1 com lote fixo (1000) — Iceberg.
    # Bradesco e outros batem uma vez cada (agressores vendedores únicos).
    # Fluxo: muitos agressores vendedores de pequeno porte, 1 player comprador grande.

    # 1. Injetar agressores vendedores (vários brokers, 1 tick cada = não forma Iceberg)
    info("Injetando agressores vendedores (1 tick cada, brokers diferentes)...")
    sell_brokers = ["BRADESCO", "SANTANDER", "RICO", "CLEAR", "XP INC",
                    "AGORA", "TORO", "GENIAL", "CM CAPITAL", "INTER"]
    for i, broker in enumerate(sell_brokers):
        engine.add_tick(Tick(
            timestamp = time.time() - (12 - i),
            price     = 19.04,
            qty       = 100 + i * 20,
            broker    = broker,
            side      = Side.SELL,
        ))

    # 2. Injetar renovações de Iceberg: JP MORGAN sempre volta com 1000 no mesmo preço
    info("Injetando 4 renovações de ICEBERG comprador (JP MORGAN @ 19.04, lote 1000)...")
    for i in range(4):
        engine.add_tick(Tick(
            timestamp = time.time() - (4 - i) * 0.5,
            price     = 19.04,
            qty       = 1000,
            broker    = "JP MORGAN",
            side      = Side.BUY,  # Iceberg passivo no bid
        ))

    # 3. Injetar Book com JP MORGAN no melhor bid
    info("Atualizando Book: JP MORGAN no Bid 1 @ 19.04...")
    engine.update_book([
        BookLevel(price=19.04, qty=1000, broker="JP MORGAN", side=Side.BUY),
        BookLevel(price=19.03, qty=500,  broker="BRADESCO",  side=Side.BUY),
        BookLevel(price=19.05, qty=300,  broker="SANTANDER", side=Side.SELL),
        BookLevel(price=19.06, qty=800,  broker="ITAU",      side=Side.SELL),
    ])

    # 4. Verificar sinal
    signal = engine.get_signal()
    state  = engine.get_state()

    info(f"Fluxo: {state['flow_pct_buy']:.1f}% compra / {state['flow_pct_sell']:.1f}% venda")
    info(f"Icebergs confirmados: {len(state['icebergs_confirmed'])}")
    info(f"Sinal gerado: {signal.signal.value} | Padrão: {signal.pattern.value}")
    info(f"Confiança: {signal.confidence:.2f} | Broker: {signal.broker}")
    info(f"Razão: {signal.reason}")

    if signal.signal == Signal.BUY:
        ok(f"Sinal BUY gerado corretamente!")
    else:
        err(f"Sinal esperado BUY, recebeu {signal.signal.value}")

    if signal.confidence >= 0.50:
        ok(f"Confiança OK: {signal.confidence:.2f}")
    else:
        err(f"Confiança muito baixa: {signal.confidence:.2f}")

    if "JP MORGAN" in signal.broker:
        ok(f"Broker correto: {signal.broker}")
    else:
        err(f"Broker incorreto: {signal.broker}")

    return engine


def test_iceberg_expira(engine: FlowEngine):
    print(f"\n{AMARELO}═══ TESTE 2: Iceberg Expira (Stop de Fluxo) ═══{RESET}")

    info("Simulando iceberg parando (timeout)...")
    # Forçar expiração modificando timestamp dos icebergs
    for ic in engine._icebergs.values():
        ic.last_renewed -= 60  # 60 segundos atrás = expirado

    # Injetar um novo tick para disparar a análise
    engine.add_tick(Tick(
        timestamp = time.time(),
        price     = 19.03,
        qty       = 100,
        broker    = "RICO",
        side      = Side.SELL,
    ))

    state  = engine.get_state()
    signal = engine.get_signal()

    info(f"Icebergs ativos: {len(state['icebergs_confirmed'])}")
    info(f"Sinal após expiração: {signal.signal.value} | Confiança: {signal.confidence:.2f}")

    if len(state["icebergs_confirmed"]) == 0:
        ok("Iceberg expirado e removido corretamente")
    else:
        err(f"Iceberg deveria ter expirado, mas ainda há {len(state['icebergs_confirmed'])}")


def test_urgencia():
    print(f"\n{AMARELO}═══ TESTE 3: Urgência de Compra ═══{RESET}")

    cfg = EngineConfig(
        flow_window_sec    = 10.0,
        flow_pct_threshold = 60.0,
        urgency_levels_min = 3,
        urgency_window_sec = 8.0,
        min_confidence     = 0.50,
    )
    engine = FlowEngine("VALE3", cfg)

    # Fluxo comprador
    info("Injetando fluxo comprador...")
    for i in range(8):
        engine.add_tick(Tick(
            timestamp = time.time() - (8 - i),
            price     = 65.00 + i * 0.10,
            qty       = 500,
            broker    = "ITAU",
            side      = Side.BUY,
        ))

    # Player com urgência: Goldman Sachs comprando em múltiplos preços
    info("Injetando Goldman Sachs com urgência (5 preços diferentes em 5 segundos)...")
    precos = [65.00, 65.10, 65.20, 65.30, 65.40]
    for i, p in enumerate(precos):
        engine.add_tick(Tick(
            timestamp = time.time() - (5 - i),
            price     = p,
            qty       = 2000,
            broker    = "GOLDMAN SACHS",
            side      = Side.BUY,
        ))

    signal = engine.get_signal()
    state  = engine.get_state()

    info(f"Urgência detectada: {state['urgent_brokers']}")
    info(f"Sinal: {signal.signal.value} | Padrão: {signal.pattern.value}")

    if state["urgent_brokers"]:
        ok(f"Urgência detectada: {[u['broker'] for u in state['urgent_brokers']]}")
    else:
        err("Nenhuma urgência detectada")


def test_absorcao():
    print(f"\n{AMARELO}═══ TESTE 4: Absorção de Nível ═══{RESET}")

    cfg = EngineConfig(
        flow_window_sec      = 20.0,
        flow_pct_threshold   = 60.0,
        absorption_min_touches = 4,
        absorption_window_sec  = 60.0,
        min_confidence       = 0.50,
    )
    engine = FlowEngine("ITUB4", cfg)

    # Preço batendo várias vezes no mesmo nível (19.50) sem romper
    info("Simulando preço batendo 6x no nível 19.50 (absorção)...")
    for i in range(6):
        engine.add_tick(Tick(
            timestamp = time.time() - (30 - i * 5),
            price     = 19.50,
            qty       = 800,
            broker    = "BRADESCO",
            side      = Side.SELL,
        ))
        # Recuos entre os toques
        engine.add_tick(Tick(
            timestamp = time.time() - (28 - i * 5),
            price     = 19.48,
            qty       = 400,
            broker    = "ITAU",
            side      = Side.BUY,
        ))

    state = engine.get_state()
    info(f"Níveis absorvidos: {state['absorbed_levels']}")

    if state["absorbed_levels"]:
        lvl = state["absorbed_levels"][0]
        ok(f"Absorção detectada @ R${lvl['price']:.2f} com {lvl['touches']} toques "
           f"(vol {lvl['volume']:,}, agressor absorvido: {lvl['absorbed_side']})")
    else:
        err("Nenhuma absorção detectada")

    # 19.48 também foi tocado 6x, mas só nos recuos (volume baixo) → não é absorção
    precos = [l["price"] for l in state["absorbed_levels"]]
    if 19.48 in precos:
        err(f"19.48 não deveria contar como absorção (volume baixo): {state['absorbed_levels']}")
    else:
        ok("Nível de recuo com volume baixo (19.48) filtrado corretamente")

    if state["absorbed_levels"][0]["absorbed_side"] == "venda":
        ok("Lado absorvido correto: agressão vendedora")
    else:
        err(f"Lado absorvido incorreto: {state['absorbed_levels'][0]['absorbed_side']}")


def test_delta():
    print(f"\n{AMARELO}═══ TESTE 5: Delta Acumulado ═══{RESET}")

    engine = FlowEngine("WEGE3", EngineConfig(delta_window_sec=10.0))
    now = time.time()
    # Agressões antigas (fora da janela de 10s): +3000 compra
    for i in range(3):
        engine.add_tick(Tick(now - 60 + i, 40.00, 1000, f"B{i}", Side.BUY))
    # Agressões recentes: +500 compra, -2000 venda
    engine.add_tick(Tick(now - 5, 40.00, 500,  "X", Side.BUY))
    engine.add_tick(Tick(now - 4, 39.99, 1200, "Y", Side.SELL))
    engine.add_tick(Tick(now - 3, 39.98, 800,  "Z", Side.SELL))

    d = engine.get_state()["delta"]
    info(f"Delta: {d}")
    if d["cumulative"] == 3000 + 500 - 2000:
        ok(f"Delta acumulado correto: {d['cumulative']:+,}")
    else:
        err(f"Delta acumulado esperado +1500, recebeu {d['cumulative']}")
    if d["window"] == 500 - 2000 and d["window_buy"] == 500 and d["window_sell"] == 2000:
        ok(f"Delta da janela correto: {d['window']:+,}")
    else:
        err(f"Delta da janela incorreto: {d}")

    engine.reset()
    if engine.get_state()["delta"]["cumulative"] == 0:
        ok("Delta zerado no reset")
    else:
        err("Delta não foi zerado no reset")


def _simular_pernas(engine: FlowEngine, inicio: float, sentido: int,
                    pernas: list[tuple[int, int, float]], recuo_ticks: int = 4) -> float:
    """
    Gera pernas na direção `sentido` (+1 alta, -1 baixa) separadas por recuos.
    pernas: [(n_ticks_avanço, lote_agressão, intervalo_seg)]
    Cada perna sobe/desce n_ticks e depois recua recuo_ticks (agressão contrária).
    Retorna o timestamp do último tick.
    """
    tk = engine.cfg.tick_size
    a_favor = Side.BUY if sentido > 0 else Side.SELL
    contra  = Side.SELL if sentido > 0 else Side.BUY
    preco = 20.00
    ts = inicio
    n = 0
    engine.add_tick(Tick(ts, preco, 100, "INICIO", a_favor))
    for avanco, lote, dt in pernas:
        for _ in range(avanco):
            ts += dt; n += 1
            preco = round(preco + sentido * tk, 2)
            engine.add_tick(Tick(ts, preco, lote, f"B{n}", a_favor))
        for _ in range(recuo_ticks):
            ts += 0.5; n += 1
            preco = round(preco - sentido * tk, 2)
            engine.add_tick(Tick(ts, preco, 300, f"B{n}", contra))
    return ts


def _cfg_exaustao() -> EngineConfig:
    return EngineConfig(
        flow_window_sec           = 10.0,
        tick_size                 = 0.01,
        exhaustion_reversal_ticks = 3,
        exhaustion_min_legs       = 3,
        exhaustion_vol_ratio      = 0.6,
        min_confidence            = 0.50,
    )


def test_exaustao_topo():
    print(f"\n{AMARELO}═══ TESTE 6: Exaustão Compradora (topo) ═══{RESET}")

    engine = FlowEngine("PETR4", _cfg_exaustao())
    info("3 pernas de alta: lote 1000 rápido → 900 → 150 lento (máximas mais altas)...")
    _simular_pernas(engine, time.time() - 60, +1, [
        (10, 1000, 0.3),
        (8,  900,  0.4),
        (6,  150,  1.5),
    ])

    state  = engine.get_state()
    signal = engine.get_signal()
    info(f"Pernas: {[(l['direction'], l['end_price'], l['vol_with']) for l in state['legs']]}")
    info(f"Sinal: {signal.signal.value} | Padrão: {signal.pattern.value} | "
         f"Conf: {signal.confidence:.2f} | Stop: {signal.stop_price}")
    info(f"Razão: {signal.reason}")

    if not state["exhaustions"]:
        err("Nenhuma exaustão detectada")
    ev = state["exhaustions"][0]
    if ev["exhausted_side"] == "compra":
        ok(f"Exaustão compradora @ {ev['extreme_price']:.2f} (vol {ev['vol_ratio']:.0%})")
    else:
        err(f"Lado exaurido incorreto: {ev['exhausted_side']}")
    if ev["delta_divergence"]:
        ok("Divergência de delta detectada")
    else:
        err("Divergência de delta esperada")
    if signal.signal == Signal.SELL and signal.pattern.value == "Exaustão":
        ok("Sinal SELL por exaustão gerado")
    else:
        err(f"Esperado SELL/Exaustão, recebeu {signal.signal.value}/{signal.pattern.value}")
    if signal.stop_price > ev["extreme_price"]:
        ok(f"Stop acima da máxima: {signal.stop_price:.2f}")
    else:
        err(f"Stop deveria ficar acima de {ev['extreme_price']}: {signal.stop_price}")

    # Preço rompe a máxima → exaustão invalidada
    last = engine._ticks[-1]
    engine.add_tick(Tick(last.timestamp + 1, round(ev["extreme_price"] + 0.01, 2),
                         2000, "ROMPE", Side.BUY))
    if not engine.get_state()["exhaustions"]:
        ok("Exaustão invalidada após rompimento da máxima")
    else:
        err("Exaustão deveria ser invalidada após rompimento")


def test_exaustao_fundo():
    print(f"\n{AMARELO}═══ TESTE 7: Exaustão Vendedora (fundo) ═══{RESET}")

    engine = FlowEngine("VALE3", _cfg_exaustao())
    _simular_pernas(engine, time.time() - 60, -1, [
        (10, 1000, 0.3),
        (8,  800,  0.4),
        (6,  200,  1.5),
    ])
    signal = engine.get_signal()
    info(f"Sinal: {signal.signal.value} | Padrão: {signal.pattern.value} | Razão: {signal.reason}")
    if signal.signal == Signal.BUY and signal.pattern.value == "Exaustão":
        ok("Sinal BUY por exaustão vendedora gerado")
    else:
        err(f"Esperado BUY/Exaustão, recebeu {signal.signal.value}/{signal.pattern.value}")


def test_sem_exaustao():
    print(f"\n{AMARELO}═══ TESTE 8: Tendência saudável (sem exaustão) ═══{RESET}")

    engine = FlowEngine("ITUB4", _cfg_exaustao())
    _simular_pernas(engine, time.time() - 60, +1, [
        (10, 1000, 0.3),
        (8,  1000, 0.3),
        (8,  1100, 0.3),
    ])
    state = engine.get_state()
    if not state["exhaustions"]:
        ok("Nenhuma exaustão com volume crescente nas pernas")
    else:
        err(f"Exaustão falsa: {state['exhaustions']}")


def programa_asset_ok(programa) -> bool:
    sys_argv = sys.argv
    try:
        sys.argv = ["main.py", "--asset", "petr4"]
        return programa.parse_args().asset == "PETR4"
    finally:
        sys.argv = sys_argv


def test_profitdll():
    print(f"\n{AMARELO}═══ TESTE 9: Ponte ProfitDLL (negócios simulados) ═══{RESET}")

    import json, tempfile, threading
    from profitdll.bridge import (ProfitDLLBridge, trade_para_tick, validar_ativo, BOLSA,
                                  AGRESSAO_COMPRA, AGRESSAO_VENDA)

    # Lado agressor e corretora agressora vêm do TradeType
    t = trade_para_tick(3, 8, 500, 5.12, AGRESSAO_COMPRA, 1000.0, {3: "XP INC", 8: "UBS"})
    if t and t.side == Side.BUY and t.broker == "XP INC" and t.qty == 500:
        ok("Agressão de compra → BUY, corretora compradora")
    else:
        err(f"Conversão de agressão de compra incorreta: {t}")
    t = trade_para_tick(3, 8, 200, 5.11, AGRESSAO_VENDA, 1000.0, {3: "XP INC", 8: "UBS"})
    if t and t.side == Side.SELL and t.broker == "UBS":
        ok("Agressão de venda → SELL, corretora vendedora")
    else:
        err(f"Conversão de agressão de venda incorreta: {t}")
    if trade_para_tick(3, 8, 100, 5.11, 1, 1000.0) is None:
        ok("Negócio sem agressão (cross/leilão) ignorado")
    else:
        err("Negócio sem agressão deveria ser ignorado")
    if trade_para_tick(77, 8, 100, 5.11, AGRESSAO_COMPRA, 1000.0).broker == "77":
        ok("Corretora sem nome mapeado usa o código")
    else:
        err("Corretora sem nome deveria usar o código")

    recusados = []
    for futuro in ("WDOFUT", "WINZ26", "DOLF27", "INDFUT", "wdofut"):
        try:
            validar_ativo(futuro)
        except ValueError:
            recusados.append(futuro)
    if validar_ativo(" petr4 ") == "PETR4" and len(recusados) == 5 and BOLSA == "B"             and ProfitDLLBridge("BBAS3").exchange == "B":
        ok("Só ações: ticker de futuro recusado, bolsa sempre B (Bovespa)")
    else:
        err(f"Validação de ativo incorreta: recusados={recusados}")
    try:
        ProfitDLLBridge("WDOFUT")
        err("Ponte deveria recusar ticker de futuro")
    except ValueError:
        ok("Ponte recusa ticker de futuro")
    import contextlib, io
    import main as programa
    from profitdll.historico import parse_args as args_historico
    recusas = 0
    for argv, analisar in ((["main.py", "--asset", "WINZ26", "--modo", "replay"], lambda: programa.parse_args()),
                           (None, lambda: args_historico(["--asset", "WDOFUT", "--inicio", "2026-10-01"]))):
        sys_argv = sys.argv
        try:
            if argv:
                sys.argv = argv
            with contextlib.redirect_stderr(io.StringIO()):
                analisar()
        except SystemExit:
            recusas += 1
        finally:
            sys.argv = sys_argv
    if recusas == 2 and programa_asset_ok(programa):
        ok("main.py e o histórico recusam futuro na linha de comando; ação passa normalizada")
    else:
        err(f"Linha de comando aceitou futuro ({recusas}/2 recusas)")

    # Fila → consumidor → engine, com nomes vindos de JSON
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"3": "xp inc", "8": "UBS"}, f)
    engine = FlowEngine("PETR4", EngineConfig(delta_window_sec=60.0))
    bridge = ProfitDLLBridge("PETR4", agentes_path=f.name)
    os.unlink(f.name)
    bridge.on_tick = engine.add_tick
    consumidor = threading.Thread(target=bridge._consumir, daemon=True)
    consumidor.start()
    now = time.time()
    bridge.fila.put(("trade", 3, 8, 10, 5100.0, AGRESSAO_COMPRA, now - 3))
    bridge.fila.put(("trade", 3, 8, 4,  5100.5, AGRESSAO_VENDA,  now - 2))
    bridge.fila.put(("trade", 3, 8, 7,  5100.5, 1,               now - 1))   # sem agressão
    deadline = time.time() + 3
    while bridge.trades_recebidos < 3 and time.time() < deadline:
        time.sleep(0.05)
    bridge._parar.set()
    consumidor.join(timeout=2)

    state = engine.get_state()
    if state["tick_count"] == 2 and state["delta"]["cumulative"] == 10 - 4:
        ok(f"Engine recebeu 2 ticks, delta {state['delta']['cumulative']:+}")
    else:
        err(f"Esperado 2 ticks e delta +6: {state['tick_count']} / {state['delta']}")
    if bridge.trades_ignorados == 1:
        ok("Contagem de negócios ignorados correta")
    else:
        err(f"Ignorados: {bridge.trades_ignorados}")
    if engine._ticks[0].broker == "XP INC":
        ok("Nome da corretora carregado do JSON")
    else:
        err(f"Nome esperado XP INC: {engine._ticks[0].broker}")

    if sys.platform != "win32":
        if not ProfitDLLBridge("PETR4").start():
            ok("Fora do Windows, start() falha com erro claro (sem travar)")
        else:
            err("start() deveria falhar fora do Windows")


def test_profitdll_tempo_real():
    print(f"\n{AMARELO}═══ TESTE 9b: ProfitDLL tempo real (horário do negócio + TinyBook) ═══{RESET}")

    from types import SimpleNamespace
    from datetime import datetime, timezone
    from profitdll.bridge import (ProfitDLLBridge, data_b3_para_epoch, systemtime_para_epoch,
                                  horario_negocio, topo_para_niveis,
                                  AGRESSAO_COMPRA, AGRESSAO_VENDA, TINYBOOK_BID, TINYBOOK_ASK)

    # 14/10/2026 10:00:00.125 em Brasília = 13:00:00.125 UTC
    esperado = datetime(2026, 10, 14, 13, 0, 0, tzinfo=timezone.utc).timestamp() + 0.125

    st = SimpleNamespace(wYear=2026, wMonth=10, wDayOfWeek=3, wDay=14, wHour=10,
                         wMinute=0, wSecond=0, wMilliseconds=125)
    ts = systemtime_para_epoch(st)
    if ts is not None and abs(ts - esperado) < 1e-6:
        ok(f"SYSTEMTIME → epoch com UTC-3 e ms ({ts:.3f})")
    else:
        err(f"SYSTEMTIME convertido errado: {ts} (esperado {esperado:.3f})")

    ts = data_b3_para_epoch("14/10/2026 10:00:00.125")
    if ts is not None and abs(ts - esperado) < 1e-6:
        ok("Texto 'DD/MM/YYYY HH:mm:SS.ZZZ' → mesmo epoch")
    else:
        err(f"Texto convertido errado: {ts}")
    ts = data_b3_para_epoch("14/10/2026 10:00:00")
    if ts is not None and abs(ts - (esperado - 0.125)) < 1e-6:
        ok("Texto sem milissegundos aceito")
    else:
        err(f"Texto sem ms convertido errado: {ts}")

    # O epoch gravado no CSV (--gravar) volta igual na leitura do replay
    from replay.csv_ticks import _timestamp
    if abs(_timestamp(f"{esperado:.3f}") - esperado) < 1e-6:
        ok("Epoch é consistente com o formato do CSV de replay")
    else:
        err("Epoch não sobrevive ao CSV de replay")

    zerado = SimpleNamespace(wYear=0, wMonth=0, wDay=0, wHour=0, wMinute=0,
                             wSecond=0, wMilliseconds=0)
    invalido = SimpleNamespace(wYear=2026, wMonth=13, wDay=40, wHour=0, wMinute=0,
                               wSecond=0, wMilliseconds=0)
    falhas = [horario_negocio(None), horario_negocio(zerado), horario_negocio(invalido),
              horario_negocio(""), horario_negocio("lixo"), horario_negocio(12345)]
    if all(f is None for f in falhas):
        ok("Zerado / inválido / vazio / desconhecido → None (fallback)")
    else:
        err(f"Esperado None em todos: {falhas}")
    if horario_negocio(st) == systemtime_para_epoch(st) and \
       horario_negocio("14/10/2026 10:00:00.125") == data_b3_para_epoch("14/10/2026 10:00:00.125"):
        ok("horario_negocio aceita SYSTEMTIME e texto")
    else:
        err("horario_negocio não despachou corretamente")

    niveis = topo_para_niveis((5100.0, 30), None, 1000.0)
    if len(niveis) == 1 and niveis[0].side == Side.BUY and niveis[0].broker == "":
        ok("Topo do livro com só um lado gera um nível sem corretora")
    else:
        err(f"topo_para_niveis incorreto: {niveis}")

    # Sequência intercalada trade/book processada direto (sem thread, sem DLL)
    engine = FlowEngine("PETR4", EngineConfig(tick_size=0.5, delta_window_sec=60.0))
    bridge = ProfitDLLBridge("PETR4")
    bridge.on_tick = engine.add_tick
    bridge.on_book = engine.update_book
    t0 = esperado
    chegada_local = t0 + 5000.0     # relógio local bem adiantado: não pode contaminar o engine
    eventos = [
        ("book",  TINYBOOK_BID, 5100.0, 20, chegada_local),   # antes de qualquer negócio
        ("trade", 3, 8, 10, 5100.5, AGRESSAO_COMPRA, t0),
        ("book",  TINYBOOK_ASK, 5101.0, 15, chegada_local),
        ("book",  TINYBOOK_BID, 5100.5, 12, chegada_local),
        ("trade", 3, 8, 4,  5100.5, AGRESSAO_VENDA,  t0 + 0.250),
        ("trade", 3, 8, 7,  5100.5, 1,               t0 + 0.300),   # sem agressão
        ("trade", 3, 8, 2,  5101.0, AGRESSAO_COMPRA, None),         # sem horário → fallback
        ("book",  TINYBOOK_ASK, 0.0, 0, chegada_local),              # lado vazio
        ("book",  7, 1.0, 1, chegada_local),                         # lado desconhecido
    ]
    engine_ts = []
    for ev in eventos[:6]:
        bridge._processar_evento(ev)
        engine_ts.append(engine._clock)

    if engine._book_buy and max(engine._book_buy) == 5100.5 and \
       engine._book_sell and min(engine._book_sell) == 5101.0:
        ok("Engine recebeu o topo do livro: bid 5100.5 / ask 5101.0")
    else:
        err(f"Book incorreto: bid {list(engine._book_buy)} ask {list(engine._book_sell)}")
    if all(b >= a for a, b in zip(engine_ts, engine_ts[1:])):
        ok("Relógio do engine nunca andou para trás")
    else:
        err(f"Relógio voltou: {engine_ts}")
    nivel = engine._book_buy[5100.5]
    if nivel.broker == "" and nivel.timestamp == t0:
        ok("Book usa o horário do último negócio (não o relógio local)")
    else:
        err(f"Nível do book: broker={nivel.broker!r} ts={nivel.timestamp}")
    if not engine._best_bid_log and not engine._best_ask_log and \
       not engine.get_state()["best_bid_brokers"]:
        ok("Book sem corretora não gera falso player no Best Offer")
    else:
        err(f"Best offer contaminado: {dict(engine._best_bid_log)}")

    antes = time.time()
    for ev in eventos[6:]:
        bridge._processar_evento(ev)
    st_dll = bridge.stats()
    if st_dll["trades_recebidos"] == 4 and st_dll["trades_ignorados"] == 1 and \
       st_dll["horarios_fallback"] == 1 and st_dll["book_atualizacoes"] == 4:
        ok(f"Contadores: {st_dll['trades_recebidos']} trades, {st_dll['trades_ignorados']} ignorado, "
           f"{st_dll['horarios_fallback']} fallback, {st_dll['book_atualizacoes']} books")
    else:
        err(f"Contadores incorretos: {st_dll}")
    if engine._ticks[-1].timestamp >= antes and engine._ticks[0].timestamp == t0:
        ok("Negócio sem horário usa o relógio local; os demais, o TradeDate")
    else:
        err(f"Timestamps dos ticks: {[t.timestamp for t in engine._ticks]}")
    if st_dll["ask"] is None and st_dll["bid"] == [5100.5, 12] and not engine._book_sell:
        ok("Ask zerado remove o lado do book")
    else:
        err(f"Topo após ask zerado: bid {st_dll['bid']} ask {st_dll['ask']} / {list(engine._book_sell)}")
    state = engine.get_state()
    if state["tick_count"] == 3 and state["delta"]["cumulative"] == 10 - 4 + 2:
        ok(f"Engine com 3 ticks e delta {state['delta']['cumulative']:+}")
    else:
        err(f"Esperado 3 ticks e delta +8: {state['tick_count']} / {state['delta']}")

    # Mesma sequência pela fila + thread consumidora: ordem preservada
    engine2 = FlowEngine("PETR4", EngineConfig(tick_size=0.5, delta_window_sec=60.0))
    bridge2 = ProfitDLLBridge("PETR4")
    bridge2.on_tick = engine2.add_tick
    bridge2.on_book = engine2.update_book
    for ev in eventos:
        bridge2.fila.put(ev)
    import threading
    consumidor = threading.Thread(target=bridge2._consumir, daemon=True)
    consumidor.start()
    deadline = time.time() + 3
    while bridge2.fila.qsize() and time.time() < deadline:
        time.sleep(0.05)
    time.sleep(0.1)
    bridge2._parar.set()
    consumidor.join(timeout=2)
    # latencia_ms depende do relógio no momento do processamento: fora da comparação de ordem
    neutro = {"fila_pendente": 0, "latencia_ms": None}
    if bridge2.stats() | neutro == st_dll | neutro:
        ok("Fila única + consumidor chega ao mesmo estado (ordem preservada)")
    else:
        err(f"Estado divergente: {bridge2.stats()} vs {st_dll}")

    # GET /state expõe o bloco "dll"
    import json, urllib.request
    from api.server import FlowServer
    server = FlowServer(engine, host="127.0.0.1", port=15556)
    server.registrar_dll(bridge)
    server.start()
    try:
        with urllib.request.urlopen("http://127.0.0.1:15556/state", timeout=3) as r:
            estado = json.loads(r.read())
    finally:
        server.stop()
        server.registrar_dll(None)
    if estado.get("dll", {}).get("book_atualizacoes") == 4 and "rtd" in estado:
        ok("GET /state traz o bloco \"dll\" com os contadores")
    else:
        err(f"Bloco dll ausente/incorreto no /state: {estado.get('dll')}")


def test_profitdll_nomes_e_descartes():
    print(f"\n{AMARELO}═══ TESTE 9d: ProfitDLL — nome da corretora e descartes por tipo ═══{RESET}")

    from profitdll.bridge import ProfitDLLBridge, AGRESSAO_COMPRA, AGRESSAO_VENDA

    class DLLFalsa:
        NOMES = {8: "UBS", 107: "Terra"}
        def __init__(self): self.chamadas = 0
        def GetAgentNameLength(self, codigo, curto):
            self.chamadas += 1
            return len(self.NOMES.get(codigo, ""))
        def GetAgentName(self, tam, codigo, buf, curto):
            buf.value = self.NOMES[codigo][:tam - 1]
            return 0

    engine = FlowEngine("PETR4", EngineConfig(tick_size=0.5))
    b = ProfitDLLBridge("PETR4", agentes_path=None)
    b.nomes = {107: "TERRA (JSON)"}          # o JSON vence a DLL
    b.dll = DLLFalsa()
    b.on_tick = engine.add_tick
    t0 = 1_800_000_000.0
    b._processar_evento(("trade", 107, 8, 1, 5078.5, AGRESSAO_COMPRA, t0))
    b._processar_evento(("trade", 8, 1618, 2, 5078.5, AGRESSAO_VENDA, t0 + 1))
    b._processar_evento(("trade", 8, 107, 3, 5078.5, AGRESSAO_COMPRA, t0 + 2))
    b._processar_evento(("trade", 8, 107, 5, 5078.5, 1, t0 + 3))    # cross
    b._processar_evento(("trade", 8, 107, 5, 5078.5, 1, t0 + 4))    # cross
    b._processar_evento(("trade", 8, 107, 5, 5078.5, 4, t0 + 5))    # leilão
    recentes = engine.get_state()["recent_trades"]
    pares = [(t["broker"], t["passive_broker"]) for t in recentes[-3:]]
    if pares == [("TERRA (JSON)", "UBS"), ("1618", "UBS"), ("UBS", "TERRA (JSON)")]:
        ok(f"Nomes da DLL em maiúsculas, JSON vence, código sem nome fica como código: {pares}")
    else:
        err(f"Nomes errados: {pares}")
    if 8 in b._nomes_dll and 1618 not in b._nomes_dll:
        ok("Cache guarda só nomes resolvidos (código sem nome tenta de novo)")
    else:
        err(f"Cache inesperado: {b._nomes_dll}")
    st = b.stats()
    if st["ignorados_por_tipo"] == {"cross": 2, "leilão": 1} and st["trades_ignorados"] == 3:
        ok(f"Descartes contados por tipo: {st['ignorados_por_tipo']}")
    else:
        err(f"Descartes por tipo errados: {st['ignorados_por_tipo']}")

    sem_dll = ProfitDLLBridge("PETR4")
    if sem_dll._nome_agente(8) == "8":
        ok("Sem DLL o broker continua sendo o código")
    else:
        err("Sem DLL deveria devolver o código")


def test_profitdll_reconexao():
    print(f"\n{AMARELO}═══ TESTE 9e: ProfitDLL — start() depois de stop() e stats da tela Conexão ═══{RESET}")

    import json as _json
    from profitdll.bridge import ProfitDLLBridge, AGRESSAO_COMPRA, mascarar_caminho

    class DLLFalsa:
        def SubscribeTicker(self, *a): return 0
        def UnsubscribeTicker(self, *a): return 0
        def DLLFinalize(self): return 0

    b = ProfitDLLBridge("PETR4", timeout=0.5)
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
            and st["ativo"] == "PETR4" and st["bolsa"] == "B":
        ok(f"stats() com latência ({st['latencia_ms']} ms), estados com nome, ativo e bolsa")
    else:
        err(f"stats() incompleto: {st}")
    b.stop()

    # Durante o DLLFinalize a DLL manda (3,1): depois do stop() isso não é falha de ativação
    b._on_estado(3, 1)
    if b.motivo_falha is None and b.stats()["estados"]["ativacao"] == {"codigo": 0, "nome": "válida"}:
        ok("Estado recebido depois do stop() é ignorado (sem falsa 'ativação inválida' no log)")
    else:
        err(f"estado depois do stop virou falha: {b.motivo_falha} {b.stats()['estados']}")

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


def test_profitdll_correcoes():
    print(f"\n{AMARELO}═══ TESTE 9c: ProfitDLL — edição de negócio e estados de conexão ═══{RESET}")

    from profitdll.bridge import ProfitDLLBridge, AGRESSAO_COMPRA, TC_IS_EDIT

    # P1: negócio editado (flag TC_IS_EDIT) não entra no engine como negócio novo
    engine = FlowEngine("PETR4", EngineConfig(delta_window_sec=60.0))
    bridge = ProfitDLLBridge("PETR4")
    bridge.on_tick = engine.add_tick
    t0 = 1_800_000_000.0
    bridge._processar_evento(("trade", 3, 8, 100, 38.47, AGRESSAO_COMPRA, t0, 0, 501))
    bridge._processar_evento(("trade", 3, 8, 100, 38.47, AGRESSAO_COMPRA, t0 + 0.1, TC_IS_EDIT, 501))
    bridge._processar_evento(("trade", 3, 8, 200, 38.48, AGRESSAO_COMPRA, t0 + 0.2))  # formato antigo
    st = bridge.stats()
    state = engine.get_state()
    if state["tick_count"] == 2 and state["delta"]["cumulative"] == 300:
        ok("Edição de negócio não duplica volume nem delta")
    else:
        err(f"Edição entrou no engine: {state['tick_count']} ticks, delta {state['delta']}")
    if st["trades_editados"] == 1 and st["trades_recebidos"] == 2:
        ok("Edições contadas à parte em stats() (trades_editados)")
    else:
        err(f"Contadores com edição incorretos: {st}")

    # P2: login/ativação inválidos abortam a espera na hora, com motivo legível
    for tipo, resultado, trecho in ((0, 2, "senha inválida"), (0, 1, "login inválido"),
                                    (0, 3, "senha bloqueada"), (3, 1, "ativação inválida")):
        b = ProfitDLLBridge("PETR4", timeout=5)
        b._on_estado(tipo, resultado)
        inicio = time.time()
        try:
            b._aguardar_conexao()
            err(f"({tipo},{resultado}) não abortou a conexão")
        except RuntimeError as e:
            if trecho in str(e).lower() and time.time() - inicio < 1:
                ok(f"({tipo},{resultado}) aborta na hora: {e}")
            else:
                err(f"({tipo},{resultado}) mensagem/tempo errados: {e!r} em {time.time() - inicio:.1f}s")

    b = ProfitDLLBridge("PETR4", timeout=0.3)
    b._on_estado(0, 0)
    b._on_estado(3, 0)
    try:
        b._aguardar_conexao()
        err("Timeout sem market data não foi detectado")
    except TimeoutError as e:
        if "market" in str(e):
            ok(f"Timeout aponta o que faltou: {e}")
        else:
            err(f"Timeout sem dizer o que faltou: {e}")

    # Conectado → queda do market data, aviso (2,6) e reconexão
    b = ProfitDLLBridge("PETR4", timeout=1)
    for tipo, resultado in ((0, 0), (2, 4), (3, 0)):
        b._on_estado(tipo, resultado)
    b._aguardar_conexao()
    if b.stats()["conectado"] and b.stats()["estado_market"] == "conectado":
        ok("Conexão completa: login, market data e ativação")
    else:
        err(f"Estado após conectar: {b.stats()}")
    b._on_estado(2, 6)
    b._on_estado(2, 0)
    st = b.stats()
    if st["avisos_partial"] == 1 and st["quedas_market"] == 1 and not st["conectado"] \
            and st["estado_market"] == "desconectado":
        ok("Aviso (2,6) e queda do market data registrados em stats()")
    else:
        err(f"Queda/aviso não registrados: {st}")
    b._on_estado(2, 4)
    if b.stats()["conectado"] and b.stats()["quedas_market"] == 1:
        ok("Market data reconectado volta ao estado conectado")
    else:
        err(f"Reconexão não reconhecida: {b.stats()}")


def test_rtd():
    print(f"\n{AMARELO}═══ TESTE 10: Inferência de negócios do RTD ═══{RESET}")

    from core.rtd import RTDTradeInferer, RTDSnapshot

    def snap(price, vol, neg, bid=0.0, ask=0.0, buyer="ITAU", seller="XP INC"):
        return RTDSnapshot(price=price, volume=vol, trades=neg, buyer=buyer,
                           seller=seller, bid=bid, ask=ask, timestamp=time.time())

    inf = RTDTradeInferer()
    if inf.update(snap(19.50, 100000, 500)) is None:
        ok("Primeiro retrato só define a base (volume acumulado não vira tick)")
    else:
        err("Primeiro retrato não deveria gerar tick")

    t = inf.update(snap(19.51, 100300, 501))
    if t and t.qty == 300 and t.side == Side.BUY and t.broker == "ITAU":
        ok("Quantidade = diferença do VOL (300); preço subiu → compra pelo ACP")
    else:
        err(f"Tick incorreto: {t}")

    t = inf.update(snap(19.51, 100500, 502))
    if t and t.side == Side.BUY and t.qty == 200:
        ok("Zero-tick mantém o lado anterior")
    else:
        err(f"Zero-tick incorreto: {t}")

    t = inf.update(snap(19.49, 101500, 505))
    if t and t.side == Side.SELL and t.broker == "XP INC" and t.qty == 1000:
        ok("Preço caiu → venda pelo AVD")
    else:
        err(f"Tick de venda incorreto: {t}")
    if inf.aggregated_trades == 2:
        ok("3 negócios entre retratos contados como agregados (2 extras)")
    else:
        err(f"aggregated_trades esperado 2: {inf.aggregated_trades}")

    if inf.update(snap(19.49, 101500, 505, bid=19.48, ask=19.50)) is None:
        ok("Retrato sem negócio novo não gera tick")
    else:
        err("Retrato sem negócio não deveria gerar tick")

    # Regra da cotação usa o bid/ask ANTERIOR: preço caiu, mas negociou no ask → compra
    inf2 = RTDTradeInferer()
    inf2.update(snap(19.52, 1000, 10, bid=19.48, ask=19.50))
    t = inf2.update(snap(19.50, 1500, 11, bid=19.49, ask=19.51))
    if t and t.side == Side.BUY:
        ok("Regra da cotação: negócio no ask anterior → compra (mesmo com preço caindo)")
    else:
        err(f"Regra da cotação incorreta: {t}")
    t = inf2.update(snap(19.49, 1800, 12, bid=19.48, ask=19.50))
    if t and t.side == Side.SELL and inf2.side_by_quote == 2:
        ok("Regra da cotação: negócio no bid anterior → venda")
    else:
        err(f"Regra da cotação (bid) incorreta: {t} / {inf2.stats()}")

    if inf2.update(snap(19.50, 50, 1)) is None and inf2.update(snap(19.51, 80, 2)).qty == 30:
        ok("Virada de dia (acumulados zeraram) redefine a base")
    else:
        err("Virada de dia não tratada")


def test_api_http():
    print(f"\n{AMARELO}═══ TESTE 11: API HTTP (servidor embutido) ═══{RESET}")

    import threading
    import urllib.request

    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from api.server import FlowServer

    engine = FlowEngine("BBDC4")
    server = FlowServer(engine, host="127.0.0.1", port=15555)
    server.start()
    time.sleep(0.3)

    info("Testando GET /health ...")
    try:
        with urllib.request.urlopen("http://127.0.0.1:15555/health", timeout=3) as r:
            data = r.read().decode()
            if "ok" in data:
                ok("GET /health respondeu corretamente")
            else:
                err(f"Resposta inesperada: {data}")
    except Exception as e:
        err(f"Erro ao acessar /health: {e}")

    info("Testando POST /tick ...")
    import json
    payload = json.dumps({
        "price": 23.50, "qty": 500,
        "broker": "JP MORGAN", "side": "C"
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:15555/tick",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            resp = json.loads(r.read().decode())
            if resp.get("ok"):
                ok("POST /tick aceito corretamente")
            else:
                err(f"Resposta inesperada: {resp}")
    except Exception as e:
        err(f"Erro ao enviar tick: {e}")

    info("Testando POST /tick com passive_broker ...")
    req = urllib.request.Request(
        "http://127.0.0.1:15555/tick",
        data=json.dumps({"price": 23.50, "qty": 300, "broker": "XP INC",
                         "side": "V", "passive_broker": "BTG PACTUAL"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=3) as r:
        json.loads(r.read().decode())
    if engine._ticks[-1].passive_broker == "BTG PACTUAL" and engine._ticks[0].passive_broker == "":
        ok("POST /tick aceita passive_broker opcional (sem ele fica vazio)")
    else:
        err(f"passive_broker não propagado: {engine._ticks[-1]}")

    info("Testando POST /tick com side inválido ...")
    req = urllib.request.Request(
        "http://127.0.0.1:15555/tick",
        data=json.dumps({"price": 23.50, "qty": 500, "side": "N"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=3)
        err("side 'N' deveria ser recusado")
    except urllib.error.HTTPError as e:
        if e.code == 400:
            ok("side 'N' recusado com 400 (antes virava venda)")
        else:
            err(f"Código inesperado: {e.code}")

    info("Testando POST /rtd ...")
    def post_rtd(body):
        r = urllib.request.Request("http://127.0.0.1:15555/rtd",
                                   data=json.dumps(body).encode(),
                                   headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(r, timeout=3) as resp:
            return resp.read().decode()
    post_rtd({"price": 23.50, "volume": 10000, "trades": 50, "buyer": "itau", "seller": "xp inc"})
    raw = post_rtd({"price": 23.51, "volume": 10400, "trades": 51, "buyer": "itau", "seller": "xp inc"})
    resp = json.loads(raw)
    if resp.get("tick") == {"side": "compra", "qty": 400, "broker": "ITAU"}:
        ok("POST /rtd inferiu compra de 400 pelo ITAU")
    else:
        err(f"Resposta inesperada do /rtd: {resp}")
    # A macro VBA lê estes campos por texto — o formato precisa bater
    if '"signal": "' in raw and '"confidence": ' in raw and '"stop_price": ' in raw:
        ok("Resposta no formato que a macro VBA lê")
    else:
        err(f"Formato da resposta mudou: {raw[:120]}")

    info("Testando GET /state ...")
    try:
        with urllib.request.urlopen("http://127.0.0.1:15555/state", timeout=3) as r:
            state = json.loads(r.read().decode())
            if state.get("asset") == "BBDC4" and state.get("rtd", {}).get("ticks_emitted") == 1 \
                    and "icebergs_weak_heuristic" in state:
                ok(f"GET /state OK | ticks: {state['tick_count']} | rtd: {state['rtd']}")
            else:
                err(f"Ativo incorreto: {state.get('asset')}")
    except Exception as e:
        err(f"Erro ao acessar /state: {e}")

    server.stop()


def _cfg_iceberg() -> EngineConfig:
    return EngineConfig(
        flow_window_sec      = 30.0,
        flow_pct_threshold   = 60.0,
        iceberg_min_renewals = 3,
        iceberg_vol_ratio    = 3.0,
        iceberg_min_share    = 0.5,
        tick_size            = 0.01,
        min_confidence       = 0.50,
        defesa_iceberg_vol_sinal        = {},   # testes antigos: sem corte de volume do sinal
        defesa_iceberg_vol_sinal_padrao = 0,
    )


def _base_negocios(engine: FlowEngine, inicio: float) -> float:
    """10 negócios pequenos (lote 100) acima do nível, cada um com outra passiva."""
    ts = inicio
    for i in range(10):
        ts += 0.5
        engine.add_tick(Tick(ts, round(19.05 + (i % 3) * 0.01, 2), 100, f"AGR{i}",
                             Side.BUY, passive_broker=f"PAS{i}"))
    return ts


def test_iceberg_passiva():
    print(f"\n{AMARELO}═══ TESTE 12: Iceberg pela corretora PASSIVA ═══{RESET}")

    engine = FlowEngine("PETR4", _cfg_iceberg())
    ts = _base_negocios(engine, time.time() - 20)

    info("8 agressões de venda @ 19.04, agressores diferentes, sempre contra JP MORGAN (passiva)...")
    vendedores = ["BRADESCO", "RICO", "CLEAR", "XP INC", "TORO", "GENIAL", "INTER", "ITAU"]
    for i, agr in enumerate(vendedores):
        ts += 1.0
        engine.add_tick(Tick(ts, 19.04, 150 + (i % 3) * 50, agr, Side.SELL,
                             passive_broker="JP MORGAN"))

    if engine.get_state()["icebergs_confirmed"]:
        err("8 agressões sem reposição não são iceberg")
    else:
        ok("8 agressões contra JP MORGAN, sem a corretora repor o lote, não confirmam iceberg")
    _renovar(engine, "JP MORGAN", "compra", 19.04, ts)

    state  = engine.get_state()
    signal = engine.get_signal()
    ics = state["icebergs_confirmed"]
    info(f"Icebergs: {ics}")
    info(f"Sinal: {signal.signal.value} | {signal.pattern.value} | conf {signal.confidence:.2f} | {signal.reason}")

    if len(ics) == 1 and ics[0]["passive_broker"] == "JP MORGAN" and ics[0]["side"] == "compra":
        ok("Iceberg COMPRADOR de JP MORGAN (passiva) confirmado")
    else:
        err(f"Esperado 1 iceberg comprador de JP MORGAN: {ics}")
    ic = ics[0]
    if ic["role"] == "suporte" and ic["price"] == 19.04 and ic["renewals"] == 2 \
            and ic["aggressors"] == 8 and not ic["weak_heuristic"]:
        ok("Estado: suporte @ 19.04 | 2 giros e 8 agressores | não é heurística fraca")
    else:
        err(f"Campos do iceberg incorretos: {ic}")
    if ic["vol_ratio"] >= 3.0 and ic["share"] == 1.0 and 0 < ic["confidence"] <= 0.9:
        ok(f"Volume {ic['vol_ratio']:.1f}x o lote médio, fatia {ic['share']:.0%}, "
           f"confiança {ic['confidence']:.2f}")
    else:
        err(f"Métricas incorretas: {ic}")
    if state["icebergs_weak_heuristic"] is False:
        ok("Estado não sinaliza heurística fraca")
    else:
        err("icebergs_weak_heuristic deveria ser False")
    if signal.signal == Signal.BUY and signal.pattern.value == "Iceberg" \
            and signal.broker == "JP MORGAN" and signal.stop_price == 19.03:
        ok(f"Sinal BUY no suporte, stop no 1º tick além do nível ({signal.stop_price:.2f}, aula-02 24:15)")
    else:
        err(f"Esperado BUY/Iceberg JP MORGAN com stop 19,03: {signal.to_dict()}")

    info("Venda negociada ABAIXO do nível (19.03): o iceberg acabou...")
    engine.add_tick(Tick(ts + 1, 19.03, 200, "RICO", Side.SELL, passive_broker="ITAU"))
    if not engine.get_state()["icebergs_confirmed"]:
        ok("Preço atravessou o nível → iceberg descartado")
    else:
        err("Iceberg deveria ser descartado quando o preço atravessa")

    info("Sem acontecimento de fim, o iceberg continua mesmo depois de muito tempo...")
    engine2 = FlowEngine("PETR4", _cfg_iceberg())
    ts = _base_negocios(engine2, 1_000_000.0)   # tempo antigo: só o tick conta
    for i in range(5):
        ts += 1.0
        engine2.add_tick(Tick(ts, 19.04, 300, f"V{i}", Side.SELL, passive_broker="UBS"))
    _renovar(engine2, "UBS", "compra", 19.04, ts)
    antes = len(engine2.get_state()["icebergs_confirmed"])
    engine2.add_tick(Tick(ts + engine2.cfg.iceberg_timeout_sec + 1, 19.05, 100, "X",
                          Side.BUY, passive_broker="Y"))
    depois = len(engine2.get_state()["icebergs_confirmed"])
    if antes == 1 and depois == 1:
        ok("Sem tempo de expiração (decisão de 17/10): a defesa só termina por acontecimento")
    else:
        err(f"Defesa sem acontecimento de fim deveria continuar: antes={antes} depois={depois}")

    info("Iceberg VENDEDOR: compras agredindo a mesma passiva → resistência...")
    engine3 = FlowEngine("VALE3", _cfg_iceberg())
    ts = time.time() - 20
    for i in range(10):
        ts += 0.5
        engine3.add_tick(Tick(ts, 19.02, 100, f"A{i}", Side.SELL, passive_broker=f"P{i}"))
    for i in range(6):
        ts += 1.0
        engine3.add_tick(Tick(ts, 19.03, 250, f"C{i}", Side.BUY, passive_broker="MORGAN STANLEY"))
    _renovar(engine3, "MORGAN STANLEY", "venda", 19.03, ts)
    ics = engine3.get_state()["icebergs_confirmed"]
    sig = engine3.get_signal()
    if ics and ics[0]["side"] == "venda" and ics[0]["role"] == "resistência" \
            and sig.signal == Signal.SELL and sig.stop_price > 19.03:
        ok(f"Iceberg vendedor (resistência) → SELL, stop {sig.stop_price:.2f}")
    else:
        err(f"Iceberg vendedor incorreto: {ics} / {sig.to_dict()}")


def test_iceberg_passivas_espalhadas():
    print(f"\n{AMARELO}═══ TESTE 13: Agressões espalhadas entre várias passivas ═══{RESET}")

    engine = FlowEngine("PETR4", _cfg_iceberg())
    ts = _base_negocios(engine, time.time() - 30)
    passivas = ["JP MORGAN", "ITAU", "BTG PACTUAL", "UBS"]
    info("16 vendas @ 19.04 alternando entre 4 passivas (4 execuções cada)...")
    for i in range(16):
        ts += 1.0
        engine.add_tick(Tick(ts, 19.04, 150, f"V{i}", Side.SELL,
                             passive_broker=passivas[i % 4]))

    state = engine.get_state()
    nivel = engine._defesas.nivel(19.04)
    cands = [d for d in engine._defesas._defesas.values() if d.vol_passivo and d.nivel == nivel]
    info(f"Candidatas: {[(c.corretora, c.giros, c.vol_passivo) for c in cands]}")
    if not state["icebergs_confirmed"]:
        ok("Nenhum iceberg: nenhuma passiva domina o nível")
    else:
        err(f"Agressões espalhadas não deveriam virar iceberg: {state['icebergs_confirmed']}")
    if len(cands) == 4 and all(c.giros == 0 and c.vol_passivo == 600 and c.estado == "candidata"
                               for c in cands):
        ok("Cada passiva com 4 agressões e 600 ações, 0 giros: abaixo de 1.000 e sem reposição")
    else:
        err(f"Candidatas inesperadas: {[(c.corretora, c.giros, c.vol_passivo, c.estado) for c in cands]}")
    if engine.get_signal().pattern.value != "Iceberg":
        ok("Nenhum sinal de iceberg emitido")
    else:
        err(f"Sinal de iceberg indevido: {engine.get_signal().to_dict()}")

    info("Mesma passiva, mas volume pequeno vs lote médio → não confirma...")
    engine2 = FlowEngine("PETR4", _cfg_iceberg())
    ts = time.time() - 30
    for i in range(10):
        ts += 0.5
        engine2.add_tick(Tick(ts, 19.06, 1000, f"G{i}", Side.BUY, passive_broker=f"P{i}"))
    for i in range(3):
        ts += 1.0
        engine2.add_tick(Tick(ts, 19.04, 100, f"V{i}", Side.SELL, passive_broker="JP MORGAN"))
    if not engine2.get_state()["icebergs_confirmed"]:
        ok("3 execuções de 100 (300 ações) não é iceberg: abaixo de 1.000")
    else:
        err("Passiva com menos de 1.000 ações não deveria confirmar")


def test_iceberg_fallback():
    print(f"\n{AMARELO}═══ TESTE 14: Fallback sem corretora passiva (heurística fraca) ═══{RESET}")

    engine = FlowEngine("PETR4", _cfg_iceberg())
    now = time.time()
    # Chamada posicional antiga (sem passive_broker) continua funcionando
    for i in range(10):
        engine.add_tick(Tick(now - 12 + i, 19.04, 100 + i * 20, f"V{i}", Side.SELL))
    for i in range(4):
        engine.add_tick(Tick(now - 2 + i * 0.5, 19.04, 1000, "JP MORGAN", Side.BUY))

    state = engine.get_state()
    ics = state["icebergs_confirmed"]
    info(f"Icebergs: {ics}")
    if len(ics) == 1 and ics[0]["broker"] == "JP MORGAN" and ics[0]["passive_broker"] == "" \
            and ics[0]["weak_heuristic"] is True:
        ok("Fallback por lote repetido detectado e marcado como heurística fraca")
    else:
        err(f"Fallback incorreto: {ics}")
    if state["icebergs_weak_heuristic"] is True:
        ok("Estado sinaliza icebergs_weak_heuristic = True")
    else:
        err("icebergs_weak_heuristic deveria ser True")
    sig = engine.get_signal()
    if sig.pattern.value == "Iceberg" and "heurística fraca" in sig.reason:
        ok(f"Sinal {sig.signal.value} com razão marcada como heurística fraca")
    else:
        err(f"Sinal do fallback deveria citar heurística fraca: {sig.to_dict()}")


def test_iceberg_rtd_passiva():
    print(f"\n{AMARELO}═══ TESTE 15: RTD e DLL inferindo a corretora passiva ═══{RESET}")

    from core.rtd import RTDTradeInferer, RTDSnapshot
    from profitdll.bridge import trade_para_tick, AGRESSAO_COMPRA, AGRESSAO_VENDA

    t0 = time.time() - 30
    def snap(price, vol, neg, ts, buyer="ITAU", seller="XP INC"):
        return RTDSnapshot(price=price, volume=vol, trades=neg, buyer=buyer,
                           seller=seller, timestamp=ts)

    inf = RTDTradeInferer()
    inf.update(snap(19.50, 1000, 10, t0))
    t = inf.update(snap(19.51, 1300, 11, t0 + 1))
    if t and t.side == Side.BUY and t.broker == "ITAU" and t.passive_broker == "XP INC":
        ok("Compra: agressora = ACP (ITAU), passiva = AVD (XP INC)")
    else:
        err(f"Passiva na compra incorreta: {t}")
    t = inf.update(snap(19.49, 1500, 12, t0 + 2))
    if t and t.side == Side.SELL and t.broker == "XP INC" and t.passive_broker == "ITAU":
        ok("Venda: agressora = AVD (XP INC), passiva = ACP (ITAU)")
    else:
        err(f"Passiva na venda incorreta: {t}")
    t = inf.update(snap(19.48, 1600, 13, t0 + 3, buyer=""))
    if t and t.passive_broker == "":
        ok("ACP vazio → passive_broker vazio (engine cai no fallback)")
    else:
        err(f"Passiva vazia esperada: {t}")

    # DLL: TranslateTrade traz comprador e vendedor
    nomes = {3: "XP INC", 8: "UBS"}
    tc = trade_para_tick(3, 8, 500, 5.12, AGRESSAO_COMPRA, 1000.0, nomes)
    tv = trade_para_tick(3, 8, 500, 5.12, AGRESSAO_VENDA, 1000.0, nomes)
    if tc.passive_broker == "UBS" and tv.passive_broker == "XP INC":
        ok("DLL: passiva = vendedor na agressão de compra, comprador na de venda")
    else:
        err(f"DLL passiva incorreta: {tc} / {tv}")

    info("RTD → engine: preço trava em 19.40 com BTG PACTUAL comprando de vários vendedores...")
    engine = FlowEngine("PETR4", _cfg_iceberg())
    inf = RTDTradeInferer()
    ts, vol, neg = t0, 10000, 100
    inf.update(snap(19.45, vol, neg, ts))
    for i in range(10):   # negócios pequenos subindo e descendo acima do nível
        ts += 0.5; vol += 100; neg += 1
        p = 19.45 + (0.01 if i % 2 else 0.0)
        tick = inf.update(snap(round(p, 2), vol, neg, ts, buyer=f"C{i}", seller=f"V{i}"))
        if tick:
            engine.add_tick(tick)
    vendedores = ["XP INC", "RICO", "CLEAR", "TORO", "GENIAL", "INTER"]
    for i, v in enumerate(vendedores):
        ts += 1.0; vol += 400; neg += 1
        tick = inf.update(snap(19.40, vol, neg, ts, buyer="BTG PACTUAL", seller=v))
        if tick:
            engine.add_tick(tick)
    _renovar(engine, "BTG PACTUAL", "compra", 19.40, ts)
    ics = engine.get_state()["icebergs_confirmed"]
    info(f"Icebergs: {ics}")
    if ics and ics[0]["passive_broker"] == "BTG PACTUAL" and ics[0]["side"] == "compra" \
            and not ics[0]["weak_heuristic"]:
        ok("Iceberg comprador de BTG PACTUAL (passiva inferida do RTD) confirmado")
    else:
        err(f"Iceberg via RTD não detectado: {ics}")


# ──────────────────────────────────────────────────────────────
# MODO REPLAY
# ──────────────────────────────────────────────────────────────

_PASTA = os.path.dirname(os.path.abspath(__file__))
_EXEMPLO = os.path.join(_PASTA, "replay", "exemplo_petr4.csv")


def _arquivo_temp(conteudo: str, encoding: str = "utf-8") -> str:
    import tempfile
    fd, caminho = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
        f.write(conteudo)
    return caminho


def test_relogio_engine():
    print(f"\n{AMARELO}═══ TESTE 12: Engine usa o tempo do tick (não o relógio do PC) ═══{RESET}")

    engine = FlowEngine("PETR4", EngineConfig(flow_window_sec=30.0,
                                              absorption_min_touches=4))
    if abs(engine._now() - time.time()) < 5:
        ok("Sem ticks, o relógio do engine cai no relógio do computador")
    else:
        err("Fallback do relógio incorreto")

    # Pregão de 14/10/2025 (um ano antes): com o relógio do PC, tudo
    # estaria fora das janelas e o fluxo daria 50/50
    base = 1760443200.0
    for i in range(6):
        engine.add_tick(Tick(base + i * 2, 19.50, 800, f"V{i}", Side.SELL))
        engine.add_tick(Tick(base + i * 2 + 1, 19.48, 100, f"C{i}", Side.BUY))
    st = engine.get_state()
    if engine._now() == base + 11:
        ok("Relógio do engine = timestamp do último tick")
    else:
        err(f"Relógio esperado {base + 11}, recebeu {engine._now()}")
    if st["flow_pct_sell"] > 80:
        ok(f"Pressão de fluxo calculada no tempo do pregão ({st['flow_pct_sell']:.1f}% venda)")
    else:
        err(f"Fluxo deveria ser vendedor no tempo do tick: {st['flow_pct_buy']}/{st['flow_pct_sell']}")
    if st["absorbed_levels"] and st["absorbed_levels"][0]["price"] == 19.50:
        ok("Absorção detectada com ticks antigos (janela no tempo do tick)")
    else:
        err(f"Absorção esperada em 19.50: {st['absorbed_levels']}")

    # Tick atrasado não volta o relógio
    engine.add_tick(Tick(base + 3, 19.49, 100, "ATRASADO", Side.BUY))
    if engine._now() == base + 11:
        ok("Tick fora de ordem não faz o relógio voltar")
    else:
        err("Relógio voltou com tick atrasado")

    sig = engine.get_signal()
    if abs(sig.timestamp - (base + 11)) < 1e-6:
        ok("Timestamp do sinal = tempo do pregão")
    else:
        err(f"Sinal com timestamp do relógio do PC: {sig.timestamp}")

    engine.reset()
    if engine._clock == 0.0:
        ok("Reset zera o relógio do engine")
    else:
        err("Reset deveria zerar o relógio")


def test_replay_leitura():
    print(f"\n{AMARELO}═══ TESTE 13: Leitura de CSV (formato próprio e Profit) ═══{RESET}")

    from replay.csv_ticks import ler_csv
    from dataclasses import fields
    tem_passiva = "passive_broker" in {f.name for f in fields(Tick)}

    # Formato do Fluxo Server
    arq = _arquivo_temp(
        "timestamp,preco,quantidade,agressor,corretora_agressora,corretora_passiva\n"
        "1760443200.125,5123.5,10,B,XP INC,BTG PACTUAL\n"
        "1760443200.250,5123,3,S,UBS,\n"
        "2026-10-14T10:00:01.500,5123.5,7,C,\"ITAU, SA\",GENIAL\n")
    try:
        r = ler_csv(arq)
    finally:
        os.unlink(arq)
    t = r.ticks
    if len(t) == 3 and t[0].price == 5123.5 and t[0].qty == 10 and t[0].side == Side.BUY \
            and t[1].side == Side.SELL and t[0].broker == "XP INC" and t[2].broker == "ITAU, SA":
        ok("Formato próprio: preço, quantidade, lado e corretora lidos")
    else:
        err(f"Leitura do formato próprio incorreta: {t}")
    if abs(t[0].timestamp - 1760443200.125) < 1e-6:
        ok("Timestamp epoch com milissegundos preservado")
    else:
        err(f"Timestamp incorreto: {t[0].timestamp}")
    if tem_passiva:
        if t[0].passive_broker == "BTG PACTUAL":
            ok("Corretora passiva lida (Tick com passive_broker)")
        else:
            err(f"passive_broker incorreto: {t[0].passive_broker}")
    else:
        ok("Tick ainda sem passive_broker: leitura funciona sem o campo")

    # Exportação do Times & Trades do Profit: ';', vírgula decimal, mais novo primeiro
    arq = _arquivo_temp(
        "Times & Trades - PETR4\n"
        "Data;Compradora;Preço;Quantidade;Vendedora;Agressor\n"
        "14/10/2026 10:00:03,100;XP INC;5.124,00;1.000;UBS;Comprador\n"
        "14/10/2026 10:00:02,000;ITAU;5.123,50;5;BTG PACTUAL;Vendedor\n"
        "14/10/2026 10:00:01,500;GENIAL;5.123,50;2;CLEAR;Leilão\n"
        "14/10/2026 10:00:01,000;MODAL;5.123,00;3;SAFRA;Comprador\n",
        encoding="cp1252")
    try:
        r = ler_csv(arq)
    finally:
        os.unlink(arq)
    t = r.ticks
    if r.separador == ";" and len(t) == 3 and r.linhas_ignoradas == 1:
        ok("Profit: separador ';' e linha de leilão (sem agressor) ignorada")
    else:
        err(f"Leitura do Profit incorreta: sep={r.separador!r} ticks={len(t)} ign={r.linhas_ignoradas}")
    if [x.price for x in t] == [5123.0, 5123.5, 5124.0] and r.invertido:
        ok("Profit: vírgula decimal e ordem do mais novo para o mais antigo corrigida")
    else:
        err(f"Preços/ordem incorretos: {[x.price for x in t]}")
    if t[2].qty == 1000:
        ok("Profit: quantidade com separador de milhar (1.000)")
    else:
        err(f"Quantidade incorreta: {t[2].qty}")
    if t[1].side == Side.SELL and t[1].broker == "BTG PACTUAL" \
            and t[2].side == Side.BUY and t[2].broker == "XP INC":
        ok("Profit: corretora agressora tirada da Compradora/Vendedora conforme o agressor")
    else:
        err(f"Agressora incorreta: {t[1]} / {t[2]}")
    if tem_passiva and t[2].passive_broker != "UBS":
        err(f"Passiva do Profit incorreta: {t[2].passive_broker}")
    if abs(t[2].timestamp - t[0].timestamp - 2.1) < 1e-3:
        ok("Profit: hora com milissegundos depois da vírgula")
    else:
        err(f"Diferença de tempo incorreta: {t[2].timestamp - t[0].timestamp}")

    # Data e hora em colunas separadas, separador ','
    arq = _arquivo_temp('Data,Hora,Preço,Qtd,Agressor,Corretora\n'
                        '14/10/2026,10:00:00.500,"5123,5",4,V,UBS\n')
    try:
        t = ler_csv(arq).ticks
    finally:
        os.unlink(arq)
    if len(t) == 1 and t[0].price == 5123.5 and t[0].side == Side.SELL and t[0].broker == "UBS":
        ok("Data e Hora em colunas separadas; cabeçalhos reconhecidos de forma flexível")
    else:
        err(f"Leitura com Data/Hora separadas incorreta: {t}")


def test_replay_gravacao():
    print(f"\n{AMARELO}═══ TESTE 14: Gravação → leitura (ida e volta) ═══{RESET}")

    import tempfile
    from replay.csv_ticks import GravadorTicks, ler_ticks, criar_tick

    originais = [
        criar_tick(1760443200.125, 5123.5, 10, "XP INC", Side.BUY, "UBS"),
        criar_tick(1760443200.987, 5123.0, 3, "MORGAN, STANLEY", Side.SELL, ""),
        criar_tick(1760443201.5, 5122.5, 1500, "BTG PACTUAL", Side.SELL, "ITAU"),
    ]
    fd, caminho = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    os.unlink(caminho)
    try:
        engine = FlowEngine("PETR4", EngineConfig(tick_size=0.5))
        grav = GravadorTicks(caminho)
        engine.add_tick = grav.envolver(engine.add_tick)
        for t in originais:
            engine.add_tick(t)
        grav.fechar()
        if engine.get_state()["tick_count"] == 3 and grav.gravados == 3:
            ok("Gravador entrega os ticks ao engine e grava os 3")
        else:
            err(f"Gravador falhou: engine={engine.get_state()['tick_count']} gravados={grav.gravados}")
        lidos = ler_ticks(caminho)
    finally:
        if os.path.exists(caminho):
            os.unlink(caminho)

    iguais = len(lidos) == len(originais) and all(
        abs(a.timestamp - b.timestamp) < 1e-6 and a.price == b.price and a.qty == b.qty
        and a.side == b.side and a.broker == b.broker
        and getattr(a, "passive_broker", "") == getattr(b, "passive_broker", "")
        for a, b in zip(originais, lidos))
    if iguais:
        ok("Ida e volta preserva tempo (ms), preço, quantidade, lado e corretoras")
    else:
        err(f"Ida e volta diferente:\n{originais}\n{lidos}")


def test_replay_deterministico():
    print(f"\n{AMARELO}═══ TESTE 15: Replay determinístico + mini backtest + grid ═══{RESET}")

    from replay.csv_ticks import ler_ticks
    from replay.player import (executar_replay, interpretar_grid, rodar_grid,
                               avaliar_sinais, SinalReplay)

    def rodar():
        cfg = EngineConfig(tick_size=0.01, flow_pct_threshold=65.0, min_confidence=0.60)
        sinais, player = executar_replay(FlowEngine("PETR4", cfg), ler_ticks(_EXEMPLO),
                                         velocidade=0, alvo_ticks=4, horizonte_sec=300)
        return [(s.indice, s.sinal, s.padrao, s.preco, s.stop, s.confianca, s.resultado,
                 s.mfe_ticks, s.mae_ticks) for s in sinais], player

    a, player = rodar()
    b, _ = rodar()
    info(f"{player.ticks_entregues} ticks, {len(a)} sinais")
    if a and a == b:
        ok(f"Duas execuções → os mesmos {len(a)} sinais e resultados")
    else:
        err("Replay não é determinístico")
    padroes = {x[2] for x in a}
    if "Exaustão" in padroes and "Absorção" in padroes:
        ok("Exemplo PETR4 gera sinais de exaustão e de absorção")
    else:
        err(f"Exemplo deveria gerar exaustão e absorção: {padroes}")

    # Mini backtest num caso controlado: BUY @ 100, stop 99, tick 0.5, alvo 2 ticks
    ticks = [Tick(0, 100.0, 1, "", Side.BUY), Tick(1, 100.5, 1, "", Side.BUY),
             Tick(2, 101.0, 1, "", Side.BUY), Tick(3, 98.0, 1, "", Side.SELL)]
    s = SinalReplay(0, 0, "BUY", "Exaustão", 100.0, 99.0, 0.7, "", "")
    s2 = SinalReplay(1, 1, "SELL", "Absorção", 100.5, 101.0, 0.7, "", "")
    avaliar_sinais([s, s2], ticks, 0.5, alvo_ticks=2, horizonte_sec=60)
    if s.resultado == "alvo" and s.mfe_ticks == 2 and s.mae_ticks == 4:
        ok("BUY: alvo antes do stop; MFE 2 / MAE 4 ticks no horizonte")
    else:
        err(f"Backtest BUY incorreto: {s}")
    if s2.resultado == "stop":
        ok("SELL: stop tocado antes do alvo")
    else:
        err(f"Backtest SELL incorreto: {s2}")

    grade = interpretar_grid(["exhaustion_vol_ratio=0.3,0.6", "exhaustion_reversal_ticks=3,4"])
    if grade == {"exhaustion_vol_ratio": [0.3, 0.6], "exhaustion_reversal_ticks": [3, 4]} \
            and isinstance(grade["exhaustion_reversal_ticks"][0], int):
        ok("Grid interpretado com os tipos do EngineConfig")
    else:
        err(f"Grid interpretado errado: {grade}")
    try:
        interpretar_grid(["parametro_que_nao_existe=1,2"])
        err("Parâmetro inexistente deveria dar erro")
    except ValueError:
        ok("Parâmetro inexistente no grid é recusado")
    linhas = rodar_grid(ler_ticks(_EXEMPLO), grade, EngineConfig(tick_size=0.01),
                        asset="PETR4", alvo_ticks=4, horizonte_sec=300)
    if len(linhas) == 4 and all("taxa_acerto" in l and "n_sinais" in l for l in linhas):
        resumo = [(l["exhaustion_vol_ratio"], l["exhaustion_reversal_ticks"],
                   l["n_sinais"], l["n_exaustao"]) for l in linhas]
        ok(f"Grid rodou 4 combinações (vol_ratio, reversal, sinais, exaustões): {resumo}")
    else:
        err(f"Grid incorreto: {linhas}")


def test_historico_limites():
    print(f"\n{AMARELO}═══ TESTE 16b: Histórico — limite de 30 dias da DLL ═══{RESET}")

    import tempfile
    from datetime import date
    from profitdll.historico import (validar_janela_historico, BaixadorHistorico,
                                     NL_HISTORY_PERIOD_LIMIT, NL_INVALID_ARGS, LIMITE_DIAS_HISTORICO)

    hoje = date(2026, 10, 16)
    try:
        validar_janela_historico(date(2026, 9, 16), hoje)
        ok(f"Início a {LIMITE_DIAS_HISTORICO} dias de hoje é aceito")
    except ValueError as e:
        err(f"Limite exato recusado: {e}")
    try:
        validar_janela_historico(date(2026, 9, 15), hoje)
        err("Início com mais de 30 dias não foi recusado")
    except ValueError as e:
        if "30 dias" in str(e):
            ok(f"Início com mais de 30 dias recusado antes de conectar: {e}")
        else:
            err(f"Mensagem não cita o limite: {e}")

    class DLLFalsa:
        def __init__(self, ret):
            self.ret, self.chamadas = ret, 0

        def GetHistoryTrades(self, *args):
            self.chamadas += 1
            return self.ret

    for ret, nome in ((NL_HISTORY_PERIOD_LIMIT, "NL_HISTORY_PERIOD_LIMIT"),
                      (NL_INVALID_ARGS, "NL_INVALID_ARGS")):
        baixador = BaixadorHistorico("PETR4", timeout_dia=1)
        baixador.dll = DLLFalsa(ret)
        with tempfile.TemporaryDirectory() as pasta:
            resumo = baixador.baixar_periodo([date(2026, 10, 15)], pasta + "/{data}.csv",
                                             "09:00", "18:00", tentativas=3)
        if baixador.dll.chamadas == 1 and resumo["dias_falhos"] == ["2026-10-15"]:
            ok(f"{nome}: dia marcado como falho sem repetir a tentativa")
        else:
            err(f"{nome}: {baixador.dll.chamadas} chamadas, resumo {resumo}")


def test_historico_dll():
    print(f"\n{AMARELO}═══ TESTE 16: Histórico pela ProfitDLL → CSV do replay ═══{RESET}")

    import tempfile, shutil
    from datetime import date, datetime, timezone
    from profitdll.historico import (data_b3_para_epoch, dias_uteis, janela_do_dia,
                                     converter_trades, gravar_dia, caminho_do_dia,
                                     ler_data, ler_hora)
    from replay.csv_ticks import ler_csv

    # Data B3 (Brasília, UTC-3) com milissegundos → epoch
    esperado = datetime(2026, 10, 14, 13, 0, 0, 125000, tzinfo=timezone.utc).timestamp()
    if abs(data_b3_para_epoch("14/10/2026 10:00:00.125") - esperado) < 1e-6:
        ok("14/10/2026 10:00:00.125 (Brasília) = 13:00:00.125 UTC, com ms")
    else:
        err(f"Conversão de data B3 errada: {data_b3_para_epoch('14/10/2026 10:00:00.125')}")
    if abs(data_b3_para_epoch("14/10/2026 10:00:00") - (esperado - 0.125)) < 1e-6:
        ok("Data sem milissegundos também é aceita")
    else:
        err("Data sem milissegundos convertida errado")
    for ruim in ("2026-10-14 10:00:00", "10/14/2026 10:00:00", "", "14/10/2026"):
        try:
            data_b3_para_epoch(ruim)
            err(f"Data fora do formato deveria falhar: {ruim!r}")
        except ValueError:
            pass
    ok("Datas fora do formato DD/MM/YYYY HH:mm:SS.ZZZ são recusadas")

    # Janela da requisição no formato estrito da DLL (strftime, com zeros)
    if janela_do_dia(date(2026, 3, 5)) == ("05/03/2026 09:00:00", "05/03/2026 18:35:00") \
            and janela_do_dia(date(2026, 3, 5), "9:30", "17:00:00") == \
            ("05/03/2026 09:30:00", "05/03/2026 17:00:00"):
        ok("Janela do dia: '%d/%m/%Y %H:%M:%S' com zeros à esquerda")
    else:
        err(f"Janela do dia incorreta: {janela_do_dia(date(2026, 3, 5))}")
    try:
        janela_do_dia(date(2026, 3, 5), "18:00:00", "09:00:00")
        err("Hora final antes da inicial deveria falhar")
    except ValueError:
        ok("Hora final antes da inicial é recusada")
    if ler_data("2026-10-01") == ler_data("01/10/2026") == date(2026, 10, 1) \
            and ler_hora("9:05") == "09:05:00":
        ok("Datas AAAA-MM-DD / DD/MM/AAAA e horas HH:MM[:SS] da linha de comando")
    else:
        err("Leitura de data/hora da linha de comando incorreta")

    # Dias úteis: 01/10/2026 (quinta) a 10/10/2026 (sábado)
    dias = dias_uteis(date(2026, 10, 1), date(2026, 10, 10))
    esperados = [date(2026, 10, d) for d in (1, 2, 5, 6, 7, 8, 9)]
    if dias == esperados:
        ok(f"Dias úteis entre 01/10 e 10/10: {[d.day for d in dias]} (sem sáb/dom)")
    else:
        err(f"Dias úteis incorretos: {dias}")
    if dias_uteis(date(2026, 10, 3), date(2026, 10, 4)) == []:
        ok("Fim de semana sozinho → nenhum dia")
    else:
        err("Fim de semana deveria dar lista vazia")
    try:
        dias_uteis(date(2026, 10, 10), date(2026, 10, 1))
        err("Data final antes da inicial deveria falhar")
    except ValueError:
        ok("Data final antes da inicial é recusada")
    if caminho_do_dia("historico/petr4_{data}.csv", date(2026, 10, 1)) == "historico/petr4_2026-10-01.csv" \
            and caminho_do_dia("h/{asset}_{data}.csv", date(2026, 10, 1), "PETR4") == \
            "h/PETR4_2026-10-01.csv":
        ok("Nome do arquivo por dia: {data} → AAAA-MM-DD, {asset} → ticker")
    else:
        err("caminho_do_dia incorreto")

    # Tuplas como o callback acumula, fora de ordem e com sujeira
    # (data, tradeNumber, preço, volume R$, qtd, comprador, vendedor, tradeType)
    nomes = {3: "XP INC", 8: "UBS", 72: "BRADESCO"}
    brutos = [
        ("14/10/2026 10:00:01.500", 103, 5401.0, 0.0, 5, 3, 8, 3),      # venda: agressor UBS
        ("14/10/2026 10:00:00.250", 101, 5400.5, 0.0, 2, 3, 8, 2),      # compra: agressor XP
        ("14/10/2026 10:00:00.250", 100, 5400.0, 0.0, 1, 72, 3, 2),     # mesmo ms, nº menor
        ("14/10/2026 10:00:00.900", 102, 5400.5, 0.0, 10, 3, 8, 4),     # leilão → ignorado
        ("14/10/2026 10:00:01.000", 104, 5400.5, 0.0, 3, 3, 8, 1),      # cross → ignorado
        ("14/10/2026 10:00:00.250", 101, 5400.5, 0.0, 2, 3, 8, 2),      # duplicado
        ("13/10/2026 17:59:59.000", 99, 5390.0, 0.0, 1, 3, 8, 2),       # outro dia
        ("14-10-2026 10:00:02", 105, 5401.0, 0.0, 1, 3, 8, 2),          # data inválida
        ("14/10/2026 10:00:03.000", 106, 5401.5, 0.0, 7, 8, 72, 2),     # compra: agressor UBS
    ]
    res = converter_trades(brutos, nomes, date(2026, 10, 14))
    if (res.recebidos, res.ignorados, res.duplicados, res.fora_do_dia, res.invalidos) \
            == (9, 2, 1, 1, 1) and res.numeros_duplicados == [101]:
        ok("Contagem: 9 recebidos, 2 sem agressão, 1 duplicado (nº 101), "
           "1 de outro dia, 1 data inválida")
    else:
        err(f"Contagem incorreta: {res}")
    seq = [(t.price, t.qty, t.side, t.broker, getattr(t, "passive_broker", ""))
           for t in res.ticks]
    if seq == [(5400.0, 1, Side.BUY, "BRADESCO", "XP INC"),
               (5400.5, 2, Side.BUY, "XP INC", "UBS"),
               (5401.0, 5, Side.SELL, "UBS", "XP INC"),
               (5401.5, 7, Side.BUY, "UBS", "BRADESCO")]:
        ok("Ordem cronológica por (timestamp, tradeNumber), agressora/passiva pelo TradeType")
    else:
        err(f"Ticks convertidos incorretos: {seq}")
    ts = [t.timestamp for t in res.ticks]
    if ts == sorted(ts) and abs(ts[0] - (esperado + 0.125)) < 1e-6:
        ok("Timestamps em epoch crescentes, com milissegundos")
    else:
        err(f"Timestamps incorretos: {ts}")

    # Gravação de um dia fake e leitura de volta com o leitor do replay
    pasta = tempfile.mkdtemp()
    try:
        caminho = caminho_do_dia(os.path.join(pasta, "sub", "petr4_{data}.csv"), date(2026, 10, 14))
        n = gravar_dia(caminho, res.ticks)
        sobras = os.listdir(os.path.dirname(caminho))
        leitura = ler_csv(caminho)
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    if n == 4 and sobras == ["petr4_2026-10-14.csv"]:
        ok("Dia gravado na pasta criada, sem sobrar o arquivo .parcial")
    else:
        err(f"Gravação do dia incorreta: n={n} arquivos={sobras}")
    iguais = len(leitura.ticks) == len(res.ticks) and leitura.linhas_ignoradas == 0 and all(
        abs(a.timestamp - b.timestamp) < 1e-6 and a.price == b.price and a.qty == b.qty
        and a.side == b.side and a.broker == b.broker
        and getattr(a, "passive_broker", "") == getattr(b, "passive_broker", "")
        for a, b in zip(res.ticks, leitura.ticks))
    if iguais and not leitura.invertido:
        ok("Leitor do replay lê o dia baixado igual ao que foi gravado")
    else:
        err(f"Leitura do dia baixado diferente:\n{res.ticks}\n{leitura.ticks}")


def test_fuso_csv():
    print(f"\n{AMARELO}═══ TESTE 18: Horário do CSV no fuso da B3 (independe do PC) ═══{RESET}")

    import tempfile
    from datetime import datetime, timezone
    from replay.csv_ticks import ler_csv

    fd, arq = tempfile.mkstemp(suffix=".csv")
    os.close(fd)
    with open(arq, "w", encoding="utf-8") as f:
        f.write("Data;Preço;Quantidade;Agressor\n"
                "14/10/2026 10:00:00,125;37,40;100;Comprador\n"
                "2026-10-14T10:00:01-03:00;37,41;100;Vendedor\n"
                "2026-10-14T13:00:02Z;37,42;100;Comprador\n")
    try:
        t = ler_csv(arq).ticks
    finally:
        os.unlink(arq)
    esperado = datetime(2026, 10, 14, 13, 0, 0, 125000, tzinfo=timezone.utc).timestamp()
    if abs(t[0].timestamp - esperado) < 1e-6:
        ok("Data sem fuso é lida como horário de Brasília (13:00:00.125 UTC), em qualquer PC")
    else:
        err(f"Data sem fuso lida no fuso do PC: {t[0].timestamp} != {esperado}")
    if abs(t[1].timestamp - (esperado + 0.875)) < 1e-6 and abs(t[2].timestamp - (esperado + 1.875)) < 1e-6:
        ok("Data ISO com fuso explícito (-03:00 ou Z) é respeitada")
    else:
        err(f"Fuso explícito ignorado: {[x.timestamp - esperado for x in t]}")

    from replay.player import _hora
    if _hora(esperado).endswith("10:00:00.125"):
        ok("Relatório do replay mostra a hora da B3")
    else:
        err(f"Hora do relatório fora do fuso da B3: {_hora(esperado)}")


def test_argumentos_cli():
    print(f"\n{AMARELO}═══ TESTE 19: Opções da linha de comando valem sobre o conhecimento dos vídeos ═══{RESET}")

    from types import SimpleNamespace
    from config.cli_overrides import aplicar_argumentos
    from config.conhecimento_videos import aplicar_conhecimento

    engine = FlowEngine("PETR4", EngineConfig())
    aplicar_conhecimento(engine)
    args = SimpleNamespace(flow_window=None, flow_pct=70.0, iceberg_min=5, tick_size=0.01, min_confidence=0.75)
    aplicar_argumentos(engine.cfg, args)
    c = engine.cfg
    if (c.flow_pct_threshold, c.iceberg_min_renewals, c.min_confidence) == (70.0, 5, 0.75):
        ok("--flow-pct, --iceberg-min e --min-confidence não são sobrescritos")
    else:
        err(f"Opções sobrescritas: {c.flow_pct_threshold}, {c.iceberg_min_renewals}, {c.min_confidence}")

    engine2 = FlowEngine("PETR4", EngineConfig())
    aplicar_conhecimento(engine2)
    antes = (engine2.cfg.flow_pct_threshold, engine2.cfg.min_confidence, engine2.cfg.flow_window_sec)
    aplicar_argumentos(engine2.cfg, SimpleNamespace(flow_window=None, flow_pct=None, iceberg_min=None,
                                                    tick_size=0.01, min_confidence=None))
    if (engine2.cfg.flow_pct_threshold, engine2.cfg.min_confidence, engine2.cfg.flow_window_sec) == antes:
        ok("Opção não informada mantém o valor do conhecimento/padrão")
    else:
        err("Opção não informada alterou a configuração")


def test_desempenho_estado():
    print(f"\n{AMARELO}═══ TESTE 20: Janelas podadas (pregão longo) e últimos negócios no estado ═══{RESET}")

    import random
    random.seed(7)
    engine = FlowEngine("PETR4", EngineConfig())
    corretoras = [f"C{i}" for i in range(40)]
    ts, p = 1_000_000.0, 37.40
    inicio = time.perf_counter()
    for _ in range(12000):
        ts += random.uniform(0.05, 0.8)
        p = round(p + random.choice([-0.01, 0, 0, 0.01]), 2)
        engine.add_tick(Tick(ts, p, random.choice([100, 200, 500]), random.choice(corretoras),
                             random.choice([Side.BUY, Side.SELL]), passive_broker=random.choice(corretoras)))
    dur = time.perf_counter() - inicio
    toques = sum(len(d) for d in engine._price_touches.values())
    urg = sum(len(d) for d in engine._urgency_log.values())
    janela = engine.cfg.absorption_window_sec
    recentes = [t for t in engine._ticks if t.timestamp >= ts - janela]
    if toques <= len(recentes) + 1 and urg <= len(recentes) * 2:
        ok(f"Toques e urgência guardam só a janela ({toques} toques, {urg} urgência)")
    else:
        err(f"Histórico não podado: {toques} toques, {urg} urgência para {len(recentes)} negócios na janela")
    info(f"12.000 negócios em {dur:.1f}s ({12000 / dur:,.0f}/s)")
    if dur < 60:
        ok("Desempenho não degrada com o tamanho do pregão")
    else:
        err(f"Lento demais: {dur:.1f}s")

    estado = engine.get_state()
    ult = estado.get("recent_trades")
    if ult and len(ult) == 10 and ult[-1]["price"] == p and ult[-1]["timestamp"] == ts \
            and set(ult[-1]) >= {"timestamp", "price", "qty", "side", "broker", "passive_broker"}:
        ok("get_state() traz os 10 últimos negócios, do mais antigo ao mais novo")
    else:
        err(f"recent_trades ausente ou incompleto: {ult[-1:] if ult else ult}")


def test_api_grafico_tt_book():
    print(f"\n{AMARELO}═══ TESTE 21: API de gráfico, T&T e book ═══{RESET}")

    import json
    import tempfile
    import urllib.error
    import urllib.request
    import api.server as srv
    from api.server import FlowServer

    porta = 15571
    base = f"http://127.0.0.1:{porta}"

    def get(rota):
        try:
            with urllib.request.urlopen(base + rota, timeout=3) as r:
                return r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Content-Type", "")

    def get_json(rota):
        cod, corpo, _ = get(rota)
        return cod, json.loads(corpo)

    def post(rota, dados):
        req = urllib.request.Request(base + rota, data=json.dumps(dados).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read())

    engine = FlowEngine("PETR4", EngineConfig())
    server = FlowServer(engine, host="127.0.0.1", port=porta)
    server.start()
    time.sleep(0.3)
    try:
        # Book antes de qualquer snapshot
        cod, b = get_json("/book")
        if cod == 200 and b["depth"] == "none" and b["bids"] == [] and b["updated"] is None:
            ok("GET /book sem dados: depth none")
        else:
            err(f"/book inicial incorreto: {b}")

        # Negócios: candles de 15 s em 990, 1005 e 1020; de 60 s em 960 e 1020
        t0 = 1000.0
        negocios = [(t0 + 1, 37.40, 100, "C"), (t0 + 5, 37.45, 200, "V"), (t0 + 14, 37.42, 300, "C"),
                    (t0 + 16, 37.41, 100, "V"), (t0 + 31, 37.50, 500, "C")]
        for ts, p, q, lado in negocios:
            post("/tick", {"timestamp": ts, "price": p, "qty": q, "broker": "XP INC", "side": lado})

        cod, c15 = get_json("/candles?tf=15")
        cs = c15["candles"]
        primeiro = cs[0] if cs else {}
        seg = cs[1] if len(cs) > 1 else {}
        if cod == 200 and c15["tf"] == 15 and [c["time"] for c in cs] == [990, 1005, 1020] \
                and (primeiro["open"], primeiro["close"], primeiro["volume"], primeiro["buy"]) == (37.40, 37.40, 100, 100) \
                and (seg["open"], seg["high"], seg["low"], seg["close"]) == (37.45, 37.45, 37.41, 37.41) \
                and (seg["volume"], seg["buy"], seg["sell"]) == (600, 300, 300):
            ok("Candles de 15 s com OHLC, volume e lado agressor")
        else:
            err(f"Candles de 15 s incorretos: {cs}")
        cod, c60 = get_json("/candles?tf=60")
        if [c["time"] for c in c60["candles"]] == [960, 1020] and c60["candles"][0]["volume"] == 700:
            ok("Candles de 60 s agregam o mesmo pregão")
        else:
            err(f"Candles de 60 s incorretos: {c60}")
        cod, cs2 = get_json("/candles?tf=15&since=1005")
        if [c["time"] for c in cs2["candles"]] == [1005, 1020]:
            ok("since filtra candles a partir do horário pedido")
        else:
            err(f"since ignorado: {cs2}")
        # Negócio atrasado cai no candle dele sem mudar o fechamento
        post("/tick", {"timestamp": t0 + 0.5, "price": 37.30, "qty": 100, "broker": "UBS", "side": "V"})
        _, c15b = get_json("/candles?tf=15")
        p0 = c15b["candles"][0]
        if (p0["open"], p0["low"], p0["close"]) == (37.30, 37.30, 37.40):
            ok("Negócio fora de ordem atualiza abertura/mínima, não o fechamento")
        else:
            err(f"Negócio atrasado tratado errado: {p0}")
        cod, _ = get_json("/candles?tf=42")
        if cod == 400:
            ok("Timeframe inválido → 400")
        else:
            err(f"tf inválido devolveu {cod}")

        cod, tr = get_json("/trades?limit=3")
        t = tr["trades"]
        if cod == 200 and len(t) == 3 and t[-1]["price"] == 37.30 and t[0]["timestamp"] == t0 + 16 \
                and set(t[0]) == {"timestamp", "price", "qty", "side", "broker", "passive_broker"}:
            ok("GET /trades?limit=3 devolve os 3 últimos, do mais antigo ao mais novo")
        else:
            err(f"/trades incorreto: {t}")
        _, tr_all = get_json("/trades")
        if len(tr_all["trades"]) == 6:
            ok("GET /trades sem limit devolve o histórico disponível (até 200)")
        else:
            err(f"/trades sem limit: {len(tr_all['trades'])}")

        # Book: topo (1 nível por lado) e depois profundidade completa
        post("/book", {"levels": [{"price": 37.29, "qty": 500, "side": "C"},
                                  {"price": 37.31, "qty": 400, "side": "V"}]})
        _, b = get_json("/book")
        if b["depth"] == "top" and b["bids"][0]["price"] == 37.29 and b["asks"][0]["price"] == 37.31:
            ok("Book com 1 nível por lado → depth top")
        else:
            err(f"Book topo incorreto: {b}")
        post("/book", {"levels": [{"price": 37.29, "qty": 500, "side": "C", "broker": "ITAU"},
                                  {"price": 37.28, "qty": 900, "side": "C", "broker": "XP INC"},
                                  {"price": 37.31, "qty": 400, "side": "V"},
                                  {"price": 37.32, "qty": 100, "side": "V"}]})
        _, b = get_json("/book")
        if b["depth"] == "full" and [x["price"] for x in b["bids"]] == [37.29, 37.28] \
                and [x["price"] for x in b["asks"]] == [37.31, 37.32] and b["bids"][1]["broker"] == "XP INC":
            ok("Book com profundidade → depth full; bids decrescentes, asks crescentes")
        else:
            err(f"Book completo incorreto: {b}")

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
    finally:
        server.stop()

    # Sinais: só as trocas entram no registro (direto no engine, com um pregão conhecido; sem o corte calibrado)
    e = FlowEngine("PETR4", EngineConfig(defesa_iceberg_vol_sinal={}, defesa_iceberg_vol_sinal_padrao=0))
    vistos, ultima = [], None
    itau = ubs = 0
    for i in range(60):
        lado = Side.SELL if i % 5 else Side.BUY
        preco = 37.40 if lado == Side.SELL else 37.41
        e.add_tick(Tick(2000 + i, preco, 500, f"C{i % 3}", lado,
                        passive_broker="ITAU" if lado == Side.SELL else "UBS"))
        # O sinal de iceberg só nasce quando a passiva repõe o lote (2 giros).
        if lado == Side.SELL and itau < 2:
            itau += 1
            e.renovacao("ITAU", "compra", 37.40, 2000 + i)
        elif lado == Side.BUY and ubs < 2:
            ubs += 1
            e.renovacao("UBS", "venda", 37.41, 2000 + i)
        s = e.get_signal()
        chave = (s.signal, s.pattern, s.stop_price) if s.signal in (Signal.BUY, Signal.SELL) else None
        if chave and chave != ultima:
            vistos.append(chave)
        ultima = chave
    reg = e.get_signals()
    if vistos and [(r["signal"], r["pattern"], r["stop_price"]) for r in reg] == \
            [(c[0].value, c[1].value, c[2]) for c in vistos]:
        ok(f"/signals registra só as trocas de sinal ({len(reg)} de 60 negócios)")
    else:
        err(f"Registro de sinais diferente das trocas: {reg} vs {vistos}")
    if e.get_signals(since=reg[-1]["timestamp"]) == reg[-1:]:
        ok("since filtra os sinais")
    else:
        err("since não filtrou os sinais")
    e.reset()
    if e.get_signals() == [] and e.get_candles(60) == [] and e.get_trades() == [] and e.get_book()["depth"] == "none":
        ok("reset limpa candles, negócios, sinais e book")
    else:
        err("reset não limpou os registros da API")


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

    g0 = e.get_state()["geracao"]
    e.reset()
    if e.get_resumo()["ultimo"] is None and e.get_resumo()["saldo_corretoras"] == []:
        ok("reset zera o resumo")
    else:
        err(f"resumo depois do reset: {e.get_resumo()}")
    # Com o mercado rodando, o /state seguinte já tem negócios: a tela só percebe o reset pela geração
    e.add_tick(Tick(2000, 11.0, 100, "A", Side.BUY))
    if e.get_state()["geracao"] == g0 + 1:
        ok("Cada reset avança a geração do /state (a tela limpa mesmo com negócios novos)")
    else:
        err(f"geração: {g0} → {e.get_state()['geracao']}")


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

        # Mesmo instante (resolução do relógio do Windows) e fora de ordem: o seq não perde nenhum
        h2 = LogMemoria()
        mesmo = time.time()
        for i, criado in enumerate((mesmo, mesmo, mesmo - 1)):
            r = logging.LogRecord("TesteSeq", logging.INFO, __file__, 0, f"msg {i}", None, None)
            r.created = criado
            h2.emit(r)
        primeiro = h2.registros()[0]["seq"]
        resto = [x["msg"] for x in h2.registros(apos=primeiro)]
        if resto == ["msg 1", "msg 2"]:
            ok("apos=seq devolve registros com o mesmo horário e fora de ordem")
        else:
            err(f"apos: {resto}")
        with urllib.request.urlopen(base + f"/log?apos=0", timeout=3) as r:
            corpo = json.loads(r.read())
        maior = max(x["seq"] for x in corpo["registros"])
        if corpo.get("ultimo_seq") == maior:
            ok("GET /log?apos=N responde com o seq de cada registro e o último seq do servidor")
        else:
            err(f"/log sem seq/ultimo_seq: {corpo.get('ultimo_seq')} vs {maior}")
        # Servidor reiniciado: o seq recomeça; a tela percebe porque ultimo_seq < o que ela já viu
        with urllib.request.urlopen(base + f"/log?apos={maior + 1000}", timeout=3) as r:
            corpo = json.loads(r.read())
        if corpo["registros"] == [] and corpo["ultimo_seq"] < maior + 1000:
            ok("apos além do último seq: lista vazia + ultimo_seq menor (a tela recomeça o log)")
        else:
            err(f"apos além do fim: {corpo}")
    finally:
        server.stop()


def test_api_health_modo():
    print(f"\n{AMARELO}═══ TESTE 24: /health com modo, fonte e tick ═══{RESET}")

    import json
    import urllib.request
    from api.server import FlowServer

    porta = 15574
    for kwargs, esperado in (({}, ("manual", None)),
                             ({"modo": "replay", "fonte": "exemplo_petr4.csv"}, ("replay", "exemplo_petr4.csv"))):
        engine = FlowEngine("PETR4", EngineConfig(tick_size=0.01))
        server = FlowServer(engine, host="127.0.0.1", port=porta, **kwargs)
        server.start()
        time.sleep(0.3)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{porta}/health", timeout=3) as r:
                h = json.loads(r.read())
        finally:
            server.stop()
        if (h["modo"], h["fonte"]) == esperado and h["tick_size"] == 0.01 and h["asset"] == "PETR4":
            ok(f"/health → modo {h['modo']}, fonte {h['fonte']}, tick {h['tick_size']}")
        else:
            err(f"/health: {h}")
        porta += 1


def test_main_fonte_dll():
    print(f"\n{AMARELO}═══ TESTE 27: main.py — ponte da DLL fica registrada mesmo se a 1ª conexão falhar ═══{RESET}")

    import argparse
    import main as programa

    class PonteQueFalha:
        def __init__(self):
            self.paradas = 0

        def start(self):
            return False

        def stop(self):
            self.paradas += 1

    class ServidorFalso:
        def __init__(self):
            self.dll = None

        def registrar_dll(self, ponte):
            self.dll = ponte

    ponte, servidor = PonteQueFalha(), ServidorFalso()
    original = programa.setup_dll_mode
    programa.setup_dll_mode = lambda engine, args: ponte
    try:
        devolvida = programa.iniciar_fonte_dll(None, argparse.Namespace(), servidor)
    finally:
        programa.setup_dll_mode = original
    if devolvida is ponte and servidor.dll is ponte:
        ok("Falha na 1ª conexão: a ponte continua registrada e é devolvida (o Ctrl+C chama stop() nela)")
    else:
        err(f"ponte perdida: devolvida={devolvida} registrada={servidor.dll}")


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
            self.ocupado = False
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

    server = FlowServer(FlowEngine("PETR4", EngineConfig(tick_size=0.5)),
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

        ponte.ocupado = True                     # conexão inicial do main.py ainda em curso
        cod, corpo = post("/dll/reconectar")
        ponte.ocupado = False
        if cod == 409 and "conex" in corpo["error"] and ponte.chamadas == ["stop", "start"]:
            ok("Ponte ocupada (conexão em curso) → 409, sem mexer no processo")
        else:
            err(f"ponte ocupada: {cod} {corpo} {ponte.chamadas}")

        ponte.ok = False
        post("/dll/reconectar")
        rec = esperar_fim()
        if rec["resultado"] == "falhou: senha inválida":
            ok("Falha aparece com o motivo vindo de motivo_falha")
        else:
            err(f"falha: {rec}")

        # Defesa em profundidade: um motivo com a credencial dentro sai mascarado no /state
        antigo = os.environ.get("PROFITDLL_USER")
        os.environ["PROFITDLL_USER"] = "eu@exemplo.com"
        try:
            ponte.stats = lambda: {"conectado": False, "motivo_falha": "login eu@exemplo.com recusado"}
            ponte.motivo_falha = "login eu@exemplo.com recusado"
            post("/dll/reconectar")
            esperar_fim()
            with urllib.request.urlopen(base + "/state", timeout=3) as r:
                texto = r.read().decode()
            if "eu@exemplo.com" not in texto and "•••" in texto:
                ok("motivo_falha e resultado da reconexão saem mascarados no /state")
            else:
                err(f"/state vazou a credencial: {texto[-300:]}")
        finally:
            if antigo is None:
                os.environ.pop("PROFITDLL_USER", None)
            else:
                os.environ["PROFITDLL_USER"] = antigo
    finally:
        server.stop()


FILHO_FALSO = r'''
import sys, json, time, threading
modo = sys.argv[1]
def env(m):
    sys.stdout.write(json.dumps(m) + "\n"); sys.stdout.flush()
env({"tipo": "log", "nivel": "INFO", "origem": "ProfitDLL", "msg": "filho falso: " + modo})
if modo == "falha":
    env({"tipo": "inicio", "ok": False, "motivo": "senha inválida"}); sys.exit(0)
if modo == "lento":                 # login demorado (a conexão inicial ainda em curso)
    time.sleep(1.5)
if modo == "mudo":                  # nunca responde e ignora o "stop"
    time.sleep(60); sys.exit(0)
env({"tipo": "inicio", "ok": True})
if modo == "morre":
    time.sleep(0.3); sys.exit(3)
for i in range(3):
    env({"tipo": "tick", "ts": 1000.0 + i, "preco": 5078.5, "qtd": 1 + i, "corretora": "XP", "lado": "compra", "passiva": "UBS"})
env({"tipo": "book", "ts": 1003.0, "niveis": [[5078.0, 10, "compra"], [5078.5, 7, "venda"]]})
parar = threading.Event()
threading.Thread(target=lambda: (sys.stdin.readline(), parar.set()), daemon=True).start()
while not parar.wait(0.1):
    env({"tipo": "stats", "dados": {"conectado": True, "trades_recebidos": 3, "trades_ignorados": 1,
                                     "ignorados_por_tipo": {"RLP": 1}, "motivo_falha": None}})
'''


def test_dll_processo_filho():
    print(f"\n{AMARELO}═══ TESTE 26: ProfitDLL em processo filho ═══{RESET}")

    import io
    import json
    import logging
    import tempfile
    import threading
    from profitdll.processo import (PonteDLLProcesso, main_filho, tick_para_msg, msg_para_tick,
                                    book_para_msg, msg_para_book)

    t = Tick(1000.5, 5078.5, 3, "XP", Side.SELL, passive_broker="UBS")
    t2 = msg_para_tick(tick_para_msg(t))
    niveis = [BookLevel(5078.0, 10, "", Side.BUY, 1000.0), BookLevel(5078.5, 7, "", Side.SELL, 1000.0)]
    n2 = msg_para_book(book_para_msg(niveis, 1000.0))
    if (t2.timestamp, t2.price, t2.qty, t2.broker, t2.side, t2.passive_broker) == \
            (1000.5, 5078.5, 3, "XP", Side.SELL, "UBS") \
            and [(n.price, n.qty, n.side) for n in n2] == [(5078.0, 10, Side.BUY), (5078.5, 7, Side.SELL)]:
        ok("Tick e book vão e voltam pelo JSON do protocolo")
    else:
        err(f"ida e volta: {t2} {n2}")

    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "filho_falso.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write(FILHO_FALSO)

        def ponte(modo):
            p = PonteDLLProcesso("PETR4", timeout=5, comando=[sys.executable, script, modo])
            recebidos, livros = [], []
            p.on_tick, p.on_book = recebidos.append, livros.append
            return p, recebidos, livros

        logs = []
        captura = logging.Handler()
        captura.emit = lambda r: logs.append(r.getMessage())
        lg = logging.getLogger("ProfitDLL")
        lg.addHandler(captura)
        nivel_antigo = lg.level
        lg.setLevel(logging.INFO)
        try:
            p, recebidos, livros = ponte("ok")
            if p.start():
                for _ in range(40):
                    if len(recebidos) == 3 and livros and p.stats().get("trades_recebidos") == 3:
                        break
                    time.sleep(0.05)
            st = p.stats()
            if len(recebidos) == 3 and recebidos[2].qty == 3 and len(livros[0]) == 2 and st["conectado"]:
                ok("start() sobe o filho; ticks, book e stats chegam ao pai")
            else:
                err(f"filho ok: {len(recebidos)} ticks, {livros}, {st}")
            if "filho falso: ok" in logs:
                ok("Log do filho chega ao logging do pai (e ao /log)")
            else:
                err(f"log do filho não chegou: {logs}")

            p.stop()
            p.start()
            for _ in range(40):
                if p.stats().get("trades_recebidos") == 6:
                    break
                time.sleep(0.05)
            st = p.stats()
            if st["trades_recebidos"] == 6 and st["ignorados_por_tipo"] == {"RLP": 2}:
                ok("Reiniciar o filho soma os contadores do dia (6 recebidos, RLP 2)")
            else:
                err(f"contadores depois do reinício: {st}")
            p.stop()
            if not p.stats()["conectado"]:
                ok("stop() encerra o filho e marca desconectado")
            else:
                err("stop() deixou conectado")

            p, _, _ = ponte("falha")
            if not p.start() and p.motivo_falha == "senha inválida" and not p.stats()["conectado"]:
                ok("Filho que falha no login: start() False com o motivo")
            else:
                err(f"falha: {p.motivo_falha} {p.stats()}")

            p, _, _ = ponte("morre")
            p.start()
            time.sleep(1.0)
            st = p.stats()
            if not st["conectado"] and "processo da ProfitDLL encerrou" in (st["motivo_falha"] or ""):
                ok(f"Filho que morre vira desconectado: {st['motivo_falha']}")
            else:
                err(f"filho morto: {st}")
            p.stop()

            # Filho que nunca responde: start() desiste no prazo e mata o processo sem esperar o "stop"
            p = PonteDLLProcesso("PETR4", timeout=1, folga=0.5, comando=[sys.executable, script, "mudo"])
            inicio = time.time()
            conectou = p.start()
            gasto = time.time() - inicio
            if not conectou and "não respondeu" in (p.motivo_falha or "") and gasto < 5 \
                    and not p.stats()["processo"]["vivo"]:
                ok(f"Filho que não responde: start() desiste em {gasto:.1f} s e mata o processo")
            else:
                err(f"filho mudo: {conectou} {p.motivo_falha} {gasto:.1f}s {p.stats()['processo']}")

            # Conexão em curso: ocupado; um stop() concorrente espera o start() e encerra o filho certo
            p, _, _ = ponte("lento")
            resultado = {}
            th = threading.Thread(target=lambda: resultado.update(ok=p.start()))
            th.start()
            time.sleep(0.4)
            ocupado = p.ocupado and p.stats()["ocupado"]
            p.stop()
            th.join(10)
            if ocupado and resultado.get("ok") is True and not p.stats()["processo"]["vivo"] and not p.ocupado:
                ok("start()/stop() serializados: stop() no meio da conexão espera e encerra o filho certo")
            else:
                err(f"concorrência: ocupado={ocupado} {resultado} {p.stats()['processo']}")

            # main_filho com uma ponte falsa: protocolo no stdout, EOF no stdin chama bridge.stop()
            class PonteFalsaFilho:
                def __init__(self):
                    self.motivo_falha, self.parou, self.on_tick, self.on_book = None, False, None, None

                def start(self):
                    logging.getLogger("ProfitDLL").info("conectada (falsa)")
                    self.on_tick(Tick(1000.0, 10.0, 1, "XP", Side.BUY))
                    return True

                def stop(self):
                    self.parou = True

                def stats(self):
                    return {"conectado": not self.parou}

            criadas = []
            saida = io.StringIO()
            stdout_antes = sys.stdout
            codigo = main_filho(["--asset", "PETR4"], fabrica_ponte=lambda *a, **k: criadas.append(PonteFalsaFilho())
                                or criadas[-1], entrada=io.StringIO(""), saida=saida)
            msgs = [json.loads(linha) for linha in saida.getvalue().splitlines()]
            tipos = [m["tipo"] for m in msgs]
            if codigo == 0 and sys.stdout is stdout_antes and criadas and criadas[0].parou \
                    and {"tipo": "inicio", "ok": True, "motivo": None} in msgs and "tick" in tipos \
                    and any(m["tipo"] == "log" and m["msg"] == "conectada (falsa)" for m in msgs) \
                    and tipos[-1] == "stats":
                ok("main_filho: log, inicio, tick e stats no protocolo; EOF no stdin para a ponte")
            else:
                err(f"main_filho: código {codigo}, tipos {tipos}, parou {criadas and criadas[0].parou}")

            # Filho real (main_filho) cuja "DLL" escreve bytes nativos direto no fd 1, sem quebra de linha:
            # o protocolo não pode ser corrompido
            ruidoso = os.path.join(tmp, "filho_ruidoso.py")
            with open(ruidoso, "w", encoding="utf-8") as f:
                f.write(
                    "import os, sys\n"
                    f"sys.path.insert(0, {os.path.dirname(os.path.abspath(__file__))!r})\n"
                    "from core.engine import Tick, Side\n"
                    "from profitdll.processo import main_filho\n"
                    "class Ponte:\n"
                    "    def __init__(self, *a, **k): self.motivo_falha = None; self.on_tick = self.on_book = None\n"
                    "    def start(self):\n"
                    "        os.write(1, b'LIXO NATIVO SEM QUEBRA')\n"
                    "        self.on_tick(Tick(1000.0, 10.0, 7, 'XP', Side.BUY)); return True\n"
                    "    def stop(self): pass\n"
                    "    def stats(self): return {'conectado': True, 'trades_recebidos': 1}\n"
                    "sys.exit(main_filho(['--asset', 'PETR4'], fabrica_ponte=Ponte))\n")
            p = PonteDLLProcesso("PETR4", timeout=5, comando=[sys.executable, ruidoso])
            recebidos = []
            p.on_tick = recebidos.append
            conectou = p.start()
            for _ in range(40):
                if recebidos:
                    break
                time.sleep(0.05)
            p.stop()
            if conectou and [t.qty for t in recebidos] == [7]:
                ok("Saída nativa no stdout do filho não corrompe o protocolo")
            else:
                err(f"protocolo corrompido: start={conectou} ticks={recebidos} motivo={p.motivo_falha}")
        finally:
            lg.removeHandler(captura)
            lg.setLevel(nivel_antigo)


# ──────────────────────────────────────────────────────────────
# DEFESAS (core/defesas.py)
# ──────────────────────────────────────────────────────────────

def _pasta_aulas():
    """Sequências transcritas das aulas: só no computador do dono, fora do git."""
    pasta = os.environ.get("FLUXO_CENARIOS_AULAS") or os.path.join(
        os.path.expanduser("~"), "Documents", "fluxo-cursos", "estrategias", "medidas", "cenarios")
    return pasta if os.path.isdir(pasta) else None


def _hb3(data: str, hora: str) -> float:
    """Epoch de um horário da B3 (UTC-3): _hb3('27/11/2024', '10:14:14.100')."""
    from datetime import datetime, timedelta, timezone
    dt = datetime.strptime(f"{data} {hora}", "%d/%m/%Y %H:%M:%S.%f")
    return dt.replace(tzinfo=timezone(timedelta(hours=-3))).timestamp()


def test_defesas_ordem_original():
    print(f"\n{AMARELO}═══ TESTE 28: Defesas — ordem original (pedaços da mesma agressão) ═══{RESET}")
    from core.defesas import juntar_ordens

    t0 = 1_000_000.0
    ticks = [
        Tick(t0, 18.58, 3900, "ATIVA", Side.BUY, passive_broker="XP"),
        Tick(t0, 18.59, 9400, "ATIVA", Side.BUY, passive_broker="BTG"),
        Tick(t0, 18.60, 2000, "BTG", Side.BUY, passive_broker="UBS"),          # mesmo ms, outro agressor
        Tick(t0, 18.60, 6700, "ATIVA", Side.BUY, passive_broker="ATIVA"),      # volta a ser a ATIVA
        Tick(t0 + 0.111, 18.60, 400, "ATIVA", Side.BUY, passive_broker="XP"),  # 111 ms depois: outra ordem
        Tick(t0 + 0.2, 18.60, 100, "LEILAO", Side.NONE),
    ]
    obtido = [(o.corretora, o.lado, o.qtd, o.pedacos, o.preco_ini, o.preco_fim) for o in juntar_ordens(ticks)]
    esperado = [("ATIVA", "compra", 20000, 3, 18.58, 18.60), ("BTG", "compra", 2000, 1, 18.60, 18.60),
                ("ATIVA", "compra", 400, 1, 18.60, 18.60)]
    if obtido == esperado:
        ok("Mesma corretora, lado e ms = uma ordem; outro agressor ou outro ms = outra; sem agressor fica fora")
    else:
        err(f"Ordens originais erradas: {obtido}")

    pasta = _pasta_aulas()
    if not pasta:
        info("Sequências das aulas não encontradas (FLUXO_CENARIOS_AULAS): parte da aula 9393818 pulada")
        return
    from replay.csv_ticks import ler_ticks
    casos = {
        "leitura-tt_9393818_0600_negocios.csv": [
            ("XP", 1500), ("BGC Liquidez", 9500), ("Clear", 200), ("Itau", 1000), ("BTG", 10500),
            ("UBS", 1800), ("Santander", 3500), ("UBS", 2800), ("UBS", 400), ("CM Capital", 1000),
            ("UBS", 100), ("JP Morgan", 700)],
        "leitura-tt_9393818_1018_negocios.csv": [
            ("CM Capital", 200), ("Ideal", 400), ("Ativa", 20000), ("BTG", 2000)],
    }
    for nome, esp in casos.items():
        ordens = juntar_ordens(ler_ticks(os.path.join(pasta, nome)))
        if [(o.corretora, o.qtd) for o in ordens] == esp:
            ok(f"{nome}: ordens iguais às do Profit (UBS 3.200 com 111 ms entre pedaços fica em 2.800 + 400, spec §4)")
        else:
            err(f"{nome}: {[(o.corretora, o.qtd) for o in ordens]}")
    ativa = [o for o in juntar_ordens(ler_ticks(os.path.join(pasta, "leitura-tt_9393818_1018_negocios.csv")))
             if o.corretora == "Ativa"][0]
    if ativa.pedacos == 27 and (ativa.preco_ini, ativa.preco_fim) == (18.58, 18.60):
        ok("Ativa 20.000 em 27 pedaços, 18,58 → 18,60 (aula 9393818)")
    else:
        err(f"Ativa 20.000: {ativa}")


def _neg(ms, preco, qtd, agressor, lado, passiva=""):
    """Negócio sintético: ms a partir de 1.000.000 s."""
    return Tick(1_000_000.0 + ms / 1000, preco, qtd, agressor, lado, passive_broker=passiva)


def _giro(det, corretora, lado, preco, ms, vezes=1):
    """Reposição no livro. O último giro cai exatamente em `ms`."""
    base = 1_000_000.0 + ms / 1000
    for i in range(vezes):
        det.on_renovacao(corretora, lado, preco, base - (vezes - 1 - i) * 1e-4)


def _renovar(engine, corretora, lado, preco, ts, vezes=2):
    """O motor confirma o iceberg na reposição, não na agressão."""
    for i in range(vezes):
        engine.renovacao(corretora, lado, preco, ts + i * 1e-4)


def _evs(det, evento=None):
    return [e for e in det.eventos(200) if evento is None or e.evento == evento]


def _e2_consistente(det):
    """Todo E2 aponta para um parceiro que aponta de volta (sem par órfão)."""
    for k, d in det._defesas.items():
        if d.e2_par:
            o = det._defesas.get(d.e2_par)
            if o is None or o.e2_par != k:
                return False
        elif d.e2_com:
            return False
    return True


def test_defesas_classificacao():
    print(f"\n{AMARELO}═══ TESTE 29: Defesas — iceberg, sniper, fantasma e fim ═══{RESET}")
    from core.defesas import DefesaDetector

    # ── Iceberg: passiva repetida, ≥ 1.000, 2 giros, nenhum negócio além (aula-02; aula 9393845)
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 19.04, 1000, "XP", Side.SELL, "JP MORGAN"))
    _giro(det, "JP MORGAN", "compra", 19.04, 0)
    alerta = _evs(det, "alerta")
    det.on_tick(_neg(1000, 19.04, 300, "RICO", Side.SELL, "JP MORGAN"))
    _giro(det, "JP MORGAN", "compra", 19.04, 1000)
    at = det.ativas()
    if alerta and not alerta[0].tipo and len(at) == 1 and at[0].tipo == "iceberg" \
            and at[0].lado == "compra" and at[0].giros == 2 and at[0].vol_passivo == 1300:
        ok("1 giro de 1.000 = alerta; 2º giro confirma iceberg comprador de JP MORGAN @ 19,04")
    else:
        err(f"Iceberg: alerta={alerta} ativas={[d.to_dict() for d in at]}")

    det.on_tick(_neg(2000, 19.03, 100, "CLEAR", Side.SELL, "ITAU"))
    if _evs(det, "rompida") and not det.ativas():
        ok("1º negócio 1 tick além → iceberg rompido (aula-02 24:15)")
    else:
        err(f"Rompimento: {[e.to_dict() for e in _evs(det)]}")
    det.on_tick(_neg(3000, 19.04, 200, "TORO", Side.SELL, "JP MORGAN"))
    at = det.ativas()
    rec = _evs(det, "reclassificada")
    if len(at) == 1 and at[0].tipo == "sniper" and rec and "iceberg → sniper" in rec[-1].detalhe:
        ok("JP MORGAN volta a defender o 19,04 depois do negócio além → reclassificado como sniper (spec §5.5)")
    else:
        err(f"Reclassificação: {[d.to_dict() for d in at]} / {[e.to_dict() for e in rec]}")

    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 19.04, 600, "XP", Side.SELL, "JP MORGAN"))
    det.on_tick(_neg(1000, 19.04, 300, "RICO", Side.SELL, "JP MORGAN"))
    if not det.ativas() and not _evs(det, "alerta"):
        ok("Passiva repetida com 900 ações (< 1.000) não é iceberg nem alerta")
    else:
        err(f"Lote mínimo ignorado: {[d.to_dict() for d in det.ativas()]}")

    # ── Sniper: passiva E agressora do mesmo lado no mesmo preço (aula-02 12:20; aula 9393841 11:39)
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 21.17, 1000, "BTG", Side.SELL, "MORGAN"))
    det.on_tick(_neg(10, 21.17, 700, "MORGAN", Side.BUY, "UBS"))
    at = det.ativas()
    if len(at) == 1 and at[0].tipo == "sniper" and at[0].corretora == "MORGAN" and at[0].lado == "compra":
        ok("MORGAN absorve no 21,17 e boleta de volta no 21,17 → sniper comprador")
    else:
        err(f"Sniper passiva+agressora: {[d.to_dict() for d in at]}")

    # Sem reação: absorveu e só agrediu muito depois (outro cliente) → não é sniper
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 21.17, 100, "BTG", Side.SELL, "XP"))
    det.on_tick(_neg(3 * 3600 * 1000, 21.17, 100, "XP", Side.BUY, "UBS"))
    det.on_tick(_neg(3 * 3600 * 1000 + 1000, 21.17, 100, "ITAU", Side.SELL, "XP"))
    det.on_tick(_neg(3 * 3600 * 1000 + 2000, 21.16, 100, "ITAU", Side.SELL, "BTG"))
    det.on_tick(_neg(3 * 3600 * 1000 + 3000, 21.17, 100, "ITAU", Side.SELL, "XP"))
    if not [d for d in det.ativas() if d.corretora == "XP"]:
        ok("Absorver 100 e agredir horas depois, ou absorver de novo após 1 tick além, não faz sniper")
    else:
        err(f"Sniper falso: {[d.to_dict() for d in det.ativas()]}")

    # Mesma corretora vendendo no preço = cliente diferente, não conta (aula-02 09:18)
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 21.17, 1000, "BTG", Side.SELL, "MORGAN"))
    det.on_tick(_neg(500, 21.17, 700, "MORGAN", Side.SELL, "ITAU"))
    if not [d for d in det.ativas() if d.corretora == "MORGAN"]:
        ok("MORGAN passiva na compra e agressora na venda no mesmo preço: não é sniper")
    else:
        err(f"Lados misturados: {[d.to_dict() for d in det.ativas()]}")

    # Reação: agressão contrária no preço e o defensor agride de volta em ≤ 30 ms (aula 9393841)
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 21.17, 800, "BTG", Side.SELL))
    det.on_tick(_neg(10, 21.17, 1200, "MORGAN", Side.BUY))
    s1 = [d.corretora for d in det.ativas() if d.tipo == "sniper"]
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 21.17, 800, "BTG", Side.SELL))
    det.on_tick(_neg(40, 21.17, 1200, "MORGAN", Side.BUY))
    s2 = [d.corretora for d in det.ativas() if d.tipo == "sniper"]
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 21.17, 800, "BTG", Side.SELL, "ITAU"))
    det.on_tick(_neg(10, 21.17, 1200, "MORGAN", Side.BUY))
    s3 = [d.corretora for d in det.ativas() if d.tipo == "sniper"]
    if s1 == ["MORGAN"] and s2 == [] and s3 == []:
        ok("Reação em 10 ms = sniper; 40 ms não; passiva conhecida de outra corretora (ITAU) não")
    else:
        err(f"Reação: 10 ms={s1} 40 ms={s2} passiva ITAU={s3}")

    # Tolerância: até 3 ticks além continua; a 4 ticks = defensor ausente (aulas 9393833/9393841)
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 21.17, 800, "BTG", Side.SELL))
    det.on_tick(_neg(10, 21.17, 1200, "MORGAN", Side.BUY))
    for ms, p in ((1000, 21.16), (2000, 21.15), (3000, 21.14)):
        det.on_tick(_neg(ms, p, 100, "UBS", Side.SELL, "XP"))
    vivo = [d.alem_max for d in det.ativas() if d.corretora == "MORGAN"]
    det.on_tick(_neg(4000, 21.13, 100, "UBS", Side.SELL, "XP"))
    aus = [e for e in _evs(det, "defensor_ausente") if e.corretora == "MORGAN"]
    if vivo == [3] and aus and not [d for d in det.ativas() if d.corretora == "MORGAN"]:
        ok("Sniper aguenta negócios a 1, 2 e 3 ticks além; a 4 ticks → defensor_ausente")
    else:
        err(f"Tolerância: vivo={vivo} ausente={[e.to_dict() for e in aus]}")

    # Recuo de 2 ticks com o defensor ainda lá não encerra (aula 9393841 13:44–13:54)
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 21.30, 800, "UBS", Side.SELL))
    det.on_tick(_neg(10, 21.30, 1000, "MORGAN", Side.BUY))
    det.on_tick(_neg(1000, 21.28, 1800, "UBS", Side.SELL, "XP"))
    det.on_tick(_neg(2000, 21.30, 600, "XP", Side.SELL, "MORGAN"))
    if [d.preco for d in det.ativas() if d.corretora == "MORGAN"] == [21.30] and not _evs(det, "defensor_ausente"):
        ok("Recuo 21,30 → 21,28 → 21,30: sniper continua")
    else:
        err(f"Recuo: {[d.to_dict() for d in det.ativas()]}")

    # Mudou de nível: mesma corretora passa a defender outro preço do mesmo lado (aula 9393841)
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 21.17, 800, "BTG", Side.SELL))
    det.on_tick(_neg(10, 21.17, 1200, "MORGAN", Side.BUY))
    det.on_tick(_neg(5000, 21.19, 200, "ELLIOT", Side.SELL))
    det.on_tick(_neg(5010, 21.19, 7800, "MORGAN", Side.BUY))
    morgan = [d for d in det.ativas() if d.corretora == "MORGAN"]
    mud = _evs(det, "mudou_nivel")
    if len(morgan) == 1 and morgan[0].preco == 21.19 and morgan[0].to_dict()["niveis_anteriores"] == [21.17] \
            and mud and mud[-1].detalhe == "21,17 → 21,19":
        ok("Sniper MORGAN mudou de nível 21,17 → 21,19 (uma defesa só, com histórico)")
    else:
        err(f"Mudança de nível: {[d.to_dict() for d in morgan]} / {[e.to_dict() for e in mud]}")

    # Reclassificação também funde o sniper antigo da mesma corretora
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 21.10, 800, "BTG", Side.SELL))
    det.on_tick(_neg(10, 21.10, 1200, "MORGAN", Side.BUY))        # sniper MORGAN no 21,10
    det.on_tick(_neg(1000, 21.12, 1000, "XP", Side.SELL, "MORGAN"))
    det.on_tick(_neg(2000, 21.12, 300, "RICO", Side.SELL, "MORGAN"))   # volume do iceberg MORGAN no 21,12
    _giro(det, "MORGAN", "compra", 21.12, 2000, vezes=2)
    det.on_tick(_neg(3000, 21.11, 100, "CLEAR", Side.SELL, "ITAU"))   # rompe o 21,12
    det.on_tick(_neg(4000, 21.12, 200, "TORO", Side.SELL, "MORGAN"))  # volta: iceberg → sniper
    morgan = [d for d in det.ativas() if d.corretora == "MORGAN"]
    if len(morgan) == 1 and morgan[0].preco == 21.12 and 21.10 in morgan[0].to_dict()["niveis_anteriores"]:
        ok("Iceberg reclassificado como sniper absorve o sniper antigo da MORGAN: uma defesa só")
    else:
        err(f"Duas defesas da MORGAN: {[d.to_dict() for d in morgan]}")

    # ── Fantasma: agressora no preço com o lado dela vazio, 3 vezes (aula-02 25:09–25:35; aula 9393842)
    det = DefesaDetector(EngineConfig())
    for i in range(3):
        det.on_tick(_neg(i * 1000, 22.42, 100, "UBS", Side.BUY))        # compras pagam 22,42: venda vazia no 22,40
        det.on_tick(_neg(i * 1000 + 100, 22.40, 300, "TULLETT", Side.SELL))
    at = [d for d in det.ativas() if d.corretora == "TULLETT"]
    det2 = DefesaDetector(EngineConfig())
    for i in range(3):
        det2.on_tick(_neg(i * 1000, 22.42, 100, "UBS", Side.BUY))
        det2.on_tick(_neg(i * 1000 + 50, 22.40, 100, "XP", Side.SELL))   # outro vendedor também no 22,40
        det2.on_tick(_neg(i * 1000 + 100, 22.40, 300, "TULLETT", Side.SELL))
    at2 = [d for d in det2.ativas() if d.corretora == "TULLETT"]
    if len(at) == 1 and at[0].tipo == "fantasma" and at[0].lado == "venda" and not at2:
        ok("TULLETT vende 3 vezes no 22,40 com a venda vazia ali → fantasma; com outro vendedor no 22,40, não")
    else:
        err(f"Fantasma: {[d.to_dict() for d in at]} / com XP: {[d.to_dict() for d in at2]}")
    det.on_tick(_neg(4000, 22.43, 100, "XP", Side.BUY, "BTG"))
    vivo = bool([d for d in det.ativas() if d.corretora == "TULLETT"])
    det.on_tick(_neg(5000, 22.44, 100, "XP", Side.BUY, "BTG"))
    if vivo and [e for e in _evs(det, "defensor_ausente") if e.corretora == "TULLETT"]:
        ok("Fantasma aguenta 3 ticks além (22,43); a 4 ticks (22,44) → defensor_ausente")
    else:
        err(f"Fim do fantasma: vivo={vivo} eventos={[e.to_dict() for e in _evs(det)]}")

    # Negócio sem lado agressor é ignorado
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 19.04, 5000, "LEILAO", Side.NONE, "JP MORGAN"))
    if not det._defesas and not det.eventos():
        ok("Negócio sem agressor (leilão/cross) não cria defesa")
    else:
        err("Negócio sem agressor deveria ser ignorado")

    # ── Iceberg depois de uma agressão antiga da mesma corretora no preço (revisão final, item 1)
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 10.00, 100, "XP", Side.BUY, "ITAU"))            # XP agride 100 no 10,00
    det.on_tick(_neg(2000, 10.00, 600, "RICO", Side.SELL, "XP"))
    det.on_tick(_neg(3000, 10.00, 600, "CLEAR", Side.SELL, "XP"))
    _giro(det, "XP", "compra", 10.00, 3000, vezes=2)
    xp = [d for d in det.ativas() if d.corretora == "XP" and d.tipo == "iceberg"]
    if len(xp) == 1 and xp[0].lado == "compra" and xp[0].vol_passivo == 1200:
        ok("XP agrediu 100 antes e depois é passiva em 2 giros (1.200): iceberg confirmado")
    else:
        err(f"Iceberg com agressão antiga: {[d.to_dict() for d in det.ativas()]} / {[e.to_dict() for e in _evs(det)]}")

    # ── "Continua defendendo depois de negócio além" só com defesa confirmada e nova ABSORÇÃO (item 2)
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 10.05, 1800, "ITAU", Side.BUY, "BRADESCO"))     # BRADESCO passiva 1.800 na venda
    _giro(det, "BRADESCO", "venda", 10.05, 0)                            # 1 giro: alerta, não iceberg
    det.on_tick(_neg(1000, 10.06, 100, "RICO", Side.BUY, "XP"))
    det.on_tick(_neg(2000, 10.07, 100, "RICO", Side.BUY, "XP"))
    det.on_tick(_neg(3000, 10.05, 600, "BRADESCO", Side.SELL, "TORO"))  # agride 600 no mesmo nível
    brad = [d for d in det.ativas() if d.corretora == "BRADESCO"]
    if not brad:
        ok("Alerta + negócios além + agressão no nível: BRADESCO não vira sniper")
    else:
        err(f"Sniper falso em alerta: {[d.to_dict() for d in brad]}")

    # Defesa confirmada (iceberg rompido): agressão depois do negócio além não reclassifica; absorção sim
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 19.04, 1000, "XP", Side.SELL, "JP MORGAN"))
    _giro(det, "JP MORGAN", "compra", 19.04, 0)
    det.on_tick(_neg(1000, 19.04, 300, "RICO", Side.SELL, "JP MORGAN"))
    _giro(det, "JP MORGAN", "compra", 19.04, 1000)                        # iceberg
    det.on_tick(_neg(2000, 19.03, 100, "CLEAR", Side.SELL, "ITAU"))       # rompe
    det.on_tick(_neg(3000, 19.04, 200, "JP MORGAN", Side.BUY, "TORO"))    # só agressão: não conta
    nada = not det.ativas()
    det.on_tick(_neg(4000, 19.04, 200, "TORO", Side.SELL, "JP MORGAN"))   # nova absorção: sniper
    if nada and [d.tipo for d in det.ativas()] == ["sniper"]:
        ok("Iceberg rompido: agressão no nível não reclassifica; nova absorção passiva sim")
    else:
        err(f"Reclassificação estrita: nada={nada} {[d.to_dict() for d in det.ativas()]}")


def test_defesas_fila_e2():
    print(f"\n{AMARELO}═══ TESTE 30: Defesas — fila formada e E2 ═══{RESET}")
    from core.defesas import DefesaDetector

    def sniper_morgan():
        det = DefesaDetector(EngineConfig())
        det.on_tick(_neg(0, 21.17, 800, "BTG", Side.SELL))
        det.on_tick(_neg(10, 21.17, 1200, "MORGAN", Side.BUY))
        return det

    # Fila: a venda para no preço do sniper comprador; o próximo negócio não é ele limpando a fila
    det = sniper_morgan()
    det.on_book(21.16, 21.17)
    det.on_tick(_neg(1000, 21.17, 300, "XP", Side.BUY, "UBS"))
    fila = [e for e in _evs(det, "fila_formada") if e.corretora == "MORGAN"]
    det2 = sniper_morgan()
    det2.on_book(21.16, 21.17)
    det2.on_tick(_neg(1000, 21.17, 300, "MORGAN", Side.BUY, "UBS"))
    if fila and not [d for d in det.ativas() if d.corretora == "MORGAN"] \
            and [d for d in det2.ativas() if d.corretora == "MORGAN"] and not _evs(det2, "fila_formada"):
        ok("Venda parada no 21,17 e o próximo negócio não é o MORGAN → fila_formada; se ele limpa, continua")
    else:
        err(f"Fila: {[e.to_dict() for e in _evs(det)]} / {[e.to_dict() for e in _evs(det2)]}")

    # Negócio que não é contra a fila não decide nada; o pendente espera o negócio contra ela
    det = sniper_morgan()
    det.on_book(21.16, 21.17)
    det.on_tick(_neg(1000, 21.16, 100, "ITAU", Side.SELL, "XP"))       # venda no 21,16: não é contra a fila
    vivo = bool([d for d in det.ativas() if d.corretora == "MORGAN"]) and not _evs(det, "fila_formada")
    det.on_tick(_neg(2000, 21.17, 300, "XP", Side.BUY, "UBS"))         # compra contra a fila, não é o MORGAN
    if vivo and [e for e in _evs(det, "fila_formada") if e.corretora == "MORGAN"]:
        ok("Fila só se decide no negócio contra ela (compra no 21,17); outros negócios não encerram")
    else:
        err(f"Fila decidida pelo negócio errado: {[e.to_dict() for e in _evs(det)]}")

    # Fantasma vendedor: compra parada no 22,40 e o próximo negócio não é a TULLETT vendendo ali
    det = DefesaDetector(EngineConfig())
    for i in range(3):
        det.on_tick(_neg(i * 1000, 22.42, 100, "UBS", Side.BUY))
        det.on_tick(_neg(i * 1000 + 100, 22.40, 300, "TULLETT", Side.SELL))
    det.on_book(22.40, 22.42)
    det.on_tick(_neg(5000, 22.40, 200, "CLEAR", Side.SELL, "XP"))
    if [e for e in _evs(det, "fila_formada") if e.corretora == "TULLETT"]:
        ok("Fantasma TULLETT: compra parada no 22,40 sem ela vender → fila_formada (aula 9393842)")
    else:
        err(f"Fila do fantasma: {[e.to_dict() for e in _evs(det)]}")

    # E2 no mesmo preço: ÁGORA iceberg confirmado + TULLETT com 1 giro de 1.000 (aula 9393845 04:49–06:11)
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 22.05, 800, "XP", Side.SELL, "AGORA"))
    det.on_tick(_neg(1000, 22.05, 700, "BTG", Side.SELL, "AGORA"))
    _giro(det, "AGORA", "compra", 22.05, 1000, vezes=2)
    det.on_tick(_neg(2000, 22.05, 1000, "JP MORGAN", Side.SELL, "TULLETT"))
    _giro(det, "TULLETT", "compra", 22.05, 2000)
    e2 = _evs(det, "e2_formado")
    if e2 and {e2[-1].corretora, e2[-1].parceiro} == {"AGORA", "TULLETT"}:
        ok("E2 no 22,05: ÁGORA (iceberg) + TULLETT (alerta, player novo de 1.000)")
    else:
        err(f"E2 mesmo preço: {[e.to_dict() for e in _evs(det)]}")

    # E2 próximo (1 tick): ÁGORA iceberg no 22,05 + MERRILL sniper no 22,06; a fila acaba com o MERRILL
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 22.05, 800, "XP", Side.SELL, "AGORA"))
    det.on_tick(_neg(1000, 22.05, 700, "BTG", Side.SELL, "AGORA"))
    _giro(det, "AGORA", "compra", 22.05, 1000, vezes=2)
    det.on_tick(_neg(2000, 22.06, 1000, "UBS", Side.SELL, "MERRILL"))
    det.on_tick(_neg(2010, 22.06, 1000, "MERRILL", Side.BUY, "ITAU"))
    pares = sorted(f"{d.corretora}+{d.e2_com}" for d in det.ativas() if d.e2_com)
    det.on_book(22.05, 22.06)
    det.on_tick(_neg(3000, 22.06, 300, "XP", Side.BUY, "ITAU"))
    acabou = _evs(det, "e2_uma_acabou")
    agora_vivo = [d for d in det.ativas() if d.corretora == "AGORA"]
    if pares == ["AGORA+MERRILL", "MERRILL+AGORA"] and acabou and acabou[-1].corretora == "AGORA" \
            and agora_vivo and not agora_vivo[0].e2_com:
        ok("E2 a 1 tick (ÁGORA 22,05 + MERRILL 22,06); MERRILL perde a fila → e2_uma_acabou, ÁGORA continua")
    else:
        err(f"E2 próximo: pares={pares} eventos={[e.to_dict() for e in _evs(det)]}")

    # Mesma corretora em dois preços não é E2
    det = DefesaDetector(EngineConfig())
    for ms, p in ((0, 22.05), (1000, 22.05), (2000, 22.06), (3000, 22.06)):
        det.on_tick(_neg(ms, p, 800, "XP", Side.SELL, "AGORA"))
    if not _evs(det, "e2_formado"):
        ok("ÁGORA no 22,05 e no 22,06: mesma corretora, não é E2")
    else:
        err(f"E2 com a mesma corretora: {[e.to_dict() for e in _evs(det)]}")

    # Parceiro em alerta removido a 4 ticks: o E2 se desfaz (sem par órfão)
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 22.07, 1000, "XP", Side.SELL, "AGORA"))        # AGORA em alerta no 22,07
    _giro(det, "AGORA", "compra", 22.07, 0)
    det.on_tick(_neg(1000, 22.06, 800, "UBS", Side.SELL, "MERRILL"))
    det.on_tick(_neg(1010, 22.06, 1000, "MERRILL", Side.BUY, "ITAU"))  # sniper MERRILL no 22,06 → E2
    formou = bool(_evs(det, "e2_formado"))
    det.on_tick(_neg(2000, 22.03, 100, "BTG", Side.SELL, "GENIAL"))     # 4 ticks além do 22,07, 3 do 22,06
    merrill = [d for d in det.ativas() if d.corretora == "MERRILL"]
    if formou and merrill and not merrill[0].e2_com and _evs(det, "e2_uma_acabou"):
        ok("AGORA (alerta) sai a 4 ticks: o E2 se desfaz e o MERRILL continua sem par")
    else:
        err(f"E2 órfão: {[d.to_dict() for d in merrill]} / {[e.to_dict() for e in _evs(det)]}")

    # ── Par do E2 pela chave: cada fim desfaz só o próprio par (revisão final, item 3)
    def sniper(det, corretora, preco, ms):
        det.on_tick(_neg(ms, preco, 100, "BTG", Side.SELL))
        det.on_tick(_neg(ms + 10, preco, 100, corretora, Side.BUY))

    def chave(corretora, preco):
        return (corretora, "compra", round(preco / 0.01))

    # rompida
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 22.05, 800, "XP", Side.SELL, "AGORA"))
    det.on_tick(_neg(1000, 22.05, 700, "BTG", Side.SELL, "AGORA"))
    _giro(det, "AGORA", "compra", 22.05, 1000, vezes=2)
    det.on_tick(_neg(2000, 22.05, 1000, "JP MORGAN", Side.SELL, "TULLETT"))
    _giro(det, "TULLETT", "compra", 22.05, 2000)
    par = det._defesas[chave("TULLETT", 22.05)].e2_par
    det.on_tick(_neg(3000, 22.04, 100, "CLEAR", Side.SELL, "ITAU"))       # rompe o iceberg da AGORA
    tull = det._defesas[chave("TULLETT", 22.05)]
    if par == chave("AGORA", 22.05) and not tull.e2_par and tull.e2_com == "" and _e2_consistente(det):
        ok("E2 desfeito por rompida: a TULLETT fica sem par")
    else:
        err(f"E2 rompida: par={par} tull={tull.to_dict()}")

    # defensor_ausente
    det = DefesaDetector(EngineConfig())
    sniper(det, "X", 22.06, 0)
    sniper(det, "MERRILL", 22.05, 1000)
    formou = det._defesas[chave("MERRILL", 22.05)].e2_par == chave("X", 22.06)
    det.on_tick(_neg(2000, 22.02, 100, "ITAU", Side.SELL, "XP"))          # X a 4 ticks, MERRILL a 3
    mer = det._defesas.get(chave("MERRILL", 22.05))
    if formou and _evs(det, "defensor_ausente") and mer and not mer.e2_par and _e2_consistente(det):
        ok("E2 desfeito por defensor_ausente: o MERRILL continua sem par")
    else:
        err(f"E2 ausente: formou={formou} mer={mer and mer.to_dict()}")

    # mudou_nivel
    det = DefesaDetector(EngineConfig())
    sniper(det, "MORGAN", 21.17, 0)
    sniper(det, "UBS", 21.18, 1000)
    formou = det._defesas[chave("UBS", 21.18)].e2_par == chave("MORGAN", 21.17)
    det.on_tick(_neg(5000, 21.19, 200, "ELLIOT", Side.SELL))
    det.on_tick(_neg(5010, 21.19, 7800, "MORGAN", Side.BUY))
    ubs = det._defesas[chave("UBS", 21.18)]
    if formou and _evs(det, "mudou_nivel") and ubs.e2_par == chave("MORGAN", 21.19) and _e2_consistente(det):
        ok("E2 e mudou_nivel: o par antigo se desfaz e o UBS forma par com o MORGAN no novo nível")
    else:
        err(f"E2 mudou_nivel: formou={formou} ubs={ubs.to_dict()} par={ubs.e2_par}")

    # órfão: X e Y em dois níveis vizinhos; acabar o par de cima não pode mexer no de baixo
    det = DefesaDetector(EngineConfig())
    sniper(det, "X", 22.06, 0)
    sniper(det, "Y", 22.06, 1000)
    for ms, corr in ((2000, "X"), (3000, "Y")):                         # abaixo, icebergs (sniper não repete nível)
        det.on_tick(_neg(ms, 22.05, 1000, "XP", Side.SELL, corr))
        det.on_tick(_neg(ms + 100, 22.05, 300, "RICO", Side.SELL, corr))
        _giro(det, corr, "compra", 22.05, ms + 100, vezes=2)
    pares = (det._defesas[chave("X", 22.06)].e2_par, det._defesas[chave("X", 22.05)].e2_par)
    det.on_book(22.05, 22.06)
    det.on_tick(_neg(4000, 22.06, 300, "ITAU", Side.BUY))                 # fila formada no 22,06 (X e Y)
    x2, y2 = det._defesas.get(chave("X", 22.05)), det._defesas.get(chave("Y", 22.05))
    if pares == (chave("Y", 22.06), chave("Y", 22.05)) and x2 and y2 and x2.e2_par == chave("Y", 22.05) \
            and y2.e2_par == chave("X", 22.05) and _e2_consistente(det):
        ok("Dois pares vizinhos (X+Y sniper em 22,06 e icebergs em 22,05): acabar o de cima não desfaz o de baixo")
    else:
        err(f"E2 órfão: pares={pares} x2={x2 and x2.to_dict()} y2={y2 and y2.to_dict()}")


def test_defesas_engine():
    print(f"\n{AMARELO}═══ TESTE 31: Defesas dentro do motor ═══{RESET}")

    engine = FlowEngine("PETR4", _cfg_iceberg())
    ts = _base_negocios(engine, 1_000_000.0)
    for i, agr in enumerate(["BRADESCO", "RICO", "CLEAR", "XP INC", "TORO", "GENIAL"]):
        ts += 1.0
        engine.add_tick(Tick(ts, 19.04, 200, agr, Side.SELL, passive_broker="JP MORGAN"))
    _renovar(engine, "JP MORGAN", "compra", 19.04, ts)
    st = engine.get_state()
    ativas = st["defesas"]["ativas"]
    sig = engine.get_signal()
    if [(d["tipo"], d["corretora"], d["lado"]) for d in ativas] == [("iceberg", "JP MORGAN", "compra")]             and st["icebergs_confirmed"] and st["icebergs_confirmed"][0]["passive_broker"] == "JP MORGAN"             and sig.pattern.value == "Iceberg" and sig.stop_price == 19.03:
        ok("Iceberg das defesas no estado, em icebergs_confirmed e no sinal (stop 19,03)")
    else:
        err(f"Integração: {ativas} / {st['icebergs_confirmed']} / {sig.to_dict()}")
    if any(e["evento"] == "confirmada" for e in st["defesas"]["eventos"]):
        ok("Eventos das defesas expostos em get_state()['defesas']['eventos']")
    else:
        err(f"Eventos ausentes: {st['defesas']}")

    engine.add_tick(Tick(ts + 1, 19.05, 100, "ITAU", Side.BUY, passive_broker="XP INC"))
    st = engine.get_state()
    if st["defesas"]["ativas"] and engine.get_signal().pattern.value != "Iceberg":
        ok("Preço fora do nível: a defesa continua (sem tempo), mas o sinal de iceberg sai")
    else:
        err(f"Sinal fora do nível: {engine.get_signal().to_dict()} / {st['defesas']['ativas']}")

    # Topo do book chega ao módulo: fila formada contra um sniper
    engine = FlowEngine("PETR4", EngineConfig())
    ts = 1_000_000.0
    engine.add_tick(Tick(ts, 21.17, 800, "BTG", Side.SELL))
    engine.add_tick(Tick(ts + 0.01, 21.17, 1200, "MORGAN", Side.BUY))
    engine.update_book([BookLevel(21.16, 500, "", Side.BUY, ts + 1), BookLevel(21.17, 900, "", Side.SELL, ts + 1)])
    engine.add_tick(Tick(ts + 2, 21.17, 300, "XP", Side.BUY, passive_broker="UBS"))
    if any(e["evento"] == "fila_formada" and e["corretora"] == "MORGAN"
           for e in engine.get_state()["defesas"]["eventos"]):
        ok("update_book alimenta o módulo: fila_formada contra o sniper MORGAN")
    else:
        err(f"Fila pelo book: {engine.get_state()['defesas']}")

    # Confluência da exaustão aceita sniper/fantasma do lado oposto
    engine = FlowEngine("PETR4", EngineConfig())
    engine.add_tick(Tick(1_000_000.0, 21.17, 800, "BTG", Side.SELL))
    engine.add_tick(Tick(1_000_000.01, 21.17, 1200, "MORGAN", Side.BUY))
    perto = engine._defesas_opostas_perto("compra", 21.18, 3 * 0.01 + 1e-9)
    if [d.corretora for d in perto] == ["MORGAN"]:
        ok("Defesa sniper conta como confluência perto da extremidade da exaustão")
    else:
        err(f"Confluência: {[d.to_dict() for d in perto]}")


    # Fonte sem passiva (OCR/DDE/manual): sniper/fantasma aparecem, mas não entram na confluência (item 5)
    engine = FlowEngine("PETR4", EngineConfig())
    engine.add_tick(Tick(1_000_000.0, 21.17, 800, "BTG", Side.SELL))
    engine.add_tick(Tick(1_000_000.01, 21.17, 1200, "MORGAN", Side.BUY))
    sem = engine._defesas_na_confluencia("compra", 21.18, 3 * 0.01 + 1e-9)
    mostra = [d["corretora"] for d in engine.get_state()["defesas"]["ativas"]]
    engine.add_tick(Tick(1_000_001.0, 21.17, 100, "ITAU", Side.BUY, passive_broker="XP"))
    com = [d.corretora for d in engine._defesas_na_confluencia("compra", 21.18, 3 * 0.01 + 1e-9)]
    if sem == [] and mostra == ["MORGAN"] and com == ["MORGAN"]:
        ok("Sem passiva na fonte: sniper aparece na tela mas fica fora da confluência; com passiva entra")
    else:
        err(f"Confluência sem passiva: sem={sem} tela={mostra} com={com}")

    # Reação só com 0 <= delta <= 30 ms (item 5): ms negativo (relógio fora de ordem) não vale
    from core.defesas import DefesaDetector
    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(100, 21.17, 800, "BTG", Side.SELL))
    det.on_tick(_neg(90, 21.17, 1200, "MORGAN", Side.BUY))
    if not det.ativas():
        ok("Agressão de volta com timestamp anterior (delta negativo) não é reação")
    else:
        err(f"Reação com delta negativo: {[d.to_dict() for d in det.ativas()]}")

    engine.reset()
    if not engine.get_state()["defesas"]["ativas"] and not engine.get_state()["defesas"]["eventos"]:
        ok("reset() limpa defesas e eventos")
    else:
        err(f"reset() deixou defesas: {engine.get_state()['defesas']}")


def test_iceberg_corte_volume():
    print(f"\n{AMARELO}═══ TESTE 33: Sinal de iceberg só a partir do volume calibrado ═══{RESET}")

    def rodar(ativo, vol_por_ordem, n=6):
        cfg = EngineConfig(min_confidence=0.50, flow_pct_threshold=60.0)
        engine = FlowEngine(ativo, cfg)
        ts = _base_negocios(engine, 1_000_000.0)
        for i in range(n):
            ts += 1.0
            engine.add_tick(Tick(ts, 19.04, vol_por_ordem, f"V{i}", Side.SELL, passive_broker="JP MORGAN"))
        _renovar(engine, "JP MORGAN", "compra", 19.04, ts)
        ativas = [d["tipo"] for d in engine.get_state()["defesas"]["ativas"] if d["corretora"] == "JP MORGAN"]
        return ativas, engine.get_signal().pattern.value

    cfg = EngineConfig()
    if cfg.defesa_iceberg_vol_sinal.get("PETR4") == 50000 and cfg.defesa_iceberg_vol_sinal.get("RENT3") == 5000             and cfg.defesa_iceberg_vol_sinal_padrao == 5000:
        ok("Cortes calibrados: PETR4 50 mil, RENT3 5 mil, demais 5 mil")
    else:
        err(f"Cortes: {cfg.defesa_iceberg_vol_sinal} / {cfg.defesa_iceberg_vol_sinal_padrao}")
    a, p = rodar("RENT3", 300)            # 1.800 absorvidas: defesa sim, sinal não
    b, q = rodar("RENT3", 1000)           # 6.000 absorvidas: sinal
    c, r = rodar("PETR4", 1000)           # 6.000 em PETR4: abaixo de 50 mil, sem sinal
    if a == ["iceberg"] and p != "Iceberg" and b == ["iceberg"] and q == "Iceberg" and c == ["iceberg"] and r != "Iceberg":
        ok("Defesa detectada sempre; sinal só com o volume do papel (RENT3 6 mil sim, 1,8 mil não; PETR4 6 mil não)")
    else:
        err(f"Corte de volume: RENT3 1,8k {a}/{p}; RENT3 6k {b}/{q}; PETR4 6k {c}/{r}")


def test_acerto_iceberg():
    print(f"\n{AMARELO}═══ TESTE 34: Acerto histórico do iceberg no lugar da força ═══{RESET}")
    import json, tempfile
    from core.calibracao import faixa_volume, acerto_iceberg, agregar

    if (faixa_volume(1999), faixa_volume(2000), faixa_volume(49999), faixa_volume(50000)) == \
            ("1-2k", "2-5k", "20-50k", "50k+"):
        ok("Faixas de volume com limite superior exclusivo")
    else:
        err("Faixas de volume erradas")
    dias = [{"ativo": "RENT3", "faixas": {"5-10k": {"n": 40, "alvo": 20, "stop": 20, "ganho": 60.0}}},
            {"ativo": "PETR4", "faixas": {"5-10k": {"n": 10, "alvo": 1, "stop": 9, "ganho": -5.0}}}]
    tabela = agregar(dias, "teste", 4, 300)
    r = acerto_iceberg(tabela, "RENT3", 6000)
    p = acerto_iceberg(tabela, "PETR4", 6000)      # só 10 sinais de PETR4: usa todos os papéis
    nada = acerto_iceberg(tabela, "RENT3", 60000)
    if r == {"taxa": 0.5, "ganho": 1.5, "n": 40, "faixa": "5-10k", "base": "RENT3"} \
            and p["base"] == "TODOS" and p["n"] == 50 and nada is None:
        ok("Acerto pela faixa do papel; com menos de 30 sinais, pela de todos; sem medida, nada")
    else:
        err(f"acerto_iceberg: {r} / {p} / {nada}")

    fd, caminho = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(agregar([{"ativo": "PETR4", "faixas": {"1-2k": {"n": 100, "alvo": 44, "stop": 56, "ganho": 120.0}}}],
                          "teste", 4, 300), f)
    try:
        cfg = _cfg_iceberg()
        cfg.calibracao_iceberg = caminho
        engine = FlowEngine("PETR4", cfg)
        ts = _base_negocios(engine, 1_000_000.0)
        for i, agr in enumerate(["BRADESCO", "RICO", "CLEAR", "XP INC", "TORO", "GENIAL"]):
            ts += 1.0
            engine.add_tick(Tick(ts, 19.04, 200, agr, Side.SELL, passive_broker="JP MORGAN"))
        _renovar(engine, "JP MORGAN", "compra", 19.04, ts)
        sig = engine.get_signal().to_dict()
        reg = engine.get_signals()[-1]
    finally:
        os.unlink(caminho)
    esperado = {"taxa": 0.44, "ganho": 1.2, "n": 100, "faixa": "1-2k", "base": "PETR4"}
    if sig["pattern"] == "Iceberg" and sig["acerto"] == esperado and reg["acerto"] == esperado:
        ok("Sinal de iceberg traz o acerto histórico (no /signal e no registro de sinais)")
    else:
        err(f"Acerto no sinal: {sig.get('acerto')} / {reg.get('acerto')}")


def test_defesas_aulas():
    print(f"\n{AMARELO}═══ TESTE 32: Defesas nas sequências das aulas (material local) ═══{RESET}")
    pasta = _pasta_aulas()
    if not pasta:
        info("Sequências das aulas não encontradas (FLUXO_CENARIOS_AULAS): teste pulado")
        return
    from replay.csv_ticks import ler_ticks

    def rodar(*nomes):
        engine = FlowEngine("PETR4", EngineConfig())
        for nome in nomes:
            for t in ler_ticks(os.path.join(pasta, nome)):
                engine.add_tick(t)
        return engine._defesas.eventos(200)

    def ev(evs, evento, corretora, preco=None):
        return [e for e in evs if e.evento == evento and e.corretora == corretora
                and (preco is None or abs(e.preco - preco) < 1e-9)]

    # Sniper "Morgan de 1K", BRAV3 27/11/2024 (aula 9393841), 4 trechos em sequência
    d = "27/11/2024"
    evs = rodar("sniper_9393841_1113.csv", "sniper_9393841_1257.csv",
                "sniper_9393841_1327.csv", "sniper_9393841_1429.csv")
    conf = ev(evs, "confirmada", "Morgan", 21.17)
    if conf and _hb3(d, "10:12:10.750") <= conf[0].ts <= _hb3(d, "10:12:10.830") and conf[0].tipo == "sniper":
        ok("Sniper Morgan no 21,17 entre 10:12:10,75 e 10:12:10,83 (\"absorvendo e boletando\", 11:13)")
    else:
        err(f"Sniper 21,17: {[e.to_dict() for e in conf]}")
    mud = [(e.preco, round(e.ts, 3)) for e in ev(evs, "mudou_nivel", "Morgan")]
    esperado = [(21.19, round(_hb3(d, "10:12:51.970"), 3)), (21.30, round(_hb3(d, "10:13:33.690"), 3)),
                (21.34, round(_hb3(d, "10:14:05.550"), 3))]
    if mud == esperado:
        ok("Morgan sobe 21,17 → 21,19 → 21,30 → 21,34 como uma defesa só")
    else:
        err(f"Mudanças de nível: {mud} (esperado {esperado})")
    aus = ev(evs, "defensor_ausente", "Morgan")
    if len(aus) == 1 and abs(aus[0].ts - _hb3(d, "10:14:14.100")) < 1e-6 and aus[0].preco == 21.34:
        ok("\"Cadê ele?\": defensor ausente no negócio de 10:14:14,10 a 4 ticks (21,30), nem antes nem depois")
    else:
        err(f"Fim do sniper: {[e.to_dict() for e in aus]}")

    # Mesmo trecho isolado: Morgan volta no 21,01 ("voltou", aula 9393841 08:39)
    evs = rodar("sniper_9393841_0545.csv")
    volta = [e for e in ev(evs, "confirmada", "Morgan", 21.01) if e.tipo == "sniper"]
    if volta and abs(volta[0].ts - _hb3(d, "10:11:02.890")) < 1e-6 and not ev(evs, "confirmada", "Morgan", 21.03):
        ok("Morgan reconhecido no 21,01 às 10:11:02,89; no 21,03 a passiva não aparece na tela (sem marcação)")
    else:
        err(f"Trecho 0545: {[e.to_dict() for e in evs if e.corretora == 'Morgan']}")

    # Fantasma Tullett no 22,40, RECV3 04/04/2024 (aula 9393842)
    d = "04/04/2024"
    evs = rodar("fantasma_9393842_0436.csv")
    f1 = [e for e in ev(evs, "confirmada", "Tullett", 22.40) if e.tipo == "fantasma"]
    if f1 and abs(f1[0].ts - _hb3(d, "10:47:41.740")) < 1e-6:
        ok("Fantasma vendedor Tullett no 22,40 na 3ª agressão com a venda vazia (10:47:41,74; \"40, 40, 40\")")
    else:
        err(f"Fantasma 0436: {[e.to_dict() for e in evs if e.corretora == 'Tullett']}")
    evs = rodar("fantasma_9393842_1306.csv")
    f2 = [e for e in ev(evs, "confirmada", "Tullett", 22.40) if e.tipo == "fantasma"]
    fim = ev(evs, "defensor_ausente", "Tullett", 22.40)
    if f2 and abs(f2[0].ts - _hb3(d, "11:08:48.560")) < 1e-6 \
            and len(fim) == 1 and abs(fim[0].ts - _hb3(d, "11:09:05.570")) < 1e-6:
        ok("Fantasma ativo até a última venda (11:09:03,57); varrida a 22,47 às 11:09:05,57 = fim")
    else:
        err(f"Fantasma 1306: {[e.to_dict() for e in evs if e.corretora == 'Tullett']}")

    # E2 no mesmo preço, MRFG3 14/07/2025 (aula 9393845) — a única sequência com a passiva
    d = "14/07/2025"
    evs = rodar("e2_9393845_0411.csv")
    ic = [e for e in ev(evs, "confirmada", "Agora", 22.05) if e.tipo == "iceberg"]
    e2 = [e for e in evs if e.evento == "e2_formado" and {e.corretora, e.parceiro} == {"Agora", "Tullett"}]
    if not ic and not e2:
        ok("Sem livro de ofertas a fita não confirma iceberg nem E2 (o giro é a reposição no book)")
    else:
        err(f"E2 0411 não devia sair só da fita: {[e.to_dict() for e in evs if e.corretora in ('Agora', 'Tullett')]}")

    # Icebergs da aula 9393840: nenhum negócio além do nível → nenhum rompimento
    for nome in ("iceberg_9393840_0403.csv", "iceberg_9393840_0845.csv"):
        ticks = ler_ticks(os.path.join(pasta, nome))
        engine = FlowEngine("PETR4", EngineConfig())
        for t in ticks:
            engine.add_tick(t)
        evs = engine._defesas.eventos(200)
        recebidos = engine.get_state()["tick_count"]
        if ticks and recebidos == len(ticks) and not [e for e in evs if e.evento == "rompida"]:
            ok(f"{nome}: {recebidos} negócios, nenhum rompimento (a passiva não aparece na tela; só o nível é verificável)")
        else:
            err(f"{nome}: {recebidos}/{len(ticks)} negócios; rompimentos {[e.to_dict() for e in evs if e.evento == 'rompida']}")


def test_defesas_segurou():
    print(f"\n{AMARELO}═══ TESTE 35: Iceberg que segurou o preço (4 ticks a favor) ═══{RESET}")
    from core.defesas import DefesaDetector

    def iceberg_compra():
        det = DefesaDetector(EngineConfig())
        det.on_tick(_neg(0, 19.04, 800, "XP", Side.SELL, "AGORA"))
        det.on_tick(_neg(1000, 19.04, 700, "BTG", Side.SELL, "AGORA"))
        _giro(det, "AGORA", "compra", 19.04, 1000, vezes=2)                 # iceberg antes do preço andar
        return det

    vistos = []
    det = iceberg_compra()
    det.ao_evento = lambda ev, d: vistos.append((ev.evento, d.corretora))
    det.on_tick(_neg(2000, 19.07, 100, "UBS", Side.BUY, "ITAU"))            # 3 ticks: ainda não
    antes = [e for e in det.eventos(50) if e.evento == "segurou"]
    det.on_tick(_neg(3000, 19.08, 100, "UBS", Side.BUY, "ITAU"))            # 4 ticks a favor
    seg = [e for e in det.eventos(50) if e.evento == "segurou"]
    ag = [d for d in det.ativas() if d.corretora == "AGORA"]
    if not antes and len(seg) == 1 and ag and ag[0].segurou_em == 1_000_003.0 and ("segurou", "AGORA") in vistos:
        ok("Iceberg comprador segura a 4 ticks (19,08), não a 3; continua ativo; gancho ao_evento chamado")
    else:
        err(f"segurou: antes={antes} depois={[e.to_dict() for e in seg]} ativas={[d.to_dict() for d in ag]}")

    det.on_tick(_neg(4000, 19.09, 100, "UBS", Side.BUY, "ITAU"))
    det.on_tick(_neg(5000, 19.03, 100, "CLEAR", Side.SELL, "XP"))           # rompe depois de segurar
    evs = [e.evento for e in det.eventos(50) if e.corretora == "AGORA"]
    if evs.count("segurou") == 1 and "rompida" in evs:
        ok("Segura uma vez só; romper depois fica registrado também")
    else:
        err(f"Sequência AGORA: {evs}")

    det = DefesaDetector(EngineConfig())
    det.on_tick(_neg(0, 22.40, 800, "XP", Side.BUY, "TULLETT"))
    det.on_tick(_neg(1000, 22.40, 700, "BTG", Side.BUY, "TULLETT"))
    _giro(det, "TULLETT", "venda", 22.40, 1000, vezes=2)                  # iceberg antes dos 4 ticks
    det.on_tick(_neg(2000, 22.36, 100, "UBS", Side.SELL, "ITAU"))           # 4 ticks abaixo = a favor
    if [e.corretora for e in det.eventos(50) if e.evento == "segurou"] == ["TULLETT"]:
        ok("Iceberg vendedor segura com o preço 4 ticks abaixo")
    else:
        err(f"segurou vendedor: {[e.to_dict() for e in det.eventos(50)]}")
    det.reset()
    if det.ao_evento is None and not det.eventos():
        ok("reset() limpa os eventos e mantém o gancho como estava")
    else:
        err("reset() do detector")


def test_livro_ofertas():
    print(f"\n{AMARELO}═══ TESTE 41: Giro é reposição do lote, não cada agressão ═══{RESET}")
    import struct
    from core.livro_ofertas import LivroOfertas
    from profitdll.bridge import (ProfitDLLBridge, AGRESSAO_VENDA, decodificar_ofertas,
                                  OFERTA_ADD, OFERTA_EDIT, OFERTA_DELETE)

    livro = LivroOfertas()
    ts = 1_000_000.0

    def por(qtd, oid, preco=19.04, corr="UBS", lado="compra", quando=None):
        return livro.atualizar("PETR4", lado, preco, qtd, corr, oid, ts if quando is None else quando)

    def nego(qtd, quando, corr="UBS", lado="compra", preco=19.04):
        return livro.negocio("PETR4", corr, lado, preco, qtd, quando)

    por(1500, 10)
    if nego(300, ts + 1) == [] and por(1200, 10) == [] and nego(300, ts + 2) == [] and por(900, 10) == []:
        ok("UBS 1.500 na compra: agredir 300 e de novo 300 não é giro (o lote continua no book)")
    else:
        err("Agressão parcial contou como giro")

    if nego(900, ts + 3) == [] and por(0, 10) == []:
        volta = por(1500, 11)
        if len(volta) == 1 and volta[0].corretora == "UBS" and volta[0].qtd == 1500 and volta[0].lado == "compra":
            ok("Os 1.500 acabam e a UBS volta com 1.500 no mesmo preço: 1 giro")
        else:
            err(f"Reposição: {volta}")
    else:
        err("Consumir o lote não devia emitir giro antes da oferta voltar")

    if nego(1500, ts + 4) == [] and por(0, 11) == [] and len(por(1500, 12)) == 1:
        ok("Segunda vez que o lote acaba e volta: 2º giro")
    else:
        err("Segundo ciclo não contou um giro")

    livro.reset()
    por(1500, 20)
    if por(0, 20) == [] and por(1500, 21) == [] and nego(1500, ts + 10.5) == []:
        ok("Cancelar sem execução e repor, ou negociar depois da janela, não é giro")
    else:
        err("Cancelamento virou giro")

    livro.reset()
    por(1500, 30, corr="XP")
    por(0, 30, corr="XP", quando=ts + 20)
    cedo = por(1500, 31, corr="XP", quando=ts + 20.01)
    tarde = nego(1500, ts + 20.04, corr="XP")
    if cedo == [] and len(tarde) == 1 and tarde[0].corretora == "XP":
        ok("Oferta some e volta antes do negócio: o lote que chega em seguida ainda conta")
    else:
        err(f"Fora de ordem: cedo={cedo} tarde={tarde}")

    livro.reset()
    por(1500, 40, corr="ITAU", lado="venda", preco=22.40)
    if (nego(1500, ts + 30, corr="ITAU", lado="venda", preco=22.40) == []
            and por(0, 40, corr="ITAU", lado="venda", preco=22.40) == []
            and len(por(1500, 41, corr="ITAU", lado="venda", preco=22.40)) == 1):
        ok("Venda: consumir o lote e a corretora voltar no mesmo preço é 1 giro")
    else:
        err("Giro na venda não saiu")

    entrada = struct.pack("=dqiqH", 19.04, 1500, 8, 10, 0)
    blob = struct.pack("ii", 1, 8 + len(entrada)) + entrada
    ofertas, primeiro, ultimo = decodificar_ofertas(blob)
    if ofertas == [(10, 19.04, 1500, 8)] and primeiro and ultimo and decodificar_ofertas(b"") == ([], True, True):
        ok("Full book: uma oferta de 1.500 da corretora 8 no 19,04")
    else:
        err(f"Full book: {ofertas} primeiro={primeiro} ultimo={ultimo}")

    ponte = ProfitDLLBridge("PETR4")
    ponte.nomes = {8: "UBS", 3: "XP"}
    giros = []
    ponte.on_renovacao = lambda *a: giros.append(a)

    def oferta(acao, qtd, oid, quando):
        ponte._processar_oferta_giro("PETR4", acao, 0, 0, qtd, 8, oid, 19.04,
                                True, True, True, True, None, None, quando)

    oferta(OFERTA_ADD, 1500, 10, ts)
    ponte._processar_trade(8, 3, 300, 19.04, AGRESSAO_VENDA, ts + 1, ativo="PETR4")
    oferta(OFERTA_EDIT, 1200, 10, ts + 1)
    ponte._processar_trade(8, 3, 1200, 19.04, AGRESSAO_VENDA, ts + 2, ativo="PETR4")
    oferta(OFERTA_DELETE, 0, 10, ts + 2)
    oferta(OFERTA_ADD, 1500, 11, ts + 2)
    if len(giros) == 1 and giros[0][:4] == ("PETR4", "UBS", "compra", 19.04):
        ok("Livro da DLL: 300 de 1.500 não gira; consumir e a UBS voltar gira uma vez")
    else:
        err(f"Ponte: {giros}")


def test_radar():
    print(f"\n{AMARELO}═══ TESTE 36: Radar — icebergs de vários papéis ═══{RESET}")
    from core.radar import Radar

    def neg(ativo, ms, preco, qtd, agr, lado, pas=""):
        t = _neg(ms, preco, qtd, agr, lado, pas)
        t.asset = ativo
        return t

    radar = Radar(EngineConfig(), calibracao_tabela={})
    for t in [neg("RENT3", 0, 50.36, 800, "XP", Side.SELL, "AGORA"),
              neg("PETR4", 10, 38.00, 900, "BTG", Side.BUY, "ITAU"),
              neg("RENT3", 1000, 50.36, 700, "BTG", Side.SELL, "AGORA"),
              neg("PETR4", 1010, 38.00, 600, "XP", Side.BUY, "ITAU")]:
        radar.on_tick(t)
    radar.on_renovacao("RENT3", "AGORA", "compra", 50.36, 1_000_000.0)
    radar.on_renovacao("RENT3", "AGORA", "compra", 50.36, 1_000_001.0)
    radar.on_renovacao("PETR4", "ITAU", "venda", 38.00, 1_000_000.01)
    radar.on_renovacao("PETR4", "ITAU", "venda", 38.00, 1_000_001.01)
    for t in [neg("RENT3", 2000, 50.40, 100, "UBS", Side.BUY, "XP"),         # 4 ticks a favor → segurou
              neg("PETR4", 3000, 38.01, 100, "UBS", Side.BUY, "XP")]:        # 1 além → rompeu
        radar.on_tick(t)
    lst = radar.lista()
    resumo = radar.resumo()
    por = {(r["ativo"], r["corretora"]): r for r in lst}
    rent, petr = por.get(("RENT3", "AGORA")), por.get(("PETR4", "ITAU"))
    if rent and petr and rent["situacao"] == "segurou" and rent["segurou_as"] == 1_000_002.0 \
            and petr["situacao"] == "rompeu" and petr["rompeu_as"] == 1_000_003.0 \
            and rent["giros"] == 2 and rent["volume"] == 1500 and rent["lado"] == "compra":
        ok("Um detector por papel; RENT3 segurou, PETR4 rompeu, com giros e volume")
    else:
        err(f"Lista do radar: {lst}")
    if resumo == {"segurando": 0, "seguraram": 1, "romperam": 1, "viraram_sniper": 0, "papeis": 2, "negocios": 6}:
        ok("Resumo do radar")
    else:
        err(f"Resumo: {resumo}")
    if [r["corretora"] for r in radar.lista("rompeu")] == ["ITAU"]:
        ok("Filtro por situação")
    else:
        err(f"Filtro: {radar.lista('rompeu')}")

    # Ordem: segurando primeiro (maior volume), depois os resolvidos (mais recente primeiro)
    radar = Radar(EngineConfig(), calibracao_tabela={})
    for t in [neg("VALE3", 0, 60.00, 600, "XP", Side.SELL, "UBS"), neg("VALE3", 1000, 60.00, 600, "BTG", Side.SELL, "UBS"),
              neg("TAEE11", 0, 35.00, 2000, "XP", Side.SELL, "BTG"), neg("TAEE11", 1000, 35.00, 2000, "XP", Side.SELL, "BTG"),
              neg("ABEV3", 0, 13.00, 600, "XP", Side.BUY, "ITAU"), neg("ABEV3", 1000, 13.00, 600, "XP", Side.BUY, "ITAU")]:
        radar.on_tick(t)
    radar.on_renovacao("VALE3", "UBS", "compra", 60.00, 1_000_000.0)
    radar.on_renovacao("VALE3", "UBS", "compra", 60.00, 1_000_001.0)
    radar.on_renovacao("TAEE11", "BTG", "compra", 35.00, 1_000_000.0)
    radar.on_renovacao("TAEE11", "BTG", "compra", 35.00, 1_000_001.0)
    radar.on_renovacao("ABEV3", "ITAU", "venda", 13.00, 1_000_000.0)
    radar.on_renovacao("ABEV3", "ITAU", "venda", 13.00, 1_000_001.0)
    radar.on_tick(neg("ABEV3", 2000, 13.01, 100, "XP", Side.BUY, "UBS"))
    ordem = [(r["ativo"], r["situacao"]) for r in radar.lista()]
    if ordem == [("TAEE11", "segurando"), ("VALE3", "segurando"), ("ABEV3", "rompeu")]:
        ok("Ordem: segurando por volume, depois resolvidos")
    else:
        err(f"Ordem: {ordem}")

    # Troca de dia zera sozinho
    radar.on_tick(neg("VALE3", 86_400_000, 60.00, 100, "XP", Side.SELL, "UBS"))
    if radar.lista() == [] and radar.resumo()["papeis"] == 1:
        ok("Primeiro negócio de um dia novo zera o radar")
    else:
        err(f"Troca de dia: {radar.lista()} {radar.resumo()}")

    # envolver: todo negócio vai ao radar; só o do papel aberto vai ao motor
    radar = Radar(EngineConfig(), calibracao_tabela={})
    engine = FlowEngine("RENT3", EngineConfig())
    recebidos = []
    entrega = radar.envolver(lambda t: recebidos.append((t.asset, t.price)), engine)
    entrega(neg("PETR4", 0, 38.00, 100, "XP", Side.BUY, "UBS"))
    entrega(neg("RENT3", 10, 50.00, 100, "XP", Side.BUY, "UBS"))
    sem = _neg(20, 50.01, 100, "XP", Side.BUY, "UBS")                       # sem papel = papel aberto
    entrega(sem)
    if recebidos == [("RENT3", 50.00), ("RENT3", 50.01)] and radar.resumo()["negocios"] == 3:
        ok("envolver: o motor só recebe o papel aberto; o radar recebe tudo")
    else:
        err(f"envolver: {recebidos} / {radar.resumo()}")

    # Os detectores do radar não escrevem cada evento no log (com ~650 papéis inundaria o log e a tela Conexão)
    import logging as _logging
    linhas = []

    class _Pega(_logging.Handler):
        def emit(self, r):
            linhas.append(r.getMessage())
    pega = _Pega(_logging.DEBUG)
    _logging.getLogger("Defesas").addHandler(pega)
    try:
        radar = Radar(EngineConfig(), calibracao_tabela={})
        radar.on_tick(neg("RENT3", 0, 50.36, 800, "XP", Side.SELL, "AGORA"))
        radar.on_tick(neg("RENT3", 1000, 50.36, 700, "BTG", Side.SELL, "AGORA"))
        radar.on_renovacao("RENT3", "AGORA", "compra", 50.36, 1_000_000.0)
        radar.on_renovacao("RENT3", "AGORA", "compra", 50.36, 1_000_001.0)
    finally:
        _logging.getLogger("Defesas").removeHandler(pega)
    if radar.resumo()["segurando"] == 1 and not linhas:
        ok("Eventos do radar ficam na lista, não no log")
    else:
        err(f"log do radar: {linhas}")

    # Mesmo resultado de papéis juntos e separados; desempenho (material local)
    import os as _os
    arqs = ["historico/petr4_2026-10-16.csv", "historico/rent3_2026-10-16.csv"]
    if not all(_os.path.exists(a) for a in arqs):
        info("Pregões de 16/10 não encontrados em historico/: parte multi-ativo pulada")
        return
    import heapq
    from replay.csv_ticks import ler_ticks
    porpapel = {}
    for a in arqs:
        ativo = _os.path.basename(a).split("_")[0].upper()
        ticks = ler_ticks(a)
        for t in ticks:
            t.asset = ativo
        porpapel[ativo] = ticks
    sozinhos = {}
    for ativo, ticks in porpapel.items():
        r = Radar(EngineConfig(), calibracao_tabela={})
        for t in ticks:
            r.on_tick(t)
        sozinhos[ativo] = [(x["corretora"], x["preco"], x["situacao"]) for x in r.lista(limite=10**6) if x["ativo"] == ativo]
    juntos = Radar(EngineConfig(), calibracao_tabela={})
    inicio = time.perf_counter()
    for t in heapq.merge(*porpapel.values(), key=lambda t: t.timestamp):
        juntos.on_tick(t)
    dur = time.perf_counter() - inicio
    iguais = all(sorted(sozinhos[a]) == sorted((x["corretora"], x["preco"], x["situacao"])
                                               for x in juntos.lista(limite=10**6) if x["ativo"] == a)
                 for a in porpapel)
    total = sum(len(v) for v in porpapel.values())
    if iguais and dur < 60:
        ok(f"PETR4 + RENT3 juntos = cada um sozinho; {total:,} negócios em {dur:.1f}s")
    else:
        err(f"Multi-ativo: iguais={iguais} tempo={dur:.1f}s")


def test_acoes_b3():
    print(f"\n{AMARELO}═══ TESTE 37: Lista de ações à vista (cadastro da B3) ═══{RESET}")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
    from acoes_b3 import filtrar, carregar_lista
    cab = "RptDt;TckrSymb;Asst;AsstDesc;SgmtNm;MktNm;SctyCtgyNm;SpcfctnCd"
    linhas = [cab,
              "2026-10-16;PETR4;PETR;PETR;CASH;EQUITY-CASH;SHARES;PN      N2",
              "2026-10-16;RENT3;RENT;RENT;CASH;EQUITY-CASH;SHARES;ON      NM",
              "2026-10-16;TAEE11;TAEE;TAEE;CASH;EQUITY-CASH;UNIT;UNT     N2",
              "2026-10-16;TAXA100;TAXA;TAXA;CASH;EQUITY-CASH;SHARES;DIA LIVR",       # não é ação
              "2026-10-16;A1AP34;A1AP;A1AP;CASH;EQUITY-CASH;BDR;DRN",                # BDR
              "2026-10-16;003H11;003H;003H;CASH;EQUITY-CASH;FUNDS;CI",              # FII
              "2026-10-16;PETR4F;PETR;PETR;ODD LOT;EQUITY-CASH;SHARES;PN      N2",   # fracionário
              "2026-10-16;ABCB10;ABCB;ABCB;CASH;EQUITY-CASH;RECEIPTS;PN REC NN2"]   # recibo
    if filtrar(linhas) == ["PETR4", "RENT3", "TAEE11"]:
        ok("Só ações ON/PN/UNIT do lote padrão (sem BDR, FII, fracionário, recibo, taxa)")
    else:
        err(f"Filtro: {filtrar(linhas)}")
    caminho = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "acoes_b3.txt")
    lista = carregar_lista(caminho)
    if len(lista) > 300 and {"PETR4", "RENT3", "VALE3"} <= set(lista) and lista == sorted(set(lista)):
        ok(f"config/acoes_b3.txt com {len(lista)} ações, ordenadas e sem repetição")
    else:
        err(f"Lista: {len(lista)} papéis")


def test_dll_varios_papeis():
    print(f"\n{AMARELO}═══ TESTE 38: ProfitDLL assinando vários papéis ═══{RESET}")
    from profitdll.bridge import ProfitDLLBridge, AGRESSAO_COMPRA
    from profitdll.processo import tick_para_msg, msg_para_tick

    b = ProfitDLLBridge("RENT3", extras=["PETR4", "rent3", "WDOFUT", "VALE3"])
    if b.papeis == ["RENT3", "PETR4", "VALE3"] and b.recusados == ["WDOFUT"]:
        ok("Papel principal primeiro, sem repetição; futuro recusado na lista (não derruba os outros)")
    else:
        err(f"papeis={b.papeis} recusados={b.recusados}")
    chegou = []
    b.on_tick = chegou.append
    b._processar_trade(3, 8, 100, 38.0, AGRESSAO_COMPRA, 1000.0, 0, 1, "PETR4")
    b._processar_trade(3, 8, 100, 50.0, AGRESSAO_COMPRA, 1001.0, 0, 2)
    if [t.asset for t in chegou] == ["PETR4", "RENT3"]:
        ok("Cada negócio leva o papel (sem papel = o principal)")
    else:
        err(f"ativos: {[t.asset for t in chegou]}")
    st = b.stats()
    if st["papeis"] == {"pedidos": 3, "assinados": 0, "recusados": ["WDOFUT"]}:
        ok("stats() traz papéis pedidos, assinados e recusados")
    else:
        err(f"stats papeis: {st.get('papeis')}")
    t = msg_para_tick(tick_para_msg(chegou[0]))
    if t.asset == "PETR4":
        ok("Protocolo filho → pai leva o papel")
    else:
        err(f"msg sem papel: {tick_para_msg(chegou[0])}")


def test_api_radar():
    print(f"\n{AMARELO}═══ TESTE 39: API do radar e troca de papel da Operar ═══{RESET}")
    import json
    import urllib.error
    import urllib.request
    from api.server import FlowServer
    from core.radar import Radar

    engine = FlowEngine("RENT3", EngineConfig())
    radar = Radar(EngineConfig(), calibracao_tabela={})
    engine.add_tick = radar.envolver(engine.add_tick, engine)
    porta = 15581
    server = FlowServer(engine, host="127.0.0.1", port=porta)
    server.registrar_radar(radar)
    server.start()
    base = f"http://127.0.0.1:{porta}"
    try:
        for ms, preco, qtd, agr in ((0, 50.36, 800, "XP"), (1000, 50.36, 700, "BTG")):
            t = _neg(ms, preco, qtd, agr, Side.SELL, "AGORA")
            t.asset = "RENT3"
            engine.add_tick(t)
        radar.on_renovacao("RENT3", "AGORA", "compra", 50.36, 1_000_000.0)
        radar.on_renovacao("RENT3", "AGORA", "compra", 50.36, 1_000_001.0)
        corpo = json.loads(urllib.request.urlopen(f"{base}/api/radar").read())
        if corpo["resumo"]["segurando"] == 1 and corpo["lista"][0]["corretora"] == "AGORA":
            ok("GET /api/radar traz resumo e lista")
        else:
            err(f"/api/radar: {corpo}")
        vazio = json.loads(urllib.request.urlopen(f"{base}/api/radar?situacao=rompeu").read())
        if vazio["lista"] == []:
            ok("GET /api/radar?situacao filtra")
        else:
            err(f"/api/radar filtro: {vazio}")
        ativos = json.loads(urllib.request.urlopen(f"{base}/api/ativos").read())["ativos"]
        if "PETR4" in ativos and "VALE3" in ativos and len(ativos) > 500 and not any(x.startswith("#") for x in ativos):
            ok("GET /api/ativos traz a lista de papéis do autocompletar")
        else:
            err(f"/api/ativos: {len(ativos)} itens")
        pagina = urllib.request.urlopen(f"{base}/radar")
        if "text/html" in pagina.headers.get("Content-Type", ""):
            ok("GET /radar serve a tela")
        else:
            err(f"/radar: {pagina.headers.get('Content-Type')}")
        pedido = urllib.request.Request(f"{base}/operar/ativo", data=b'{"ativo": "petr4"}', method="POST",
                                        headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(pedido).read())
        if resp == {"ativo": "PETR4", "historico": False} and engine.asset == "PETR4" and engine.get_state()["tick_count"] == 0:
            ok("POST /operar/ativo troca o papel da Operar e zera o motor")
        else:
            err(f"troca de papel: {resp} / {engine.asset}")
        ruim = urllib.request.Request(f"{base}/operar/ativo", data=b'{"ativo": "WDOFUT"}', method="POST")
        try:
            urllib.request.urlopen(ruim)
            err("Futuro deveria dar 400")
        except urllib.error.HTTPError as e:
            if e.code == 400:
                ok("Futuro recusado com 400")
            else:
                err(f"código {e.code}")
    finally:
        server.stop()
        FlowServer.registrar_radar(server, None)


def test_radar_revisao():
    print(f"\n{AMARELO}═══ TESTE 40: Radar — correções da revisão final ═══{RESET}")
    import json
    import types
    import urllib.error
    import urllib.request
    from ctypes import Structure, c_ubyte, c_wchar_p
    from profitdll.bridge import ticker_do_ativo
    from core.radar import Radar
    import main as programa

    # 1) Callback de negócio da DLL: o campo é Ticker (T maiúsculo) no TConnectorAssetIdentifier (profitTypes.py)
    class TConnectorAssetIdentifier(Structure):
        _fields_ = [("Version", c_ubyte), ("Ticker", c_wchar_p), ("Exchange", c_wchar_p), ("FeedType", c_ubyte)]
    real = TConnectorAssetIdentifier(0, "petr4", "B", 0)
    if (ticker_do_ativo(real), ticker_do_ativo(types.SimpleNamespace(ticker="rent3")),
            ticker_do_ativo(types.SimpleNamespace(Ticker=None))) == ("PETR4", "RENT3", ""):
        ok("Papel lido do Ticker (struct da DLL) e do ticker (TAssetID do TinyBook)")
    else:
        err("ticker_do_ativo")

    # 2) Iceberg novo no mesmo nível depois de o antigo sair: registro novo, não some
    def neg(ms, preco, qtd, agr, lado, pas=""):
        t = _neg(ms, preco, qtd, agr, lado, pas)
        t.asset = "RENT3"
        return t
    radar = Radar(EngineConfig(), calibracao_tabela={})
    for t in [neg(0, 50.36, 800, "XP", Side.SELL, "AGORA"), neg(1000, 50.36, 700, "BTG", Side.SELL, "AGORA")]:
        radar.on_tick(t)
    radar.on_renovacao("RENT3", "AGORA", "compra", 50.36, 1_000_000.0)
    radar.on_renovacao("RENT3", "AGORA", "compra", 50.36, 1_000_001.0)   # confirmado_as do que vai romper
    for t in [neg(2000, 50.35, 100, "UBS", Side.SELL, "ITAU"),              # rompe
              neg(3000, 50.32, 100, "UBS", Side.SELL, "ITAU")]:             # 4 ticks além: sai do detector
        radar.on_tick(t)
    for t in [neg(4000, 50.36, 800, "XP", Side.SELL, "AGORA"), neg(5000, 50.36, 700, "BTG", Side.SELL, "AGORA")]:
        radar.on_tick(t)
    radar.on_renovacao("RENT3", "AGORA", "compra", 50.36, 1_000_004.0)
    radar.on_renovacao("RENT3", "AGORA", "compra", 50.36, 1_000_005.0)
    agora = [(r["situacao"], r["confirmado_as"]) for r in radar.lista() if r["corretora"] == "AGORA"]
    if sorted(agora) == [("rompeu", 1_000_001.0), ("segurando", 1_000_005.0)]:
        ok("Mesmo nível, iceberg novo depois do antigo sair: dois registros (rompeu e segurando)")
    else:
        err(f"Registros AGORA: {agora}")

    # 3/4) Radar e motor recebem o negócio sob o lock do engine (GET /api/radar e troca de papel usam o mesmo lock)
    engine = FlowEngine("RENT3", EngineConfig())
    radar = Radar(EngineConfig(), calibracao_tabela={})
    sob_lock = []
    original = radar.on_tick
    radar.on_tick = lambda t: (sob_lock.append(engine._lock._is_owned()), original(t))
    entrega = radar.envolver(lambda t: sob_lock.append(engine._lock._is_owned()), engine)
    entrega(neg(0, 50.36, 100, "XP", Side.BUY, "UBS"))
    if sob_lock == [True, True]:
        ok("Radar e motor recebem o negócio com o lock do engine")
    else:
        err(f"lock: {sob_lock}")

    # 5a) Livro (TinyBook do --asset) só vai ao motor enquanto ele está nesse papel
    chegou = []
    falso = types.SimpleNamespace(asset="PETR4", update_book=lambda niveis: chegou.append(niveis))
    entrega_livro = programa.livro_do_papel_aberto(falso, "PETR4")
    entrega_livro(["n1"])
    falso.asset = "RENT3"
    entrega_livro(["n2"])
    if chegou == [["n1"]]:
        ok("Livro do papel da DLL não vai para a Operar depois da troca de papel")
    else:
        err(f"livro: {chegou}")

    # 5b) Gravação só do papel com que o servidor subiu
    gravados, ao_motor = [], []
    grav = types.SimpleNamespace(envolver=lambda f: (lambda t: (gravados.append(t.asset), f(t))))
    falso = types.SimpleNamespace(asset="RENT3", add_tick=lambda t: ao_motor.append(t.asset))
    programa.envolver_gravacao(falso, grav, "RENT3")
    for ativo in ("RENT3", "PETR4", ""):
        t = _neg(0, 1.0, 100, "XP", Side.BUY, "UBS")
        t.asset = ativo
        falso.add_tick(t)
    if gravados == ["RENT3", ""] and ao_motor == ["RENT3", "PETR4", ""]:
        ok("Gravador grava só o papel original; o motor continua recebendo o que o radar entrega")
    else:
        err(f"gravação: {gravados} / {ao_motor}")

    # 5c) Sem radar não há troca de papel (o motor rotularia o papel antigo como o novo)
    from api.server import FlowServer
    porta = 15583
    server = FlowServer(FlowEngine("RENT3", EngineConfig()), host="127.0.0.1", port=porta)
    server.registrar_radar(None)
    server.start()
    try:
        pedido = urllib.request.Request(f"http://127.0.0.1:{porta}/operar/ativo", data=b'{"ativo": "PETR4"}',
                                        method="POST", headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(pedido)
            err("Sem radar a troca deveria dar 409")
        except urllib.error.HTTPError as e:
            if e.code == 409:
                ok("Sem --radar, POST /operar/ativo responde 409")
            else:
                err(f"código {e.code}")
    finally:
        server.stop()



# ──────────────────────────────────────────────────────────────
# LIVRO DE OFERTAS (book completo por ordem, sem DLL)
# ──────────────────────────────────────────────────────────────

def _array_v2(entradas, flags, datas=None):
    """Monta um array V2 da DLL: cabeçalho (Q, tamanho) + entradas =dqiqH com data de tamanho variável + rodapé de flags."""
    import struct
    corpo = b""
    for i, (preco, qtd, agente, oid) in enumerate(entradas):
        d = (datas[i] if datas else "19/10/2026 10:00:00.123").encode("latin-1")
        corpo += struct.pack("=dqiqH", preco, qtd, agente, oid, len(d)) + d
    corpo += struct.pack("=I", flags)
    return struct.pack("=ii", len(entradas), 8 + len(corpo)) + corpo


def test_livro_decodificador():
    print(f"\n{AMARELO}═══ TESTE 40: Livro de ofertas — decodificador do array V2 ═══{RESET}")
    from profitdll.livro import decodifica_array_v2

    arr = _array_v2([(30.01, 5000, 3, 111), (30.00, 12_000_000_000, 8, 222)], flags=3,
                    datas=["19/10/2026 10:00:00.1", "19/10/2026 10:00:00.123456"])
    entradas, flags = decodifica_array_v2(arr)
    if [(e[0], e[1], e[2], e[3]) for e in entradas] == [(30.01, 5000, 3, 111), (30.00, 12_000_000_000, 8, 222)] and flags == 3:
        ok("1 pacote com datas de tamanhos diferentes: parse sequencial, qtd int64 preservada, flags=3")
    else:
        err(f"decodificação: {entradas} flags={flags}")

    e0, f0 = decodifica_array_v2(_array_v2([], flags=3))
    if e0 == [] and f0 == 3:
        ok("Q=0 devolve lista vazia e as flags do rodapé")
    else:
        err(f"Q=0: {e0} {f0}")

    primeiro, f1 = decodifica_array_v2(_array_v2([(30.0, 1, 1, 1)], flags=2))
    ultimo, f2 = decodifica_array_v2(_array_v2([(29.99, 2, 2, 2)], flags=1))
    if f1 == 2 and f2 == 1 and len(primeiro) == 1 and len(ultimo) == 1:
        ok("Flags de pacote: 2 = primeiro, 1 = último")
    else:
        err(f"flags: {f1} {f2}")

    for nome, ruim in (("truncado", arr[:-9]), ("vazio", b""), ("só cabeçalho parcial", arr[:5]),
                       ("Q absurdo", b"\xff\xff\xff\x7f" + arr[4:])):
        try:
            decodifica_array_v2(ruim)
        except ValueError:
            continue
        err(f"array {nome} deveria levantar ValueError")
    ok("Array corrompido/truncado levanta ValueError (quem chama conta e ignora)")


def test_livro_operacoes():
    print(f"\n{AMARELO}═══ TESTE 41: Livro de ofertas — add/edit/delete/deleteFrom/fullbook ═══{RESET}")
    from profitdll import livro as lv
    from profitdll.livro import LivroOfertas, AT_ADD, AT_EDIT, AT_DELETE, AT_DELETE_FROM, LADO_COMPRA, LADO_VENDA

    L = LivroOfertas()
    # Posição contada do FIM da lista: add com posição 0 entra no fim (melhor nível)
    L.aplicar(AT_ADD, 0, LADO_COMPRA, 29.98, 100, 1, 1001)
    L.aplicar(AT_ADD, 0, LADO_COMPRA, 29.99, 200, 2, 1002)   # fim = melhor
    L.aplicar(AT_ADD, 1, LADO_COMPRA, 29.985, 50, 3, 1003)   # tamanho 2 − 1 = índice 1 (antes do último)
    precos = [o[0] for o in L.compra]
    if precos == [29.98, 29.985, 29.99]:
        ok("atAdd insere em tamanho − posição (posição 0 = fim da lista)")
    else:
        err(f"ordem após adds: {precos}")

    L.aplicar(AT_EDIT, 0, LADO_COMPRA, 0.0, 30, 0, 0)         # edita o último (índice tamanho − 0 − 1)
    if L.compra[-1][1] == 230 and L.compra[-1][0] == 29.99 and L.compra[-1][2] == 2:
        ok("atEdit (EDIT_SOMA=True) soma a quantidade no item da posição contada do fim; agente/preço ausentes preservados")
    else:
        err(f"edit soma: {L.compra[-1]}")
    lv.EDIT_SOMA = False
    try:
        L.aplicar(AT_EDIT, 0, LADO_COMPRA, 0.0, 77, 0, 0)
        if L.compra[-1][1] == 77:
            ok("Com EDIT_SOMA=False o edit substitui a quantidade (fácil de inverter após validar ao vivo)")
        else:
            err(f"edit substitui: {L.compra[-1]}")
    finally:
        lv.EDIT_SOMA = True

    L.aplicar(AT_DELETE, 1, LADO_COMPRA, 0, 0, 0, 0)          # índice 3 − 1 − 1 = 1 (29.985)
    if [o[0] for o in L.compra] == [29.98, 29.99]:
        ok("atDelete remove tamanho − posição − 1")
    else:
        err(f"delete: {L.compra}")

    for i, p in enumerate((30.03, 30.02, 30.01, 30.00)):      # vendas: melhor (menor) no fim
        L.aplicar(AT_ADD, 0, LADO_VENDA, p, 100, 5, 2000 + i)
    L.aplicar(AT_DELETE_FROM, 1, LADO_VENDA, 0, 0, 0, 0)      # índice 4 − 1 − 1 = 2 → apaga do índice 2 em diante
    if [o[0] for o in L.venda] == [30.03, 30.02]:
        ok("atDeleteFrom apaga da posição em diante (até o fim da lista)")
    else:
        err(f"deleteFrom: {L.venda}")
    if L.erros == 0 and L.ordens_total == 4:
        ok("Sem erros; ordens_total soma os dois lados")
    else:
        err(f"erros={L.erros} total={L.ordens_total}")

    # FullBook em vários pacotes: o livro só troca quando fecha o último
    from profitdll.livro import decodifica_array_v2
    p1 = decodifica_array_v2(_array_v2([(10.0, 1, 1, 1)], flags=2))[0]
    p2 = decodifica_array_v2(_array_v2([(10.1, 2, 1, 2)], flags=0))[0]
    p3 = decodifica_array_v2(_array_v2([(10.2, 3, 1, 3)], flags=1))[0]
    L2 = LivroOfertas()
    L2.aplicar(AT_ADD, 0, LADO_COMPRA, 9.0, 9, 9, 9)
    L2.full_book(compra=p1, flags_compra=2)
    L2.full_book(compra=p2, flags_compra=0)
    antes = [o[0] for o in L2.compra]
    L2.full_book(compra=p3, flags_compra=1)
    depois = [o[0] for o in L2.compra]
    if antes == [9.0] and depois == [10.0, 10.1, 10.2]:
        ok("FullBook em 3 pacotes: acumula entre primeiro e último; livro antigo vale até fechar")
    else:
        err(f"fullbook multipacote: antes={antes} depois={depois}")
    L2.full_book(compra=p1, flags_compra=3, venda=[], flags_venda=3)
    if len(L2.compra) == 1 and L2.venda == [] and L2.erros == 0:
        ok("FullBook de pacote único (flags=3) troca na hora; lado vazio (Q=0) esvazia")
    else:
        err(f"fullbook único: {L2.compra} {L2.venda} erros={L2.erros}")
    L2.full_book(compra=p2, flags_compra=0)   # pacote do meio sem começo
    if L2.erros == 1 and len(L2.compra) == 1:
        ok("Pacote do meio/último sem o primeiro é descartado e contado em erros")
    else:
        err(f"pacote órfão: erros={L2.erros} compra={L2.compra}")


def test_livro_snapshot_e_erros():
    print(f"\n{AMARELO}═══ TESTE 42: Livro de ofertas — agregação por preço, corretoras e posição inválida ═══{RESET}")
    from profitdll.livro import LivroOfertas, AT_ADD, AT_EDIT, AT_DELETE, AT_DELETE_FROM, LADO_COMPRA, LADO_VENDA

    L = LivroOfertas()
    L.compra = [[59.04, 1000, 8, 1], [59.05, 3000, 8, 2], [59.05, 2000, 3, 3], [59.05, 1500, 8, 4],
                [59.05, 900, 9, 5], [59.05, 800, 10, 6]]
    L.venda = [[59.07, 400, 3, 7], [59.06, 700, 3, 8], [59.06, 300, 9, 9]]
    nomes = {8: "UBS", 3: "XP INC", 9: "BTG"}
    snap = L.snapshot(n=15, nomes=nomes)
    b0, b1 = snap["bids"][0], snap["bids"][1]
    if b0["price"] == 59.05 and b0["qty"] == 8200 and b0["ordens"] == 5 and b1["price"] == 59.04:
        ok("Bids agregados por preço, do maior para o menor (qtd e nº de ordens somados)")
    else:
        err(f"bids: {snap['bids']}")
    if b0["corretoras"] == [["UBS", 4500], ["XP INC", 2000], ["BTG", 900]]:
        ok("Top 3 corretoras do nível (qtd somada por corretora, nome pelo mapa)")
    else:
        err(f"corretoras: {b0['corretoras']}")
    if [a["price"] for a in snap["asks"]] == [59.06, 59.07] and snap["asks"][0]["qty"] == 1000 and snap["asks"][0]["ordens"] == 2:
        ok("Asks agregados do menor para o maior preço")
    else:
        err(f"asks: {snap['asks']}")
    sem_nome = L.snapshot(n=1, nomes={})
    if sem_nome["bids"][0]["corretoras"][0][0] == "8" and len(sem_nome["bids"]) == 1:
        ok("Sem nome no mapa usa o código como texto; n limita os níveis")
    else:
        err(f"sem nome: {sem_nome['bids']}")
    por_funcao = L.snapshot(n=1, nomes=lambda c: f"C{c}")
    if por_funcao["bids"][0]["corretoras"][0][0] == "C8":
        ok("nomes também aceita função código → nome (resolve só os que aparecem)")
    else:
        err(f"nomes por função: {por_funcao['bids'][0]}")

    # posição inválida: ignora, conta, nunca levanta
    L3 = LivroOfertas()
    resultados = [
        L3.aplicar(AT_EDIT, 0, LADO_COMPRA, 1.0, 1, 1, 1),        # lista vazia
        L3.aplicar(AT_DELETE, 5, LADO_VENDA, 0, 0, 0, 0),
        L3.aplicar(AT_DELETE_FROM, 3, LADO_COMPRA, 0, 0, 0, 0),
        L3.aplicar(AT_ADD, 4, LADO_COMPRA, 1.0, 1, 1, 1),         # posição > tamanho
        L3.aplicar(AT_ADD, -1, LADO_COMPRA, 1.0, 1, 1, 1),
        L3.aplicar(9, 0, LADO_COMPRA, 1.0, 1, 1, 1),              # ação desconhecida
        L3.aplicar(AT_ADD, 0, 7, 1.0, 1, 1, 1),                   # lado desconhecido
    ]
    if resultados == [False] * 7 and L3.erros == 7 and L3.ordens_total == 0:
        ok("Posição/ação/lado inválidos: ignorados, contados em erros, sem exceção")
    else:
        err(f"inválidos: {resultados} erros={L3.erros}")
    if L3.aplicar(AT_ADD, 0, LADO_COMPRA, 1.0, 1, 1, 1) and L3.erros == 7:
        ok("Livro segue utilizável depois dos erros")
    else:
        err("livro quebrou depois dos erros")


def test_livro_bridge():
    print(f"\n{AMARELO}═══ TESTE 43: Livro de ofertas na ponte — taxa, fallback do TinyBook, cópia do array ═══{RESET}")
    import ctypes
    from profitdll.bridge import ProfitDLLBridge, copiar_array_v2
    from profitdll.livro import AT_ADD, AT_FULLBOOK

    # cópia do array dentro do callback (ponteiro só vale ali)
    bruto = _array_v2([(30.0, 100, 3, 1)], flags=3)
    buf = (ctypes.c_ubyte * len(bruto)).from_buffer_copy(bruto)
    ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    copia = copiar_array_v2(ptr)
    buf[0] = 99   # o buffer original muda: a cópia não
    if copia == bruto and copiar_array_v2(ctypes.POINTER(ctypes.c_ubyte)()) is None:
        ok("copiar_array_v2 copia 'tamanho' bytes do cabeçalho; ponteiro nulo devolve None")
    else:
        err("cópia do array")

    def monta(livro_ativo=True):
        b = ProfitDLLBridge("PETR4", intervalo_livro=0.2)
        relogio = {"t": 100.0}
        b._agora = lambda: relogio["t"]
        b.livro_ativo = livro_ativo
        entregues = []
        b.on_book = entregues.append
        b.nomes = {3: "XP INC", 8: "UBS"}
        return b, relogio, entregues

    compra = _array_v2([(29.98, 500, 3, 1), (29.99, 1000, 8, 2), (29.99, 700, 3, 3)], flags=3)
    venda = _array_v2([(30.02, 400, 3, 4), (30.01, 900, 8, 5)], flags=3)
    ev_full = ("oferta", AT_FULLBOOK, 0, 0, 0.0, 0, 0, 0, venda, compra, 1.0)

    b, rel, got = monta()
    b._processar_evento(ev_full)
    n = got[-1]
    bids = [l for l in n if l.side == Side.BUY]
    asks = [l for l in n if l.side == Side.SELL]
    topo_b = max(bids, key=lambda l: l.price)
    if len(bids) == 2 and len(asks) == 2 and topo_b.price == 29.99 and topo_b.qty == 1700 and topo_b.ordens == 2 \
            and topo_b.corretoras == [["UBS", 1000], ["XP INC", 700]] and topo_b.broker == "":
        ok("FullBook vira BookLevel com ordens e corretoras (broker vazio: não alimenta o detector de Best Offer)")
    else:
        err(f"níveis: {[(l.price, l.qty, l.ordens, l.corretoras) for l in n]}")

    # limitação de taxa: várias atualizações dentro do intervalo → 1 entrega; o resto sai no descarregar
    for i in range(10):
        rel["t"] += 0.01
        b._processar_evento(("oferta", AT_ADD, 0, 0, 29.99 + 0.0001 * i, 10, 3, 900 + i, None, None, 1.0))
    if len(got) == 1:
        ok("Taxa limitada: 10 atualizações em 0,1 s não geram entregas extras (intervalo 0,2 s)")
    else:
        err(f"entregas dentro do intervalo: {len(got)}")
    rel["t"] += 0.3
    b._descarregar_livro()
    if len(got) == 2 and b.stats()["livro_atualizacoes"] == 2:
        ok("Pendente é entregue quando o intervalo vence (nada se perde)")
    else:
        err(f"depois de descarregar: {len(got)} {b.stats()}")
    b._descarregar_livro()
    if len(got) == 2:
        ok("Sem nada novo não reenvia")
    else:
        err("reenviou sem mudança")

    # fallback: TinyBook diverge por mais que a tolerância (TOLERANCIA_DIVERGENCIA)
    b, rel, got = monta()
    b._processar_evento(("book", 0, 29.99, 1700, 1.0))
    b._processar_evento(("book", 1, 30.01, 900, 1.0))
    b._processar_evento(ev_full)
    if got and any(l.ordens for l in got[-1]):
        ok("TinyBook coerente com o livro: entrega o livro completo")
    else:
        err("deveria entregar o livro completo")
    rel["t"] += 0.5
    b._processar_evento(("book", 0, 29.50, 100, 2.0))       # TinyBook diz outro bid
    antes = len(got)
    if any(l.ordens for l in got[-1]):
        ok("Divergência abaixo da tolerância: tolera (latência) e continua no livro")
    else:
        err("não deveria cair no topo antes de 1 s")
    from profitdll.bridge import TOLERANCIA_DIVERGENCIA
    rel["t"] += TOLERANCIA_DIVERGENCIA + 0.2
    b._descarregar_livro()
    if len(got) > antes and not any(l.ordens or l.corretoras for l in got[-1]) \
            and {l.price for l in got[-1]} == {29.50, 30.01}:
        ok("Divergência acima da tolerância: volta ao topo do TinyBook (sem corretoras)")
    else:
        err(f"fallback: {[(l.price, l.ordens) for l in got[-1]]}")
    st = b.stats()
    if st["livro_divergencias"] == 1:
        ok("Divergência contada em livro_divergencias")
    else:
        err(f"divergencias: {st['livro_divergencias']}")
    rel["t"] += 0.3
    b._processar_evento(("book", 0, 29.99, 1700, 3.0))      # TinyBook volta a bater
    b._descarregar_livro()
    if any(l.ordens for l in got[-1]):
        ok("TinyBook voltou a bater: retoma o livro completo")
    else:
        err("não retomou o livro")

    # livro_ativo False: só o TinyBook, como antes
    b, rel, got = monta(livro_ativo=False)
    b._processar_evento(ev_full)
    b._processar_evento(("book", 0, 29.99, 1700, 1.0))
    if got and not any(l.ordens for l in got[-1]) and [l.price for l in got[-1]] == [29.99]:
        ok("livro_ativo=False: continua entregando só o topo do TinyBook")
    else:
        err(f"sem livro ativo: {[(l.price, l.ordens) for l in got[-1]] if got else got}")

    # array corrompido: conta erro e não derruba
    b, rel, got = monta()
    b._processar_evento(("oferta", AT_FULLBOOK, 0, 0, 0.0, 0, 0, 0, b"\x01\x02", compra, 1.0))
    st = b.stats()
    if st["livro_erros"] >= 1 and st["livro_ativo"] is True:
        ok("Array corrompido: livro_erros sobe, sem exceção")
    else:
        err(f"stats com array ruim: {st}")
    for k in ("livro_ordens", "livro_erros", "livro_ativo", "livro_atualizacoes"):
        if k not in st:
            err(f"stats sem {k}")
    ok("stats() traz livro_ordens, livro_erros, livro_ativo, livro_atualizacoes")


def test_radar_persistencia():
    print(f"\n{AMARELO}═══ TESTE 53: Radar — histórico dos registros em disco ═══{RESET}")
    import json
    import os
    import tempfile
    from core.radar import Radar, _dia

    def neg(ativo, ms, preco, qtd, agr, lado, pas=""):
        t = _neg(ms, preco, qtd, agr, lado, pas)
        t.asset = ativo
        return t

    with tempfile.TemporaryDirectory() as pasta:
        radar = Radar(EngineConfig(), calibracao_tabela={}, pasta_persistencia=pasta)
        for t in [neg("RENT3", 0, 50.36, 800, "XP", Side.SELL, "AGORA"),
                  neg("PETR4", 10, 38.00, 900, "BTG", Side.BUY, "ITAU"),
                  neg("VALE3", 20, 60.00, 900, "BTG", Side.BUY, "SANTANDER"),
                  neg("RENT3", 1000, 50.36, 700, "BTG", Side.SELL, "AGORA"),
                  neg("PETR4", 1010, 38.00, 600, "XP", Side.BUY, "ITAU"),
                  neg("VALE3", 1020, 60.00, 600, "XP", Side.BUY, "SANTANDER")]:
            radar.on_tick(t)
        for ativo, corr, lado, preco, ts in [("RENT3", "AGORA", "compra", 50.36, 1_000_000.0),
                                              ("RENT3", "AGORA", "compra", 50.36, 1_000_001.0),
                                              ("PETR4", "ITAU", "venda", 38.00, 1_000_000.01),
                                              ("PETR4", "ITAU", "venda", 38.00, 1_000_001.01),
                                              ("VALE3", "SANTANDER", "venda", 60.00, 1_000_000.02),
                                              ("VALE3", "SANTANDER", "venda", 60.00, 1_000_001.02)]:
            radar.on_renovacao(ativo, corr, lado, preco, ts)
        for t in [neg("RENT3", 2000, 50.40, 100, "UBS", Side.BUY, "XP"),         # 4 ticks a favor → segurou
                  neg("PETR4", 3000, 38.01, 100, "UBS", Side.BUY, "XP")]:        # 1 além → rompeu
            radar.on_tick(t)                                                     # VALE3 fica segurando
        antes = {(r["ativo"]): r["situacao"] for r in radar.lista()}
        gravados = radar.salvar()
        dia = _dia(1_000_003.0)
        arq = os.path.join(pasta, f"radar_{dia.isoformat()}.jsonl")
        if gravados == 3 and os.path.exists(arq) and antes == {"RENT3": "segurou", "PETR4": "rompeu", "VALE3": "segurando"}:
            ok("Salva os 3 registros (segurou, rompeu, segurando) em radar_AAAA-MM-DD.jsonl")
        else:
            err(f"Gravados {gravados}; arquivo {os.path.exists(arq)}; antes {antes}")
        if radar.salvar() == 0:
            ok("Sem mudança, não regrava")
        else:
            err("Regravou registros que não mudaram")

        novo = Radar(EngineConfig(), calibracao_tabela={}, pasta_persistencia=pasta)
        n = novo.carregar(dia)
        por = {r["ativo"]: r for r in novo.lista()}
        rent, petr, vale = por.get("RENT3"), por.get("PETR4"), por.get("VALE3")
        if n == 3 and rent and rent["situacao"] == "segurou" and rent["giros"] == 2 and rent["segurou_as"] == 1_000_002.0 \
                and petr and petr["situacao"] == "rompeu" and petr["rompeu_as"] == 1_000_003.0 \
                and rent["volume"] == 1500 and rent["lado"] == "compra":
            ok("Recarrega seguraram e romperam com giros, volume e horários")
        else:
            err(f"Recarregado: {n} {por}")
        if vale and vale["situacao"] == "interrompido" and vale["giros"] == 2:
            ok("O que estava segurando volta como interrompido (sem desfecho conhecido)")
        else:
            err(f"VALE3 recarregado: {vale}")
        resumo = novo.resumo()
        if resumo.get("seguraram") == 1 and resumo.get("romperam") == 1 and resumo.get("interrompidos") == 1 \
                and resumo.get("segurando") == 0:
            ok("Resumo conta seguraram, romperam e interrompidos")
        else:
            err(f"Resumo recarregado: {resumo}")
        # o interrompido (situação alterada ao recarregar) é gravado de novo, e uma terceira subida lê a última linha
        if novo.salvar() == 1:
            ok("Grava só a mudança de situação do interrompido")
        else:
            err("Gravação após recarregar")
        terceiro = Radar(EngineConfig(), calibracao_tabela={}, pasta_persistencia=pasta)
        terceiro.carregar(dia)
        if {r["ativo"]: r["situacao"] for r in terceiro.lista()}["VALE3"] == "interrompido":
            ok("Vale a última linha de cada id")
        else:
            err("Última linha não prevaleceu")
        # linha cortada (queda no meio da escrita) não derruba a subida
        with open(arq, "a", encoding="utf-8") as f:
            f.write('{"id": 9, "ativo": "ABEV3", "corr')
        quarto = Radar(EngineConfig(), calibracao_tabela={}, pasta_persistencia=pasta)
        if quarto.carregar(dia) == 3:
            ok("Linha cortada no fim do arquivo é ignorada")
        else:
            err("Linha cortada")
        # negócio ou giro de DIA ANTERIOR (ex.: "último negócio" antigo de papel ilíquido ao assinar 649 papéis) não pode zerar o dia recarregado
        quinto = Radar(EngineConfig(), calibracao_tabela={}, pasta_persistencia=pasta)
        quinto.carregar(dia)
        quinto.on_tick(neg("ABEV3", -2 * 86_400_000, 14.00, 100, "XP", Side.BUY, "ITAU"))
        quinto.on_renovacao("ABEV3", "ITAU", "venda", 14.00, 1_000_000.0 - 2 * 86_400)
        if len(quinto.lista()) == 3 and quinto.resumo()["negocios"] == 0:
            ok("Negócio/giro de dia anterior é ignorado: o dia recarregado não é apagado")
        else:
            err(f"Dia anterior zerou o radar: {len(quinto.lista())} registros, {quinto.resumo()}")
        quinto.on_tick(neg("ABEV3", 2 * 86_400_000, 14.00, 100, "XP", Side.BUY, "ITAU"))
        if quinto.lista() == [] and quinto._dia == _dia(1_000_000.0 + 2 * 86_400):
            ok("Negócio de dia POSTERIOR vira o dia (zera como antes)")
        else:
            err("A virada para um dia posterior deixou de zerar")
        # replay/sem pasta: não grava nada
        sem = Radar(EngineConfig(), calibracao_tabela={})
        sem.on_tick(neg("RENT3", 0, 50.36, 800, "XP", Side.SELL, "AGORA"))
        if sem.salvar() == 0 and sem.carregar(dia) == 0:
            ok("Sem pasta de persistência o radar não grava nem lê")
        else:
            err("Radar sem pasta gravou ou leu")


def test_livro_protocolo_e_api():
    print(f"\n{AMARELO}═══ TESTE 44: Livro de ofertas — protocolo do processo filho, get_book e POST /book ═══{RESET}")
    import json
    import urllib.error
    import urllib.request
    from profitdll.processo import book_para_msg, msg_para_book, PonteDLLProcesso
    from api.server import FlowServer

    # formato antigo continua valendo (níveis [preco, qtd, lado])
    antigo = {"tipo": "book", "ts": 1000.0, "niveis": [[5078.0, 10, "compra"], [5078.5, 7, "venda"]]}
    n = msg_para_book(antigo)
    if [(x.price, x.qty, x.side, x.ordens, x.corretoras) for x in n] == \
            [(5078.0, 10, Side.BUY, 0, []), (5078.5, 7, Side.SELL, 0, [])]:
        ok("Mensagem no formato antigo [preco, qtd, lado] é lida (ordens=0, corretoras=[])")
    else:
        err(f"formato antigo: {n}")
    sem_extra = book_para_msg([BookLevel(5078.0, 10, "", Side.BUY, 1000.0)], 1000.0)
    if sem_extra["niveis"] == [[5078.0, 10, "compra"]]:
        ok("Nível sem ordens/corretoras continua saindo no formato antigo (3 campos)")
    else:
        err(f"msg sem extra: {sem_extra}")
    novo_niveis = [BookLevel(59.05, 8200, "", Side.BUY, 1000.0, ordens=5, corretoras=[["UBS", 4500], ["XP INC", 2000]]),
                   BookLevel(59.06, 1000, "", Side.SELL, 1000.0, ordens=2, corretoras=[])]
    msg = json.loads(json.dumps(book_para_msg(novo_niveis, 1000.0)))
    n2 = msg_para_book(msg)
    if [(x.price, x.qty, x.side, x.ordens, x.corretoras) for x in n2] == \
            [(59.05, 8200, Side.BUY, 5, [["UBS", 4500], ["XP INC", 2000]]), (59.06, 1000, Side.SELL, 2, [])]:
        ok("Níveis com ordens e corretoras vão e voltam pelo JSON do protocolo")
    else:
        err(f"ida e volta novo: {n2}")

    p = PonteDLLProcesso("PETR4", comando=["x"])
    st = p.stats()
    if st["livro_ativo"] is False and st["livro_ordens"] == 0 and st["livro_erros"] == 0 and st["livro_atualizacoes"] == 0:
        ok("Stats do pai trazem os contadores do livro mesmo sem filho")
    else:
        err(f"stats do pai: {st}")
    p._ultimo = {"livro_ativo": True, "livro_ordens": 40, "livro_erros": 2, "livro_atualizacoes": 9}
    st = p.stats()
    if st["livro_ativo"] is True and st["livro_ordens"] == 40 and st["livro_erros"] == 2 and st["livro_atualizacoes"] == 9:
        ok("Stats novas passam pelo canal de stats existente")
    else:
        err(f"stats do filho: {st}")

    # get_book com campos novos
    engine = FlowEngine("PETR4", EngineConfig())
    engine.update_book([BookLevel(59.05, 100, "", Side.BUY, 1000.0)])
    gb = engine.get_book()
    if gb["fonte"] == "topo" and gb["bids"][0] == {"price": 59.05, "qty": 100, "broker": "", "ordens": 0, "corretoras": [], "fila": []}:
        ok("get_book sem ordens/corretoras: fonte='topo' e campos novos com valor neutro")
    else:
        err(f"get_book topo: {gb}")
    engine.update_book(novo_niveis)
    gb = engine.get_book()
    if gb["fonte"] == "ofertas" and gb["depth"] in ("top", "full") and gb["bids"][0]["ordens"] == 5 \
            and gb["bids"][0]["corretoras"] == [["UBS", 4500], ["XP INC", 2000]] \
            and set(gb) == {"depth", "fonte", "bids", "asks", "updated"}:
        ok("get_book com níveis do livro: fonte='ofertas', ordens e corretoras nos níveis")
    else:
        err(f"get_book ofertas: {gb}")

    # POST /book aceita ordens e corretoras; GET devolve o contrato
    porta = 15599
    server = FlowServer(FlowEngine("PETR4", EngineConfig()), host="127.0.0.1", port=porta)
    server.start()
    base = f"http://127.0.0.1:{porta}"
    try:
        time.sleep(0.3)
        corpo = {"levels": [
            {"side": "compra", "price": 59.05, "qty": 7900, "ordens": 6, "corretoras": [["UBS", 3000], ["XP", 2000]]},
            {"side": "compra", "price": 59.04, "qty": 100},
            {"side": "venda", "price": 59.06, "qty": 500, "ordens": 2, "corretoras": [["BTG", 500]]}]}
        req = urllib.request.Request(base + "/book", data=json.dumps(corpo).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            postado = json.loads(r.read())
        with urllib.request.urlopen(base + "/book") as r:
            livro = json.loads(r.read())
        if postado.get("ok") and livro["fonte"] == "ofertas" and livro["depth"] == "full" \
                and livro["bids"][0] == {"price": 59.05, "qty": 7900, "broker": "", "ordens": 6,
                                         "corretoras": [["UBS", 3000], ["XP", 2000]], "fila": []} \
                and livro["bids"][1]["ordens"] == 0 and livro["asks"][0]["corretoras"] == [["BTG", 500]]:
            ok("POST /book aceita ordens/corretoras opcionais e GET /book devolve o contrato novo")
            print("  contrato GET /book:", json.dumps(livro, ensure_ascii=False))
        else:
            err(f"GET /book: {livro}")
        ruim = {"levels": [{"side": "compra", "price": 1.0, "qty": 1, "corretoras": ["so-um-texto-solto-x"]}]}
        req = urllib.request.Request(base + "/book", data=json.dumps(ruim).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req)
            err("corretoras malformadas deveriam dar 400")
        except urllib.error.HTTPError as e:
            if e.code == 400:
                ok("POST /book com corretoras malformadas responde 400")
            else:
                err(f"status {e.code}")
    finally:
        server.stop()


def test_historico_do_dia():
    print(f"\n{AMARELO}═══ TESTE 45: Histórico do dia ao abrir um papel — portão, ordem do relógio, ponte, protocolo ═══{RESET}")
    import types
    from datetime import datetime
    from core.portao_historico import PortaoHistorico
    from profitdll.bridge import ProfitDLLBridge, FUSO_B3
    from profitdll.processo import historico_para_msgs, msg_para_tick, PonteDLLProcesso

    def tk(ts, preco=10.0, qtd=100, lado=Side.BUY, corretora="XP", ativo="B3SA3"):
        return Tick(timestamp=ts, price=preco, qty=qtd, broker=corretora, side=lado, asset=ativo)

    # 1) o ao vivo espera; o histórico entra na ordem do relógio; o que já estava no histórico não repete
    motor, gravado = [], []
    portao = PortaoHistorico(types.SimpleNamespace(), entrega_direta=motor.append)
    entrega = portao.envolver(gravado.append)
    portao.abrir("B3SA3")
    entrega(tk(105.0, 10.2))                          # ao vivo durante o download
    entrega(tk(110.0, 10.3))
    portao.historico("B3SA3", [tk(101.0), tk(105.0, 10.2)])
    portao.historico("B3SA3", [tk(99.0)])            # pedaço fora de ordem: o portão ordena
    if motor == [] and gravado == [] and portao.estado()["carregando"]:
        ok("Enquanto o histórico carrega, o negócio ao vivo do papel aberto fica retido")
    else:
        err(f"retido: {motor} {gravado}")
    portao.fim("B3SA3", 3)
    if [t.timestamp for t in motor] == [99.0, 101.0, 105.0] and [t.timestamp for t in gravado] == [110.0]:
        ok("Histórico vai direto ao motor em ordem cronológica; o ao vivo repetido (105) cai e o novo (110) segue pelo gravador")
    else:
        err(f"ordem: {[t.timestamp for t in motor]} {[t.timestamp for t in gravado]}")
    entrega(tk(120.0))
    if [t.timestamp for t in gravado] == [110.0, 120.0]:
        ok("Depois do fim o negócio ao vivo passa direto")
    else:
        err(f"depois do fim: {gravado}")

    # 2) outro papel não é retido; histórico de papel antigo é ignorado; sem DLL o cancelar solta tudo
    motor, gravado = [], []
    portao = PortaoHistorico(types.SimpleNamespace(), entrega_direta=motor.append)
    entrega = portao.envolver(gravado.append)
    portao.abrir("B3SA3")
    entrega(tk(1.0, ativo="PETR4"))
    portao.historico("PETR4", [tk(0.5, ativo="PETR4")])
    portao.fim("PETR4", 1)
    entrega(tk(2.0))
    if len(gravado) == 1 and gravado[0].asset == "PETR4" and motor == [] and portao.estado()["carregando"]:
        ok("Negócio de outro papel passa; histórico/fim de papel que já não está aberto são ignorados")
    else:
        err(f"outro papel: {gravado} {motor}")
    portao.cancelar()
    if [t.timestamp for t in gravado] == [1.0, 2.0] and not portao.estado()["carregando"]:
        ok("cancelar() solta o retido e segue ao vivo")
    else:
        err(f"cancelar: {gravado}")

    # 3) timeout: o download que não termina não congela o gráfico
    relogio = {"t": 0.0}
    gravado = []
    portao = PortaoHistorico(types.SimpleNamespace(), entrega_direta=lambda t: None, timeout=60.0,
                             relogio=lambda: relogio["t"])
    entrega = portao.envolver(gravado.append)
    portao.abrir("B3SA3")
    entrega(tk(1.0))
    relogio["t"] = 61.0
    entrega(tk(2.0))
    if [t.timestamp for t in gravado] == [1.0, 2.0] and not portao.estado()["carregando"]:
        ok("Passado o timeout o portão abre e entrega o retido")
    else:
        err(f"timeout: {gravado}")

    # 4) ponte: tuplas da DLL viram Ticks do dia (nomes pelo mapa), fim sempre avisa o servidor
    hoje = datetime.now(FUSO_B3).strftime("%d/%m/%Y")
    ponte = ProfitDLLBridge("B3SA3")
    ponte.nomes = {3: "XP", 8: "UBS"}
    entregues = []
    ponte.on_historico = lambda ativo, ticks: entregues.append((ativo, ticks))
    ponte._hist_buffer["B3SA3"] = [
        (f"{hoje} 10:00:01.500", 2, 12.31, 1231.0, 100, 3, 8, 3),   # venda agressora, ponta passiva = comprador 3
        (f"{hoje} 10:00:00.250", 1, 12.30, 1230.0, 200, 3, 8, 2),   # compra agressora
        (f"{hoje} 10:00:02.000", 3, 12.30, 0.0, 100, 3, 8, 4),      # leilão: ignorado
    ]
    ponte._concluir_historico("B3SA3")
    ativo, ticks = entregues[-1]
    if (ativo == "B3SA3" and [t.price for t in ticks] == [12.30, 12.31] and ticks[0].side == Side.BUY
            and ticks[0].broker == "XP" and ticks[0].asset == "B3SA3" and ponte.historico["estado"] == "pronto"
            and ponte.historico["negocios"] == 2):
        ok("Ponte: histórico do dia convertido (ordem do relógio, corretora, leilão fora) e entregue")
    else:
        err(f"ponte: {entregues} {ponte.historico}")
    ponte.asset = "PETR4"
    ponte._hist_buffer["B3SA3"] = [(f"{hoje} 10:00:00.250", 1, 12.30, 1230.0, 200, 3, 8, 2)]
    n = len(entregues)
    ponte._concluir_historico("B3SA3")
    if len(entregues) == n:
        ok("Histórico de um papel que já foi trocado é descartado")
    else:
        err("histórico de papel antigo entregue")
    sem_dll = ProfitDLLBridge("B3SA3")
    vazio = []
    sem_dll.on_historico = lambda a, t: vazio.append((a, t))
    if sem_dll.pedir_historico() is False and vazio == [("B3SA3", [])]:
        ok("Sem DLL/histórico a ponte avisa com lista vazia (o servidor solta o ao vivo)")
    else:
        err(f"sem histórico: {vazio}")

    # 5) protocolo: pedaços + fim; o pai repassa e filtra o livro de papel antigo
    msgs = historico_para_msgs("B3SA3", [tk(float(i)) for i in range(4500)])
    if [len(m.get("ticks", [])) for m in msgs] == [2000, 2000, 500, 0] and msgs[-1] == {"tipo": "historico_fim", "ativo": "B3SA3", "n": 4500}:
        ok("Protocolo: histórico em pedaços de 2000 + mensagem de fim")
    else:
        err(f"protocolo: {[m['tipo'] for m in msgs]}")
    pai = PonteDLLProcesso("B3SA3", comando=["x", "--asset", "B3SA3"])
    chegou = {"ticks": [], "fim": None, "livros": []}
    pai.on_historico = lambda a, t: chegou["ticks"].extend(t)
    pai.on_historico_fim = lambda a, n: chegou.__setitem__("fim", (a, n))
    pai.on_book = chegou["livros"].append
    for m in msgs:
        pai._tratar(m)
    pai._tratar({"tipo": "book", "ts": 1.0, "ativo": "B3SA3", "niveis": [[10.0, 5, "compra"]]})
    pai._tratar({"tipo": "book", "ts": 1.0, "ativo": "PETR4", "niveis": [[9.0, 5, "compra"]]})
    if len(chegou["ticks"]) == 4500 and chegou["fim"] == ("B3SA3", 4500) and len(chegou["livros"]) == 1:
        ok("Pai: recebe o histórico e o fim; livro etiquetado com outro papel é descartado")
    else:
        err(f"pai: {len(chegou['ticks'])} {chegou['fim']} {len(chegou['livros'])}")
    pai._proc = types.SimpleNamespace(poll=lambda: None, stdin=types.SimpleNamespace(
        write=lambda x: chegou.setdefault("escrito", []).append(x), flush=lambda: None))
    if (pai.trocar_ativo("rent3") and chegou["escrito"] == ["trocar RENT3\n"] and pai.asset == "RENT3"
            and pai._comando == ["x", "--asset", "RENT3"]):
        ok("Pai: trocar_ativo manda 'trocar RENT3' ao filho e o Reconectar passa a subir já no papel novo")
    else:
        err(f"trocar: {chegou.get('escrito')} {pai.asset} {pai._comando}")


import threading


def test_giro_lote_minimo():
    print(f"\n{AMARELO}═══ TESTE 52: Giro — lote menor que 1.000 (sniper/pulguinha) não é giro de iceberg ═══{RESET}")
    from core.livro_ofertas import LivroOfertas as LivroGiro, LOTE_MIN_ICEBERG

    def ciclo(livro, lote, oid, ts):
        """A ordem `oid` (já no livro) é agredida por inteiro e a corretora repõe o mesmo lote no mesmo preço
        com outro offer_id: devolve os giros emitidos."""
        livro.negocio("KLBN11", "INTER", "compra", 18.30, lote, ts + 0.1)
        livro.atualizar("KLBN11", "compra", 18.30, 0, "INTER", oid, ts + 0.2, apagar=True)
        return livro.atualizar("KLBN11", "compra", 18.30, lote, "INTER", oid + 1, ts + 0.3)

    livro = LivroGiro(lote_min=LOTE_MIN_ICEBERG)
    livro.atualizar("KLBN11", "compra", 18.30, 100, "INTER", 1, 1000.0)
    giros_100 = sum(len(ciclo(livro, 100, i, 1000.0 + i)) for i in range(1, 9))
    if LOTE_MIN_ICEBERG == 1000 and giros_100 == 0:
        ok("KLBN11: lote de 100 consumido e reposto 8 vezes = 0 giros (era 8: contava a cada lote de 100)")
    else:
        err(f"lote 100: {giros_100} giros")
    livro = LivroGiro(lote_min=LOTE_MIN_ICEBERG)
    livro.atualizar("KLBN11", "compra", 18.30, 1500, "INTER", 1, 1000.0)
    giros_1500 = [len(ciclo(livro, 1500, i, 1000.0 + i)) for i in range(1, 4)]
    if giros_1500 == [1, 1, 1]:
        ok(f"Lote de 1.500 consumido e reposto no mesmo preço pela mesma corretora: 1 giro por reposição ({giros_1500})")
    else:
        err(f"lote 1500: {giros_1500}")
    # mesma quantidade: 1.500 consumidos e repostos com 1.200 = absorção do player; repostos com 1.500 = iceberg
    for repoe, esperado in ((1200, 0), (1500, 1)):
        livro = LivroGiro(lote_min=LOTE_MIN_ICEBERG, mesma_qtd=True)
        livro.atualizar("JP", "venda", 23.50, 1500, "JP MORGAN", 1, 1.0)
        livro.negocio("JP", "JP MORGAN", "venda", 23.50, 1500, 1.1)
        livro.atualizar("JP", "venda", 23.50, 0, "JP MORGAN", 1, 1.2, apagar=True)
        n = len(livro.atualizar("JP", "venda", 23.50, repoe, "JP MORGAN", 2, 1.3))
        if n == esperado:
            ok(f"JP 1.500 consumidos e repostos com {repoe:,}".replace(",", ".") + f": {n} giro" + ("" if n == 1 else "s (outra quantidade)"))
        else:
            err(f"reposição de {repoe}: {n} giros, esperava {esperado}")
    livro = LivroGiro(lote_min=1000)
    livro.atualizar("X", "venda", 10.0, 1000, "UBS", 1, 1.0)
    livro.negocio("X", "UBS", "venda", 10.0, 1000, 1.1)
    livro.atualizar("X", "venda", 10.0, 0, "UBS", 1, 1.2, apagar=True)
    if len(livro.atualizar("X", "venda", 10.0, 1000, "UBS", 2, 1.3)) == 1:
        ok("Exatamente 1.000 já vale (o corte é 'nunca < 1.000')")
    else:
        err("lote de 1.000 não contou")


def test_radar_ordem_giros():
    print(f"\n{AMARELO}═══ TESTE 50: Radar — lista do maior para o menor número de giros ═══{RESET}")
    from core.radar import Radar
    radar = Radar(EngineConfig(), calibracao_tabela={})
    base = 1_000_000.0
    # três registros com giros diferentes e um empate de giros resolvido pelo volume
    for ativo, corr, giros, vol in [("AAA3", "UBS", 2, 900), ("BBB3", "XP", 5, 100), ("CCC3", "BTG", 3, 100), ("DDD3", "JP MORGAN", 3, 700)]:
        radar._seq += 1
        i = radar._seq
        radar._registros[i] = {"ativo": ativo, "corretora": corr, "lado": "compra", "preco": 10.0, "giros": giros,
                               "volume": vol, "confirmado_as": base, "ultimo_giro_as": base + i, "situacao": "segurando",
                               "desfecho_as": None, "segurou_as": None, "rompeu_as": None}
        chave = (ativo, corr, "compra", 1000)
        radar._chave_de[i], radar._atual[chave] = chave, i
    padrao = [r["ativo"] for r in radar.lista()]
    giros = [(r["ativo"], r["giros"]) for r in radar.lista(ordem="giros")]
    if giros == [("BBB3", 5), ("DDD3", 3), ("CCC3", 3), ("AAA3", 2)]:
        ok("ordem='giros': maior primeiro; no empate, o de maior volume (DDD3 700 antes de CCC3 100)")
    else:
        err(f"ordem por giros: {giros}")
    if padrao == ["AAA3", "DDD3", "BBB3", "CCC3"]:
        ok("A ordem padrão (volume) continua a mesma sem o parâmetro")
    else:
        err(f"ordem padrão: {padrao}")
    if [r["ativo"] for r in radar.lista(limite=2, ordem="giros")] == ["BBB3", "DDD3"]:
        ok("O corte por limite vem depois de ordenar: os 2 com mais giros")
    else:
        err("limite + ordem")


def test_radar_agrupa_papel():
    print(f"\n{AMARELO}═══ TESTE 51: Radar — corretoras do mesmo papel e preço agrupadas ═══{RESET}")
    from core.radar import Radar
    radar = Radar(EngineConfig(), calibracao_tabela={})
    base = 1_000_000.0
    linhas = [("MOTV3", "UBS", "venda", 20.70, 4, 5000), ("VALE3", "BTG", "compra", 60.0, 5, 100),
              ("MOTV3", "XP", "venda", 20.70, 2, 9000), ("MOTV3", "CITIGROUP", "venda", 20.70, 3, 300),
              ("MOTV3", "UBS", "compra", 20.60, 2, 100), ("ABEV3", "XP", "compra", 14.0, 4, 100)]
    for ativo, corr, lado, preco, giros, vol in linhas:
        radar._seq += 1
        i = radar._seq
        radar._registros[i] = {"ativo": ativo, "corretora": corr, "lado": lado, "preco": preco, "giros": giros,
                               "volume": vol, "confirmado_as": base, "ultimo_giro_as": base, "situacao": "segurando",
                               "desfecho_as": None, "segurou_as": None, "rompeu_as": None}
        chave = (ativo, corr, lado, int(preco * 100))
        radar._chave_de[i], radar._atual[chave] = chave, i
    lst = radar.lista(ordem="giros")
    quem = [(r["ativo"], r["corretora"], r["preco"]) for r in lst]
    esperado = [("VALE3", "BTG", 60.0),                                              # grupo com 5 giros
                ("MOTV3", "UBS", 20.70), ("MOTV3", "CITIGROUP", 20.70), ("MOTV3", "XP", 20.70),   # 4 giros (UBS), junto
                ("ABEV3", "XP", 14.0),                                                # também 4 giros, mas volume menor
                ("MOTV3", "UBS", 20.60)]
    if quem == esperado:
        ok("MOTV3 @ 20,70: UBS, CITIGROUP e XP juntas, em ordem de giros (4, 3, 2); grupos por giros da 1ª corretora")
    else:
        err(f"agrupamento: {quem}")
    inicios = [r["grupo_inicio"] for r in lst]
    if inicios == [True, True, False, False, True, True]:
        ok("A 1ª linha de cada grupo vem marcada (a tela desenha o separador)")
    else:
        err(f"grupo_inicio: {inicios}")
    if "grupo_inicio" not in radar.lista()[0]:
        ok("Fora da ordem por giros a lista não leva a marca de grupo")
    else:
        err("grupo_inicio vazou na ordem padrão")


def test_giro_por_posicao():
    print(f"\n{AMARELO}═══ TESTE 49: Giro com o livro real — EDIT/DELETE só trazem lado e posição (sem offer_id) ═══{RESET}")
    from profitdll.bridge import (ProfitDLLBridge, AGRESSAO_VENDA, OFERTA_ADD, OFERTA_EDIT, OFERTA_DELETE,
                                  OFERTA_FULL)
    ponte = ProfitDLLBridge("PETR4")
    ponte.nomes = {8: "UBS", 3: "XP"}
    giros = []
    ponte.on_renovacao = lambda *a: giros.append(a)
    ts = 1_000_000.0

    def evento(acao, posicao, qtd=0, oid=0, agente=0, preco=0.0, lado=0, compra=None):
        # formato do callback real: ADD traz tudo; EDIT/DELETE só ação, lado, posição (e nQtd no EDIT)
        tem_add = acao == OFERTA_ADD
        ponte._processar_oferta_giro("PETR4", acao, posicao, lado, qtd, agente, oid, preco,
                                     int(tem_add), int(tem_add or acao == OFERTA_EDIT), int(tem_add), int(tem_add),
                                     compra, None, ts)

    # FullBook da compra: uma ordem SEM agente na frente (posição 1) e a da UBS no fim da lista (posição 0)
    compra = _array_v2([(19.05, 100, 0, 5), (19.04, 1500, 8, 10)], flags=3)
    evento(OFERTA_FULL, 0, compra=compra)
    pos = ponte._livros_pos["PETR4"]
    if len(pos.compra) == 2 and ponte.giro_erros == 0:
        ok("FullBook entra inteiro no livro por posição, inclusive a ordem sem agente")
    else:
        err(f"fullbook: {pos.compra} erros={ponte.giro_erros}")
    ponte._processar_trade(8, 3, 300, 19.04, AGRESSAO_VENDA, ts + 1, ativo="PETR4")    # UBS compra, agressor vende
    evento(OFERTA_EDIT, 0, qtd=-300)                          # nQtd é delta negativo: 1500 → 1200
    ponte._processar_trade(8, 3, 1200, 19.04, AGRESSAO_VENDA, ts + 2, ativo="PETR4")
    evento(OFERTA_DELETE, 0)                                  # lote acabou: some a ordem da frente (posição 0)
    evento(OFERTA_ADD, 0, qtd=1500, oid=11, agente=8, preco=19.04)   # UBS repõe 1.500 no mesmo preço
    if len(giros) == 1 and giros[0][:4] == ("PETR4", "UBS", "compra", 19.04) and ponte.giro_erros == 0:
        ok("Lote de 1.500 consumido (300 + 1.200) e reposto no mesmo preço pela mesma corretora = 1 giro")
    else:
        err(f"giro: {giros} erros={ponte.giro_erros} {ponte.giro_erros_motivo}")
    evento(OFERTA_DELETE, 1)                                  # sai a ordem sem agente: não pode deslocar as outras
    if ponte.giro_erros == 0 and [o[3] for o in pos.compra] == [11]:
        ok("Ordem sem agente participa das posições (apagar a posição 1 não dá erro nem apaga a errada)")
    else:
        err(f"posições: {pos.compra} erros={ponte.giro_erros} {ponte.giro_erros_motivo}")
    evento(OFERTA_DELETE, 5)
    if ponte.giro_erros == 1 and ponte.giro_erros_motivo == {"livro_vazio" if not pos.compra else "posicao_fora_da_lista": 1}:
        ok("Posição fora da lista é contada com o motivo, sem derrubar a ponte")
    else:
        err(f"motivo: {ponte.giro_erros} {ponte.giro_erros_motivo}")


def test_radar_janela():
    print(f"\n{AMARELO}═══ TESTE 48: Radar — janela de 2 e 5 min (icebergs com giro recente) ═══{RESET}")
    from core.radar import Radar

    def neg(ativo, ms, preco, qtd, agr, lado, pas=""):
        t = _neg(ms, preco, qtd, agr, lado, pas)
        t.asset = ativo
        return t

    radar = Radar(EngineConfig(), calibracao_tabela={})
    # RENT3: dois giros no começo; PETR4: dois giros 4 min depois (o "agora" do radar é o do último giro)
    for t in [neg("RENT3", 0, 50.36, 800, "XP", Side.SELL, "AGORA"), neg("RENT3", 1000, 50.36, 700, "BTG", Side.SELL, "AGORA")]:
        radar.on_tick(t)
    radar.on_renovacao("RENT3", "AGORA", "compra", 50.36, 1_000_000.0)
    radar.on_renovacao("RENT3", "AGORA", "compra", 50.36, 1_000_001.0)
    for t in [neg("PETR4", 240_000, 38.00, 900, "BTG", Side.BUY, "ITAU"), neg("PETR4", 241_000, 38.00, 600, "XP", Side.BUY, "ITAU")]:
        radar.on_tick(t)
    radar.on_renovacao("PETR4", "ITAU", "venda", 38.00, 1_000_240.0)
    radar.on_renovacao("PETR4", "ITAU", "venda", 38.00, 1_000_241.0)
    todos = radar.lista()
    d2, d5 = radar.lista(janela=120), radar.lista(janela=300)
    if sorted(r["ativo"] for r in todos) == ["PETR4", "RENT3"] and todos[0]["ultimo_giro_as"] is not None:
        ok("Cada registro leva a hora do último giro")
    else:
        err(f"último giro: {todos}")
    if [r["ativo"] for r in d2] == ["PETR4"]:
        ok("Janela de 2 min: só quem teve giro nos últimos 2 min (RENT3, de 4 min atrás, sai)")
    else:
        err(f"2 min: {[(r['ativo'], r['ultimo_giro_as']) for r in d2]}")
    if [r["ativo"] for r in d5] == ["PETR4", "RENT3"]:
        ok("Janela de 5 min: os dois, o giro mais recente primeiro")
    else:
        err(f"5 min: {[(r['ativo'], r['ultimo_giro_as']) for r in d5]}")
    if len(radar.lista(janela=None)) == 2 and radar.lista("rompeu", janela=120) == []:
        ok("Sem janela volta ao dia inteiro; a janela combina com o filtro de situação")
    else:
        err("janela sem/ com situação")


def test_encerramento_limpo():
    print(f"\n{AMARELO}═══ TESTE 47: POST /encerrar — encerramento limpo (DLL finalizada antes de sair) ═══{RESET}")
    import json
    import urllib.error
    import urllib.request
    from api.server import FlowServer
    engine = FlowEngine("PETR4", EngineConfig())
    servidor = FlowServer(engine, host="127.0.0.1", port=15621)
    servidor.start()
    base = "http://127.0.0.1:15621"
    try:
        pedido = urllib.request.Request(base + "/encerrar", data=b"", method="POST")
        try:
            urllib.request.urlopen(pedido)
            err("POST /encerrar sem função registrada deveria dar 404")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                ok("Sem função de encerramento registrada (outros modos) a rota responde 404")
            else:
                err(f"/encerrar sem função: {e.code}")
        chamadas = []
        feito = threading.Event()
        servidor.registrar_encerrar(lambda: (chamadas.append(1), feito.set()))
        with urllib.request.urlopen(urllib.request.Request(base + "/encerrar", data=b"", method="POST")) as r:
            corpo = json.loads(r.read())
            codigo = r.status
        feito.wait(3)
        if codigo == 202 and corpo.get("ok") and chamadas == [1]:
            ok("POST /encerrar responde 202 e chama o encerramento numa thread própria")
        else:
            err(f"/encerrar: {codigo} {corpo} {chamadas}")
    finally:
        servidor.stop()


def test_livro_giro_escala():
    print(f"\n{AMARELO}═══ TESTE 46: Livro do giro com o radar inteiro — FullBook de centenas de papéis não pode travar ═══{RESET}")
    from core.livro_ofertas import LivroOfertas as LivroGiro
    L = LivroGiro()
    t0 = time.time()
    for a in range(200):
        for lado in ("compra", "venda"):
            ofs = [(a * 100000 + i + (1 if lado == "compra" else 50000), 20 + (i % 60) / 100, 100 + i, f"C{i % 40}")
                   for i in range(800)]
            L.definir(f"A{a}", lado, ofs, 1.0)
    t_carga = time.time() - t0
    t0 = time.time()
    for _ in range(100):
        L.definir("A7", "compra", [(7 * 100000 + i + 1, 20.5, 100, "C1") for i in range(800)], 2.0)
    t_redef = time.time() - t0
    if t_carga < 20 and t_redef < 5:
        ok(f"200 papéis × 2 lados × 800 ordens em {t_carga:.1f}s; 100 redefinições de um livro em {t_redef:.2f}s (sem varrer o índice inteiro)")
    else:
        err(f"livro do giro lento: carga {t_carga:.1f}s, redefinição {t_redef:.1f}s")
    # o índice por papel/lado acompanha add, edit e delete
    L2 = LivroGiro()
    L2.atualizar("X", "compra", 10.0, 500, "UBS", 1, 1.0)
    L2.definir("X", "compra", [(2, 10.0, 300, "XP")], 2.0)
    L2.atualizar("X", "compra", 10.0, 0, "XP", 2, 3.0, apagar=True)
    if L2._por == {} and L2._onde == {} and not any(L2._chaves.values()):
        ok("Índice de chaves e de ofertas fica vazio depois que todas as ofertas saem")
    else:
        err(f"índices: {L2._por} {L2._onde} {L2._chaves}")


def test_leilao():
    print(f"\n{AMARELO}═══ TESTE 54: Leilão de abertura — teórico, sobra, desequilíbrio, escora e perfil ═══{RESET}")
    from core.leilao import PainelLeilao, ConfigLeilao, preco_teorico, sobra, tendencia, no_perfil

    # Teórico: maior quantidade casada; empate desfeito pela menor sobra
    t, q = preco_teorico({10.02: 500, 10.00: 300}, {9.99: 400, 10.01: 300})
    if (t, q) == (10.01, 500):
        ok("Preço teórico = o que casa mais (10,01 casa 500)")
    else:
        err(f"teórico {t} {q}")
    if preco_teorico({9.90: 100}, {10.00: 100}) == (None, 0):
        ok("Livro sem cruzamento não tem teórico")
    else:
        err("livro sem cruzamento")
    c, v, mc, mv = sobra({10.02: 500, 10.00: 300}, {9.99: 400, 10.01: 300}, 10.01, 500)
    if c == {10.00: 300} and v == {10.01: 200} and (mc, mv) == (0, 0):
        ok("Sobra: tira o casado das melhores compras e vendas")
    else:
        err(f"sobra {c} {v}")
    # Ordem a mercado casa em qualquer preço e tem prioridade
    if preco_teorico({10.00: 300}, {10.05: 200}, None, 0, 500) == (10.00, 300):
        ok("Venda a mercado entra na oferta de todos os preços (teórico 10,00 com 300)")
    else:
        err(f"teórico com mercado {preco_teorico({10.00: 300}, {10.05: 200}, None, 0, 500)}")
    if preco_teorico({}, {}, 10.0, 400, 100) == (10.0, 100) and preco_teorico({}, {}, None, 400, 100) == (None, 0):
        ok("Só ordens a mercado: casa na referência (sem referência, sem teórico)")
    else:
        err("só mercado")
    c, v, mc, mv = sobra({10.00: 300}, {10.05: 200}, 10.00, 300, 0, 500)
    if c == {} and v == {10.05: 200} and mv == 200:
        ok("Sobra: a mercado é consumida primeiro (sobram 200 a mercado na venda)")
    else:
        err(f"sobra com mercado {c} {v} {mc} {mv}")

    # Exemplo do VALE3: teórico 45,50, sobram 300 mil na compra (45,00) e 900 mil na venda
    painel = PainelLeilao(ConfigLeilao(escora_min_liq=0))
    painel.cadastrar("VALE3", referencia=45.40, tendencia_="baixa", liquidez=1.5e9)
    painel.ordem("VALE3", 1, "compra", 45.50, 200_000, "XP", 1000.0)
    painel.ordem("VALE3", 2, "venda", 45.50, 200_000, "BTG", 1001.0)
    painel.ordem("VALE3", 3, "compra", 45.00, 300_000, "ITAU", 1002.0)
    for i, (p, qtd) in enumerate([(45.60, 100_000), (45.70, 100_000), (45.80, 100_000), (45.90, 100_000)]):
        painel.ordem("VALE3", 10 + i, "venda", p, qtd, "UBS", 1003.0 + i)
    painel.ordem("VALE3", 20, "venda", 45.65, 500_000, "JP MORGAN", 1010.0)
    r = painel.lista()[0]
    if r["teorico"] == 45.50 and r["qtd_teorica"] == 200_000:
        ok("Teórico 45,50 com 200 mil casados")
    else:
        err(f"teórico {r['teorico']} {r['qtd_teorica']}")
    if (r["banda_compra"], r["banda_venda"], r["desbalanceado"], r["pressao"]) == (300_000, 900_000, "venda", -2):
        ok("300 mil × 900 mil = desbalanceado na venda, seta dupla para baixo (3×)")
    else:
        err(f"desequilíbrio {r}")
    e = r["escora_acima"]
    if e and e["preco"] == 45.65 and e["corretora"] == "JP MORGAN" and e["dist_ticks"] == 15 and r["escora_abaixo"] is None:
        ok("Escora de venda acima: 500 mil do JP MORGAN em 45,65, 15 ticks do teórico")
    else:
        err(f"escora {r['escora_acima']} / {r['escora_abaixo']}")
    if r["no_perfil"]:
        ok("No perfil: desbalanceado na venda, tendência de baixa e escora de venda acima")
    else:
        err("deveria estar no perfil")
    if not no_perfil({**r, "tendencia": "alta"}) and not no_perfil({**r, "escora_acima": None}):
        ok("Fora do perfil com tendência contra ou sem escora do lado")
    else:
        err("perfil sem tendência/escora")

    # Quem entrou e saiu: o evento diz o que fez com o teórico
    painel.ordem("VALE3", 30, "compra", 45.70, 400_000, "GOLDMAN", 1020.0)
    ev = painel.book("VALE3")["eventos"][0]
    if ev["tipo"] == "entrou" and ev["corretora"] == "GOLDMAN" and ev["teorico_antes"] == 45.50 and ev["teorico_depois"] > 45.50:
        ok(f"GOLDMAN entrou na compra e empurrou o teórico (45,50 → {ev['teorico_depois']})")
    else:
        err(f"evento {ev}")
    painel.cancelar("VALE3", 30, 1021.0)
    ev = painel.book("VALE3")["eventos"][0]
    if ev["tipo"] == "saiu" and ev["qtd"] == -400_000 and ev["teorico_depois"] == 45.50:
        ok("GOLDMAN saiu e o teórico voltou a 45,50")
    else:
        err(f"evento de saída {ev}")
    if painel.lista()[0]["delta_ticks"] == 0 and painel.teorico("VALE3") == (45.50, 200_000):
        ok("Δ do teórico na janela volta a zero")
    else:
        err(f"delta {painel.lista()[0]['delta_ticks']}")

    # Δ leilão: ticks do teórico contra o preço em que o leilão começou
    pd = PainelLeilao(tick=0.01)
    pd.definir_teorico("MGLU3", 10.40, 1000, 1000.0)
    seq = []
    for preco in (10.41, 10.43, 10.39, 10.40):
        pd.definir_teorico("MGLU3", preco, 1000, 1001.0)
        seq.append(pd.lista()[0]["delta_ticks"])
    r = pd.lista()[0]
    pd.definir_teorico("MGLU3", 10.42, 1000, 1002.0)
    r2 = pd.lista()[0]
    if (r["cruzou_acima"], r["cruzou_abaixo"]) == (1, 1) and (r2["cruzou_acima"], r2["cruzou_abaixo"]) == (2, 1):
        ok("Cruzadas: subir de 1 a 3 ticks conta uma vez; ir abaixo e voltar acima conta de novo")
    else:
        err(f"cruzadas {r['cruzou_acima']}/{r['cruzou_abaixo']} e {r2['cruzou_acima']}/{r2['cruzou_abaixo']}")
    pd.definir_fase("MGLU3", 0)
    pd.definir_fase("MGLU3", 4)
    pd.definir_teorico("MGLU3", 10.55, 1000, 5000.0)
    if seq == [1, 3, -1, 0] and pd.lista()[0]["delta_ticks"] == 0:
        ok("Δ leilão: +1, +3, −1 e 0 contra o início (10,40); novo leilão parte do novo preço")
    else:
        err(f"delta contra o início {seq} {pd.lista()[0]['delta_ticks']}")

    # Book: sobra (sem o casado) e livro inteiro (cruzado)
    b = painel.book("VALE3", "sobra")
    linha = {n["preco"]: n for n in b["niveis"]}
    if 45.50 in linha and linha[45.50]["teorico"] and linha[45.50]["compra"] == 0 and linha[45.65]["escora"] == "venda":
        ok("Book da sobra marca o teórico e a escora")
    else:
        err(f"book sobra {b['niveis']}")
    if {n["preco"]: n for n in painel.book("VALE3", "livro")["niveis"]}[45.50]["compra"] == 200_000:
        ok("Livro inteiro mostra o casado também")
    else:
        err("livro inteiro")

    # Teórico da DLL prevalece sobre o calculado
    painel.definir_teorico("VALE3", 45.48, 150_000, 1030.0)
    if painel.lista()[0]["teorico"] == 45.48:
        ok("Teórico da DLL vence o calculado")
    else:
        err("teórico da DLL")

    # A mercado e agressiva no painel (preço None = a mercado; além de ±3% do fechamento = agressiva)
    pm = PainelLeilao(ConfigLeilao(escora_min_liq=0))
    pm.cadastrar("PETR4", referencia=38.00)
    pm.definir_livro("PETR4", [("compra", 38.00, 100_000, "XP"), ("venda", 38.00, 100_000, "UBS"),
                               ("compra", None, 300_000, "BTG"), ("compra", 39.50, 50_000, "GENIAL"),
                               ("venda", 38.10, 120_000, "ITAU")], 2000.0)
    r = pm.lista()[0]
    if (r["mercado_compra"], r["agressiva_compra"], r["teorico"], r["qtd_teorica"]) == (300_000, 50_000, 38.10, 220_000):
        ok("Compra a mercado (300 mil) e agressiva a 39,50 (50 mil) puxam o teórico para 38,10 (220 mil casados)")
    else:
        err(f"mercado/agressiva {r}")
    if r["desbalanceado"] == "compra" and r["banda_compra"] == 230_000 and r["banda_venda"] == 0:
        ok("Sobra 230 mil na compra (80 mil a mercado, 50 mil agressiva, 100 mil a 38,00) contra nada na venda")
    else:
        err(f"pressão com mercado {r['banda_compra']} {r['banda_venda']} {r['desbalanceado']}")
    niv = pm.book("PETR4", "livro")["niveis"]
    if niv[0]["mercado"] and niv[0]["compra"] == 300_000 and niv[0]["corretora_compra"] == "BTG" \
            and {n["preco"]: n for n in niv[1:]}[39.5]["agressiva"] == "compra":
        ok("Book: linha 'a mercado' no topo e nível agressivo marcado")
    else:
        err(f"book mercado {niv[:3]}")
    evs = {e["corretora"]: e for e in pm.book("PETR4")["eventos"]}
    if evs["BTG"]["mercado"] and evs["BTG"]["preco"] is None and evs["GENIAL"]["agressiva"] and not evs["XP"]["agressiva"]:
        ok("Eventos marcam a mercado e agressiva")
    else:
        err(f"eventos mercado {evs}")

    fech = [10 + 0.1 * i for i in range(25)]
    if tendencia(fech) == "alta" and tendencia(fech[::-1]) == "baixa" and tendencia([10.0] * 25) == "lateral":
        ok("Tendência: acima da média de 20 subindo = alta; espelho = baixa")
    else:
        err("tendência")


def test_leilao_simulado_e_api():
    print(f"\n{AMARELO}═══ TESTE 55: Leilão simulado e GET /api/leilao ═══{RESET}")
    import json
    import urllib.request
    from api.server import FlowServer
    from core.leilao import PainelLeilao
    from core.leilao_simulado import SimuladorLeilao, DURACAO, ABERTO_POR

    painel = PainelLeilao(fonte="simulado")
    sim = SimuladorLeilao(painel, semente=3, inicio=1_792_000_000.0)
    for _ in range(400):
        sim.passo(1.0)
    lista = painel.lista()
    if len(lista) == 25 and all(r["teorico"] for r in lista) and painel.resumo(lista)["desbal_compra"] > 0 \
            and painel.resumo(lista)["desbal_venda"] > 0:
        ok("Simulador: 25 papéis com teórico e desbalanceados dos dois lados")
    else:
        err(f"simulador {painel.resumo(lista)}")
    while sim.t < painel.abertura_prevista + 1:
        sim.passo(1.0)
    if all(r["fase"] == "aberto" and r["abertura"] for r in painel.lista()):
        ok("Às 10:00 todos abrem no último teórico")
    else:
        err("abertura simulada")
    sim.passo(ABERTO_POR)
    if all(r["fase"] == "pré-abertura" for r in painel.lista()) and sim.t < painel.abertura_prevista:
        ok("Depois de aberto o ciclo recomeça na pré-abertura")
    else:
        err("ciclo do simulador")

    engine = FlowEngine("PETR4", EngineConfig())
    porta = 15583
    server = FlowServer(engine, host="127.0.0.1", port=porta)
    server.start()
    base = f"http://127.0.0.1:{porta}"
    try:
        server.registrar_leilao(None)
        vazio = json.loads(urllib.request.urlopen(f"{base}/api/leilao").read())
        if vazio["resumo"] is None and vazio["lista"] == []:
            ok("GET /api/leilao sem leilão ligado: resumo nulo")
        else:
            err(f"leilão desligado {vazio}")
        server.registrar_leilao(painel)
        corpo = json.loads(urllib.request.urlopen(f"{base}/api/leilao?ativo=vale3&visao=livro").read())
        if corpo["fonte"] == "simulado" and len(corpo["lista"]) == 25 and corpo["book"]["ativo"] == "VALE3" \
                and corpo["book"]["visao"] == "livro" and corpo["resumo"]["papeis"] == 25:
            ok("GET /api/leilao traz lista, resumo e o book do papel pedido")
        else:
            err(f"/api/leilao {corpo.get('resumo')} {corpo.get('book', {}).get('ativo')}")
        pagina = urllib.request.urlopen(f"{base}/leilao")
        if "text/html" in pagina.headers.get("Content-Type", ""):
            ok("GET /leilao serve a tela")
        else:
            err("/leilao")
    finally:
        server.registrar_leilao(None)
        server.stop()


def test_leilao_dll():
    print(f"\n{AMARELO}═══ TESTE 56: Leilão pela ProfitDLL — estado, teórico, retrato do livro e abertura ═══{RESET}")
    from datetime import datetime
    from profitdll.bridge import ProfitDLLBridge, FUSO_B3
    from profitdll.livro import AT_FULLBOOK, AT_ADD
    from profitdll.processo import PonteDLLProcesso
    from core.leilao import PainelLeilao
    import main as principal

    ts = datetime(2026, 10, 27, 9, 50, tzinfo=FUSO_B3).timestamp()
    b = ProfitDLLBridge("PETR4", extras=["VALE3"])
    b.leilao_ligado = True
    msgs = []
    b.on_leilao = msgs.append
    b.nomes = {3: "XP", 8: "UBS"}
    rel = {"t": 100.0}
    b._agora = lambda: rel["t"]

    b._processar_evento(("fase", "VALE3", 13, "27/10/2026 09:45:00", ts))
    if msgs[-1] == {"evento": "fase", "ativo": "VALE3", "codigo": 13, "ts": ts}:
        ok("Estado do papel (13 = pré-abertura) vai para a tela")
    else:
        err(f"fase {msgs}")
    compra = _array_v2([(45.60, 1000, 3, 1), (45.50, 300, 8, 2), (45.50, 200, 8, 3), (0.0, 500, 3, 4)], flags=3)
    venda = _array_v2([(45.40, 800, 8, 5), (45.70, 900, 3, 6)], flags=3)
    b._processar_evento(("offer", "VALE3", AT_FULLBOOK, 0, 0, 0, 0, 0, 0.0, 0, 0, 0, 0, compra, venda, ts))
    msgs.clear()
    rel["t"] += 1.5
    b._descarregar_leilao(agora=ts)
    livro = [m for m in msgs if m["evento"] == "livro"]
    if len(livro) == 1 and sorted(map(tuple, livro[0]["entradas"]), key=str) == sorted([
            ("compra", 45.6, 1000, "XP"), ("compra", 45.5, 500, "UBS"), ("compra", None, 500, "XP"),
            ("venda", 45.4, 800, "UBS"), ("venda", 45.7, 900, "XP")], key=str):
        ok("Retrato do livro em leilão somado por lado, preço e corretora")
    else:
        err(f"retrato {msgs}")
    if ("compra", None, 500, "XP") in map(tuple, livro[0]["entradas"]) and b.leilao_contadores["ordens_a_mercado"] == 1 \
            and b.stats()["leilao"]["amostras"]["mercado"][0] == ["VALE3", "compra", 0.0, 500, 0]:
        ok("Ordem sem preço vai como a mercado (preço None) e entra na amostra com a posição na fila")
    else:
        err(f"a mercado {livro[0]['entradas']} {b.stats()['leilao']}")
    b._processar_evento(("offer", "VALE3", AT_ADD, 0, 0, 700, 3, 9, 0.0, 0, 1, 1, 1, None, None, ts))
    if b._livros_pos["VALE3"].compra[-1][:2] == [0.0, 700]:
        ok("Ordem nova sem preço entra no livro por posição (a fila não desloca)")
    else:
        err(f"add sem preço {b._livros_pos['VALE3'].compra}")
    rel["t"] += 1.5
    b._descarregar_leilao(agora=ts)
    msgs.clear()
    rel["t"] += 1.5
    b._descarregar_leilao(agora=ts)
    if not msgs:
        ok("Livro sem mudança não é reenviado")
    else:
        err(f"reenvio {msgs}")
    rel["t"] = b._ultimo_leilao + 0.3
    b._processar_evento(("offer", "VALE3", AT_ADD, 0, 0, 100, 8, 7, 45.45, 1, 1, 1, 1, None, None, ts))
    b._descarregar_leilao(agora=ts)
    if not msgs:
        ok("Dentro do intervalo de 1 s o retrato espera")
    else:
        err("taxa do retrato")
    rel["t"] += 1.0
    b._descarregar_leilao(agora=ts)
    if msgs and ("compra", 45.45, 100, "UBS") in map(tuple, msgs[-1]["entradas"]):
        ok("Ordem nova entra no próximo retrato")
    else:
        err(f"ordem nova {msgs}")

    b._processar_evento(("teorico", "VALE3", 45.5, 1300, ts))
    b._processar_evento(("teorico", "VALE3", float("-inf"), 0, ts))
    if msgs[-2]["preco"] == 45.5 and msgs[-2]["qtd"] == 1300 and msgs[-1]["preco"] is None:
        ok("Teórico vai para a tela; -INF (sem teórico) vira None")
    else:
        err(f"teórico {msgs[-2:]}")
    b._processar_evento(("trade", 3, 8, 1300, 45.5, 4, ts + 600, 0, 1, "VALE3"))
    if msgs[-1]["evento"] == "abertura" and msgs[-1]["preco"] == 45.5 and b.trades_ignorados == 1:
        ok("Negócio de leilão (tipo 4) abre o papel na tela e continua fora do motor")
    else:
        err(f"abertura {msgs[-1]} {b.trades_ignorados}")

    # Fora do leilão: aberto (0) não manda retrato; sem estado, só na janela 9:30-10:15
    b._processar_evento(("fase", "VALE3", 0, "", ts))
    b._leilao_sujo.add("VALE3")
    b._leilao_sujo.add("PETR4")
    msgs.clear()
    rel["t"] += 2
    b._descarregar_leilao(agora=ts)
    if [m["ativo"] for m in msgs] == ["PETR4"]:
        ok("Papel aberto para de mandar o livro; sem estado, vale a janela do horário")
    else:
        err(f"fora do leilão {msgs}")
    msgs.clear()
    b._leilao_sujo.add("PETR4")
    rel["t"] += 2
    b._descarregar_leilao(agora=ts + 3 * 3600)
    if not msgs:
        ok("Sem estado e fora da janela (12:50): nada")
    else:
        err("janela do horário")
    b2 = ProfitDLLBridge("PETR4")
    b2.on_leilao = msgs.append
    b2._processar_evento(("teorico", "PETR4", 38.0, 100, ts))
    if b2.stats()["leilao"] is None and msgs == []:
        ok("Sem --leilao a ponte não manda nada do leilão")
    else:
        err("leilão desligado")

    # Pai: comando do filho e repasse da mensagem; main: mensagem → painel
    ponte = PonteDLLProcesso("PETR4", radar="lista.txt", leilao=True)
    recebidas = []
    ponte.on_leilao = recebidas.append
    ponte._tratar({"tipo": "leilao", "evento": "teorico", "ativo": "VALE3", "preco": 45.5, "qtd": 10, "ts": ts})
    if "--leilao" in ponte._comando and recebidas and recebidas[0]["ativo"] == "VALE3":
        ok("Processo filho sobe com --leilao e a mensagem chega ao pai")
    else:
        err(f"processo {ponte._comando} {recebidas}")
    painel = PainelLeilao(fonte="dll")
    entregar = principal.entregar_leilao(painel)
    entregar({"evento": "fase", "ativo": "VALE3", "codigo": 13, "ts": ts})
    entregar({"evento": "livro", "ativo": "VALE3", "ts": ts, "entradas": [
        ["compra", 45.6, 1000, "XP"], ["compra", 45.5, 500, "UBS"], ["venda", 45.4, 800, "UBS"], ["venda", 45.7, 900, "XP"]]})
    r = painel.lista()[0]
    if r["fase"] == "pré-abertura" and r["teorico"] == 45.6 and r["qtd_teorica"] == 800 \
            and painel.abertura_prevista == datetime(2026, 10, 27, 10, 0, tzinfo=FUSO_B3).timestamp():
        ok("Painel recebe estado e livro; teórico pelo livro: 45,60 (800 casados com a menor sobra); abertura às 10:00")
    else:
        err(f"painel {r} {painel.abertura_prevista}")
    entregar({"evento": "livro", "ativo": "VALE3", "ts": ts + 1, "entradas": [
        ["compra", 45.6, 1000, "XP"], ["compra", 45.5, 500, "UBS"], ["venda", 45.4, 800, "UBS"], ["venda", 45.7, 900, "XP"],
        ["compra", 45.65, 2000, "GOLDMAN"]]})
    ev = painel.book("VALE3")["eventos"][0]
    if ev["tipo"] == "entrou" and ev["corretora"] == "GOLDMAN" and ev["qtd"] == 2000:
        ok("Retrato novo: quem entrou sai da diferença entre retratos")
    else:
        err(f"evento do retrato {ev}")
    entregar({"evento": "livro", "ativo": "VALE3", "ts": ts + 2, "entradas": [
        ["compra", 45.6, 1000, "XP"], ["compra", 45.5, 500, "UBS"], ["venda", 45.4, 800, "UBS"]]})
    tipos = {(e["corretora"], e["tipo"]) for e in painel.book("VALE3")["eventos"][:2]}
    if tipos == {("GOLDMAN", "saiu"), ("XP", "cancelou")}:
        ok("Saída da corretora e cancelamento de um preço viram eventos")
    else:
        err(f"saída {tipos}")
    entregar({"evento": "teorico", "ativo": "VALE3", "preco": 45.48, "qtd": 700, "ts": ts + 3})
    entregar({"evento": "abertura", "ativo": "VALE3", "preco": 45.48, "ts": ts + 600})
    if painel.lista() == [] and painel.book("VALE3") is None and painel.resumo()["em_leilao"] == 0:
        ok("Abertura tira o papel da tela (lista e book vazios)")
    else:
        err(f"papel aberto ainda na tela {painel.lista()}")
    entregar({"evento": "livro", "ativo": "VALE3", "ts": ts + 601, "entradas": [["compra", 45.5, 100, "XP"]]})
    if painel.lista() == []:
        ok("Livro do pregão aberto não volta o papel à tela")
    else:
        err("livro do pregão aberto reapareceu na tela")
    entregar({"evento": "fase", "ativo": "VALE3", "codigo": 4, "ts": ts + 3600})
    entregar({"evento": "livro", "ativo": "VALE3", "ts": ts + 3601, "entradas": [
        ["compra", 46.0, 300, "BTG"], ["venda", 46.0, 200, "UBS"]]})
    lista = painel.lista()
    b = painel.book("VALE3")
    if len(lista) == 1 and lista[0]["fase"] == "leilão" and b and {e["corretora"] for e in b["eventos"]} == {"BTG", "UBS"}:
        ok("Novo leilão do papel volta à tela sem o estado do anterior")
    else:
        err(f"reentrada no leilão {lista} {b and b['eventos']}")


def test_giro_ordem_a_mercado():
    print(f"\n{AMARELO}═══ TESTE 58: Giro de iceberg ignora ordem a mercado (preço infinito) ═══{RESET}")
    import math
    from core.livro_ofertas import LivroOfertas
    L = LivroOfertas(tick_size=0.01)
    try:
        a = L.definir("PETR4", "compra", [(1, math.inf, 100, "XP"), (2, 10.0, 100, "XP")], 1.0)
        b = L.atualizar("PETR4", "venda", -math.inf, 100, "XP", 3, 1.0)
        c = L.atualizar("PETR4", "venda", math.nan, 100, "XP", 4, 1.0)
        d = L.negocio("PETR4", "XP", "compra", math.inf, 100, 1.0)
    except OverflowError as e:
        err(f"ordem a mercado derrubou o giro: {e}")
        return
    if (a, b, c, d) == ([], [], [], []) and L.preco_de("PETR4", 2) == 10.0 and L.preco_de("PETR4", 1) == 0.0:
        ok("Preço infinito/NaN (a mercado) é ignorado; a ordem de preço normal do mesmo livro fica")
    else:
        err(f"giro com a mercado {(a, b, c, d)} {L.preco_de('PETR4', 2)} {L.preco_de('PETR4', 1)}")
    L.atualizar("PETR4", "compra", 10.0, 100, "XP", 5, 2.0)
    L.atualizar("PETR4", "compra", math.inf, 200, "XP", 5, 2.1)      # mesma oferta vira a mercado: mantém o preço
    if L.preco_de("PETR4", 5) == 10.0:
        ok("Oferta existente que passa a preço infinito mantém o nível anterior")
    else:
        err(f"preço da oferta editada {L.preco_de('PETR4', 5)}")


def test_cotahist():
    print(f"\n{AMARELO}═══ TESTE 57: COTAHIST da B3 — fechamento, tendência e liquidez do leilão ═══{RESET}")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
    from cotahist_b3 import ler_linhas, juntar
    from core.leilao import PainelLeilao

    def linha(data, bdi, ticker, mercado, fech, vol):
        l = ("01" + data + bdi + ticker.ljust(12) + mercado).ljust(108)
        l += f"{round(fech * 100):013d}".ljust(170 - 108, "0") + f"{round(vol * 100):018d}"
        return l.ljust(245)
    # linha real do COTAHIST (PETR4 em 01/09/2026) e as sintéticas
    real = ("012026090102PETR4       010PETROBRAS   PN  EDJ N2   R$  0000000004550000000000469400000000045500000000004643"
            "00000000046870000000004686000000000468775161000000000049726600000000230881483100000000000000009999123100000010"
            "000000000000BRPETRACNPR6230")
    dia = ler_linhas([real, linha("20260901", "96", "PETR4F", "020", 46.0, 1.0), "00COTAHIST.2026BOVESPA 20260930"])
    if dia == {"PETR4": ("2026-09-01", 46.87, 2308814831.0)}:
        ok("Lê o registro 01 (lote padrão, à vista): fechamento 46,87 e R$ 2,3 bi; ignora fracionário e cabeçalho")
    else:
        err(f"COTAHIST {dia}")
    pregoes = [ler_linhas([linha(f"202609{i + 1:02d}", "02", "VALE3", "010", 60 + i, 1e9 + i)]) for i in range(25)]
    series = juntar(pregoes)
    painel = PainelLeilao()
    if painel.carregar_diario(series) == 1:
        p = painel._papeis["VALE3"]
        if p.referencia == 84 and p.tendencia == "alta" and abs(p.liquidez - (1e9 + 14.5)) < 1e-3:
            ok("Diário → fechamento anterior 84, tendência de alta e liquidez média de 20 pregões")
        else:
            err(f"diário {p.referencia} {p.tendencia} {p.liquidez}")
    else:
        err("carregar_diario")


def main():
    print(f"\n{AZUL}╔══════════════════════════════════════════════╗{RESET}")
    print(f"{AZUL}║   FLUXO SERVER — Suite de Testes Automáticos  ║{RESET}")
    print(f"{AZUL}╚══════════════════════════════════════════════╝{RESET}")

    engine = test_iceberg_buy()
    test_iceberg_expira(engine)
    test_urgencia()
    test_absorcao()
    test_delta()
    test_exaustao_topo()
    test_exaustao_fundo()
    test_sem_exaustao()
    test_profitdll()
    test_profitdll_tempo_real()
    test_profitdll_correcoes()
    test_profitdll_nomes_e_descartes()
    test_profitdll_reconexao()
    test_rtd()
    test_api_http()
    test_iceberg_passiva()
    test_iceberg_passivas_espalhadas()
    test_iceberg_fallback()
    test_iceberg_rtd_passiva()
    test_relogio_engine()
    test_replay_leitura()
    test_replay_gravacao()
    test_replay_deterministico()
    test_historico_dll()
    test_historico_limites()
    test_fuso_csv()
    test_argumentos_cli()
    test_desempenho_estado()
    test_api_grafico_tt_book()
    test_resumo_pregao()
    test_log_memoria()
    test_api_health_modo()
    test_api_reconectar()
    test_dll_processo_filho()
    test_main_fonte_dll()
    test_defesas_ordem_original()
    test_defesas_classificacao()
    test_defesas_fila_e2()
    test_defesas_engine()
    test_defesas_aulas()
    test_iceberg_corte_volume()
    test_acerto_iceberg()
    test_defesas_segurou()
    test_livro_ofertas()
    test_radar()
    test_acoes_b3()
    test_dll_varios_papeis()
    test_api_radar()
    test_radar_revisao()
    test_livro_decodificador()
    test_livro_operacoes()
    test_livro_snapshot_e_erros()
    test_livro_bridge()
    test_historico_do_dia()
    test_livro_giro_escala()
    test_encerramento_limpo()
    test_radar_janela()
    test_giro_por_posicao()
    test_giro_lote_minimo()
    test_radar_ordem_giros()
    test_radar_agrupa_papel()
    test_radar_persistencia()
    test_livro_protocolo_e_api()
    test_leilao()
    test_leilao_simulado_e_api()
    test_leilao_dll()
    test_giro_ordem_a_mercado()
    test_cotahist()

    print(f"\n{VERDE}╔══════════════════════════════════════════╗{RESET}")
    print(f"{VERDE}║  ✓  TODOS OS TESTES PASSARAM!             ║{RESET}")
    print(f"{VERDE}╚══════════════════════════════════════════╝{RESET}\n")


if __name__ == "__main__":
    main()
