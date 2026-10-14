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
    bridge.fila.put((3, 8, 10, 5100.0, AGRESSAO_COMPRA, now - 3))
    bridge.fila.put((3, 8, 4,  5100.5, AGRESSAO_VENDA,  now - 2))
    bridge.fila.put((3, 8, 7,  5100.5, 1,               now - 1))   # sem agressão
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
    test_rtd()
    test_api_http()
    test_iceberg_passiva()
    test_iceberg_passivas_espalhadas()
    test_iceberg_fallback()
    test_iceberg_rtd_passiva()

    print(f"\n{VERDE}╔══════════════════════════════════════════╗{RESET}")
    print(f"{VERDE}║  ✓  TODOS OS TESTES PASSARAM!             ║{RESET}")
    print(f"{VERDE}╚══════════════════════════════════════════╝{RESET}\n")


if __name__ == "__main__":
    main()
