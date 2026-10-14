"""
OPÇÕES DA LINHA DE COMANDO SOBRE A CONFIGURAÇÃO
=================================================
O main.py aplica primeiro o conhecimento dos vídeos e o JSON do transcritor,
e só depois as opções que o usuário digitou: quem passa --min-confidence 0.7
tem 0.7, não o valor fixo do conhecimento. Opção não informada (None) mantém
o que já estava na configuração.
"""

# argumento do argparse → campo do EngineConfig
_MAPA = {
    "flow_window":    "flow_window_sec",
    "flow_pct":       "flow_pct_threshold",
    "iceberg_min":    "iceberg_min_renewals",
    "min_confidence": "min_confidence",
}


def aplicar_argumentos(cfg, args) -> None:
    """Aplica em cfg as opções informadas em args (None = não informada)."""
    for arg, campo in _MAPA.items():
        valor = getattr(args, arg, None)
        if valor is not None:
            setattr(cfg, campo, valor)
    tick = getattr(args, "tick_size", None)
    if tick is not None:
        cfg.tick_size = tick
