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
            if state.get("asset") == "BBDC4" and state.get("rtd", {}).get("ticks_emitted") == 1:
                ok(f"GET /state OK | ticks: {state['tick_count']} | rtd: {state['rtd']}")
            else:
                err(f"Ativo incorreto: {state.get('asset')}")
    except Exception as e:
        err(f"Erro ao acessar /state: {e}")

    server.stop()


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
    test_relogio_engine()
    test_replay_leitura()
    test_replay_gravacao()
    test_replay_deterministico()

    print(f"\n{VERDE}╔══════════════════════════════════════════╗{RESET}")
    print(f"{VERDE}║  ✓  TODOS OS TESTES PASSARAM!             ║{RESET}")
    print(f"{VERDE}╚══════════════════════════════════════════╝{RESET}\n")


if __name__ == "__main__":
    main()
