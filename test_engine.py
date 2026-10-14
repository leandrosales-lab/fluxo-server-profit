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


def test_profitdll():
    print(f"\n{AMARELO}═══ TESTE 9: Ponte ProfitDLL (negócios simulados) ═══{RESET}")

    import json, tempfile, threading
    from profitdll.bridge import (ProfitDLLBridge, trade_para_tick, bolsa_padrao,
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

    if (bolsa_padrao("WDOFUT"), bolsa_padrao("WINZ26"), bolsa_padrao("PETR4")) == ("F", "F", "B"):
        ok("Bolsa inferida: futuros → F, ações → B")
    else:
        err("Inferência de bolsa incorreta")

    # Fila → consumidor → engine, com nomes vindos de JSON
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"3": "xp inc", "8": "UBS"}, f)
    engine = FlowEngine("WDOFUT", EngineConfig(delta_window_sec=60.0))
    bridge = ProfitDLLBridge("WDOFUT", agentes_path=f.name)
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
    engine = FlowEngine("WDOFUT", EngineConfig(tick_size=0.5, delta_window_sec=60.0))
    bridge = ProfitDLLBridge("WDOFUT")
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
    engine2 = FlowEngine("WDOFUT", EngineConfig(tick_size=0.5, delta_window_sec=60.0))
    bridge2 = ProfitDLLBridge("WDOFUT")
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
    if bridge2.stats() | {"fila_pendente": 0} == st_dll | {"fila_pendente": 0}:
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
    if ic["role"] == "suporte" and ic["price"] == 19.04 and ic["renewals"] == 8 \
            and ic["aggressors"] == 8 and not ic["weak_heuristic"]:
        ok(f"Estado: suporte @ 19.04 | 8 execuções de 8 agressores | não é heurística fraca")
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
            and signal.broker == "JP MORGAN" and signal.stop_price < 19.04:
        ok(f"Sinal BUY no suporte, stop {signal.stop_price:.2f}")
    else:
        err(f"Esperado BUY/Iceberg JP MORGAN com stop abaixo: {signal.to_dict()}")

    info("Venda negociada ABAIXO do nível (19.03): o iceberg acabou...")
    engine.add_tick(Tick(ts + 1, 19.03, 200, "RICO", Side.SELL, passive_broker="ITAU"))
    if not engine.get_state()["icebergs_confirmed"]:
        ok("Preço atravessou o nível → iceberg descartado")
    else:
        err("Iceberg deveria ser descartado quando o preço atravessa")

    info("Expiração pelo tempo do TICK (não do relógio local)...")
    engine2 = FlowEngine("PETR4", _cfg_iceberg())
    ts = _base_negocios(engine2, 1_000_000.0)   # tempo antigo: só o tick conta
    for i in range(5):
        ts += 1.0
        engine2.add_tick(Tick(ts, 19.04, 300, f"V{i}", Side.SELL, passive_broker="UBS"))
    antes = len(engine2.get_state()["icebergs_confirmed"])
    engine2.add_tick(Tick(ts + engine2.cfg.iceberg_timeout_sec + 1, 19.05, 100, "X",
                          Side.BUY, passive_broker="Y"))
    depois = len(engine2.get_state()["icebergs_confirmed"])
    if antes == 1 and depois == 0:
        ok("Iceberg confirmado com timestamps antigos e expirado pelo tempo dos ticks")
    else:
        err(f"Expiração pelo tempo do tick falhou: antes={antes} depois={depois}")

    info("Iceberg VENDEDOR: compras agredindo a mesma passiva → resistência...")
    engine3 = FlowEngine("VALE3", _cfg_iceberg())
    ts = time.time() - 20
    for i in range(10):
        ts += 0.5
        engine3.add_tick(Tick(ts, 19.02, 100, f"A{i}", Side.SELL, passive_broker=f"P{i}"))
    for i in range(6):
        ts += 1.0
        engine3.add_tick(Tick(ts, 19.03, 250, f"C{i}", Side.BUY, passive_broker="MORGAN STANLEY"))
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
    cands = [ic for ic in engine._icebergs.values() if ic.passive]
    info(f"Candidatos: {[(c.broker, c.renewals, round(c.share, 2)) for c in cands]}")
    if not state["icebergs_confirmed"]:
        ok("Nenhum iceberg: nenhuma passiva domina o nível")
    else:
        err(f"Agressões espalhadas não deveriam virar iceberg: {state['icebergs_confirmed']}")
    # A fatia conta o volume do nível desde que cada passiva apareceu (~25-31%)
    if len(cands) == 4 and all(c.renewals == 4 and c.share < engine.cfg.iceberg_min_share
                               for c in cands):
        ok("Cada passiva com 4 execuções e fatia ~25-31% do nível (abaixo de iceberg_min_share)")
    else:
        err(f"Candidatos inesperados: {[(c.broker, c.renewals, c.share) for c in cands]}")
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
        ok("3 execuções de 100 com lote médio ~800 não é iceberg (vol_ratio baixo)")
    else:
        err("Volume abaixo de iceberg_vol_ratio não deveria confirmar")


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
_EXEMPLO = os.path.join(_PASTA, "replay", "exemplo_wdo.csv")


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
        "Times & Trades - WDOFUT\n"
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
        engine = FlowEngine("WDOFUT", EngineConfig(tick_size=0.5))
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
        cfg = EngineConfig(tick_size=0.5, flow_pct_threshold=65.0, min_confidence=0.60)
        sinais, player = executar_replay(FlowEngine("WDOFUT", cfg), ler_ticks(_EXEMPLO),
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
        ok("Exemplo WDO gera sinais de exaustão e de absorção")
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
    linhas = rodar_grid(ler_ticks(_EXEMPLO), grade, EngineConfig(tick_size=0.5),
                        asset="WDOFUT", alvo_ticks=4, horizonte_sec=300)
    if len(linhas) == 4 and all("taxa_acerto" in l and "n_sinais" in l for l in linhas):
        resumo = [(l["exhaustion_vol_ratio"], l["exhaustion_reversal_ticks"],
                   l["n_sinais"], l["n_exaustao"]) for l in linhas]
        ok(f"Grid rodou 4 combinações (vol_ratio, reversal, sinais, exaustões): {resumo}")
    else:
        err(f"Grid incorreto: {linhas}")


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
    if caminho_do_dia("historico/wdo_{data}.csv", date(2026, 10, 1)) == "historico/wdo_2026-10-01.csv" \
            and caminho_do_dia("h/{asset}_{data}.csv", date(2026, 10, 1), "WDOFUT") == \
            "h/WDOFUT_2026-10-01.csv":
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
        caminho = caminho_do_dia(os.path.join(pasta, "sub", "wdo_{data}.csv"), date(2026, 10, 14))
        n = gravar_dia(caminho, res.ticks)
        sobras = os.listdir(os.path.dirname(caminho))
        leitura = ler_csv(caminho)
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    if n == 4 and sobras == ["wdo_2026-10-14.csv"]:
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

        # Estáticos: travessia recusada, arquivo inexistente 404
        for rota in ("/static/../server.py", "/static/..%2Fserver.py", "/static/sub/x.js", "/static/naoexiste.js"):
            cod, _, _ = get(rota)
            if cod != 404:
                err(f"{rota} devolveu {cod} (esperado 404)")
        ok("/static recusa '..', subpastas e arquivos inexistentes")

        # /dashboard sem o arquivo → 503; com o arquivo → estado injetado com </ escapado
        original = srv.STATIC_DIR
        with tempfile.TemporaryDirectory() as tmp:
            srv.STATIC_DIR = tmp
            cod, corpo, _ = get("/dashboard")
            if cod == 503:
                ok("/dashboard sem api/static/dashboard.html → 503")
            else:
                err(f"/dashboard sem arquivo devolveu {cod}")
            with open(os.path.join(tmp, "dashboard.html"), "w", encoding="utf-8") as f:
                f.write("<script>var s = __STATE_JSON__;</script>")
            with open(os.path.join(tmp, "x.js"), "w", encoding="utf-8") as f:
                f.write("var x = 1;")
            post("/tick", {"timestamp": t0 + 40, "price": 37.33, "qty": 100,
                           "broker": "</script><b>", "side": "C"})
            cod, corpo, tipo = get("/dashboard")
            html = corpo.decode()
            if cod == 200 and "__STATE_JSON__" not in html and "<\\/script><b>" in html and "text/html" in tipo:
                ok("/dashboard injeta o estado e escapa </ dentro do JSON")
            else:
                err(f"/dashboard incorreto: {cod} {html[:200]}")
            cod, corpo, tipo = get("/static/x.js")
            if cod == 200 and corpo == b"var x = 1;" and tipo.startswith("application/javascript"):
                ok("/static serve .js com o content-type certo")
            else:
                err(f"/static/x.js: {cod} {tipo}")
        srv.STATIC_DIR = original
    finally:
        server.stop()

    # Sinais: só as trocas entram no registro (direto no engine, com um pregão conhecido)
    e = FlowEngine("PETR4", EngineConfig())
    vistos, ultima = [], None
    for i in range(60):
        lado = Side.SELL if i % 5 else Side.BUY
        e.add_tick(Tick(2000 + i, 37.40 if lado == Side.SELL else 37.41, 500, f"C{i % 3}", lado,
                        passive_broker="ITAU" if lado == Side.SELL else "UBS"))
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
    test_fuso_csv()
    test_argumentos_cli()
    test_desempenho_estado()
    test_api_grafico_tt_book()

    print(f"\n{VERDE}╔══════════════════════════════════════════╗{RESET}")
    print(f"{VERDE}║  ✓  TODOS OS TESTES PASSARAM!             ║{RESET}")
    print(f"{VERDE}╚══════════════════════════════════════════╝{RESET}\n")


if __name__ == "__main__":
    main()
