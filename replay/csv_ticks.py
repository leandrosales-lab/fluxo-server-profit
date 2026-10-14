"""
GRAVAÇÃO E LEITURA DE TICKS EM CSV
===================================
Formato gravado pelo Fluxo Server (--gravar arquivo.csv):

    timestamp,preco,quantidade,agressor,corretora_agressora,corretora_passiva
    1760443200.125,5123.5,10,B,XP INC,BTG PACTUAL

  - timestamp: segundos desde 1970 (epoch) com milissegundos, ou data/hora
               ISO (2026-10-14T10:00:00.125) ou 14/10/2026 10:00:00.125
  - preco:     preço do negócio
  - quantidade: contratos / ações do negócio
  - agressor:  B (compra) ou S (venda). Também aceita C/V, Compra/Venda,
               Comprador/Vendedor
  - corretora_agressora: quem agrediu
  - corretora_passiva:   quem estava no book (opcional)

A leitura também aceita o CSV exportado do Times & Trades do Profit:
separador ";" ou ",", decimal com vírgula e cabeçalhos em português
(Data, Hora, Preço, Quantidade, Agressor, Compradora, Vendedora...).
Os cabeçalhos são reconhecidos de forma flexível (sem acento, sem
maiúsculas, com ou sem "Corretora"). Linhas sem agressor (leilão, direto)
são ignoradas e contadas.
"""

import csv
import dataclasses
import io
import logging
import os
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from core.engine import Tick, Side

logger = logging.getLogger("ReplayCSV")

CABECALHO = ["timestamp", "preco", "quantidade", "agressor",
             "corretora_agressora", "corretora_passiva"]

# O campo passive_broker pode ou não existir no Tick (outra frente de trabalho)
_CAMPOS_TICK = {f.name for f in dataclasses.fields(Tick)}

# Data usada quando o arquivo só tem a hora do negócio
DATA_PADRAO = "01/01/2000"


def criar_tick(timestamp: float, preco: float, qtd: int, corretora: str,
               lado: Side, passiva: str = "") -> Tick:
    """Monta um Tick; só passa passive_broker se o dataclass tiver o campo."""
    kw = dict(timestamp=timestamp, price=preco, qty=qtd,
              broker=corretora, side=lado)
    if "passive_broker" in _CAMPOS_TICK:
        kw["passive_broker"] = passiva
    return Tick(**kw)


# ──────────────────────────────────────────────────────────────
# GRAVAÇÃO
# ──────────────────────────────────────────────────────────────

class GravadorTicks:
    """
    Grava cada Tick entregue ao engine num CSV (formato acima).
    Uso: engine.add_tick = GravadorTicks("pregao.csv").envolver(engine.add_tick)
    """

    def __init__(self, caminho: str):
        self.caminho = caminho
        self._lock = threading.Lock()
        novo = True
        try:
            novo = not os.path.exists(caminho) or os.path.getsize(caminho) == 0
        except OSError:
            pass
        # Abre em modo "append" para não apagar uma gravação anterior
        self._arq = open(caminho, "a", newline="", encoding="utf-8")
        self._csv = csv.writer(self._arq)
        if novo:
            self._csv.writerow(CABECALHO)
            self._arq.flush()
        self.gravados = 0
        logger.info(f"Gravando ticks em {caminho}")

    def gravar(self, tick: Tick):
        lado = "B" if tick.side == Side.BUY else "S" if tick.side == Side.SELL else ""
        if not lado:
            return
        linha = [f"{float(tick.timestamp):.3f}", format(float(tick.price), ".10g"),
                 int(tick.qty), lado, tick.broker or "",
                 getattr(tick, "passive_broker", "") or ""]
        with self._lock:
            if self._arq.closed:
                return
            self._csv.writerow(linha)
            self.gravados += 1
            # Descarrega a cada tick: se o processo for morto, nada se perde
            self._arq.flush()

    def envolver(self, add_tick):
        """Devolve um add_tick que grava o tick e depois o entrega ao engine."""
        def _add_tick_gravando(tick: Tick):
            try:
                self.gravar(tick)
            except Exception as e:     # gravação nunca derruba a captura
                logger.warning(f"Falha ao gravar tick: {e}")
            return add_tick(tick)
        return _add_tick_gravando

    def fechar(self):
        with self._lock:
            if not self._arq.closed:
                self._arq.flush()
                self._arq.close()
        logger.info(f"Gravação encerrada: {self.gravados} ticks em {self.caminho}")


# ──────────────────────────────────────────────────────────────
# LEITURA
# ──────────────────────────────────────────────────────────────

@dataclass
class ResultadoLeitura:
    ticks:            list = field(default_factory=list)
    linhas_lidas:     int = 0
    linhas_ignoradas: int = 0           # sem agressor, inválidas etc.
    separador:        str = ","
    colunas:          dict = field(default_factory=dict)   # campo → nome da coluna
    invertido:        bool = False      # arquivo vinha do mais novo para o mais antigo


def _normalizar(nome: str) -> str:
    """'Corretora Compradora' → 'corretoracompradora' (sem acento/espaço)."""
    s = unicodedata.normalize("NFKD", nome or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


# Nomes exatos (já normalizados) aceitos para cada campo
_NOMES = {
    "datahora":   {"timestamp", "ts", "datahora", "datetime", "momento", "dataehora"},
    "data":       {"data", "date", "dia"},
    "hora":       {"hora", "horario", "time", "horas"},
    "preco":      {"preco", "price", "valor", "ultimo", "ult", "precoultimo"},
    "qtd":        {"quantidade", "qtd", "qtde", "qty", "quant", "quantity", "volume"},
    "lado":       {"agressor", "lado", "side", "agressao", "ladoagressor", "aggressor",
                   "tipo", "tipoagressao"},
    "agressora":  {"corretoraagressora", "corretora", "broker", "agente",
                   "agenteagressor", "agressora"},
    "passiva":    {"corretorapassiva", "passivebroker", "passiva", "agentepassivo"},
    "compradora": {"compradora", "corretoracompradora", "comprador", "agentecomprador",
                   "compra", "buyer"},
    "vendedora":  {"vendedora", "corretoravendedora", "vendedor", "agentevendedor",
                   "venda", "seller"},
}

# Se o nome exato não bater: pedaços do nome (ordem importa)
_PEDACOS = [
    ("passiva",    ("passiv",)),
    ("agressora",  ("agressora",)),
    ("compradora", ("compr",)),
    ("vendedora",  ("vend",)),
    ("preco",      ("preco", "price")),
    ("qtd",        ("quant", "qtd", "qty")),
    ("lado",       ("agress", "lado", "side")),
    ("datahora",   ("datahora", "timestamp")),
    ("hora",       ("hora", "time")),
    ("data",       ("data", "date")),
]


def _mapear_colunas(cabecalho: list[str]) -> dict:
    """{campo: índice da coluna}."""
    norm = [_normalizar(c) for c in cabecalho]
    mapa = {}
    for campo, nomes in _NOMES.items():
        for i, n in enumerate(norm):
            if n in nomes and i not in mapa.values():
                mapa[campo] = i
                break
    for campo, pedacos in _PEDACOS:
        if campo in mapa:
            continue
        for i, n in enumerate(norm):
            if i in mapa.values() or not n:
                continue
            if any(p in n for p in pedacos):
                mapa[campo] = i
                break
    return mapa


def _detectar_separador(linha: str) -> str:
    contagem = {sep: linha.count(sep) for sep in (";", "\t", ",")}
    sep = max(contagem, key=contagem.get)
    return sep if contagem[sep] > 0 else ","


def _numero(txt: str) -> float:
    """Aceita 5123.5, 5123,5, 5.123,50 e 5,123.50."""
    s = (txt or "").strip().replace("R$", "").replace("\xa0", "").replace(" ", "")
    if not s:
        raise ValueError("número vazio")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")     # 5.123,50
        else:
            s = s.replace(",", "")                       # 5,123.50
    elif "," in s:
        s = s.replace(",", ".")
    return float(s)


def _quantidade(txt: str) -> int:
    s = (txt or "").strip().replace("\xa0", "").replace(" ", "")
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):            # 1.000 = mil
        s = s.replace(".", "")
    return int(round(_numero(s)))


def _lado(txt: str) -> Side:
    n = _normalizar(txt)
    if n in ("b", "c", "buy", "compra") or n.startswith("compr") or n.startswith("buy"):
        return Side.BUY
    if n in ("s", "v", "sell", "venda") or n.startswith("vend") or n.startswith("sell"):
        return Side.SELL
    return Side.NONE        # leilão, direto, RLP, vazio...


_FORMATOS_DATA = [
    "%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
    "%d/%m/%y %H:%M:%S.%f", "%d/%m/%y %H:%M:%S", "%d/%m/%y %H:%M",
    "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
    "%d-%m-%Y %H:%M:%S.%f", "%d-%m-%Y %H:%M:%S",
]


def _timestamp(txt: str) -> float:
    """Epoch (s ou ms), ISO, ou dd/mm/aaaa hh:mm:ss[.mmm]. Só hora → DATA_PADRAO."""
    s = (txt or "").strip()
    if not s:
        raise ValueError("data/hora vazia")
    if re.fullmatch(r"\d+([.,]\d+)?", s):
        v = float(s.replace(",", "."))
        return v / 1000.0 if v > 1e11 else v            # epoch em milissegundos
    s = s.replace("T", " ") if re.match(r"\d{4}-\d{2}-\d{2}T", s) else s
    # Milissegundos com vírgula: 10:00:00,125
    s = re.sub(r"(\d{2}:\d{2}:\d{2}),(\d+)", r"\1.\2", s)
    if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?", s):
        s = f"{DATA_PADRAO} {s}"
    try:
        iso = s[:-1] + "+00:00" if s.endswith("Z") else s
        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        pass
    for fmt in _FORMATOS_DATA:
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    raise ValueError(f"data/hora não reconhecida: {txt!r}")


def _abrir_texto(caminho: str) -> str:
    with open(caminho, "rb") as f:
        dados = f.read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return dados.decode(enc)
        except UnicodeDecodeError:
            continue
    return dados.decode("latin-1", errors="replace")


def ler_csv(caminho: str) -> ResultadoLeitura:
    """Lê o CSV (formato do Fluxo Server ou exportação do Profit)."""
    texto = _abrir_texto(caminho)
    linhas = texto.splitlines()

    # Achar a linha de cabeçalho (o Profit pode pôr linhas de título antes)
    inicio, sep, mapa = None, ",", {}
    for i, linha in enumerate(linhas[:30]):
        if not linha.strip():
            continue
        sep = _detectar_separador(linha)
        cab = next(csv.reader([linha], delimiter=sep))
        mapa = _mapear_colunas(cab)
        tem_tempo = "datahora" in mapa or "data" in mapa or "hora" in mapa
        if "preco" in mapa and "qtd" in mapa and tem_tempo:
            inicio = i
            break
    if inicio is None:
        raise ValueError(f"{caminho}: cabeçalho não reconhecido (precisa de "
                         f"data/hora, preço e quantidade)")
    if "lado" not in mapa:
        raise ValueError(f"{caminho}: sem coluna de agressor (B/S, C/V, Comprador/Vendedor)")

    cab = next(csv.reader([linhas[inicio]], delimiter=sep))
    res = ResultadoLeitura(separador=sep,
                           colunas={k: cab[v] for k, v in mapa.items()})
    leitor = csv.reader(io.StringIO("\n".join(linhas[inicio + 1:])), delimiter=sep)

    def col(row, campo) -> str:
        i = mapa.get(campo)
        return row[i].strip() if i is not None and i < len(row) else ""

    for row in leitor:
        if not row or not any(c.strip() for c in row):
            continue
        res.linhas_lidas += 1
        try:
            if "datahora" in mapa:
                ts_txt = col(row, "datahora")
            elif "data" in mapa and "hora" in mapa:
                ts_txt = f"{col(row, 'data')} {col(row, 'hora')}"
            else:
                ts_txt = col(row, "data") or col(row, "hora")
            ts    = _timestamp(ts_txt)
            preco = _numero(col(row, "preco"))
            qtd   = _quantidade(col(row, "qtd"))
            lado  = _lado(col(row, "lado"))
        except (ValueError, IndexError):
            res.linhas_ignoradas += 1
            continue
        if lado == Side.NONE or qtd <= 0 or preco <= 0:
            res.linhas_ignoradas += 1
            continue

        compradora, vendedora = col(row, "compradora"), col(row, "vendedora")
        agressora = col(row, "agressora") or (compradora if lado == Side.BUY else vendedora)
        passiva = col(row, "passiva") or (vendedora if lado == Side.BUY else compradora)
        res.ticks.append(criar_tick(ts, preco, qtd, agressora or "DESCONHECIDA",
                                    lado, passiva))

    # O Times & Trades do Profit lista do mais novo para o mais antigo
    if len(res.ticks) > 1 and res.ticks[0].timestamp > res.ticks[-1].timestamp:
        res.ticks.reverse()
        res.invertido = True
    res.ticks.sort(key=lambda t: t.timestamp)     # estável: mantém a ordem do arquivo
    logger.info(f"{caminho}: {len(res.ticks)} ticks lidos, "
                f"{res.linhas_ignoradas} linhas ignoradas (sep {sep!r})")
    return res


def ler_ticks(caminho: str) -> list[Tick]:
    return ler_csv(caminho).ticks
