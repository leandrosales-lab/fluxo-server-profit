"""
LEILÃO SIMULADO — dados de demonstração da tela Leilão
======================================================
Enquanto a ponte da DLL não manda o livro, o estado e o teórico do leilão, este simulador alimenta o
PainelLeilao com ordens inventadas para os papéis mais líquidos. Os números NÃO são de mercado: a tela
mostra "dados simulados" e o servidor só liga isto com --leilao-demo.

Cada ciclo vai de 09:45:00 a 10:00:00 (horário da B3 do dia), abre o papel no último teórico, fica
ABERTO_POR segundos e recomeça. Cada papel tem um viés (mais compradores ou vendedores) e alguns
recebem, no meio do leilão, um lote grande parado (a escora) de um lado.
"""

from __future__ import annotations

import random
import threading
import time
from datetime import datetime

from core.leilao import FUSO_B3, PainelLeilao, abertura_do_dia, tendencia

# ativo, fechamento anterior, liquidez média (R$ mi/dia), viés das ordens (+ compra / − venda), lado da escora
PAPEIS = [
    ("VALE3", 45.50, 1500, -1, "venda"),  ("PETR4", 38.40, 1800, +1, "compra"), ("ITUB4", 37.20, 900, +1, None),
    ("BBDC4", 15.80, 520, -1, "compra"),  ("BBAS3", 27.40, 480, +1, "compra"),  ("B3SA3", 12.60, 410, 0, None),
    ("ABEV3", 13.10, 350, 0, "venda"),    ("WEGE3", 52.30, 330, +1, "compra"),  ("PRIO3", 44.80, 420, -1, "venda"),
    ("RENT3", 50.40, 300, -1, None),      ("SUZB3", 55.20, 260, 0, "compra"),   ("ELET3", 41.70, 380, +1, None),
    ("GGBR4", 18.90, 210, -1, "venda"),   ("BPAC11", 34.60, 340, +1, "venda"),  ("ITSA4", 10.40, 250, 0, None),
    ("JBSS3", 33.80, 230, +1, "compra"),  ("RDOR3", 29.90, 190, 0, None),       ("EQTL3", 31.20, 170, -1, "compra"),
    ("LREN3", 16.70, 160, -1, "venda"),   ("CSNA3", 9.80, 90, -1, None),        ("MGLU3", 8.90, 120, +1, None),
    ("HAPV3", 3.95, 95, -1, "venda"),     ("CMIG4", 11.20, 140, +1, "compra"),  ("SBSP3", 98.50, 280, 0, None),
    ("PETR3", 41.20, 450, +1, None),
]
# Viés contra a tendência dos últimos pregões: desbalanceados que NÃO entram no perfil
CONTRA_TENDENCIA = {"RENT3", "ELET3", "MGLU3", "CSNA3"}
CORRETORAS = ["BTG", "XP", "ITAU", "UBS", "JP MORGAN", "MORGAN STANLEY", "GOLDMAN", "BRADESCO", "SAFRA",
              "GENIAL", "BOFA", "CITI", "SANTANDER", "CLEAR", "AGORA", "MODAL"]

DURACAO = 15 * 60       # 09:45 → 10:00
ABERTO_POR = 30         # s de "aberto" antes do próximo ciclo


class SimuladorLeilao:
    def __init__(self, painel: PainelLeilao, semente: int = 7, velocidade: float = 3.0, inicio: float | None = None):
        self.painel = painel
        self.rnd = random.Random(semente)
        self.velocidade = velocidade
        self._seq = 0
        self._parar = threading.Event()
        self._thread = None
        hoje = datetime.fromtimestamp(inicio or time.time(), FUSO_B3)
        self._inicio_dia = abertura_do_dia(hoje.timestamp()) - DURACAO
        self._papeis = {}
        for ativo, ref, liq, vies, escora in PAPEIS:
            fech = self._fechamentos(ref, -vies if ativo in CONTRA_TENDENCIA else vies)
            self._papeis[ativo] = {"ref": ref, "liq": liq * 1e6, "vies": vies, "escora": escora,
                                   "lote": max(100, round(liq * 1e6 / ref / 2500, -2)), "escora_em": None}
            painel.cadastrar(ativo, referencia=ref, tendencia_=tendencia(fech), liquidez=liq * 1e6)
        self._recomecar()

    def _fechamentos(self, ref: float, vies: int) -> list[float]:
        """30 pregões que terminam em ref: com viés, uma tendência; sem viés, lateral."""
        passo = 0.004 * vies
        return [ref * (1 - passo * (30 - i)) * (1 + self.rnd.uniform(-0.002, 0.002)) for i in range(30)] + [ref]

    def _recomecar(self):
        self.t = self._inicio_dia
        self.painel.limpar()
        self.painel.abertura_prevista = self._inicio_dia + DURACAO
        self.painel.agora = self.t
        for ativo, s in self._papeis.items():
            self.painel.definir_fase(ativo, 13, self.t)
            s["escora_em"] = self.t + self.rnd.uniform(0.3, 0.7) * DURACAO if s["escora"] else None
            for _ in range(40):
                self._nova_ordem(ativo, s)

    def _nova_ordem(self, ativo: str, s: dict, lado: str | None = None, qtd: int | None = None, preco: float | None = None,
                    corretora: str | None = None):
        r = self.rnd
        if lado is None:
            lado = "compra" if r.random() < 0.5 + 0.15 * s["vies"] else "venda"
        if preco is None:
            # compra cara e venda barata existem no leilão (é o que cruza o livro); o viés desloca as duas
            desvio = r.gauss(0.0015 * s["vies"] + (0.002 if lado == "venda" else -0.002), 0.006)
            ticks = round(s["ref"] * desvio / self.painel.tick)
            if r.random() < 0.6:
                ticks = round(ticks / 5) * 5          # preço "redondo"
            preco = round(s["ref"] + ticks * self.painel.tick, 2)
        if qtd is None:
            qtd = max(100, round(s["lote"] * r.lognormvariate(0, 0.9), -2))
        self._seq += 1
        self.painel.ordem(ativo, self._seq, lado, preco, int(qtd), corretora or r.choice(CORRETORAS), self.t)

    def passo(self, dt: float):
        """Avança dt segundos do relógio simulado."""
        r = self.rnd
        self.t += dt
        self.painel.agora = self.t
        fim = self._inicio_dia + DURACAO
        if self.t >= fim + ABERTO_POR:
            self._recomecar()
            return
        if self.t >= fim:
            for ativo in self._papeis:
                teorico = self.painel.teorico(ativo)[0]
                if self.painel.fase(ativo) != 0 and teorico:
                    self.painel.abrir(ativo, teorico, self.t)
            return
        if self.t >= fim - 5 * 60:
            for ativo in self._papeis:
                if self.painel.fase(ativo) == 13:
                    self.painel.definir_fase(ativo, 4, self.t)       # últimos 5 min: leilão (sem cancelar, na B3)
        for ativo, s in self._papeis.items():
            if s["escora_em"] and self.t >= s["escora_em"]:
                s["escora_em"] = None
                lado = s["escora"]
                distancia = round(s["ref"] * r.uniform(0.006, 0.012) / 0.05) * 0.05   # preço redondo
                preco = round(s["ref"] - distancia if lado == "compra" else s["ref"] + distancia, 2)
                self._nova_ordem(ativo, s, lado, int(s["lote"] * 25), preco, r.choice(CORRETORAS[:7]))
            for _ in range(_poisson(r, 0.6 * dt)):
                ordens = self.painel._papeis[ativo].ordens
                if len(ordens) > 40 and r.random() < 0.5:
                    oid = r.choice(list(ordens))
                    if ordens[oid][2] < s["lote"] * 10:                  # a escora não sai
                        self.painel.cancelar(ativo, oid, self.t)
                else:
                    self._nova_ordem(ativo, s)

    def iniciar(self, intervalo: float = 0.25):
        def laco():
            while not self._parar.wait(intervalo):
                self.passo(intervalo * self.velocidade)
        self._thread = threading.Thread(target=laco, name="leilao-simulado", daemon=True)
        self._thread.start()

    def parar(self):
        self._parar.set()


def _poisson(r: random.Random, media: float) -> int:
    n, limite, p = 0, pow(2.718281828, -media), r.random()
    while p > limite:
        n += 1
        p *= r.random()
    return n
