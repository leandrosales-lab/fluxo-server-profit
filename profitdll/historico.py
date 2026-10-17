"""
HISTÓRICO DE NEGÓCIOS PELA PROFITDLL → CSV DO REPLAY
====================================================
Baixa os negócios (tick a tick) de dias passados pela ProfitDLL e grava
no formato do modo replay (replay/csv_ticks.py), para calibrar o engine
com pregões reais. Veja docs/replay.md, seção "Baixar histórico pela
ProfitDLL".

Baseado no artigo oficial da Nelogica "Como requisitar trades históricos
com a ProfitDLL":
  - GetHistoryTrades(ticker, bolsa, dataInicial, dataFinal) pede o período;
  - THistoryTradeCallback é chamado uma vez por negócio;
  - TProgressCallback informa o progresso (0–100); 100 = terminou;
  - a data inicial não pode ter mais de 30 dias (NL_HISTORY_PERIOD_LIMIT)
    — aqui pedimos DIA A DIA e validamos os 30 dias antes de conectar;
  - formato de data ESTRITO '%d/%m/%Y %H:%M:%S' (sempre via strftime).

Uso (Windows, mesmas variáveis PROFITDLL_* do modo dll):
  python -m profitdll.historico --asset PETR4 --inicio 2026-10-01 --fim 2026-10-10
  python -m profitdll.historico --asset PETR4 --inicio 2026-10-01 --fim 2026-10-10 \\
      --saida historico/petr4_{data}.csv --agentes agentes.json

Saída:
  - Com {data} no caminho (padrão): UM ARQUIVO POR DIA. Dias cujo arquivo
    já existe são pulados (dá para retomar um download interrompido);
    use --refazer para baixar de novo.
  - Sem {data}: todos os dias no MESMO arquivo, um dia após o outro.

Toda a lógica de conversão (data B3 → epoch, tipos de agressão, ordem,
duplicados, dias úteis) fica em funções puras testadas em test_engine.py;
só a classe BaixadorHistorico depende da DLL real.
"""

import os
import sys
import time
import logging
import argparse
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.engine import Tick
from profitdll.bridge import (ProfitDLLBridge, trade_para_tick, validar_ativo, BOLSA,
                              carregar_nomes_agentes, FUSO_B3,
                              data_b3_para_epoch as _data_b3_ou_none)

logger = logging.getLogger("ProfitDLLHistorico")

# FUSO_B3 (UTC-3 fixo) e a conversão de data vêm do bridge.py, para o
# histórico e o tempo real gerarem exatamente o mesmo horário.

# Formato EXIGIDO pela DLL na requisição (sem milissegundos)
FORMATO_REQUISICAO = "%d/%m/%Y %H:%M:%S"

HORA_INICIO_PADRAO = "09:00:00"
HORA_FIM_PADRAO    = "18:35:00"
SAIDA_PADRAO       = os.path.join("historico", "{asset}_{data}.csv")

# Limites da DLL (manual p.30): data inicial com mais de 30 dias em relação à
# data do servidor → NL_HISTORY_PERIOD_LIMIT (pedimos dia a dia).
LIMITE_DIAS_HISTORICO   = 30
NL_INVALID_ARGS         = -2147483645
NL_HISTORY_PERIOD_LIMIT = -2147483602
_ERROS_DEFINITIVOS = {NL_HISTORY_PERIOD_LIMIT: "NL_HISTORY_PERIOD_LIMIT (data com mais de 30 dias)",
                      NL_INVALID_ARGS: "NL_INVALID_ARGS (argumentos recusados pela DLL)"}


class ErroDefinitivoHistorico(ValueError):
    """A DLL recusou o pedido de um jeito que tentar de novo não resolve."""


# ──────────────────────────────────────────────────────────────
# FUNÇÕES PURAS (testadas sem a DLL)
# ──────────────────────────────────────────────────────────────

def validar_janela_historico(inicio: date, hoje: Optional[date] = None):
    """Recusa (ValueError) um início além do limite de 30 dias da DLL."""
    hoje = hoje or date.today()
    mais_antigo = hoje - timedelta(days=LIMITE_DIAS_HISTORICO)
    if inicio < mais_antigo:
        raise ValueError(f"a ProfitDLL só entrega histórico dos últimos {LIMITE_DIAS_HISTORICO} dias: "
                         f"o início mais antigo possível hoje é {mais_antigo:%d/%m/%Y} "
                         f"(pedido: {inicio:%d/%m/%Y})")


def data_b3_para_epoch(txt: str) -> float:
    """
    "DD/MM/YYYY HH:mm:SS.ZZZ" (horário de Brasília) → segundos desde 1970.
    Ex.: "14/10/2026 10:00:00.125" → 1791982800.125 (13:00:00.125 UTC)
    Aceita também sem milissegundos. Erro de formato → ValueError.
    """
    ts = _data_b3_ou_none(txt)
    if ts is not None:
        return ts
    raise ValueError(f"data da DLL fora do formato DD/MM/YYYY HH:mm:SS.ZZZ: {txt!r}")


def ler_data(txt: str) -> date:
    """Data da linha de comando: 2026-10-14 ou 14/10/2026."""
    s = (txt or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"data inválida: {txt!r} (use AAAA-MM-DD ou DD/MM/AAAA)")


def ler_hora(txt: str) -> str:
    """Valida "HH:MM:SS" (aceita "HH:MM") e devolve sempre com segundos."""
    s = (txt or "").strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(s, fmt).strftime("%H:%M:%S")
        except ValueError:
            continue
    raise ValueError(f"hora inválida: {txt!r} (use HH:MM:SS)")


def dias_uteis(inicio: date, fim: date) -> list[date]:
    """Dias de segunda a sexta entre inicio e fim (inclusive). Feriados não são
    conhecidos aqui: a DLL simplesmente não devolve negócios nesses dias."""
    if fim < inicio:
        raise ValueError(f"data final {fim} é anterior à inicial {inicio}")
    dias, d = [], inicio
    while d <= fim:
        if d.weekday() < 5:
            dias.append(d)
        d += timedelta(days=1)
    return dias


def janela_do_dia(dia: date, hora_inicio: str = HORA_INICIO_PADRAO,
                  hora_fim: str = HORA_FIM_PADRAO) -> tuple[str, str]:
    """
    Datas de início e fim da requisição de UM dia, no formato estrito da
    DLL ('%d/%m/%Y %H:%M:%S'), montadas com strftime — nunca concatenando.
    """
    hi = datetime.strptime(ler_hora(hora_inicio), "%H:%M:%S").time()
    hf = datetime.strptime(ler_hora(hora_fim), "%H:%M:%S").time()
    if hf <= hi:
        raise ValueError(f"hora final {hora_fim} precisa ser depois da inicial {hora_inicio}")
    return (datetime.combine(dia, hi).strftime(FORMATO_REQUISICAO),
            datetime.combine(dia, hf).strftime(FORMATO_REQUISICAO))


def caminho_do_dia(modelo: str, dia: date, asset: str = "") -> str:
    """Troca {data} por AAAA-MM-DD e {asset} pelo ticker no caminho de saída."""
    return modelo.replace("{data}", dia.strftime("%Y-%m-%d")).replace("{asset}", asset)


@dataclass
class ResultadoDia:
    """Conversão dos negócios brutos de um dia em Ticks do engine."""
    ticks:        list = field(default_factory=list)   # já em ordem cronológica
    recebidos:    int = 0     # tuplas que chegaram no callback
    ignorados:    int = 0     # TradeType ≠ 2/3 (cross, leilão, RLP...) ou qtd/preço ≤ 0
    duplicados:   int = 0     # tradeNumber repetido (só o primeiro fica)
    invalidos:    int = 0     # data fora do formato
    fora_do_dia:  int = 0     # negócio de outra data (resto de requisição anterior)
    numeros_duplicados: list = field(default_factory=list)


def converter_trades(trades, nomes: Optional[dict[int, str]] = None,
                     dia: Optional[date] = None) -> ResultadoDia:
    """
    Converte as tuplas acumuladas pelo callback de histórico em Ticks.

    Cada tupla: (data, tradeNumber, preco, volume_financeiro, qtd,
                 agente_comprador, agente_vendedor, tradeType)

    - Mesma regra do tempo real (trade_para_tick): TradeType 2 = compra
      agressora, 3 = venda agressora; os demais são ignorados e contados.
      O broker do Tick é a corretora agressora; passive_broker, a outra.
    - tradeNumber repetido conta como duplicado e só o primeiro fica.
    - Com `dia`, negócios de outra data são descartados (contados).
    - Resultado ordenado por (timestamp, tradeNumber).
    """
    res = ResultadoDia()
    vistos: set = set()
    validos = []
    for tr in trades:
        res.recebidos += 1
        data_txt, numero, preco, _vol, qtd, comprador, vendedor, tipo = tr
        numero = int(numero)
        if numero in vistos:
            res.duplicados += 1
            if len(res.numeros_duplicados) < 20:     # amostra para o log
                res.numeros_duplicados.append(numero)
            continue
        vistos.add(numero)
        try:
            ts = data_b3_para_epoch(data_txt)
        except ValueError:
            res.invalidos += 1
            continue
        if dia is not None and datetime.fromtimestamp(ts, FUSO_B3).date() != dia:
            res.fora_do_dia += 1
            continue
        tick = trade_para_tick(int(comprador), int(vendedor), int(qtd), float(preco),
                               int(tipo), ts, nomes)
        if tick is None:
            res.ignorados += 1
            continue
        validos.append((ts, numero, tick))
    validos.sort(key=lambda x: (x[0], x[1]))
    res.ticks = [t for _, _, t in validos]
    return res


def gravar_ticks(caminho: str, ticks: list[Tick]) -> int:
    """
    Grava os ticks no formato do replay (GravadorTicks, modo append).
    Cria a pasta se preciso. Devolve quantos foram gravados.
    """
    from replay.csv_ticks import GravadorTicks
    pasta = os.path.dirname(os.path.abspath(caminho))
    os.makedirs(pasta, exist_ok=True)
    grav = GravadorTicks(caminho)
    try:
        for t in ticks:
            grav.gravar(t)
    finally:
        grav.fechar()
    return grav.gravados


def gravar_dia(caminho: str, ticks: list[Tick]) -> int:
    """
    Grava um dia inteiro num arquivo próprio de forma atômica: escreve em
    "<arquivo>.parcial" e só renomeia no fim. Assim um arquivo existente
    é sempre um dia COMPLETO (e pode ser pulado ao retomar o download).
    """
    parcial = caminho + ".parcial"
    if os.path.exists(parcial):
        os.unlink(parcial)
    n = gravar_ticks(parcial, ticks)
    os.replace(parcial, caminho)
    return n


def resumo_dia(dia: date, res: ResultadoDia) -> str:
    txt = (f"{dia.strftime('%d/%m/%Y')}: {res.recebidos} negócios recebidos, "
           f"{len(res.ticks)} gravados, {res.ignorados} sem agressão")
    if res.duplicados:
        txt += (f", {res.duplicados} tradeNumber duplicados "
                f"(ex.: {res.numeros_duplicados[:5]})")
    if res.invalidos:
        txt += f", {res.invalidos} com data inválida"
    if res.fora_do_dia:
        txt += f", {res.fora_do_dia} de outro dia"
    return txt


# ──────────────────────────────────────────────────────────────
# DOWNLOAD (específico da DLL / Windows)
# ──────────────────────────────────────────────────────────────

class BaixadorHistorico:
    """
    Usa a conexão da ProfitDLLBridge (login + market data, sem assinar o
    ativo) e pede o histórico dia a dia com GetHistoryTrades.

    Os callbacks da DLL só acumulam tuplas numa lista (sob lock); toda a
    conversão e gravação acontece na thread principal, depois do
    progresso chegar a 100.
    """

    def __init__(self, asset: str, agentes_path: Optional[str] = None,
                 timeout_conexao: int = 30, timeout_dia: float = 600.0):
        self.asset = validar_ativo(asset)
        self.exchange = BOLSA
        self.nomes = carregar_nomes_agentes(agentes_path)
        self.timeout_dia = timeout_dia
        self.bridge = ProfitDLLBridge(self.asset, agentes_path,
                                      timeout=timeout_conexao)
        self.dll = None
        self._callbacks: list = []      # mantém os WINFUNCTYPE vivos (anti-GC)
        self._lock = threading.Lock()
        self._buffer: list = []
        self._pronto = threading.Event()
        self.progresso = 0

    def conectar(self):
        # Reaproveita login/estado da bridge; não chama SubscribeTicker
        self.bridge._conectar()
        self.dll = self.bridge.dll
        self._registrar_callbacks()

    def fechar(self):
        self.bridge.stop()
        self.dll = None

    def _registrar_callbacks(self):
        from ctypes import WINFUNCTYPE, Structure, c_double, c_int, c_uint, c_wchar_p

        try:
            from profitTypes import TAssetID       # se o profitTypes.py tiver
        except ImportError:
            class TAssetID(Structure):              # definição do artigo da Nelogica
                _fields_ = [("ticker", c_wchar_p), ("bolsa", c_wchar_p), ("feed", c_int)]

        # (asset POR VALOR, date, tradeNumber, price, vol, qtd, buyAgent, sellAgent, tradeType)
        THistoryTradeCallback = WINFUNCTYPE(None, TAssetID, c_wchar_p, c_uint, c_double,
                                            c_double, c_int, c_int, c_int, c_int)
        TProgressCallback = WINFUNCTYPE(None, TAssetID, c_int)

        dll = self.dll
        dll.GetHistoryTrades.argtypes = [c_wchar_p, c_wchar_p, c_wchar_p, c_wchar_p]
        dll.GetHistoryTrades.restype = c_int
        dll.SetHistoryTradeCallback.argtypes = [THistoryTradeCallback]
        dll.SetHistoryTradeCallback.restype = c_int
        dll.SetSerieProgressCallback.argtypes = [TProgressCallback]
        dll.SetSerieProgressCallback.restype = c_int

        def on_historico(asset, data, numero, preco, vol, qtd, comprador, vendedor, tipo):
            # Roda na thread da DLL: só acumula (nada de I/O nem chamada à DLL)
            with self._lock:
                self._buffer.append((data, numero, preco, vol, qtd,
                                     comprador, vendedor, tipo))

        def on_progresso(asset, progresso):
            self.progresso = progresso
            if progresso >= 100:
                self._pronto.set()

        cb_hist = THistoryTradeCallback(on_historico)
        cb_prog = TProgressCallback(on_progresso)
        self._callbacks += [cb_hist, cb_prog]
        dll.SetHistoryTradeCallback(cb_hist)
        dll.SetSerieProgressCallback(cb_prog)

    def baixar_dia(self, dia: date, hora_inicio: str = HORA_INICIO_PADRAO,
                   hora_fim: str = HORA_FIM_PADRAO) -> list:
        """Pede um dia e espera o progresso 100. Devolve as tuplas brutas."""
        inicio, fim = janela_do_dia(dia, hora_inicio, hora_fim)
        with self._lock:
            self._buffer = []
        self._pronto.clear()
        self.progresso = 0

        ret = self.dll.GetHistoryTrades(self.asset, self.exchange, inicio, fim)
        if ret in _ERROS_DEFINITIVOS:
            raise ErroDefinitivoHistorico(f"GetHistoryTrades recusado: {_ERROS_DEFINITIVOS[ret]}")
        if ret != 0:
            raise RuntimeError(f"GetHistoryTrades falhou: código {ret}")

        limite = time.time() + self.timeout_dia
        ultimo_log = time.time()
        while not self._pronto.wait(1.0):
            if time.time() > limite:
                raise TimeoutError(f"histórico não terminou em {self.timeout_dia:.0f}s "
                                   f"(progresso {self.progresso}%)")
            if time.time() - ultimo_log >= 10:
                with self._lock:
                    n = len(self._buffer)
                logger.info(f"  {dia.strftime('%d/%m/%Y')}: {self.progresso}% "
                            f"({n} negócios até agora)")
                ultimo_log = time.time()

        with self._lock:
            trades, self._buffer = self._buffer, []
        return trades

    def baixar_periodo(self, dias: list[date], saida: str, hora_inicio: str,
                       hora_fim: str, refazer: bool = False, tentativas: int = 2) -> dict:
        """
        Baixa cada dia e grava logo em seguida (persistência incremental).
        Devolve um resumo {dias_ok, dias_vazios, dias_pulados, dias_falhos, ticks}.
        """
        por_dia = "{data}" in saida
        resumo = {"dias_ok": 0, "dias_vazios": 0, "dias_pulados": 0,
                  "dias_falhos": [], "ticks": 0}
        for dia in dias:
            caminho = caminho_do_dia(saida, dia, self.asset)
            if por_dia and not refazer and os.path.exists(caminho) \
                    and os.path.getsize(caminho) > 0:
                logger.info(f"{dia.strftime('%d/%m/%Y')}: já existe {caminho} — pulando")
                resumo["dias_pulados"] += 1
                continue

            trades, erro = None, None
            for tentativa in range(1, max(1, tentativas) + 1):
                try:
                    t0 = time.time()
                    trades = self.baixar_dia(dia, hora_inicio, hora_fim)
                    logger.info(f"{dia.strftime('%d/%m/%Y')}: download em "
                                f"{time.time() - t0:.1f}s")
                    break
                except ErroDefinitivoHistorico as e:
                    erro = e
                    break                       # repetir não adianta
                except (RuntimeError, TimeoutError) as e:
                    erro = e
                    logger.warning(f"{dia.strftime('%d/%m/%Y')}: tentativa "
                                   f"{tentativa} falhou — {e}")
            if trades is None:
                resumo["dias_falhos"].append(dia.isoformat())
                logger.error(f"{dia.strftime('%d/%m/%Y')}: desistindo — {erro}")
                continue

            codigos = {int(c) for tr in trades for c in (tr[5], tr[6])}
            res = converter_trades(trades, self.bridge._nomes_para(*codigos), dia)
            logger.info(resumo_dia(dia, res))
            if not res.ticks:
                logger.info(f"{dia.strftime('%d/%m/%Y')}: sem negócios (feriado?) — "
                            f"nada gravado")
                resumo["dias_vazios"] += 1
                continue
            n = gravar_dia(caminho, res.ticks) if por_dia else gravar_ticks(caminho, res.ticks)
            resumo["dias_ok"] += 1
            resumo["ticks"] += n
        return resumo


# ──────────────────────────────────────────────────────────────
# LINHA DE COMANDO
# ──────────────────────────────────────────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="python -m profitdll.historico",
        description="Baixa o histórico de negócios pela ProfitDLL para o CSV do replay")
    p.add_argument("--asset",       required=True, help="Ticker da ação (ex: PETR4)")
    p.add_argument("--inicio",      required=True, help="Primeiro dia (AAAA-MM-DD ou DD/MM/AAAA)")
    p.add_argument("--fim",         default=None,  help="Último dia (padrão: igual ao início)")
    p.add_argument("--saida",       default=SAIDA_PADRAO,
                   help="CSV de saída. Com {data}: um arquivo por dia (padrão "
                        "historico/{asset}_{data}.csv). Sem {data}: um arquivo só")
    p.add_argument("--agentes",     default=None, help="JSON {codigo: nome} das corretoras")
    p.add_argument("--hora-inicio", default=HORA_INICIO_PADRAO,
                   help=f"Início da janela de cada dia (padrão {HORA_INICIO_PADRAO})")
    p.add_argument("--hora-fim",    default=HORA_FIM_PADRAO,
                   help=f"Fim da janela de cada dia (padrão {HORA_FIM_PADRAO})")
    p.add_argument("--timeout-dia", default=600.0, type=float,
                   help="Segundos máximos por dia até o progresso chegar a 100 (padrão 600)")
    p.add_argument("--tentativas",  default=2, type=int,
                   help="Tentativas por dia em caso de erro/timeout (padrão 2)")
    p.add_argument("--refazer",     action="store_true",
                   help="Baixa de novo dias que já têm arquivo (ou apaga o arquivo único)")
    args = p.parse_args(argv)
    try:
        args.asset = validar_ativo(args.asset)      # só ações
    except ValueError as e:
        p.error(str(e))
    return args


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    args = parse_args(argv)
    try:
        inicio = ler_data(args.inicio)
        fim = ler_data(args.fim) if args.fim else inicio
        dias = dias_uteis(inicio, fim)
        janela_do_dia(inicio, args.hora_inicio, args.hora_fim)     # valida as horas
        validar_janela_historico(inicio)                           # limite de 30 dias da DLL
    except ValueError as e:
        logger.error(str(e))
        return 2
    if not dias:
        logger.error("Nenhum dia útil no período")
        return 2

    if "{data}" not in args.saida:
        caminho = caminho_do_dia(args.saida, inicio, args.asset)
        if os.path.exists(caminho) and os.path.getsize(caminho) > 0:
            if not args.refazer:
                logger.error(f"{caminho} já existe — use --refazer para substituir "
                             f"ou ponha {{data}} no nome para um arquivo por dia")
                return 2
            os.unlink(caminho)

    baixador = BaixadorHistorico(args.asset, args.agentes,
                                 timeout_dia=args.timeout_dia)
    logger.info(f"Histórico de {args.asset} (bolsa {baixador.exchange}): {len(dias)} dias "
                f"úteis de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}, "
                f"{ler_hora(args.hora_inicio)}–{ler_hora(args.hora_fim)} → {args.saida}")
    try:
        baixador.conectar()
        resumo = baixador.baixar_periodo(dias, args.saida, args.hora_inicio, args.hora_fim,
                                         refazer=args.refazer, tentativas=args.tentativas)
    except KeyboardInterrupt:
        logger.info("Interrompido — os dias já concluídos ficaram gravados")
        return 1
    except Exception as e:
        logger.error(f"Falha no download: {e}")
        return 1
    finally:
        baixador.fechar()

    logger.info(f"Fim: {resumo['dias_ok']} dias gravados ({resumo['ticks']} negócios), "
                f"{resumo['dias_vazios']} sem negócios, {resumo['dias_pulados']} pulados, "
                f"{len(resumo['dias_falhos'])} com falha {resumo['dias_falhos'] or ''}")
    return 0 if not resumo["dias_falhos"] else 1


if __name__ == "__main__":
    sys.exit(main())
