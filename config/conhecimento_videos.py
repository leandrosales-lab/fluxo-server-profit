"""
CONHECIMENTO EXTRAÍDO DOS 7 VÍDEOS
====================================
Sociedade dos Traders — Trade de Rompimento Escorado em Lote Escondido
391 trechos analisados de 7 vídeos práticos.

USO NO main.py:
    from config.conhecimento_videos import aplicar_conhecimento
    aplicar_conhecimento(engine)
"""

# ══════════════════════════════════════════════════════════════════════
# 1. IDENTIFICAÇÃO DO LOTE ESCONDIDO (Ordem Rotativa)
# ══════════════════════════════════════════════════════════════════════
# "Quando um lote ele repete, assim que consome ele volta"
# "duas, três, quatro, cinco vezes = lote escondido confirmado"

ICEBERG_CONFIG = {
    "min_renovacoes":              3,     # mínimo de repetições para confirmar
    "lote_tolerancia_pct":        20.0,   # variação permitida no lote aparente
    "timeout_seg":                15.0,   # sem renovação = expirado
    # "se o lote escondido é de 1000 e volta 900 = última ordem"
    "detectar_ultimo_lote":        True,
    "ultimo_lote_bonus_confianca": 0.15,  # +15% ao detectar último lote
}

# ══════════════════════════════════════════════════════════════════════
# 2. AS 10 SITUAÇÕES OPERACIONAIS (5 compra + 5 venda)
# Fonte: vídeo 2YLzSJqHgbU — aula completa das 10 situações
# ══════════════════════════════════════════════════════════════════════

SITUACOES = {

    # ── S1: Acumulando + RT na VENDA → Romper (BUY) — MAIS COMUM
    # "ativo quer andar e não anda por conta do lote escondido na venda"
    # "quando esse player sair, o preço desloca"
    "S1_acumulo_RT_venda_romper": {
        "direcao":        "BUY",
        "lote_lado":      "SELL",
        "operacao":       "rompimento",
        "confianca_base": 0.80,
        "premissas":      ["acumulo_tempo", "fluxo_comprador", "indice_subindo", "multiplos_players_comprando"],
    },

    # ── S2: Acumulando + RT na COMPRA → Escorar (BUY)
    # "comprar escorado no lote escondido — stop de 1 centavo"
    "S2_acumulo_RT_compra_escorar": {
        "direcao":        "BUY",
        "lote_lado":      "BUY",
        "operacao":       "escorado",
        "confianca_base": 0.75,
        "stop_ticks":     1,
        "premissas":      ["acumulo_tempo", "indice_subindo"],
    },

    # ── S3: Caindo + RT na COMPRA + índice repica → Repique (BUY)
    # "pararam de agredir o lote + índice subindo + escora formada"
    "S3_caindo_RT_compra_repique": {
        "direcao":        "BUY",
        "lote_lado":      "BUY",
        "operacao":       "repique",
        "confianca_base": 0.65,
        "premissas":      ["parou_agressao_venda", "indice_repicando", "best_offer_compra", "book_escorado"],
    },

    # ── S4: Caindo + RT na VENDA → Romper (SELL)
    # "mercado quer descer, lote escondido na venda, rompe e anda"
    "S4_caindo_RT_venda_romper": {
        "direcao":        "SELL",
        "lote_lado":      "SELL",
        "operacao":       "rompimento",
        "confianca_base": 0.80,
        "premissas":      ["acumulo_tempo", "fluxo_vendedor", "indice_caindo"],
    },

    # ── S5: Subindo + player SOBE RT artificialmente → Reversão (SELL)
    # "player subindo lote escondido 500 kg — artificializando o preço"
    # "quando acaba o preço volta... pares caindo... índice caindo"
    "S5_subindo_RT_artificial_reverter": {
        "direcao":        "SELL",
        "lote_lado":      "BUY",
        "operacao":       "reversao_artificial",
        "confianca_base": 0.70,
        "premissas":      ["pares_caindo", "indice_caindo", "lote_subindo_contra_mercado", "detectar_fim_lote"],
    },

    # ── S6: Acumulando + RT na COMPRA → Romper (SELL)
    "S6_acumulo_RT_compra_romper": {
        "direcao":        "SELL",
        "lote_lado":      "BUY",
        "operacao":       "rompimento",
        "confianca_base": 0.80,
        "premissas":      ["acumulo_tempo", "fluxo_vendedor", "indice_caindo"],
    },

    # ── S7: Acumulando + RT na VENDA → Escorar (SELL)
    # "vendo escorado nele, stop de 1 centavo"
    "S7_acumulo_RT_venda_escorar": {
        "direcao":        "SELL",
        "lote_lado":      "SELL",
        "operacao":       "escorado",
        "confianca_base": 0.75,
        "stop_ticks":     1,
        "premissas":      ["indice_caindo"],
    },

    # ── S8: Subindo + RT na VENDA + exaustão compradora → Reversão (SELL)
    "S8_subindo_RT_venda_reverter": {
        "direcao":        "SELL",
        "lote_lado":      "SELL",
        "operacao":       "reversao",
        "confianca_base": 0.65,
        "premissas":      ["parou_agressao_compra", "best_offer_venda", "indice_fraquejando"],
    },

    # ── S9: Caindo + RT na COMPRA + "último tiro" → Reversão (BUY)
    # "último cara vendendo no fundo com lote escondido, acaba e repica"
    # "os vendidos precisam de liquidez para zerar"
    "S9_caindo_RT_compra_ultimo_tiro": {
        "direcao":        "BUY",
        "lote_lado":      "BUY",
        "operacao":       "reversao_ultimo_tiro",
        "confianca_base": 0.60,
        "premissas":      ["detectar_ultimo_lote", "book_raladinho_baixo", "parou_agressao_venda"],
    },

    # ── S10: Subindo + RT na COMPRA com urgência genuína → Comprar junto (BUY)
    # "ativo subindo, RT na compra, agressão forte em cima dela"
    "S10_subindo_RT_compra_urgencia": {
        "direcao":        "BUY",
        "lote_lado":      "BUY",
        "operacao":       "urgencia_compra",
        "confianca_base": 0.72,
        "premissas":      ["agressao_forte_sobre_RT", "indice_subindo", "players_passando_na_frente"],
    },
}

# ══════════════════════════════════════════════════════════════════════
# 3. PREMISSAS DE QUALIDADE DO SETUP
# Fonte: vídeo lmcHX_-07Ys — aula completa de premissas
# ══════════════════════════════════════════════════════════════════════
# "lote escondido por lote escondido não quer dizer nada — precisa de contexto"

PREMISSAS = {
    "acumulo_min_seg":          600,   # mínimo 10 min acumulando
    "acumulo_ideal_seg":       1200,   # 20 min = setup ideal
    "volume_min_absorvido_kg":   50,   # 50.000 papéis mínimo executados
    "fluxo_dominante_pct":      65.0,  # 65%+ no T&T
    "min_players_mesmo_lado":    2,    # mercado vs 1 player = mercado tende a ganhar
    "requer_contexto_indice":   True,
}

# ══════════════════════════════════════════════════════════════════════
# 4. STOP LOSS E ALVOS
# ══════════════════════════════════════════════════════════════════════

STOP = {
    "escorado_ticks":        1,     # "stop de 1 centavo — se passar o lote não justifica"
    "rompimento_ticks":      2,     # offset do rompimento
    "saida_zero_nao_andar": True,   # "se romper e não andar, sai no 0 a 0"
}

ALVOS = {
    "alvo_por_book":         True,  # "olha o book para cima para definir alvo"
    "cuidado_redondos":      True,  # "R$9,50, R$10 — tendência de segurar"
    "parcial_rompimento":    0.50,  # saída de 50% no rompimento
    "alvo_minimo_pct":      0.008,  # 0.8% do preço mínimo
}

# ══════════════════════════════════════════════════════════════════════
# 5. CORRETORAS DE ALTA RELEVÂNCIA (identificadas nos 7 vídeos)
# ══════════════════════════════════════════════════════════════════════

CORRETORAS_RELEVANTES = [
    "ITAU",           # "Itaú sozinho na compra" / "comprou 100kg em 30 min"
    "GOLDMAN SACHS",  # "Goldman comprando devagar" / "único player segurando"
    "BRADESCO",       # "Bradesco toda hora voltando" / "maior comprado do dia"
    "UBS",            # "UBS maior comprado do dia 132kg"
    "JP MORGAN",      # "JP com meu" / "JP vendendo"
    "BTG PACTUAL",    # "BTG com lote escondido 1000 papéis"
    "SAFRA",          # "Safra no apetite de compra"
    "XP INC",         # "XP 95kg vendido" / "XP sozinha comprando"
    "MORGAN STANLEY", # "Morgan HFT que acumula e sobe preço"
    "SANTANDER",
    "TULET",          # robô que entra a cada 4 segundos
    "CAPITAL",        # "cara da Capital comprando 47kg"
    "GENIAL",
    "CLEAR",
    "C6",
    "MODAL",
    "NECTON",
    "CREDIT",
]

# ══════════════════════════════════════════════════════════════════════
# 6. ALGORITMOS IDENTIFICADOS NOS VÍDEOS
# ══════════════════════════════════════════════════════════════════════

ALGORITMOS = {
    "twap": {
        "corretoras":        ["BRADESCO", "ITAU"],
        "caracteristica":    "executa_tempo_por_quantidade_linha_reta",
        "diferenca_iceberg": "continua_apos_consumido",
    },
    "best_offer": {
        "corretoras":    ["ITAU", "MORGAN STANLEY"],
        "caracteristica": "sempre_primeiro_nivel_book_sobe_junto",
    },
    "morgan_hft": {
        "corretora":    "MORGAN STANLEY",
        "comportamento": "acumula_sobe_preco_devagar_best_offer",
    },
    "tulet_robo": {
        "corretora":     "TULET",
        "comportamento": "executa_mercado_a_cada_4_segundos",
        "intervalo_seg": 4,
    },
    "sniper": {
        "caracteristica":    "ordem_unica_nivel_fixo_nao_volta",
        "como_detectar":     "nivel_vira_vendedor_apos_consumo_total",
        "diferenca_iceberg": "nao_repoe_ordem_apos_consumido",
    },
}

# ══════════════════════════════════════════════════════════════════════
# 7. ARMADILHAS E FAKE SETUPS
# ══════════════════════════════════════════════════════════════════════

ARMADILHAS = {
    # "BTG, Genial: motivam consumo e depois somem — cri cri cri"
    "corretoras_lote_fake":    ["BTG PACTUAL", "GENIAL"],
    # "Zé com Zé: player comprando e vendendo dos dois lados"
    "ze_com_ze":               True,
    # "tirou a camisa da XP e colocou da Tulet — mesmo player"
    "troca_de_corretora":      True,
    # "UBS, marketers — buscam stops da pessoa física"
    "stop_hunt":               ["UBS", "GENIAL", "CLEAR"],
    # "1º rompimento anda muito, 2º/3º cada vez menos"
    "max_rompimentos_dia":     2,
}

# ══════════════════════════════════════════════════════════════════════
# FUNÇÃO PRINCIPAL — Aplicar ao FlowEngine
# ══════════════════════════════════════════════════════════════════════

def aplicar_conhecimento(engine) -> None:
    """
    Aplica as regras extraídas dos 7 vídeos ao FlowEngine.

    Adicione no main.py após criar o engine:
        from config.conhecimento_videos import aplicar_conhecimento
        aplicar_conhecimento(engine)
    """
    import logging
    logger = logging.getLogger("Conhecimento")

    cfg = engine.cfg

    cfg.iceberg_min_renewals    = ICEBERG_CONFIG["min_renovacoes"]
    cfg.iceberg_lot_tolerance   = ICEBERG_CONFIG["lote_tolerancia_pct"]
    cfg.iceberg_timeout_sec     = ICEBERG_CONFIG["timeout_seg"]
    cfg.flow_pct_threshold      = PREMISSAS["fluxo_dominante_pct"]
    cfg.absorption_min_touches  = 4
    cfg.absorption_window_sec   = 60.0   # janela de detecção de toques de absorção (60s)
    cfg.stop_ticks_behind       = STOP["rompimento_ticks"]
    cfg.min_confidence          = 0.60
    cfg.high_relevance_brokers  = CORRETORAS_RELEVANTES

    logger.info("=" * 60)
    logger.info("  CONHECIMENTO DOS 7 VÍDEOS APLICADO AO MOTOR")
    logger.info("=" * 60)
    logger.info(f"  Renovações mínimas     : {cfg.iceberg_min_renewals}")
    logger.info(f"  Tolerância de lote     : {cfg.iceberg_lot_tolerance}%")
    logger.info(f"  Timeout Iceberg        : {cfg.iceberg_timeout_sec}s")
    logger.info(f"  Fluxo dominante mín.   : {cfg.flow_pct_threshold}%")
    logger.info(f"  Acúmulo mínimo         : {cfg.absorption_window_sec}s ({cfg.absorption_window_sec//60} min)")
    logger.info(f"  Corretoras relevantes  : {len(cfg.high_relevance_brokers)}")
    logger.info(f"  Situações operacionais : {len(SITUACOES)} (10 total)")
    logger.info("=" * 60)
    for nome, s in SITUACOES.items():
        logger.info(f"  [{s['direcao']}] {s['operacao']:25s} conf={s['confianca_base']:.0%}")
    logger.info("=" * 60)


RESUMO = """
METODOLOGIA — TRADE ESCORADO EM LOTE ESCONDIDO
(Extraído de 7 vídeos — Sociedade dos Traders)

O QUE É LOTE ESCONDIDO?
  Player coloca ordem grande com lote APARENTE menor.
  Confirma: lote idêntico repetindo 3+ vezes no mesmo preço.
  Último lote: volta com quantidade MENOR (ex: 900 em vez de 1.000).

DIFERENÇA DOS TIPOS:
  Lote Escondido → mesmo lote, mesmo preço, repõe sempre
  TWAP/Algoritmo → repõe mas quantidades variáveis
  Best Offer     → acompanha o book, SOBE o preço junto
  Sniper         → NÃO repõe após consumido

AS 10 SITUAÇÕES:
  BUY: acumulo+venda→romper | acumulo+compra→escorar |
       caindo+compra→repique | caindo+venda→romper | último tiro
  SELL: acumulo+compra→romper | acumulo+venda→escorar |
        subindo+venda→reverter | artificial→reverter | urgência vendedora

PREMISSAS (quanto mais, melhor setup):
  ✓ Lote girando 3+ vezes | ✓ 10+ min acumulando
  ✓ 50kg+ absorvidos | ✓ Índice favorável
  ✓ 2+ players do mesmo lado | ✓ 65%+ fluxo dominante

STOP: escorado=1 tick | rompimento=2 ticks | "sem andar sai no 0"
ALVO: pelo book | cuidado redondos | parcial 50% no rompimento

ARMADILHAS: BTG/Genial (fake) | troca de corretora | UBS stop hunt
"""
