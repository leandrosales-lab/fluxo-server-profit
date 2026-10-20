"""
Livro de ofertas por corretora — reposição de iceberg
=====================================================
Um giro de iceberg não é cada agressão. É a mesma corretora voltando ao mesmo
preço depois que o lote que estava visível foi consumido.

Exemplo: UBS com 1.500 na compra. Uma agressão de 300 deixa 1.200 — não é giro.
Quando os 1.500 acabam e a UBS volta com oferta no mesmo preço, aí é 1 giro.
"""

from __future__ import annotations

from dataclasses import dataclass


# Negócio que chega pouco depois da reposição ainda pode ser o lote que acabou
# (o livro e o negócio não saem na mesma ordem). Janela curta quando ainda não
# houve execução: um cancelamento seguido de ordem nova não vira giro.
JANELA_REORDEM = 0.20
JANELA_RESTO = 1.0


@dataclass(frozen=True)
class Renovacao:
    ativo: str
    corretora: str
    lado: str          # compra | venda  (lado defendido, o que está no book)
    preco: float
    qtd: int           # quantidade visível da oferta que voltou


@dataclass
class _Fatia:
    visivel: int = 0
    lote: int = 0              # tamanho mostrado quando a fatia apareceu
    execucao: int = 0          # negociado contra ela desde então
    esperando: bool = False    # o visível chegou a zero
    lote_zerou: int = 0
    consumida: int = 0         # execução atribuída à fatia que zerou
    divida: int = 0            # execução que ainda pode chegar fora de ordem
    divida_ate: float = 0.0
    preco: float = 0.0


class LivroOfertas:
    def __init__(self, tick_size: float = 0.01):
        self.tick = tick_size
        self._por: dict[tuple, dict[int, int]] = {}     # chave → offer_id → qtd
        self._onde: dict[tuple, tuple] = {}             # (ativo, offer_id) → chave
        self._chaves: dict[tuple, set] = {}             # (ativo, lado) → chaves com ofertas (evita varrer _por inteiro)
        self._fatias: dict[tuple, _Fatia] = {}

    def corretora_de(self, ativo: str, offer_id: int) -> str:
        chave = self._onde.get((ativo, int(offer_id)))
        return chave[1] if chave else ""

    def preco_de(self, ativo: str, offer_id: int) -> float:
        chave = self._onde.get((ativo, int(offer_id)))
        return chave[3] if chave else 0.0

    def reset(self) -> None:
        self._por.clear()
        self._onde.clear()
        self._chaves.clear()
        self._fatias.clear()

    def negocio(self, ativo: str, corretora: str, lado: str, preco: float, qtd: int, ts: float) -> list[Renovacao]:
        """Execução contra a passiva. Sozinha não é giro; só completa uma reposição pendente."""
        if qtd <= 0 or not corretora:
            return []
        chave = self._chave(ativo, corretora, lado, preco)
        f = self._fatias.get(chave)
        if f is None:
            return []
        saida: list[Renovacao] = []
        if f.divida > 0 and ts <= f.divida_ate:
            usa = min(qtd, f.divida)
            f.divida -= usa
            qtd -= usa
            if f.divida == 0:
                saida.append(self._emitir(chave, f))
        elif f.esperando and f.visivel == 0:
            f.consumida += qtd
            qtd = 0
        if qtd > 0:
            f.execucao += qtd
        return saida

    def definir(self, ativo: str, lado: str, ofertas: list[tuple[int, float, int, str]], ts: float) -> list[Renovacao]:
        """Substitui um lado inteiro. Cada oferta é (offer_id, preço, qtd, corretora)."""
        novas: dict[tuple, dict[int, int]] = {}
        precos: dict[tuple, float] = {}
        for offer_id, preco, qtd, corretora in ofertas:
            if qtd <= 0 or not corretora or offer_id == 0:
                continue
            p = self._preco(preco)
            chave = (ativo, corretora, lado, p)
            novas.setdefault(chave, {})[int(offer_id)] = int(qtd)
            precos[chave] = p
        chaves = set(self._chaves.get((ativo, lado), ()))
        chaves.update(novas)
        saida: list[Renovacao] = []
        for chave in chaves:
            antigo = self._vis(chave)
            livro = novas.get(chave, {})
            for offer_id in self._por.get(chave, {}):     # só as ofertas desta fatia (varrer _onde inteiro é quadrático)
                self._onde.pop((ativo, offer_id), None)
            if livro:
                self._por[chave] = dict(livro)
                self._chaves.setdefault((ativo, lado), set()).add(chave)
            else:
                self._por.pop(chave, None)
                self._chaves.get((ativo, lado), set()).discard(chave)
            for offer_id in livro:
                self._onde[(ativo, offer_id)] = chave
            saida += self._ajustar(chave, antigo, sum(livro.values()), precos.get(chave, chave[3]), ts)
        return saida

    def atualizar(self, ativo: str, lado: str, preco: float, qtd: int, corretora: str,
                  offer_id: int, ts: float, apagar: bool = False) -> list[Renovacao]:
        """Inclui, altera ou apaga uma oferta. `qtd` é a quantidade absoluta."""
        if offer_id == 0:
            return []
        ident = (ativo, int(offer_id))
        antiga = self._onde.get(ident)
        p = self._preco(preco) if preco else (antiga[3] if antiga else 0.0)
        nova = None if apagar or qtd <= 0 or not corretora else (ativo, corretora, lado, p)
        # Mesma oferta, mesmo preço: muda a quantidade direto. Tirar e pôr de novo
        # passaria por zero e pareceria reposição.
        if antiga is not None and antiga == nova:
            livro = self._por[antiga]
            antes = sum(livro.values())
            livro[ident[1]] = int(qtd)
            return self._ajustar(antiga, antes, sum(livro.values()), p, ts)
        saida: list[Renovacao] = []
        if antiga is not None:
            livro = self._por.get(antiga, {})
            velha = livro.pop(ident[1], 0)
            if not livro:
                self._por.pop(antiga, None)
                self._chaves.get((antiga[0], antiga[2]), set()).discard(antiga)
            del self._onde[ident]
            saida += self._ajustar(antiga, self._vis(antiga) + velha, self._vis(antiga), antiga[3], ts)
        if nova is None:
            return saida
        livro = self._por.setdefault(nova, {})
        self._chaves.setdefault((nova[0], nova[2]), set()).add(nova)
        antes = sum(livro.values())
        livro[int(offer_id)] = int(qtd)
        self._onde[ident] = nova
        saida += self._ajustar(nova, antes, sum(livro.values()), p, ts)
        return saida

    # ── interno
    def _chave(self, ativo: str, corretora: str, lado: str, preco: float) -> tuple:
        return (ativo, corretora, lado, self._preco(preco))

    def _preco(self, preco: float) -> float:
        return round(round(preco / self.tick) * self.tick, 10)

    def _vis(self, chave: tuple) -> int:
        return sum(self._por.get(chave, {}).values())

    def _ajustar(self, chave: tuple, antigo: int, novo: int, preco: float, ts: float) -> list[Renovacao]:
        if novo == antigo and chave in self._fatias:
            return []
        f = self._fatias.get(chave)
        if f is None:
            if novo <= 0:
                return []
            self._fatias[chave] = _Fatia(visivel=novo, lote=novo, preco=preco)
            return []
        f.visivel = novo
        f.preco = preco
        if novo < antigo:
            if novo == 0 and f.lote > 0:
                f.esperando = True
                f.lote_zerou = f.lote
                f.consumida = f.execucao
                f.execucao = 0
            return []
        if novo > antigo and antigo == 0 and (f.esperando or f.divida > 0):
            return self._repos(chave, f, ts)
        if novo > antigo and f.execucao == 0 and not f.esperando and f.divida == 0:
            f.lote = novo
        if antigo == 0 and not f.esperando and f.divida == 0:
            f.lote = novo
            f.execucao = 0
        return []

    def _repos(self, chave: tuple, f: _Fatia, ts: float) -> list[Renovacao]:
        saida: list[Renovacao] = []
        if f.consumida >= f.lote_zerou > 0:
            saida.append(self._emitir(chave, f))
            f.divida = 0
        elif f.lote_zerou > 0:
            f.divida = f.lote_zerou - f.consumida
            f.divida_ate = ts + (JANELA_RESTO if f.consumida > 0 else JANELA_REORDEM)
        f.esperando = False
        f.lote = f.visivel
        f.execucao = 0
        f.lote_zerou = 0
        f.consumida = 0
        return saida

    def _emitir(self, chave: tuple, f: _Fatia) -> Renovacao:
        f.divida = 0
        f.divida_ate = 0.0
        f.esperando = False
        f.lote_zerou = 0
        f.consumida = 0
        return Renovacao(chave[0], chave[1], chave[2], f.preco, f.visivel)
