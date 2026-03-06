"""
CARREGADOR DE CONHECIMENTO — knowledge_loader.py
==================================================
Carrega o arquivo conhecimento_iceberg.json gerado pelo transcritor
e ajusta as configurações do FlowEngine com as regras extraídas dos vídeos.

Integração no main.py:
  from config.knowledge_loader import carregar_conhecimento
  carregar_conhecimento(engine)
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("KnowledgeLoader")


def carregar_conhecimento(engine, config_dir: Optional[Path] = None) -> bool:
    """
    Carrega conhecimento_iceberg.json e aplica ao motor de fluxo.
    Retorna True se carregou com sucesso.
    """
    # Localizar o arquivo
    if config_dir is None:
        config_dir = Path(__file__).parent

    arquivo = config_dir / "conhecimento_iceberg.json"
    if not arquivo.exists():
        logger.info("Arquivo de conhecimento não encontrado — usando configuração padrão.")
        return False

    try:
        with open(arquivo, encoding="utf-8") as f:
            dados = json.load(f)
    except Exception as e:
        logger.error(f"Erro ao carregar conhecimento: {e}")
        return False

    config_extraida = dados.get("config", {})
    n_trechos = dados.get("n_trechos", 0)

    logger.info(f"Carregando conhecimento: {n_trechos} trechos de vídeos sobre Iceberg")

    # ── Aplicar configurações extraídas ao motor
    cfg = engine.cfg

    # Renovações mínimas detectadas nos vídeos
    if "iceberg_min_renovacoes" in config_extraida:
        novo = config_extraida["iceberg_min_renovacoes"]
        if 1 <= novo <= 10:
            cfg.iceberg_min_renewals = novo
            logger.info(f"  iceberg_min_renewals = {novo} (dos vídeos)")

    # Tolerância de lote detectada
    if "iceberg_lote_tolerancia_pct" in config_extraida:
        novo = config_extraida["iceberg_lote_tolerancia_pct"]
        if 5 <= novo <= 50:
            cfg.iceberg_lot_tolerance = float(novo)
            logger.info(f"  iceberg_lot_tolerance = {novo}% (dos vídeos)")

    # Corretoras de alta relevância mencionadas nos vídeos
    corretoras_videos = config_extraida.get("corretoras_relevantes_mencionadas", [])
    if corretoras_videos:
        # Mesclar com a lista padrão (sem duplicatas)
        existentes = set(b.upper() for b in cfg.high_relevance_brokers)
        novas = [c for c in corretoras_videos if c.upper() not in existentes]
        if novas:
            cfg.high_relevance_brokers = list(cfg.high_relevance_brokers) + novas
            logger.info(f"  Corretoras adicionadas: {novas}")

    # Logar notas de metodologia
    notas = config_extraida.get("notas_metodologia", [])
    if notas:
        logger.info(f"  Notas de metodologia extraídas dos vídeos:")
        for nota in notas[:3]:
            logger.info(f"    • {nota[:120]}...")

    logger.info(f"Conhecimento carregado com sucesso de: {arquivo}")
    return True
