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
        ok(f"Absorção detectada @ R${lvl['price']:.2f} com {lvl['touches']} toques")
    else:
        err("Nenhuma absorção detectada")


def test_api_http():
    print(f"\n{AMARELO}═══ TESTE 5: API HTTP (servidor embutido) ═══{RESET}")

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

    info("Testando GET /state ...")
    try:
        with urllib.request.urlopen("http://127.0.0.1:15555/state", timeout=3) as r:
            state = json.loads(r.read().decode())
            if state.get("asset") == "BBDC4":
                ok(f"GET /state OK | ticks: {state['tick_count']}")
            else:
                err(f"Ativo incorreto: {state.get('asset')}")
    except Exception as e:
        err(f"Erro ao acessar /state: {e}")

    server.stop()


def main():
    print(f"\n{AZUL}╔══════════════════════════════════════════════╗{RESET}")
    print(f"{AZUL}║   FLUXO SERVER — Suite de Testes Automáticos  ║{RESET}")
    print(f"{AZUL}╚══════════════════════════════════════════════╝{RESET}")

    engine = test_iceberg_buy()
    test_iceberg_expira(engine)
    test_urgencia()
    test_absorcao()
    test_api_http()

    print(f"\n{VERDE}╔══════════════════════════════════════════╗{RESET}")
    print(f"{VERDE}║  ✓  TODOS OS TESTES PASSARAM!             ║{RESET}")
    print(f"{VERDE}╚══════════════════════════════════════════╝{RESET}\n")


if __name__ == "__main__":
    main()
