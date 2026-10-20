"""
FLUXO SERVER — Ponto de entrada principal
==========================================
Servidor Python para leitura de fluxo em tempo real
com integração ao Profit Pro.

USO:
  python main.py --asset PETR4 --modo ocr
  python main.py --asset VALE3 --modo dde
  python main.py --asset PETR4 --modo rtd
  python main.py --asset PETR4 --modo dll
  python main.py --asset PETR4 --modo manual --port 5000
  python main.py --asset PETR4 --modo dll --gravar pregao.csv
  python main.py --asset PETR4 --modo replay --arquivo pregao.csv --sem-servidor

MODOS:
  ocr    → Captura tela do Profit via OCR (Tesseract)
  dde    → Lê dados do Profit via DDE (Windows, pywin32) — legado
  rtd    → Recebe dados via Excel RTD Bridge
  dll    → ProfitDLL da Nelogica: cada negócio com lado agressor (recomendado)
  manual → Aguarda dados via POST /tick e /book (testes/integração)
  replay → Roda um pregão gravado em CSV (calibração — veja docs/replay.md)

REQUISITOS:
  Python 3.10+
  pip install mss pillow pytesseract opencv-python   (modo ocr)
  pip install pywin32                                 (modo dde, Windows)
  ProfitDLL.dll + profitTypes.py + variáveis PROFITDLL_* (modo dll, Windows)
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
# MODO PROFITDLL
# ──────────────────────────────────────────────────────────────

def livro_do_papel_aberto(engine, ativo_dll):
    """O livro só vale para o papel que a DLL tem aberto (str, ou função que o devolve: a troca de papel
    da Operar também troca o livro da DLL, e o filho etiqueta cada livro com o papel dele)."""
    def entregar(niveis):
        ativo = ativo_dll() if callable(ativo_dll) else ativo_dll
        if engine.asset == ativo:
            engine.update_book(niveis)
    return entregar


def envolver_gravacao(engine, gravador, ativo: str):
    """Grava só os negócios do papel com que o servidor subiu (o CSV não tem coluna de papel)."""
    motor = engine.add_tick
    gravando = gravador.envolver(motor)

    def entregar(tick):
        (gravando if tick.asset in ("", ativo) else motor)(tick)
    engine.add_tick = entregar


def setup_dll_mode(engine: FlowEngine, args):
    """
    Configura integração com a ProfitDLL (Market Data em tempo real).
    A DLL roda num processo filho: ela não aceita reinicializar no mesmo processo,
    e assim o Reconectar da tela Conexão reinicia só o filho, sem perder o engine.
    """
    from profitdll.processo import PonteDLLProcesso

    lista_radar = (os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "acoes_b3.txt")
                   if getattr(args, "radar", False) else None)
    bridge = PonteDLLProcesso(asset=args.asset, agentes_path=args.agentes, radar=lista_radar)
    bridge.on_tick = engine.add_tick
    bridge.on_book = livro_do_papel_aberto(engine, lambda: bridge.asset)   # livro de ofertas / TinyBook
    return bridge


# ──────────────────────────────────────────────────────────────
# MODO REPLAY
# ──────────────────────────────────────────────────────────────

def iniciar_fonte_dll(engine: FlowEngine, args, server, radar=None, portao=None):
    """
    Cria a ponte da ProfitDLL, registra no servidor (contadores no /state, Reconectar)
    e faz a 1ª conexão. A ponte é devolvida MESMO se essa conexão falhar: o Reconectar
    da tela Conexão pode conectar depois, e o Ctrl+C precisa chamar stop() nela.
    """
    bridge = setup_dll_mode(engine, args)

    def entregar_renovacao(ativo, corretora, lado, preco, ts):
        # Mesmo lock do negócio: a lista do radar e a troca de papel leem com ele
        with engine._lock:
            if radar is not None:
                radar.on_renovacao(ativo, corretora, lado, preco, ts)
            if ativo == engine.asset:
                engine._renovacao_sob_lock(corretora, lado, preco, ts)

    bridge.on_renovacao = entregar_renovacao
    if portao is not None:       # histórico do dia: entra direto no motor, na ordem do relógio
        bridge.on_historico = portao.historico
        bridge.on_historico_fim = portao.fim
        portao.abrir(bridge.asset)
        server.registrar_portao(portao)
    server.registrar_dll(bridge)
    if not bridge.start():
        logger.error("Falha ao iniciar ProfitDLL — veja o log acima (dá para tentar de novo pelo "
                     "Reconectar da tela Conexão)")
    return bridge


def fonte_da_captura(args) -> str:
    """Nome curto da fonte para o cabeçalho das telas (GET /health)."""
    if args.modo == "replay":
        if getattr(args, "radar", False) and getattr(args, "arquivos", None):
            return f"radar ({len(args.arquivos)} pregões)"
        return os.path.basename(args.arquivo or "")
    return {"dll": "ProfitDLL", "rtd": "rtd", "dde": "dde", "ocr": "ocr"}.get(args.modo, "manual")


def rodar_replay_radar(engine: FlowEngine, args, radar):
    """Replay de vários pregões juntos (papel pelo nome do arquivo) alimentando o radar e a Operar."""
    import heapq
    from replay.csv_ticks import ler_ticks
    from replay.player import ReplayPlayer

    listas = []
    for arq in args.arquivos:
        ativo = os.path.basename(arq).split("_")[0].upper()
        ticks = ler_ticks(arq)
        for t in ticks:
            t.asset = ativo
        listas.append(ticks)
        logger.info(f"Radar replay: {len(ticks)} negócios de {ativo} ({arq})")
    todos = list(heapq.merge(*listas, key=lambda t: t.timestamp))
    server = None
    if not args.sem_servidor:
        server = FlowServer(engine, host=args.host, port=args.port, modo="replay", fonte=fonte_da_captura(args))
        server.registrar_radar(radar)
        server.start()
        print(f"  Radar: http://{args.host}:{args.port}/radar   Operar: http://{args.host}:{args.port}/operar")
    try:
        ReplayPlayer(engine, todos, velocidade=args.velocidade).rodar()
    except KeyboardInterrupt:
        logger.info("Replay interrompido")
    print(f"  Radar: {radar.resumo()}")
    sys.stdout.flush()
    if server:
        print("  Replay terminou. O servidor continua no ar (Ctrl+C para sair).")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        server.stop()


def rodar_modo_replay(engine: FlowEngine, args):
    """Roda o CSV pelo engine, imprime o relatório e (opcional) o grid."""
    from replay.csv_ticks import ler_csv
    from replay.player import (executar_replay, montar_relatorio, salvar_sinais_csv,
                               interpretar_grid, rodar_grid, montar_tabela_grid,
                               salvar_grid_csv)

    if not args.arquivo:
        logger.error("Modo replay precisa de --arquivo pregao.csv")
        return
    leitura = ler_csv(args.arquivo)
    ticks = leitura.ticks
    logger.info(f"Replay: {len(ticks)} ticks de {args.arquivo} "
                f"({leitura.linhas_ignoradas} linhas ignoradas) | colunas: {leitura.colunas}")
    if not ticks:
        logger.error("Nenhum tick válido no arquivo")
        return

    # ── Grid de calibração: um replay por combinação, sempre em lote
    if args.grid:
        import copy
        grade = interpretar_grid(args.grid)
        total = 1
        for v in grade.values():
            total *= len(v)
        logger.info(f"Grid: {total} combinações de {list(grade)}")
        linhas = rodar_grid(ticks, grade, base_cfg=copy.deepcopy(engine.cfg),
                            asset=args.asset, alvo_ticks=args.alvo_ticks,
                            horizonte_sec=args.horizonte)
        print(montar_tabela_grid(linhas, list(grade)))
        saida = args.saida or "grid_resultado.csv"
        salvar_grid_csv(saida, linhas)
        print(f"  Resultado completo salvo em {saida}")
        return

    server = None
    if not args.sem_servidor:
        server = FlowServer(engine, host=args.host, port=args.port, modo="replay", fonte=fonte_da_captura(args))
        server.start()
        print(f"  Telas do replay: http://{args.host}:{args.port}/operar  (F2 = Conexão)")

    def ao_sinal(s):
        logger.info(f"[REPLAY] {s.sinal} {s.padrao} @ {s.preco:g} stop {s.stop:g} "
                    f"conf {s.confianca:.2f}")

    try:
        sinais, _ = executar_replay(engine, ticks, args.velocidade,
                                    args.alvo_ticks, args.horizonte, ao_sinal=ao_sinal)
    except KeyboardInterrupt:
        logger.info("Replay interrompido")
        if server:
            server.stop()
        return

    print(montar_relatorio(ticks, sinais, args.alvo_ticks, args.horizonte))
    if args.saida:
        salvar_sinais_csv(args.saida, sinais)
        print(f"  Sinais salvos em {args.saida}")
    sys.stdout.flush()

    if server:
        print("  Replay terminou. O servidor continua no ar com o estado final "
              "(Ctrl+C para sair).")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        server.stop()


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
    p.add_argument("--modo",        default="manual",  choices=["ocr", "dde", "rtd", "dll", "manual", "replay"],
                   help="Modo de captura de dados")
    p.add_argument("--host",        default="127.0.0.1", help="Host do servidor HTTP")
    p.add_argument("--port",        default=5000,      type=int, help="Porta do servidor HTTP")
    p.add_argument("--tt-region",   default=None,
                   help="Região do T&T em pixels: left,top,width,height (modo ocr)")
    p.add_argument("--book-region", default=None,
                   help="Região do Book em pixels: left,top,width,height (modo ocr)")
    p.add_argument("--calibrate",   action="store_true",
                   help="Salvar screenshots de calibração e sair (modo ocr)")
    p.add_argument("--agentes",     default=None,
                   help="JSON {codigo: nome} das corretoras (modo dll)")
    # Gravação e replay
    p.add_argument("--gravar",      default=None,
                   help="Grava cada negócio entregue ao engine neste CSV (qualquer modo)")
    p.add_argument("--arquivo",     default=None,
                   help="CSV do pregão a reproduzir (modo replay)")
    p.add_argument("--radar",       action="store_true",
                   help="Radar de fluxo: icebergs de todas as ações (dll: config/acoes_b3.txt; replay: --arquivos)")
    p.add_argument("--arquivos",    nargs="+", default=None,
                   help="Replay com --radar: vários pregões (papel pelo nome, ex.: rent3_2026-10-16.csv)")
    p.add_argument("--velocidade",  default=0.0, type=float,
                   help="Replay: 0 = máximo, 1 = tempo real, N = N vezes mais rápido")
    p.add_argument("--sem-servidor", action="store_true",
                   help="Replay em lote, sem servidor HTTP")
    p.add_argument("--alvo-ticks",  default=4.0, type=float,
                   help="Replay: ticks a favor que contam como acerto (padrão 4)")
    p.add_argument("--horizonte",   default=300.0, type=float,
                   help="Replay: segundos após o sinal para medir o resultado (padrão 300)")
    p.add_argument("--grid",        nargs="+", default=None, metavar="PARAM=V1,V2",
                   help="Replay: varre combinações do EngineConfig "
                        "(ex: exhaustion_vol_ratio=0.5,0.6 exhaustion_reversal_ticks=2,3)")
    p.add_argument("--saida",       default=None,
                   help="Replay: CSV com os sinais (ou com o grid, se --grid)")
    # Parâmetros do motor
    # None = não informada: vale o padrão/conhecimento (as informadas vencem, ver config/cli_overrides.py)
    p.add_argument("--flow-window",    default=None, type=float, help="Janela de fluxo (seg). Padrão 30")
    p.add_argument("--flow-pct",       default=None, type=float, help="%% mínimo de fluxo dominante. Padrão 65")
    p.add_argument("--iceberg-min",    default=None, type=int,   help="Renovações mínimas do Iceberg. Padrão 3")
    p.add_argument("--tick-size",      default=0.01, type=float, help="Tamanho do tick do ativo")
    p.add_argument("--min-confidence", default=None, type=float, help="Confiança mínima para sinal. Padrão 0.60")
    args = p.parse_args()
    from profitdll.bridge import validar_ativo
    try:
        args.asset = validar_ativo(args.asset)      # só ações
    except ValueError as e:
        p.error(str(e))
    return args


def main():
    args = parse_args()

    # ── Criar motor de fluxo
    from config.knowledge_loader import carregar_conhecimento
    from config.cli_overrides import aplicar_argumentos

    engine = FlowEngine(asset=args.asset, config=EngineConfig(tick_size=args.tick_size))

    # ── Aplicar conhecimento extraído dos vídeos
    try:
        from config.conhecimento_videos import aplicar_conhecimento
        aplicar_conhecimento(engine)
    except Exception as e:
        logger.warning(f"Conhecimento dos vídeos não carregado: {e}")

    # ── Carregar ajustes do JSON de conhecimento (gerado pelo transcritor)
    carregar_conhecimento(engine)

    # ── Por último, as opções digitadas na linha de comando (vencem o conhecimento)
    aplicar_argumentos(engine.cfg, args)

    # ── Histórico do dia (modo dll): o motor abre no início do pregão; o ao vivo espera o download
    add_tick_puro = engine.add_tick
    portao = None
    if args.modo == "dll":
        from core.portao_historico import PortaoHistorico
        portao = PortaoHistorico(engine, entrega_direta=add_tick_puro)

    # ── Gravação: cada tick entregue ao engine também vai para o CSV
    gravador = None
    if args.gravar:
        import atexit
        from replay.csv_ticks import GravadorTicks
        gravador = GravadorTicks(args.gravar)
        envolver_gravacao(engine, gravador, engine.asset)
        atexit.register(gravador.fechar)

    if portao is not None:
        engine.add_tick = portao.envolver(engine.add_tick)

    # ── Radar de fluxo: todo negócio vai ao radar; só o do papel aberto segue para o motor (e o gravador)
    radar = None
    if args.radar:
        from core.radar import Radar
        radar = Radar(engine.cfg)
        engine.add_tick = radar.envolver(engine.add_tick, engine)

    # ── Modo replay: roda o arquivo e sai (não precisa de captura nem reset diário)
    if args.modo == "replay":
        if radar is not None and args.arquivos:
            rodar_replay_radar(engine, args, radar)
        else:
            rodar_modo_replay(engine, args)
        if gravador:
            gravador.fechar()
        return

    # ── Calibração OCR
    if args.calibrate and args.modo == "ocr":
        reader = setup_ocr_mode(engine, args)
        if reader:
            reader.calibrate()
        return

    # ── Iniciar servidor HTTP
    server = FlowServer(engine, host=args.host, port=args.port, modo=args.modo, fonte=fonte_da_captura(args))
    if radar is not None:
        server.registrar_radar(radar)
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

    elif args.modo == "dll":
        data_source = iniciar_fonte_dll(engine, args, server, radar, portao)

    elif args.modo == "rtd":
        logger.info("Modo RTD — dados recebidos via Excel RTD Bridge (POST /tick)")
        logger.info("Abra o Excel com FLUXO_BRIDGE_RTD.bas e execute IniciarBridge()")

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
    print(f"  Telas:    http://{args.host}:{args.port}/operar  (F2 = Conexão)")
    print("=" * 60)
    print()

    # ── Aguardar sinal de encerramento
    def handle_exit(sig, frame):
        logger.info("Encerrando servidor...")
        if data_source:
            data_source.stop()
        server.stop()
        if gravador:
            gravador.fechar()
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
