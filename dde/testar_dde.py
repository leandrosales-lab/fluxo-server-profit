"""
testar_dde.py — Diagnóstico de conexão DDE com o Profit Pro
=============================================================
Execute com o Profit Pro aberto e o ativo desejado na tela:

  python dde/testar_dde.py --asset PETR4

Mostra quais tópicos DDE respondem e quais valores retornam.
"""

import sys
import site
import argparse

# Adicionar pythonwin ao path para encontrar dde.pyd
for sp in site.getsitepackages():
    _pw = sp + "\\pythonwin"
    if _pw not in sys.path:
        sys.path.insert(0, _pw)

try:
    import win32ui
    import dde
except ImportError as e:
    print(f"ERRO: pywin32 nao instalado — {e}")
    print("Instale com: python -m pip install pywin32")
    sys.exit(1)


def testar_topico(server_dde, app: str, topic: str, item: str) -> str:
    """Tenta ler um valor DDE e retorna o resultado ou o erro."""
    try:
        conv = dde.CreateConversation(server_dde)
        conv.ConnectTo(app, topic)
        valor = conv.Request(item)
        return str(valor).strip() if valor else "(vazio)"
    except Exception as e:
        return f"ERRO: {e}"


def main():
    p = argparse.ArgumentParser(description="Diagnóstico DDE Profit Pro")
    p.add_argument("--asset", default="PETR4", help="Código do ativo (ex: PETR4)")
    args = p.parse_args()
    ativo = args.asset.upper()

    print()
    print("=" * 60)
    print(f"  DIAGNOSTICO DDE — Profit Pro | Ativo: {ativo}")
    print("=" * 60)
    print("  Certifique-se de que o Profit Pro esta aberto e")
    print(f"  o ativo {ativo} esta visivel na tela.")
    print("=" * 60)
    print()

    # Criar servidor DDE local (necessário para criar conversas)
    srv = dde.CreateServer()
    srv.Create("FluxoDiagnostico")

    # ── Tópicos T&T do Profit Pro
    TOPICOS_TT = [
        ("Ultima",    "Ultimo preco negociado"),
        ("VolNeg",    "Volume do ultimo negocio"),
        ("CodAgente", "Corretora agente (broker)"),
        ("TipNeg",    "Tipo: C=compra / V=venda"),
        ("QtdNeg",    "Contador de negocios"),
        ("Hora",      "Hora do ultimo negocio"),
        ("Abertura",  "Preco de abertura"),
        ("Fechamento","Preco de fechamento"),
        ("Maximo",    "Preco maximo"),
        ("Minimo",    "Preco minimo"),
    ]

    print("  [T&T] Topicos de Times & Trades (app='Profit'):")
    print(f"  {'Topico':<15} {'Valor':<20} Descricao")
    print("  " + "-" * 55)
    for topic, descricao in TOPICOS_TT:
        valor = testar_topico(srv, "Profit", topic, ativo)
        status = "OK " if not valor.startswith("ERRO") else "---"
        print(f"  [{status}] {topic:<13} {valor:<20} {descricao}")

    print()

    # ── Tópicos Book (nível 1)
    TOPICOS_BOOK = [
        ("OfertaCompraPrc1", "Preco bid nivel 1"),
        ("OfertaCompraQtd1", "Qtd bid nivel 1"),
        ("OfertaCompraAgt1", "Agente bid nivel 1"),
        ("OfertaVendaPrc1",  "Preco ask nivel 1"),
        ("OfertaVendaQtd1",  "Qtd ask nivel 1"),
        ("OfertaVendaAgt1",  "Agente ask nivel 1"),
        # Nomes alternativos que algumas versoes usam
        ("BidPrice1",  "Preco bid nivel 1 (alt)"),
        ("AskPrice1",  "Preco ask nivel 1 (alt)"),
    ]

    print("  [Book] Topicos de Book de Ofertas (app='Profit'):")
    print(f"  {'Topico':<20} {'Valor':<20} Descricao")
    print("  " + "-" * 60)
    for topic, descricao in TOPICOS_BOOK:
        valor = testar_topico(srv, "Profit", topic, ativo)
        status = "OK " if not valor.startswith("ERRO") else "---"
        print(f"  [{status}] {topic:<18} {valor:<20} {descricao}")

    srv.Destroy()

    print()
    print("=" * 60)
    print("  Se todos mostrarem ERRO: verifique se o Profit Pro")
    print("  esta aberto e o servidor DDE esta habilitado em:")
    print("  Ferramentas > Configuracoes > DDE > Habilitar")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
