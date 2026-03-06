"""
FLUXO SERVER — Ponto de entrada principal
==========================================
Servidor Python para leitura de fluxo em tempo real
com integração ao Profit Pro.

USO:
  python main.py --asset PETR4 --modo ocr
  python main.py --asset VALE3 --modo dde
  python main.py --asset PETR4 --modo manual --port 5000

MODOS:
  ocr    → Captura tela do Profit via OCR (Tesseract)
  dde    → Lê dados do Profit via DDE (Windows, pywin32)
  manual → Aguarda dados via POST /tick e /book (testes/integração)

REQUISITOS:
  Python 3.10+
  pip install mss pillow pytesseract opencv-python   (modo ocr)
  pip install pywin32                                 (modo dde, Windows)
"""

import sys
import time
import logging
import argparse
import threading
import signal
import os
from datetime import datetime

# ── Configurar logging
_LOG_DIR = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)  # cria a pasta logs se não existir

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            os.path.join(_LOG_DIR, f"fluxo_{datetime.now().strftime('%Y%m%d')}.log"),
            encoding="utf-8"
        )
    ]
)
logger = logging.getLogger("Main")

# ── Importações internas
sys.path.insert(0, os.path.dirname(__file__))
from core.engine import FlowEngine, Tick, BookLevel, Side, EngineConfig
from api.server  import FlowServer


# ──────────────────────────────────────────────────────────────
# MODO OCR
# ──────────────────────────────────────────────────────────────

def setup_ocr_mode(engine: FlowEngine, args):
    """Configura captura de tela via OCR."""
    try:
        from ocr.screen_reader import ScreenReader, ScreenConfig, Region, TTTrade, BookRow
    except ImportError:
        logger.error("Módulo OCR não encontrado")
        return None

    cfg = ScreenConfig()

    # Ajustar coordenadas se fornecidas nos argumentos
    if args.tt_region:
        l, t, w, h = map(int, args.tt_region.split(","))
        cfg.tt_region = Region(l, t, w, h)
    if args.book_region:
        l, t, w, h = map(int, args.book_region.split(","))
        cfg.book_region = Region(l, t, w, h)

    reader = ScreenReader(cfg)

    def on_tick(trade: TTTrade):
        side = Side.BUY if trade.side == "C" else Side.SELL
        tick = Tick(
            timestamp=trade.timestamp,
            price=trade.price,
            qty=trade.qty,
            broker=trade.broker,
            side=side,
        )
        engine.add_tick(tick)
        logger.debug(f"Tick OCR: {trade.broker} {trade.side} "
                     f"@ R${trade.price:.2f} x{trade.qty}")

    def on_book(rows: list[BookRow]):
        levels = []
        for row in rows:
            side = Side.BUY if row.side == "C" else Side.SELL
            levels.append(BookLevel(
                price=row.price, qty=row.qty,
                broker=row.broker, side=side
            ))
        if levels:
            engine.update_book(levels)

    reader.on_tick = on_tick
    reader.on_book = on_book
    return reader


# ──────────────────────────────────────────────────────────────
# MODO DDE
# ──────────────────────────────────────────────────────────────

def setup_dde_mode(engine: FlowEngine, args):
    """Configura integração DDE com Profit Pro."""
    try:
        from dde.dde_bridge import DDEBridge
    except ImportError:
        logger.error("Módulo DDE não encontrado")
        return None

    bridge = DDEBridge(asset=args.asset, poll_interval=0.3)

    def on_tick(data: dict):
        side = Side.BUY if data.get("side", "V").upper() in ("C", "BUY") else Side.SELL
        tick = Tick(
            timestamp=data.get("timestamp", time.time()),
            price=float(data["price"]),
            qty=int(data["qty"]),
            broker=str(data.get("broker", "")),
            side=side,
        )
        engine.add_tick(tick)

    def on_book(data: list):
        levels = []
        for row in data:
            side = Side.BUY if row.get("side", "V").upper() in ("C", "BUY") else Side.SELL
            levels.append(BookLevel(
                price=float(row["price"]),
                qty=int(row["qty"]),
                broker=str(row.get("broker", "")),
                side=side,
            ))
        if levels:
            engine.update_book(levels)

    bridge.on_tick = on_tick
    bridge.on_book = on_book
    return bridge


# ──────────────────────────────────────────────────────────────
# RESET DIÁRIO (meia-noite)
# ──────────────────────────────────────────────────────────────

def schedule_daily_reset(engine: FlowEngine):
    """Agenda reset do motor a cada novo dia de mercado."""
    def _reset_loop():
        last_date = datetime.now().date()
        while True:
            time.sleep(60)
            today = datetime.now().date()
            if today != last_date:
                last_date = today
                engine.reset()
                logger.info(f"Reset diário automático — {today}")
    t = threading.Thread(target=_reset_loop, daemon=True)
    t.start()


# ──────────────────────────────────────────────────────────────
# LOOP DE STATUS
# ──────────────────────────────────────────────────────────────

def status_loop(engine: FlowEngine, interval: int = 30):
    """Loga o estado do motor periodicamente."""
    def _loop():
        while True:
            time.sleep(interval)
            state = engine.get_state()
            sig   = state["signal"]
            logger.info(
                f"[STATUS] {state['asset']} | Ticks: {state['tick_count']} | "
                f"Fluxo: {state['flow_pct_buy']:.1f}%C {state['flow_pct_sell']:.1f}%V | "
                f"Sinal: {sig['signal']} ({sig['pattern']}) "
                f"conf={sig['confidence']:.2f}"
            )
    t = threading.Thread(target=_loop, daemon=True)
    t.start()


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Fluxo Server — Leitura de Fluxo B3")
    p.add_argument("--asset",       default="PETR4",   help="Ticker do ativo (ex: PETR4)")
    p.add_argument("--modo",        default="manual",  choices=["ocr", "dde", "manual"],
                   help="Modo de captura de dados")
    p.add_argument("--host",        default="127.0.0.1", help="Host do servidor HTTP")
    p.add_argument("--port",        default=5000,      type=int, help="Porta do servidor HTTP")
    p.add_argument("--tt-region",   default=None,
                   help="Região do T&T em pixels: left,top,width,height (modo ocr)")
    p.add_argument("--book-region", default=None,
                   help="Região do Book em pixels: left,top,width,height (modo ocr)")
    p.add_argument("--calibrate",   action="store_true",
                   help="Salvar screenshots de calibração e sair (modo ocr)")
    # Parâmetros do motor
    p.add_argument("--flow-window",    default=30.0, type=float, help="Janela de fluxo (seg)")
    p.add_argument("--flow-pct",       default=65.0, type=float, help="%% mínimo de fluxo dominante")
    p.add_argument("--iceberg-min",    default=3,    type=int,   help="Renovações mínimas do Iceberg")
    p.add_argument("--tick-size",      default=0.01, type=float, help="Tamanho do tick do ativo")
    p.add_argument("--min-confidence", default=0.60, type=float, help="Confiança mínima para sinal")
    return p.parse_args()


def main():
    args = parse_args()

    # ── Criar motor de fluxo
    from config.knowledge_loader import carregar_conhecimento

    engine_cfg = EngineConfig(
        flow_window_sec     = args.flow_window,
        flow_pct_threshold  = args.flow_pct,
        iceberg_min_renewals = args.iceberg_min,
        tick_size           = args.tick_size,
        min_confidence      = args.min_confidence,
    )
    engine = FlowEngine(asset=args.asset, config=engine_cfg)

    # ── Aplicar conhecimento extraído dos vídeos
    try:
        from config.conhecimento_videos import aplicar_conhecimento
        aplicar_conhecimento(engine)
    except Exception as e:
        logger.warning(f"Conhecimento dos vídeos não carregado: {e}")

    # ── Carregar ajustes do JSON de conhecimento (gerado pelo transcritor)
    carregar_conhecimento(engine)

    # ── Calibração OCR
    if args.calibrate and args.modo == "ocr":
        reader = setup_ocr_mode(engine, args)
        if reader:
            reader.calibrate()
        return

    # ── Iniciar servidor HTTP
    server = FlowServer(engine, host=args.host, port=args.port)
    server.start()

    # ── Iniciar modo de captura
    data_source = None
    if args.modo == "ocr":
        data_source = setup_ocr_mode(engine, args)
        if data_source:
            ok = data_source.start()
            if not ok:
                logger.error("Falha ao iniciar OCR")
        else:
            logger.error("OCR não disponível — rodando em modo manual")

    elif args.modo == "dde":
        data_source = setup_dde_mode(engine, args)
        if data_source:
            ok = data_source.start()
            if not ok:
                logger.error("Falha ao iniciar DDE")
        else:
            logger.error("DDE não disponível — rodando em modo manual")

    else:
        logger.info("Modo MANUAL — injete dados via POST /tick e /book")

    # ── Agendar reset diário
    schedule_daily_reset(engine)

    # ── Loop de status
    status_loop(engine, interval=30)

    # ── Mensagens de boas-vindas
    print()
    print("=" * 60)
    print(f"  FLUXO SERVER INICIADO")
    print(f"  Ativo:    {args.asset}")
    print(f"  Modo:     {args.modo.upper()}")
    print(f"  API:      http://{args.host}:{args.port}/signal")
    print(f"  Dashboard: http://{args.host}:{args.port}/dashboard")
    print(f"  Abrir o dashboard no navegador para monitorar")
    print("=" * 60)
    print()

    # ── Aguardar sinal de encerramento
    def handle_exit(sig, frame):
        logger.info("Encerrando servidor...")
        if data_source:
            data_source.stop()
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,  handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    # Manter rodando
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        handle_exit(None, None)


if __name__ == "__main__":
    main()
