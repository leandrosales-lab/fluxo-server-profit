"""
TRANSCRITOR DE VÍDEOS — Whisper Local
======================================
Transcreve vídeos do seu PC usando o modelo Whisper da OpenAI.
Roda 100% offline, sem API, sem custo por uso.

INSTALAÇÃO (execute UMA VEZ antes de usar):
  pip install openai-whisper
  pip install torch torchvision torchaudio  (CPU)
  # Se tiver GPU NVIDIA:
  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

  Também precisa do ffmpeg:
  Windows: https://www.gyan.dev/ffmpeg/builds/  (baixar e adicionar ao PATH)
  ou: winget install ffmpeg

USO:
  # Transcrever todos os vídeos de uma pasta:
  python transcrever.py --pasta "C:\\Users\\Leandro\\Videos\\Iceberg"

  # Transcrever um vídeo específico:
  python transcrever.py --video "C:\\Users\\Leandro\\Videos\\iceberg_rob1.mp4"

  # Usar modelo maior (mais preciso, mais lento):
  python transcrever.py --pasta . --modelo large

  # Transcrever e já atualizar o servidor de fluxo:
  python transcrever.py --pasta . --atualizar-servidor

MODELOS DISPONÍVEIS (do mais rápido ao mais preciso):
  tiny   → mais rápido, menos preciso  (~1 min para 10 min de vídeo, CPU)
  base   → bom equilíbrio              (~2 min para 10 min de vídeo, CPU)
  small  → boa precisão em pt-BR       (~4 min para 10 min de vídeo, CPU)
  medium → excelente precisão          (~10 min para 10 min de vídeo, CPU)
  large  → máxima precisão             (~20 min para 10 min de vídeo, CPU)

  RECOMENDADO para trading/termos técnicos: small ou medium
"""

import os
import sys
import time
import json
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

# Configurar logging colorido
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("Transcritor")

# ── Cores para terminal
G = "\033[92m"   # verde
R = "\033[91m"   # vermelho
Y = "\033[93m"   # amarelo
B = "\033[94m"   # azul
C = "\033[96m"   # ciano
W = "\033[97m"   # branco
X = "\033[0m"    # reset

# ── Extensões de vídeo suportadas
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".wmv",
              ".flv", ".webm", ".m4v", ".ts", ".mpg", ".mpeg"}


# ──────────────────────────────────────────────────────────────
# VERIFICAÇÕES INICIAIS
# ──────────────────────────────────────────────────────────────

def verificar_dependencias() -> bool:
    """Verifica se Whisper e ffmpeg estão instalados."""
    ok = True

    # Whisper
    try:
        import whisper
        logger.info(f"{G}✓{X} openai-whisper instalado")
    except ImportError:
        logger.error(f"{R}✗{X} openai-whisper NÃO encontrado")
        logger.error(f"   Instale com: {Y}pip install openai-whisper{X}")
        ok = False

    # ffmpeg
    import subprocess
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            versao = result.stdout.split("\n")[0]
            logger.info(f"{G}✓{X} ffmpeg: {versao[:50]}")
        else:
            raise FileNotFoundError
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.error(f"{R}✗{X} ffmpeg NÃO encontrado no PATH")
        logger.error(f"   Windows: baixe em https://www.gyan.dev/ffmpeg/builds/")
        logger.error(f"   Adicione a pasta 'bin' do ffmpeg ao PATH do sistema")
        ok = False

    return ok


# ──────────────────────────────────────────────────────────────
# TRANSCRIÇÃO
# ──────────────────────────────────────────────────────────────

def transcrever_video(
    caminho: Path,
    modelo_nome: str,
    pasta_saida: Path,
    modelo=None,          # reusar modelo já carregado
    idioma: str = "pt",
    timestamps: bool = True,
) -> Optional[dict]:
    """
    Transcreve um único vídeo com Whisper.

    Retorna dict com:
      - texto:      transcrição limpa
      - segmentos:  lista com timestamps e texto de cada trecho
      - duracao:    duração em segundos
      - arquivo:    nome do arquivo de entrada
    """
    import whisper

    nome = caminho.stem  # nome sem extensão

    # Verificar se já foi transcrito
    saida_json = pasta_saida / f"{nome}.json"
    saida_txt  = pasta_saida / f"{nome}.txt"
    if saida_txt.exists():
        logger.info(f"{Y}⊙{X} Já transcrito: {nome}.txt (pulando)")
        return None

    logger.info(f"\n{B}{'─' * 60}{X}")
    logger.info(f"{B}▶{X} Transcrevendo: {C}{caminho.name}{X}")
    logger.info(f"   Tamanho: {caminho.stat().st_size / 1024 / 1024:.1f} MB")

    # Carregar modelo (só na primeira vez)
    if modelo is None:
        logger.info(f"   Carregando modelo {Y}{modelo_nome}{X}...")
        t0 = time.time()
        modelo = whisper.load_model(modelo_nome)
        logger.info(f"   Modelo carregado em {time.time() - t0:.1f}s")

    # Transcrever
    logger.info(f"   {W}Transcrevendo...{X} (pode demorar alguns minutos)")
    t0 = time.time()

    try:
        result = modelo.transcribe(
            str(caminho),
            language=idioma,
            verbose=False,
            # Dicas para melhorar reconhecimento de termos de trading
            initial_prompt=(
                "Transcrição de aula sobre trading, leitura de fluxo, "
                "tape reading, Book de Ofertas, Times and Trades, "
                "Iceberg, Best Offer, corretoras, B3, ações, Day Trade. "
                "Termos técnicos: Iceberg, Sniper, Fantasma, WAP, Best Offer, "
                "Scalping, Stop, agressão, absorção, defesa, player, fluxo."
            ),
            # Configurações de qualidade
            temperature=0.0,       # determinístico
            best_of=1,
            beam_size=5,
            word_timestamps=True,  # timestamps por palavra
            condition_on_previous_text=True,
            no_speech_threshold=0.6,
            logprob_threshold=-1.0,
            compression_ratio_threshold=2.4,
        )
    except Exception as e:
        logger.error(f"{R}✗{X} Erro ao transcrever {nome}: {e}")
        return None

    duracao = time.time() - t0
    texto_limpo = result["text"].strip()
    segmentos   = result.get("segments", [])
    dur_video   = segmentos[-1]["end"] if segmentos else 0

    logger.info(f"   {G}✓{X} Concluído em {duracao:.0f}s | "
                f"Vídeo: {dur_video/60:.1f} min | "
                f"Ratio: {dur_video/max(duracao,1):.1f}x")

    # ── Salvar JSON completo (com timestamps)
    dados = {
        "arquivo":       caminho.name,
        "modelo":        modelo_nome,
        "idioma":        idioma,
        "duracao_video": round(dur_video, 2),
        "texto":         texto_limpo,
        "segmentos":     [
            {
                "id":     s["id"],
                "inicio": round(s["start"], 2),
                "fim":    round(s["end"],   2),
                "texto":  s["text"].strip(),
            }
            for s in segmentos
        ],
        "transcrito_em": datetime.now().isoformat(),
    }

    with open(saida_json, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)

    # ── Salvar TXT formatado (fácil de ler)
    linhas = [
        "=" * 60,
        f"ARQUIVO: {caminho.name}",
        f"MODELO:  {modelo_nome} | IDIOMA: {idioma}",
        f"DURAÇÃO: {dur_video/60:.1f} minutos",
        f"DATA:    {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        "=" * 60,
        "",
        "─── TEXTO COMPLETO ───────────────────────────────────────",
        "",
        texto_limpo,
        "",
    ]

    if timestamps and segmentos:
        linhas += [
            "",
            "─── SEGMENTOS COM TIMESTAMPS ─────────────────────────────",
            "",
        ]
        for seg in segmentos:
            inicio = formatar_tempo(seg["start"])
            linhas.append(f"[{inicio}] {seg['text'].strip()}")

    with open(saida_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))

    logger.info(f"   {G}→{X} Salvo: {saida_txt.name}")

    return dados


def formatar_tempo(segundos: float) -> str:
    """Converte segundos para HH:MM:SS."""
    h = int(segundos // 3600)
    m = int((segundos % 3600) // 60)
    s = int(segundos % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


# ──────────────────────────────────────────────────────────────
# EXTRATOR DE CONHECIMENTO SOBRE ICEBERG
# ──────────────────────────────────────────────────────────────

PALAVRAS_ICEBERG = [
    "iceberg", "renovação", "renovando", "lote", "best offer",
    "melhor oferta", "passivo", "passiva", "ordem passiva",
    "defesa", "defendendo", "absorção", "absorvendo",
    "player", "corretora", "jp morgan", "goldman", "btg",
    "bradesco", "itaú", "robô", "hft", "algoritmo",
    "sniper", "fantasma", "wap", "scalping", "times and trades",
    "book", "nível", "leitura de fluxo", "tape reading",
    "urgência", "urgente", "acumulando", "montando posição",
]

def extrair_trechos_iceberg(segmentos: list, janela_seg: float = 30.0) -> list:
    """
    Extrai trechos da transcrição que mencionam Iceberg ou conceitos relacionados.
    Agrupa segmentos contíguos que formam um contexto completo.
    """
    trechos = []
    i = 0
    while i < len(segmentos):
        seg = segmentos[i]
        texto_lower = seg["texto"].lower()

        # Verificar se este segmento contém palavras-chave
        hit = any(p in texto_lower for p in PALAVRAS_ICEBERG)
        if hit:
            # Expandir contexto: pegar segmentos anteriores e posteriores
            inicio_ctx = max(0, i - 2)
            fim_ctx    = i + 1
            # Continuar enquanto estiver próximo no tempo
            while fim_ctx < len(segmentos):
                prox = segmentos[fim_ctx]
                if prox["inicio"] - segmentos[fim_ctx - 1]["fim"] > 5.0:
                    break  # pausa > 5s = novo contexto
                texto_prox = prox["texto"].lower()
                if any(p in texto_prox for p in PALAVRAS_ICEBERG):
                    fim_ctx = min(fim_ctx + 3, len(segmentos))
                elif fim_ctx > i + 3:
                    break
                else:
                    fim_ctx += 1

            grupo = segmentos[inicio_ctx:fim_ctx]
            if grupo:
                tempo_inicio = grupo[0]["inicio"]
                tempo_fim    = grupo[-1]["fim"]
                texto_grupo  = " ".join(s["texto"] for s in grupo).strip()
                trechos.append({
                    "inicio":   round(tempo_inicio, 2),
                    "fim":      round(tempo_fim,    2),
                    "tempo_fmt": formatar_tempo(tempo_inicio),
                    "texto":    texto_grupo,
                    "duracao":  round(tempo_fim - tempo_inicio, 1),
                })
            i = fim_ctx
        else:
            i += 1

    # Deduplicar trechos que se sobrepõem
    resultado = []
    ultimo_fim = -1
    for t in trechos:
        if t["inicio"] > ultimo_fim - 5:
            resultado.append(t)
            ultimo_fim = t["fim"]

    return resultado


# ──────────────────────────────────────────────────────────────
# GERAÇÃO DE RELATÓRIO CONSOLIDADO
# ──────────────────────────────────────────────────────────────

def gerar_relatorio(transcricoes: list[dict], pasta_saida: Path):
    """
    Gera um arquivo de consolidação com todos os trechos
    relevantes sobre Iceberg de todos os vídeos.
    """
    logger.info(f"\n{C}Gerando relatório consolidado de Iceberg...{X}")

    relatorio_txt  = pasta_saida / "RELATORIO_ICEBERG.txt"
    relatorio_json = pasta_saida / "conhecimento_iceberg.json"

    todos_trechos = []
    linhas = [
        "=" * 70,
        "RELATÓRIO CONSOLIDADO — TRECHOS SOBRE ICEBERG",
        f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        f"Vídeos processados: {len(transcricoes)}",
        "=" * 70,
    ]

    for dados in transcricoes:
        if not dados or not dados.get("segmentos"):
            continue

        trechos = extrair_trechos_iceberg(dados["segmentos"])
        if not trechos:
            continue

        linhas += [
            "",
            f"{'─' * 70}",
            f"📹 VÍDEO: {dados['arquivo']}",
            f"   Duração: {dados['duracao_video']/60:.1f} min | "
            f"Trechos relevantes: {len(trechos)}",
            f"{'─' * 70}",
        ]

        for t in trechos:
            linhas += [
                "",
                f"  ▶ [{t['tempo_fmt']}] ({t['duracao']:.0f}s)",
                f"  {t['texto']}",
            ]
            todos_trechos.append({
                "arquivo":  dados["arquivo"],
                "tempo":    t["tempo_fmt"],
                "inicio_s": t["inicio"],
                "texto":    t["texto"],
            })

    # Estatísticas finais
    linhas += [
        "",
        "=" * 70,
        f"TOTAL DE TRECHOS RELEVANTES SOBRE ICEBERG: {len(todos_trechos)}",
        "=" * 70,
    ]

    with open(relatorio_txt, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas))

    with open(relatorio_json, "w", encoding="utf-8") as f:
        json.dump(todos_trechos, f, ensure_ascii=False, indent=2)

    logger.info(f"{G}✓{X} Relatório salvo: {relatorio_txt.name}")
    logger.info(f"{G}✓{X} JSON salvo: {relatorio_json.name}")
    logger.info(f"{G}✓{X} Total de trechos sobre Iceberg: {len(todos_trechos)}")

    return todos_trechos


# ──────────────────────────────────────────────────────────────
# ATUALIZAÇÃO DO SERVIDOR PYTHON (fluxo_server)
# ──────────────────────────────────────────────────────────────

def atualizar_servidor(trechos: list, pasta_servidor: Optional[Path] = None):
    """
    Envia o conhecimento extraído para o servidor de fluxo
    para que o motor use as regras dos vídeos.

    Tenta detectar automaticamente a pasta do fluxo_server.
    """
    if not trechos:
        logger.warning("Nenhum trecho para atualizar o servidor")
        return

    # Detectar pasta do servidor
    if pasta_servidor is None:
        candidatas = [
            Path("fluxo_server"),
            Path("../fluxo_server"),
            Path.home() / "fluxo_server",
        ]
        for c in candidatas:
            if c.exists() and (c / "main.py").exists():
                pasta_servidor = c
                break

    # Gerar arquivo de configuração de conhecimento
    conhecimento_path = None
    if pasta_servidor:
        conhecimento_path = pasta_servidor / "config" / "conhecimento_iceberg.json"
        conhecimento_path.parent.mkdir(exist_ok=True)
    else:
        conhecimento_path = Path("conhecimento_iceberg.json")

    # Extrair regras de configuração dos trechos
    config_gerada = extrair_config_do_conhecimento(trechos)

    saida = {
        "gerado_em":  datetime.now().isoformat(),
        "n_trechos":  len(trechos),
        "trechos":    trechos,
        "config":     config_gerada,
    }

    with open(conhecimento_path, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)

    logger.info(f"{G}✓{X} Conhecimento salvo: {conhecimento_path}")
    logger.info(f"   O servidor irá carregar automaticamente na próxima inicialização.")

    # Tentar notificar servidor em execução via HTTP
    try:
        import urllib.request
        url = "http://127.0.0.1:5000/health"
        with urllib.request.urlopen(url, timeout=2) as r:
            if r.status == 200:
                # Servidor em execução — enviar reload
                req = urllib.request.Request(
                    "http://127.0.0.1:5000/reload-knowledge",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST"
                )
                try:
                    urllib.request.urlopen(req, timeout=2)
                    logger.info(f"{G}✓{X} Servidor notificado para recarregar conhecimento")
                except Exception:
                    logger.info(f"{Y}⊙{X} Servidor em execução — reinicie para aplicar o conhecimento")
    except Exception:
        logger.info(f"{Y}⊙{X} Servidor não encontrado em execução — inicie com: python main.py")


def extrair_config_do_conhecimento(trechos: list) -> dict:
    """
    Analisa os trechos e tenta extrair parâmetros de configuração
    mencionados nos vídeos (ex: "mínimo 3 renovações", "lote de 1000").
    """
    texto_total = " ".join(t["texto"].lower() for t in trechos)

    config = {
        "iceberg_min_renovacoes": 3,
        "iceberg_lote_tolerancia_pct": 20,
        "corretoras_relevantes_mencionadas": [],
        "notas_metodologia": [],
    }

    # Detectar corretoras mencionadas
    corretoras = [
        "jp morgan", "goldman sachs", "btg pactual", "bradesco",
        "itaú", "itau", "santander", "xp", "genial", "clear",
        "rico", "agora", "toro", "merrill lynch", "city group",
        "morgan stanley", "ubs", "scotia bank"
    ]
    encontradas = [c.upper() for c in corretoras if c in texto_total]
    config["corretoras_relevantes_mencionadas"] = encontradas

    # Detectar menção a número de renovações
    import re
    m = re.search(r"(\d+)\s*(?:ou mais\s*)?renova[çc][õo]", texto_total)
    if m:
        config["iceberg_min_renovacoes"] = int(m.group(1))

    # Extrair notas de metodologia (frases-chave)
    frases_metodologia = []
    for trecho in trechos[:20]:  # primeiros 20 trechos
        texto = trecho["texto"]
        if any(kw in texto.lower() for kw in
               ["quando", "se o", "se a", "sempre que", "regra", "estratégia"]):
            frases_metodologia.append(texto[:200])
    config["notas_metodologia"] = frases_metodologia[:5]

    return config


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="Transcritor de vídeos com Whisper — especializado em Leitura de Fluxo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  # Transcrever todos os vídeos de uma pasta:
  python transcrever.py --pasta "C:\\Videos\\Iceberg"

  # Vídeo único com modelo mais preciso:
  python transcrever.py --video "aula_iceberg.mp4" --modelo medium

  # Transcrever e atualizar o servidor de fluxo:
  python transcrever.py --pasta . --atualizar-servidor

  # Verificar instalação:
  python transcrever.py --verificar
        """
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--pasta",   type=Path, help="Pasta com vídeos para transcrever")
    g.add_argument("--video",   type=Path, help="Vídeo único para transcrever")
    p.add_argument("--modelo",  default="small",
                   choices=["tiny", "base", "small", "medium", "large"],
                   help="Modelo Whisper (padrão: small)")
    p.add_argument("--saida",   type=Path, default=None,
                   help="Pasta de saída das transcrições (padrão: ./transcricoes)")
    p.add_argument("--idioma",  default="pt",
                   help="Idioma do áudio (padrão: pt para português)")
    p.add_argument("--sem-timestamps", action="store_true",
                   help="Não incluir timestamps no .txt")
    p.add_argument("--atualizar-servidor", action="store_true",
                   help="Atualizar o servidor fluxo_server com o conhecimento extraído")
    p.add_argument("--servidor-pasta", type=Path, default=None,
                   help="Caminho da pasta fluxo_server (opcional, detecta automaticamente)")
    p.add_argument("--verificar", action="store_true",
                   help="Verificar dependências e sair")
    return p.parse_args()


def main():
    args = parse_args()

    print(f"\n{B}╔══════════════════════════════════════════════════════╗{X}")
    print(f"{B}║  🎙️  TRANSCRITOR DE VÍDEOS — WHISPER LOCAL            ║{X}")
    print(f"{B}║     Especializado em Leitura de Fluxo / Iceberg       ║{X}")
    print(f"{B}╚══════════════════════════════════════════════════════╝{X}\n")

    # ── Verificar dependências
    if not verificar_dependencias():
        if args.verificar:
            logger.error("Dependências faltando — veja as instruções acima.")
        else:
            logger.error("Instale as dependências antes de continuar.")
        sys.exit(1)

    if args.verificar:
        logger.info(f"\n{G}Tudo OK! Pronto para transcrever.{X}")
        return

    # ── Definir pasta de saída
    pasta_saida = args.saida or Path("transcricoes")
    pasta_saida.mkdir(parents=True, exist_ok=True)
    logger.info(f"Pasta de saída: {pasta_saida.resolve()}")

    # ── Coletar vídeos
    videos = []
    if args.video:
        if not args.video.exists():
            logger.error(f"Arquivo não encontrado: {args.video}")
            sys.exit(1)
        videos = [args.video]
    elif args.pasta:
        if not args.pasta.exists():
            logger.error(f"Pasta não encontrada: {args.pasta}")
            sys.exit(1)
        videos = sorted([
            f for f in args.pasta.rglob("*")
            if f.suffix.lower() in VIDEO_EXTS and f.is_file()
        ])
        if not videos:
            logger.error(f"Nenhum vídeo encontrado em: {args.pasta}")
            logger.info(f"Extensões suportadas: {', '.join(VIDEO_EXTS)}")
            sys.exit(1)
    else:
        # Buscar na pasta atual
        videos = sorted([
            f for f in Path(".").glob("*")
            if f.suffix.lower() in VIDEO_EXTS
        ])
        if not videos:
            logger.error("Nenhum vídeo encontrado. Use --pasta ou --video.")
            sys.exit(1)

    logger.info(f"\n{G}Vídeos encontrados: {len(videos)}{X}")
    for i, v in enumerate(videos, 1):
        mb = v.stat().st_size / 1024 / 1024
        logger.info(f"  {i}. {v.name} ({mb:.1f} MB)")

    # ── Carregar modelo Whisper (uma vez para todos os vídeos)
    import whisper
    logger.info(f"\n{Y}Carregando modelo '{args.modelo}'...{X}")
    logger.info(f"(Na primeira execução, o modelo é baixado automaticamente)")
    t0 = time.time()
    modelo = whisper.load_model(args.modelo)
    logger.info(f"{G}✓{X} Modelo carregado em {time.time()-t0:.1f}s")

    # ── Transcrever todos os vídeos
    transcricoes = []
    inicio_total = time.time()

    for i, video in enumerate(videos, 1):
        logger.info(f"\n{C}[{i}/{len(videos)}]{X} Processando: {video.name}")
        dados = transcrever_video(
            caminho      = video,
            modelo_nome  = args.modelo,
            pasta_saida  = pasta_saida,
            modelo       = modelo,
            idioma       = args.idioma,
            timestamps   = not args.sem_timestamps,
        )
        if dados:
            transcricoes.append(dados)

    # ── Relatório consolidado
    tempo_total = time.time() - inicio_total
    logger.info(f"\n{G}{'=' * 60}{X}")
    logger.info(f"{G}CONCLUÍDO!{X}")
    logger.info(f"  Vídeos transcritos: {len(transcricoes)}/{len(videos)}")
    logger.info(f"  Tempo total: {tempo_total/60:.1f} minutos")
    logger.info(f"  Arquivos salvos em: {pasta_saida.resolve()}")

    if transcricoes:
        trechos = gerar_relatorio(transcricoes, pasta_saida)

        # ── Atualizar servidor
        if args.atualizar_servidor and trechos:
            logger.info(f"\n{C}Atualizando servidor de fluxo...{X}")
            atualizar_servidor(trechos, args.servidor_pasta)

    print(f"\n{G}╔══════════════════════════════════════╗{X}")
    print(f"{G}║  ✓  TRANSCRIÇÃO CONCLUÍDA!            ║{X}")
    print(f"{G}║  Arquivos salvos em: {pasta_saida.name:<14}  ║{X}")
    print(f"{G}╚══════════════════════════════════════╝{X}\n")


if __name__ == "__main__":
    main()
