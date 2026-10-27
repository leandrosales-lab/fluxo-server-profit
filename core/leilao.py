"""
LEILÃO DE ABERTURA — desequilíbrio, pressão e escora
====================================================
Na pré-abertura o livro fica cruzado: compras acima de vendas. O preço teórico é o que casa a maior
quantidade. O que interessa para entrar no leilão é o que SOBRA no livro depois desse casamento,
porque é isso que fica no papel quando ele abre.

Exemplo (VALE3): teórico 45,50, sobram 300 mil na compra e 900 mil na venda dentro da banda. A venda
é 3× a compra: papel desbalanceado na venda, pressão para baixo.

Por papel, a cada mudança do livro:
  - teórico e quantidade teórica (da DLL, ou calculados aqui pelo livro);
  - sobra no teórico, banda de compra e banda de venda (só o que sobra, a ±BANDA do teórico);
  - pressão: lado e força do desequilíbrio (seta da tela);
  - escora: lote grande que sobra abaixo do teórico (compra) ou acima (venda), com a corretora dona;
  - "no perfil": desbalanceado, tendência a favor e escora do mesmo lado (ver no_perfil()).

As ordens chegam uma a uma por ordem(), cancelar() e limpar() (o simulador) ou em retratos do livro inteiro
por definir_livro() (a ponte da DLL, cerca de 1 por segundo por papel; os eventos saem da diferença entre
retratos). Fechamento anterior, tendência e liquidez vêm de carregar_diario() (tools/cotahist_b3.py).
Os limites (banda, razão, tamanho da escora) são ESCOLHAS DE TELA, não regras do curso: calibrar com
leilões reais gravados.
"""

from __future__ import annotations

import math
import statistics
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

FUSO_B3 = timezone(timedelta(hours=-3))

# Fases (SetChangeStateTickerCallback, p.32 e p.75 do manual): 13 pré-abertura, 4 leilão, 0 aberto
FASES = {13: "pré-abertura", 4: "leilão", 0: "aberto", 2: "congelado", 3: "inibido", 6: "fechado", 10: "pré-fechamento"}


@dataclass
class ConfigLeilao:
    banda: float = 0.02            # ±2% do teórico: o que está longe disso não segura o preço na abertura
    razao_min: float = 2.0         # um lado com 2× o outro na banda = desbalanceado
    razao_forte: float = 3.0       # 3× = seta dupla
    escora_fator: float = 4.0      # escora = nível com 4× a mediana dos níveis do mesmo lado na banda...
    escora_min_fin: float = 1e6    # ...com pelo menos R$ 1 mi parado no preço...
    escora_min_liq: float = 0.004  # ...e pelo menos 0,4% do volume financeiro médio do papel
    janela_delta: float = 30.0     # s: quanto o teórico andou neste tempo (coluna "Δ 30 s")
    max_eventos: int = 200


def _arred(p: float) -> float:
    return round(p, 4)


def preco_teorico(compra: dict, venda: dict, referencia: float | None = None):
    """
    (preço, quantidade casada) que maximiza o casamento entre compra (preço → qtd) e venda.
    Empates: menor sobra, depois o mais perto da referência (fechamento anterior), como na B3.
    Sem cruzamento: (None, 0).
    """
    if not compra or not venda or max(compra) < min(venda):
        return None, 0
    precos = sorted(set(compra) | set(venda))
    demanda, acc = [0] * len(precos), 0
    for i in range(len(precos) - 1, -1, -1):        # compra a p ou mais
        acc += compra.get(precos[i], 0)
        demanda[i] = acc
    melhor, oferta = None, 0
    for i, p in enumerate(precos):                   # venda a p ou menos
        oferta += venda.get(p, 0)
        casado = min(demanda[i], oferta)
        if casado <= 0:
            continue
        chave = (casado, -abs(demanda[i] - oferta), -abs(p - referencia) if referencia else 0.0)
        if melhor is None or chave > melhor[0]:
            melhor = (chave, p)
    return (melhor[1], melhor[0][0]) if melhor else (None, 0)


def sobra(compra: dict, venda: dict, teorico: float | None, casado: int):
    """
    Livro que fica depois do casamento no teórico: tira `casado` das melhores compras (maior preço
    primeiro) e das melhores vendas (menor preço primeiro). Devolve (compra, venda) por preço.
    """
    def consumir(niveis: dict, ordem_desc: bool) -> dict:
        resto, falta = {}, casado
        for p in sorted(niveis, reverse=ordem_desc):
            q = niveis[p]
            casa = min(q, falta) if (teorico is not None and (p >= teorico if ordem_desc else p <= teorico)) else 0
            falta -= casa
            if q - casa > 0:
                resto[p] = q - casa
        return resto
    if teorico is None:
        return dict(compra), dict(venda)
    return consumir(compra, True), consumir(venda, False)


def tendencia(fechamentos: list[float], n: int = 20) -> str:
    """alta / baixa / lateral: último fechamento acima da média de n dias e a média subindo (ou o contrário)."""
    if len(fechamentos) < n + 1:
        return "lateral"
    media = sum(fechamentos[-n:]) / n
    media_antes = sum(fechamentos[-n - 1:-1]) / n
    if fechamentos[-1] > media and media > media_antes:
        return "alta"
    if fechamentos[-1] < media and media < media_antes:
        return "baixa"
    return "lateral"


def no_perfil(r: dict) -> bool:
    """
    Desbalanceado, tendência a favor da pressão e escora sustentando o mesmo lado:
    sobra de compra + tendência de alta + escora de compra abaixo do teórico (ou o espelho na venda).
    Escora do MESMO lado do desequilíbrio: decisão de 27/10/2026 (a escora segura o movimento e o stop).
    """
    lado = r.get("desbalanceado")
    if lado == "compra":
        return r.get("tendencia") == "alta" and r.get("escora_abaixo") is not None
    if lado == "venda":
        return r.get("tendencia") == "baixa" and r.get("escora_acima") is not None
    return False


class _Papel:
    def __init__(self, ativo: str):
        self.ativo = ativo
        self.ordens: dict = {}                 # id → [lado, preço, qtd, corretora]
        self.fase = 13
        self.referencia: float | None = None   # fechamento anterior
        self.tendencia = "lateral"
        self.liquidez: float | None = None     # média de volume financeiro diário (R$)
        self.teorico_dll: tuple | None = None  # (preço, qtd) do SetTheoreticalPriceCallback
        self.teorico_hist: deque = deque(maxlen=600)   # (ts, preço)
        self.eventos: deque = deque()
        self.abertura: float | None = None     # preço do negócio de abertura (fase "aberto")

    def niveis(self, lado: str) -> dict:
        out: dict = {}
        for l, p, q, _c in self.ordens.values():
            if l == lado:
                out[p] = out.get(p, 0) + q
        return out

    def corretoras(self, lado: str, preco: float) -> list:
        soma: dict = {}
        for l, p, q, c in self.ordens.values():
            if l == lado and p == preco:
                soma[c] = soma.get(c, 0) + q
        return sorted(soma.items(), key=lambda x: -x[1])

    def tem_corretora(self, corretora: str) -> bool:
        return any(c == corretora for _l, _p, _q, c in self.ordens.values())


class PainelLeilao:
    """Estado do leilão de vários papéis. Thread-safe: a ponte escreve, o servidor lê."""

    def __init__(self, cfg: ConfigLeilao | None = None, tick: float = 0.01, fonte: str = "dll"):
        self.cfg = cfg or ConfigLeilao()
        self.tick = tick
        self.fonte = fonte                     # "dll" ou "simulado" (a tela avisa)
        self.abertura_prevista: float | None = None   # epoch do fim do leilão (10:00 B3)
        self.agora: float | None = None        # relógio dos dados
        self._papeis: dict[str, _Papel] = {}
        self._lock = threading.Lock()

    # ── entrada ────────────────────────────────────────────────
    def _papel(self, ativo: str) -> _Papel:
        p = self._papeis.get(ativo)
        if p is None:
            p = self._papeis[ativo] = _Papel(ativo)
        return p

    def cadastrar(self, ativo: str, referencia=None, tendencia_=None, liquidez=None):
        with self._lock:
            p = self._papel(ativo)
            if referencia is not None:
                p.referencia = referencia
            if tendencia_ is not None:
                p.tendencia = tendencia_
            if liquidez is not None:
                p.liquidez = liquidez

    def definir_fase(self, ativo: str, codigo: int, ts: float | None = None):
        with self._lock:
            self._papel(ativo).fase = codigo
            self._relogio(ts)

    def definir_teorico(self, ativo: str, preco: float | None, qtd: int, ts: float | None = None):
        """Teórico vindo da DLL (prevalece sobre o calculado). preco None volta ao cálculo pelo livro."""
        with self._lock:
            p = self._papel(ativo)
            p.teorico_dll = (preco, qtd) if preco else None
            self._relogio(ts)
            self._marcar_teorico(p)

    def abrir(self, ativo: str, preco: float, ts: float | None = None):
        """Negócio de abertura (trade tipo 4): fecha o leilão do papel."""
        with self._lock:
            p = self._papel(ativo)
            p.fase, p.abertura = 0, preco
            self._relogio(ts)

    def ordem(self, ativo: str, oid, lado: str, preco: float, qtd: int, corretora: str, ts: float | None = None):
        """Ordem nova ou alterada (mesmo id). lado: compra | venda."""
        with self._lock:
            p = self._papel(ativo)
            self._relogio(ts)
            antes = self._teorico(p)[0]
            velha = p.ordens.get(oid)
            novo_player = not p.tem_corretora(corretora)
            p.ordens[oid] = [lado, _arred(preco), int(qtd), corretora]
            delta = int(qtd) - (velha[2] if velha else 0)
            tipo = "entrou" if novo_player else ("aumentou" if delta > 0 else "reduziu")
            self._evento(p, tipo, lado, preco, delta, corretora, antes)

    def definir_livro(self, ativo: str, entradas, ts: float | None = None) -> int:
        """
        Retrato do livro do papel: [(lado, preço, qtd, corretora)]. Ordens da mesma corretora no mesmo preço
        somam. Substitui o livro e registra quem entrou, aumentou, reduziu, cancelou ou saiu pela diferença
        para o retrato anterior (o teórico antes e depois é o do retrato inteiro). Devolve quantas entradas
        foram descartadas por preço ou quantidade inválidos (ordem a mercado no leilão pode vir sem preço).
        """
        novo: dict = {}
        descartadas = 0
        for lado, preco, qtd, corretora in entradas:
            if lado not in ("compra", "venda") or not qtd or qtd < 0 or not math.isfinite(preco) or preco <= 0:
                descartadas += 1
                continue
            k = (lado, _arred(preco), corretora or "—")
            novo[k] = novo.get(k, 0) + int(qtd)
        with self._lock:
            p = self._papel(ativo)
            self._relogio(ts)
            antes = self._teorico(p)[0]
            velho: dict = {}
            for lado, preco, qtd, corretora in p.ordens.values():
                k = (lado, preco, corretora)
                velho[k] = velho.get(k, 0) + qtd
            corr_antes = {k[2] for k in velho}
            corr_depois = {k[2] for k in novo}
            p.ordens = {k: [k[0], k[1], q, k[2]] for k, q in novo.items()}
            self._marcar_teorico(p)
            depois = self._teorico(p)[0]
            for k in sorted(set(velho) | set(novo)):
                delta = novo.get(k, 0) - velho.get(k, 0)
                if not delta:
                    continue
                lado, preco, c = k
                if delta > 0:
                    tipo = "aumentou" if c in corr_antes else "entrou"
                else:
                    tipo = "saiu" if c not in corr_depois else "cancelou" if k not in novo else "reduziu"
                self._registrar(p, tipo, lado, preco, delta, c, antes, depois)
        return descartadas

    def carregar_diario(self, diario: dict) -> int:
        """
        {ativo: {"fechamentos": [...], "volumes": [...]}} (do mais antigo ao mais recente, R$ por pregão):
        fechamento anterior, tendência e liquidez (média dos últimos 20 pregões). Devolve quantos papéis.
        """
        n = 0
        for ativo, d in (diario or {}).items():
            fech = [float(x) for x in d.get("fechamentos") or [] if x]
            vols = [float(x) for x in d.get("volumes") or []][-20:]
            if not fech:
                continue
            self.cadastrar(ativo.upper(), referencia=fech[-1], tendencia_=tendencia(fech),
                           liquidez=(sum(vols) / len(vols)) if vols else None)
            n += 1
        return n

    def cancelar(self, ativo: str, oid, ts: float | None = None):
        with self._lock:
            p = self._papel(ativo)
            velha = p.ordens.get(oid)
            if velha is None:
                return
            self._relogio(ts)
            antes = self._teorico(p)[0]
            del p.ordens[oid]
            lado, preco, qtd, corretora = velha
            tipo = "saiu" if not p.tem_corretora(corretora) else "cancelou"
            self._evento(p, tipo, lado, preco, -qtd, corretora, antes)

    def limpar(self, ativo: str | None = None):
        with self._lock:
            for p in ([self._papeis[ativo]] if ativo in self._papeis else [] if ativo else self._papeis.values()):
                p.ordens.clear()
                p.eventos.clear()
                p.teorico_hist.clear()
                p.teorico_dll, p.abertura, p.fase = None, None, 13

    # ── cálculo ────────────────────────────────────────────────
    def _relogio(self, ts):
        if ts is not None:
            self.agora = ts

    def _teorico(self, p: _Papel):
        if p.teorico_dll:
            return p.teorico_dll
        return preco_teorico(p.niveis("compra"), p.niveis("venda"), p.referencia)

    def _marcar_teorico(self, p: _Papel):
        t = self._teorico(p)[0]
        if t is not None and self.agora is not None and (not p.teorico_hist or p.teorico_hist[-1][1] != t):
            p.teorico_hist.append((self.agora, t))

    def _evento(self, p: _Papel, tipo, lado, preco, delta, corretora, antes):
        self._marcar_teorico(p)
        self._registrar(p, tipo, lado, preco, delta, corretora, antes, self._teorico(p)[0])

    def _registrar(self, p: _Papel, tipo, lado, preco, delta, corretora, antes, depois):
        # Só o que importa: quem entrou/saiu, ordem grande ou ordem que mexeu o teórico
        if tipo in ("entrou", "saiu") or antes != depois or abs(delta) * preco >= self.cfg.escora_min_fin / 4:
            p.eventos.append({"ts": self.agora, "tipo": tipo, "lado": lado, "preco": preco, "qtd": delta,
                              "corretora": corretora, "teorico_antes": antes, "teorico_depois": depois})
            while len(p.eventos) > self.cfg.max_eventos:
                p.eventos.popleft()

    def _delta_ticks(self, p: _Papel, teorico):
        if teorico is None or self.agora is None:
            return None
        base = None
        for ts, t in p.teorico_hist:              # último teórico de antes da janela
            if ts <= self.agora - self.cfg.janela_delta:
                base = t
            else:
                break
        if base is None and p.teorico_hist:
            base = p.teorico_hist[0][1]
        return None if base is None else round((teorico - base) / self.tick)

    def _escora(self, p: _Papel, niveis: dict, lado: str, teorico: float):
        """Nível da sobra mais perto do teórico com escora_fator × a mediana do lado e escora_min_fin."""
        if not niveis:
            return None
        mediana = statistics.median(niveis.values())
        minimo = max(self.cfg.escora_min_fin, self.cfg.escora_min_liq * (p.liquidez or 0))
        perto = sorted(niveis, key=lambda x: abs(x - teorico))
        for preco in perto:
            q = niveis[preco]
            if q >= self.cfg.escora_fator * mediana and q * preco >= minimo:
                donos = p.corretoras(lado, preco)
                dono, qtd_dono = donos[0] if donos else ("—", 0)
                return {"preco": preco, "qtd": q, "dist_ticks": round(abs(preco - teorico) / self.tick),
                        "corretora": dono, "fatia": qtd_dono / q if q else 0.0}
        return None

    def _analisar(self, p: _Papel) -> dict:
        cfg = self.cfg
        compra, venda = p.niveis("compra"), p.niveis("venda")
        teorico, casado = self._teorico(p)
        resto_c, resto_v = sobra(compra, venda, teorico, casado)
        ref = teorico if teorico is not None else p.referencia
        r = {"ativo": p.ativo, "fase": FASES.get(p.fase, str(p.fase)), "teorico": teorico, "qtd_teorica": casado,
             "referencia": p.referencia, "abertura": p.abertura, "tendencia": p.tendencia, "liquidez": p.liquidez,
             "var_pct": (100 * (teorico / p.referencia - 1)) if teorico and p.referencia else None,
             "delta_ticks": self._delta_ticks(p, teorico), "sobra_lado": None, "sobra_qtd": 0,
             "banda_compra": 0, "banda_venda": 0, "razao": None, "desbalanceado": None, "pressao": 0,
             "escora_abaixo": None, "escora_acima": None, "no_perfil": False, "ordens": len(p.ordens)}
        if ref is None:
            return r
        lo, hi = ref * (1 - cfg.banda), ref * (1 + cfg.banda)
        banda_c = {x: q for x, q in resto_c.items() if lo <= x <= hi}
        banda_v = {x: q for x, q in resto_v.items() if lo <= x <= hi}
        bc, bv = sum(banda_c.values()), sum(banda_v.values())
        r["banda_compra"], r["banda_venda"] = bc, bv
        if teorico is not None:
            sc, sv = resto_c.get(teorico, 0), resto_v.get(teorico, 0)
            r["sobra_lado"] = "compra" if sc > sv else "venda" if sv > sc else None
            r["sobra_qtd"] = abs(sc - sv)
        if bc or bv:
            maior, menor = max(bc, bv), min(bc, bv)
            r["razao"] = (maior / menor) if menor else None      # None com um lado vazio = "só compra/venda"
            forca = float("inf") if not menor else maior / menor
            if forca >= cfg.razao_min:
                r["desbalanceado"] = "compra" if bc > bv else "venda"
                sinal = 1 if bc > bv else -1
                r["pressao"] = sinal * (2 if forca >= cfg.razao_forte else 1)
        if teorico is not None:
            r["escora_abaixo"] = self._escora(p, {x: q for x, q in banda_c.items() if x <= teorico}, "compra", teorico)
            r["escora_acima"] = self._escora(p, {x: q for x, q in banda_v.items() if x >= teorico}, "venda", teorico)
        r["no_perfil"] = no_perfil(r)
        return r

    # ── saída (GET /api/leilao) ────────────────────────────────
    def fase(self, ativo: str):
        with self._lock:
            p = self._papeis.get(ativo)
            return p.fase if p else None

    def teorico(self, ativo: str):
        with self._lock:
            p = self._papeis.get(ativo)
            return self._teorico(p) if p else (None, 0)

    def lista(self) -> list[dict]:
        with self._lock:
            linhas = [self._analisar(p) for p in self._papeis.values()]
        # No perfil primeiro, depois o mais desbalanceado (lado vazio conta como o maior)
        return sorted(linhas, key=lambda r: (not r["no_perfil"], r["desbalanceado"] is None,
                                             -(r["razao"] or (1e9 if r["desbalanceado"] else 0)), r["ativo"]))

    def resumo(self, lista: list[dict] | None = None) -> dict:
        lista = self.lista() if lista is None else lista
        return {"papeis": len(lista),
                "em_leilao": sum(1 for r in lista if r["fase"] in ("pré-abertura", "leilão")),
                "desbal_compra": sum(1 for r in lista if r["desbalanceado"] == "compra"),
                "desbal_venda": sum(1 for r in lista if r["desbalanceado"] == "venda"),
                "no_perfil": sum(1 for r in lista if r["no_perfil"])}

    def book(self, ativo: str, visao: str = "sobra", n_eventos: int = 40) -> dict | None:
        """Escada de preços do papel (só a sobra ou o livro inteiro), com a corretora maior de cada lado."""
        with self._lock:
            p = self._papeis.get(ativo)
            if p is None:
                return None
            r = self._analisar(p)
            compra, venda = p.niveis("compra"), p.niveis("venda")
            if visao == "sobra":
                compra, venda = sobra(compra, venda, r["teorico"], r["qtd_teorica"])
            ref = r["teorico"] if r["teorico"] is not None else p.referencia
            if ref is not None:
                lo, hi = ref * (1 - self.cfg.banda), ref * (1 + self.cfg.banda)
                compra = {x: q for x, q in compra.items() if lo <= x <= hi}
                venda = {x: q for x, q in venda.items() if lo <= x <= hi}
            esc_c = (r["escora_abaixo"] or {}).get("preco")
            esc_v = (r["escora_acima"] or {}).get("preco")
            niveis = []
            for preco in sorted(set(compra) | set(venda) | ({r["teorico"]} if r["teorico"] else set()), reverse=True):
                cc, cv = p.corretoras("compra", preco), p.corretoras("venda", preco)
                niveis.append({"preco": preco, "compra": compra.get(preco, 0), "venda": venda.get(preco, 0),
                               "corretora_compra": cc[0][0] if cc and compra.get(preco) else None,
                               "corretora_venda": cv[0][0] if cv and venda.get(preco) else None,
                               "teorico": preco == r["teorico"],
                               "escora": "compra" if preco == esc_c else "venda" if preco == esc_v else None})
            eventos = list(p.eventos)[-n_eventos:][::-1]
            return {**r, "visao": visao, "niveis": niveis, "eventos": eventos}


def abertura_do_dia(ts: float, hora: int = 10, minuto: int = 0) -> float:
    """Epoch das 10:00 (B3) do dia de ts: fim do leilão de abertura das ações."""
    d = datetime.fromtimestamp(ts, FUSO_B3)
    return d.replace(hour=hora, minute=minuto, second=0, microsecond=0).timestamp()
