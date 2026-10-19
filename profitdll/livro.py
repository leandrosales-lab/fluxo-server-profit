"""
LIVRO DE OFERTAS (book completo, uma entrada por ORDEM) — puro Python, sem DLL
=============================================================================
Mantém o livro que a ProfitDLL entrega pelo callback de ofertas V2
(SetOfferBookCallbackV2 / SubscribeOfferBook): duas listas de ordens
(compra e venda), cada ordem = [preço, quantidade, agente, offer_id].

Convenções (exemplo oficial da Nelogica, "Exemplo Python/main.py"):
  - Ações: atAdd=0, atEdit=1, atDelete=2, atDeleteFrom=3, atFullBook=4.
  - A posição é contada a partir do FIM da lista:
      atEdit/atDelete/atDeleteFrom → índice = tamanho − posição − 1
      atAdd                        → insere no índice = tamanho − posição
    (posição 0 = última ordem da lista). O snapshot NÃO depende da ordem da
    lista: ordena por preço (compras do maior para o menor, vendas do menor
    para o maior), então só as operações incrementais dependem desta convenção.
  - atDeleteFrom apaga do índice calculado até o fim da lista (como o exemplo).
  - atFullBook chega em 1 ou mais pacotes por lado; o rodapé do array traz
    flags: 2 = primeiro pacote, 1 = último (3 = pacote único). O livro só
    troca quando o último pacote fecha; pacote do meio/último sem o primeiro
    é descartado e contado em `erros`.

Dúvida aberta (validar com dado real ao vivo): a semântica de atEdit.
O exemplo oficial faz  qtd += nQtd  e  agente += nAgent  (soma). A soma do
agente não faz sentido (um código de corretora somado a outro), então aqui o
agente é SUBSTITUÍDO quando vem > 0. Para a quantidade, EDIT_SOMA = True segue
o exemplo (o dado recebido é tratado como delta); se o dado real mostrar que
nQtd é o valor novo da ordem, basta trocar para False (substitui). Quando
`bHasQtd` é falso o chamador passa qtd=0 e nada muda.

Nada aqui levanta exceção para a thread da DLL: posição/ação/lado inválidos
ou array corrompido são ignorados e contados em `erros`.
"""
import struct
from typing import Callable, Optional, Union

# True: atEdit soma nQtd à quantidade da ordem (exemplo oficial). False: substitui.
# FÁCIL DE INVERTER após validar com dado real.
EDIT_SOMA = True

AT_ADD, AT_EDIT, AT_DELETE, AT_DELETE_FROM, AT_FULLBOOK = 0, 1, 2, 3, 4
LADO_COMPRA, LADO_VENDA = 0, 1
FLAG_ULTIMO, FLAG_PRIMEIRO = 1, 2

CABECALHO_V2 = struct.Struct("=ii")        # Q (entradas), tamanho total do array em bytes
ENTRADA_V2   = struct.Struct("=dqiqH")     # preço, qtd (int64), agente, offer_id (int64), tamanho da data
RODAPE_V2    = struct.Struct("=I")         # flags do pacote
MAX_ENTRADAS = 1_000_000                   # sanidade: acima disso o cabeçalho está corrompido
CASAS_PRECO  = 2                           # agregação por preço (ações da B3: tick de R$ 0,01)

Nomes = Union[dict, Callable[[int], str], None]


def decodifica_array_v2(dados: bytes) -> tuple[list[tuple], int]:
    """
    Decodifica um array V2 do FullBook: cabeçalho int32 Q + int32 tamanho; Q entradas
    "=dqiqH" seguidas de T bytes de data ANSI (T varia por entrada, então o parse é
    SEQUENCIAL); rodapé uint32 de flags depois das entradas.
    Devolve ([(preço, qtd, agente, offer_id, data_texto), ...], flags).
    ValueError se o array estiver truncado/corrompido.
    """
    n = len(dados)
    if n < CABECALHO_V2.size:
        raise ValueError("array V2 menor que o cabeçalho")
    q, _tamanho = CABECALHO_V2.unpack_from(dados, 0)
    if q < 0 or q > MAX_ENTRADAS:
        raise ValueError(f"array V2 com quantidade de entradas inválida ({q})")
    pos = CABECALHO_V2.size
    entradas = []
    for _ in range(q):
        if pos + ENTRADA_V2.size > n:
            raise ValueError("array V2 truncado numa entrada")
        preco, qtd, agente, offer_id, tam_data = ENTRADA_V2.unpack_from(dados, pos)
        pos += ENTRADA_V2.size
        if pos + tam_data > n:
            raise ValueError("array V2 truncado na data da entrada")
        data = dados[pos:pos + tam_data].decode("latin-1", errors="replace")
        pos += tam_data
        entradas.append((preco, qtd, agente, offer_id, data))
    if pos + RODAPE_V2.size > n:
        raise ValueError("array V2 sem rodapé de flags")
    flags = RODAPE_V2.unpack_from(dados, pos)[0]
    return entradas, flags


class LivroOfertas:
    """Livro por ordem. Não é thread-safe: use só na thread consumidora da ponte."""

    def __init__(self):
        self.compra: list[list] = []     # [preço, qtd, agente, offer_id]
        self.venda:  list[list] = []
        self.erros = 0                   # posição/ação/lado inválidos, pacotes órfãos, arrays corrompidos
        self._acc: dict[int, Optional[list]] = {LADO_COMPRA: None, LADO_VENDA: None}

    def limpar(self) -> None:
        """Esvazia o livro e descarta pacotes em acúmulo (reconexão). Os contadores de erros acumulam."""
        self.compra, self.venda = [], []
        self._acc = {LADO_COMPRA: None, LADO_VENDA: None}

    # ── estado
    @property
    def ordens_total(self) -> int:
        return len(self.compra) + len(self.venda)

    @property
    def vazio(self) -> bool:
        return not self.compra and not self.venda

    def _lista(self, lado: int) -> Optional[list]:
        if lado == LADO_COMPRA:
            return self.compra
        if lado == LADO_VENDA:
            return self.venda
        return None

    def _erro(self) -> bool:
        self.erros += 1
        return False

    def melhor(self, lado: int) -> Optional[float]:
        """Melhor preço do lado (maior compra / menor venda) ou None."""
        lista = self._lista(lado)
        if not lista:
            return None
        precos = [round(o[0], CASAS_PRECO) for o in lista if o[1] > 0]
        if not precos:
            return None
        return max(precos) if lado == LADO_COMPRA else min(precos)

    # ── eventos incrementais
    def aplicar(self, acao: int, posicao: int, lado: int, preco: float, qtd: int,
                agente: int, offer_id: int) -> bool:
        """Aplica atAdd/atEdit/atDelete/atDeleteFrom. True se aplicou; False (e erros += 1) se inválido."""
        try:
            lista = self._lista(lado)
            if lista is None:
                return self._erro()
            tam = len(lista)
            if acao == AT_ADD:
                if not 0 <= posicao <= tam or preco <= 0 or qtd <= 0:
                    return self._erro()
                lista.insert(tam - posicao, [float(preco), int(qtd), int(agente), int(offer_id)])
                return True
            if acao in (AT_EDIT, AT_DELETE, AT_DELETE_FROM):
                idx = tam - posicao - 1
                if posicao < 0 or not 0 <= idx < tam:
                    return self._erro()
                if acao == AT_EDIT:
                    ordem = lista[idx]
                    if qtd:
                        ordem[1] = ordem[1] + int(qtd) if EDIT_SOMA else int(qtd)
                    if preco > 0:
                        ordem[0] = float(preco)
                    if agente > 0:
                        ordem[2] = int(agente)    # o exemplo oficial soma; substituir é o único sentido plausível
                    if offer_id > 0:
                        ordem[3] = int(offer_id)
                elif acao == AT_DELETE:
                    del lista[idx]
                else:
                    del lista[idx:]
                return True
            return self._erro()
        except Exception:      # nunca derruba a thread da DLL
            return self._erro()

    # ── FullBook (acúmulo de pacotes)
    def full_book(self, compra: Optional[list] = None, flags_compra: int = 0,
                  venda: Optional[list] = None, flags_venda: int = 0) -> None:
        """
        Recebe as entradas decodificadas (decodifica_array_v2) de cada lado, com as flags do
        rodapé. None = o callback não trouxe esse lado. O lado só é trocado quando fecha o último pacote.
        """
        self._pacote(LADO_COMPRA, compra, flags_compra)
        self._pacote(LADO_VENDA, venda, flags_venda)

    def _pacote(self, lado: int, entradas: Optional[list], flags: int) -> None:
        if entradas is None:
            return
        novas = [[float(e[0]), int(e[1]), int(e[2]), int(e[3])] for e in entradas]
        if flags & FLAG_PRIMEIRO:
            self._acc[lado] = []
        elif self._acc[lado] is None:
            self._erro()           # pacote do meio/último sem o primeiro: descarta
            return
        self._acc[lado].extend(novas)
        if flags & FLAG_ULTIMO:
            completo, self._acc[lado] = self._acc[lado], None
            if lado == LADO_COMPRA:
                self.compra = completo
            else:
                self.venda = completo

    # ── saída
    def snapshot(self, n: int = 15, nomes: Nomes = None) -> dict:
        """
        {"bids": [...], "asks": [...]} com até n níveis por lado, agregados por preço:
        {"price", "qty", "ordens", "corretoras": [[nome, qtd], ...2–3 maiores]}.
        `nomes`: dict código→nome ou função código→nome; sem nome vale o código como texto.
        """
        if callable(nomes):
            nome_de = nomes
        else:
            mapa = nomes or {}
            nome_de = lambda c: mapa.get(c) or str(c)
        return {"bids": self._niveis(self.compra, True, n, nome_de),
                "asks": self._niveis(self.venda, False, n, nome_de)}

    @staticmethod
    def _niveis(lista: list, maior_primeiro: bool, n: int, nome_de: Callable[[int], str]) -> list[dict]:
        por_preco: dict[float, list] = {}
        for preco, qtd, agente, _oid in lista:
            if qtd <= 0:
                continue
            nivel = por_preco.setdefault(round(preco, CASAS_PRECO), [0, 0, {}])
            nivel[0] += qtd
            nivel[1] += 1
            nivel[2][agente] = nivel[2].get(agente, 0) + qtd
        saida = []
        for preco in sorted(por_preco, reverse=maior_primeiro)[:max(0, n)]:
            qtd, ordens, agentes = por_preco[preco]
            maiores = sorted(agentes.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
            saida.append({"price": preco, "qty": qtd, "ordens": ordens,
                          "corretoras": [[nome_de(c), q] for c, q in maiores]})
        return saida
