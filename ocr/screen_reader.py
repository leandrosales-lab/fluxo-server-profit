"""
OCR SCREEN READER — Leitura do Profit via captura de tela
==========================================================
Captura as janelas de Book de Ofertas e Times & Trades do Profit Pro
e extrai os dados via OCR (Tesseract).

Requisitos (instalar no Windows):
  pip install mss pillow pytesseract opencv-python
  + Tesseract OCR: https://github.com/UB-Mannheim/tesseract/wiki

Configuração:
  1. Abrir o Profit Pro com Book e T&T visíveis
  2. Rodar este script para detectar as regiões automaticamente
  3. Ajustar ROI_* abaixo se necessário
"""

import re
import time
import threading
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable

logger = logging.getLogger("ScreenReader")

# Tentar importar dependências — falha graciosamente se não instaladas
try:
    import mss
    import mss.tools
    MSS_OK = True
except ImportError:
    MSS_OK = False
    logger.warning("mss não instalado. Captura de tela desativada.")

try:
    from PIL import Image, ImageFilter, ImageEnhance
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import pytesseract
    TESS_OK = True
    # Caminho padrão do Tesseract no Windows
    pytesseract.pytesseract.tesseract_cmd = (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    )
except ImportError:
    TESS_OK = False
    logger.warning("pytesseract não instalado. OCR desativado.")

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False


# ──────────────────────────────────────────────────────────────
# TIPOS
# ──────────────────────────────────────────────────────────────

@dataclass
class Region:
    """Região de captura de tela em pixels."""
    left:   int
    top:    int
    width:  int
    height: int

    def to_mss(self) -> dict:
        return {"left": self.left, "top": self.top,
                "width": self.width, "height": self.height}


@dataclass
class TTTrade:
    """Um negócio extraído do Times & Trades por OCR."""
    timestamp:  float
    price:      float
    qty:        int
    broker:     str
    side:       str         # "C" = compra, "V" = venda


@dataclass
class BookRow:
    """Uma linha do Book de Ofertas extraída por OCR."""
    price:  float
    qty:    int
    broker: str
    side:   str             # "C" = compra, "V" = venda


@dataclass
class ScreenConfig:
    """Coordenadas das janelas no monitor."""
    # Região do Times & Trades (ajustar para seu monitor)
    tt_region: Region = field(default_factory=lambda: Region(
        left=1600, top=100, width=600, height=900
    ))

    # Região do Book de Ofertas
    book_region: Region = field(default_factory=lambda: Region(
        left=1000, top=100, width=580, height=900
    ))

    # FPS de captura (frames por segundo)
    capture_fps: float = 4.0

    # Escala de zoom para melhorar OCR (2.0 = 2x)
    zoom_scale: float = 2.0

    # DPI do monitor (96 para Full HD, 144 para HiDPI)
    monitor_dpi: int = 96


# ──────────────────────────────────────────────────────────────
# PARSERS DE TEXTO OCR
# ──────────────────────────────────────────────────────────────

# Mapeamento de abreviações de corretoras que o Profit usa
BROKER_ALIASES = {
    "JP":      "JP MORGAN",
    "JPM":     "JP MORGAN",
    "GS":      "GOLDMAN SACHS",
    "GOLDMAN": "GOLDMAN SACHS",
    "BTG":     "BTG PACTUAL",
    "MERL":    "MERRILL LYNCH",
    "ML":      "MERRILL LYNCH",
    "CITY":    "CITY GROUP",
    "CITI":    "CITY GROUP",
    "ITAU":    "ITAU",
    "BRAD":    "BRADESCO",
    "SANT":    "SANTANDER",
    "SCOT":    "SCOTIA BANK",
    "XP":      "XP INC",
    "UBS":     "UBS",
    "AGO":     "AGORA",
    "MORG":    "MORGAN STANLEY",
    "MS":      "MORGAN STANLEY",
    "RICA":    "RICO",
    "CLEA":    "CLEAR",
    "BTG":     "BTG PACTUAL",
    "TORO":    "TORO",
    "GENE":    "GENIAL",
    "CM":      "CM CAPITAL",
}

def normalize_broker(raw: str) -> str:
    """Normaliza nome de corretora extraído por OCR."""
    raw = raw.strip().upper()
    for alias, full in BROKER_ALIASES.items():
        if raw.startswith(alias):
            return full
    return raw if raw else "DESCONHECIDA"

def parse_price(s: str) -> Optional[float]:
    """Converte string de preço para float. Ex: '19,05' → 19.05"""
    s = s.strip().replace(",", ".").replace(" ", "")
    # Remover caracteres não numéricos exceto ponto
    s = re.sub(r"[^\d.]", "", s)
    try:
        return float(s) if s else None
    except ValueError:
        return None

def parse_qty(s: str) -> Optional[int]:
    """Converte string de quantidade para int. Ex: '1.500' → 1500"""
    s = s.strip().replace(".", "").replace(",", "").replace(" ", "")
    s = re.sub(r"[^\d]", "", s)
    try:
        return int(s) if s else None
    except ValueError:
        return None


class TTParser:
    """
    Extrai trades do texto OCR do Times & Trades.

    Formato típico do Profit (linha por negócio):
      HH:MM:SS   PRECO   QTD   CORRETORA   C/V
    Ex:
      10:05:23   19,05   1.000   JPMORGAN   C
      10:05:24   19,04     500   BRADESCO   V
    """

    # Regex para capturar uma linha do T&T
    LINE_RE = re.compile(
        r"(\d{1,2}:\d{2}:\d{2})"    # horário
        r"\s+"
        r"([\d,.]+)"                  # preço
        r"\s+"
        r"([\d.,]+)"                  # quantidade
        r"\s+"
        r"([A-Za-z\s]+?)"             # corretora
        r"\s+"
        r"([CVcv])"                   # lado C ou V
    )

    def parse(self, ocr_text: str) -> list[TTTrade]:
        trades = []
        now = time.time()
        for line in ocr_text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = self.LINE_RE.search(line)
            if not m:
                continue
            hora_str, price_s, qty_s, broker_s, side_s = m.groups()
            price  = parse_price(price_s)
            qty    = parse_qty(qty_s)
            broker = normalize_broker(broker_s)
            side   = side_s.upper()
            if price and qty:
                trades.append(TTTrade(
                    timestamp=now,
                    price=price,
                    qty=qty,
                    broker=broker,
                    side=side,
                ))
        return trades


class BookParser:
    """
    Extrai o Book de Ofertas do texto OCR.

    Formato típico (colunas: CORRETORA QTD PRECO):
      JPMORGAN   1.000   19,05   ← lado venda (ask)
      BRADESCO     500   19,04   ← lado compra (bid)
    """

    LINE_RE = re.compile(
        r"([A-Za-z\s]+?)"    # corretora
        r"\s+"
        r"([\d.,]+)"          # quantidade
        r"\s+"
        r"([\d,.]+)"          # preço
    )

    def parse(self, ocr_text: str, side: str) -> list[BookRow]:
        rows = []
        for line in ocr_text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = self.LINE_RE.search(line)
            if not m:
                continue
            broker_s, qty_s, price_s = m.groups()
            price  = parse_price(price_s)
            qty    = parse_qty(qty_s)
            broker = normalize_broker(broker_s)
            if price and qty:
                rows.append(BookRow(price=price, qty=qty, broker=broker, side=side))
        return rows


# ──────────────────────────────────────────────────────────────
# LEITOR DE TELA
# ──────────────────────────────────────────────────────────────

class ScreenReader:
    """
    Captura e processa as janelas do Profit em tempo real.
    Chama callbacks quando novos dados são extraídos.
    """

    def __init__(self, config: Optional[ScreenConfig] = None):
        self.cfg         = config or ScreenConfig()
        self._tt_parser  = TTParser()
        self._book_parser = BookParser()
        self._running    = False
        self._thread: Optional[threading.Thread] = None
        self._sct = None  # mss screenshotter

        # Callbacks externos
        self.on_tick:  Optional[Callable] = None   # fn(TTTrade)
        self.on_book:  Optional[Callable] = None   # fn(list[BookRow])

        # Verificar dependências
        self._ocr_ready = MSS_OK and PIL_OK and TESS_OK
        if not self._ocr_ready:
            logger.warning("OCR não disponível — instale: mss pillow pytesseract")

    # ──────────────────────────────────────────────────────────
    # CAPTURA E PRÉ-PROCESSAMENTO
    # ──────────────────────────────────────────────────────────

    def _capture(self, region: Region) -> Optional[Image.Image]:
        """Captura uma região da tela e retorna como PIL Image."""
        if not self._ocr_ready:
            return None
        try:
            with mss.mss() as sct:
                shot = sct.grab(region.to_mss())
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                return img
        except Exception as e:
            logger.error(f"Erro na captura: {e}")
            return None

    def _preprocess(self, img: Image.Image) -> Image.Image:
        """
        Pré-processa a imagem para melhorar o OCR:
        1. Zoom (escala)
        2. Conversão para escala de cinza
        3. Aumento de contraste
        4. Binarização (threshold)
        """
        # Zoom
        w = int(img.width  * self.cfg.zoom_scale)
        h = int(img.height * self.cfg.zoom_scale)
        img = img.resize((w, h), Image.LANCZOS)

        if CV2_OK:
            # Processamento com OpenCV (melhor qualidade)
            arr = np.array(img)
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
            # Binarização adaptativa — funciona bem com fundos escuros do Profit
            binary = cv2.adaptiveThreshold(
                gray, 255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2
            )
            # Inverter se fundo escuro (Profit tem tema escuro)
            if gray.mean() < 128:
                binary = cv2.bitwise_not(binary)
            img = Image.fromarray(binary)
        else:
            # Fallback com PIL
            img = img.convert("L")
            img = ImageEnhance.Contrast(img).enhance(3.0)

        return img

    def _run_ocr(self, img: Image.Image) -> str:
        """Extrai texto da imagem com Tesseract."""
        if not TESS_OK:
            return ""
        try:
            config = "--psm 6 -l por+eng"  # Bloco de texto, pt-BR + inglês
            return pytesseract.image_to_string(img, config=config)
        except Exception as e:
            logger.error(f"Erro no OCR: {e}")
            return ""

    # ──────────────────────────────────────────────────────────
    # LOOP PRINCIPAL
    # ──────────────────────────────────────────────────────────

    def _loop(self):
        interval = 1.0 / self.cfg.capture_fps
        logger.info(f"ScreenReader iniciado @ {self.cfg.capture_fps} FPS")

        last_tt_trades  = []
        last_book_rows  = []

        while self._running:
            t0 = time.time()

            # ── Capturar Times & Trades
            img_tt = self._capture(self.cfg.tt_region)
            if img_tt:
                img_tt = self._preprocess(img_tt)
                text_tt = self._run_ocr(img_tt)
                new_trades = self._tt_parser.parse(text_tt)
                if new_trades and self.on_tick:
                    # Enviar apenas negócios novos (evitar duplicatas)
                    for trade in new_trades:
                        if trade not in last_tt_trades:
                            self.on_tick(trade)
                last_tt_trades = new_trades

            # ── Capturar Book de Ofertas
            img_book = self._capture(self.cfg.book_region)
            if img_book:
                # Dividir verticalmente: metade superior = venda, inferior = compra
                # (depende do layout do Profit; ajustar se necessário)
                h = img_book.height
                img_ask = img_book.crop((0, 0,    img_book.width, h // 2))
                img_bid = img_book.crop((0, h // 2, img_book.width, h))

                img_ask = self._preprocess(img_ask)
                img_bid = self._preprocess(img_bid)

                text_ask = self._run_ocr(img_ask)
                text_bid = self._run_ocr(img_bid)

                book_ask = self._book_parser.parse(text_ask, "V")
                book_bid = self._book_parser.parse(text_bid, "C")
                all_book = book_ask + book_bid

                if all_book and self.on_book:
                    self.on_book(all_book)
                last_book_rows = all_book

            # ── Dormir para manter o FPS
            elapsed = time.time() - t0
            sleep_t = max(0, interval - elapsed)
            time.sleep(sleep_t)

        logger.info("ScreenReader encerrado")

    def start(self):
        if not self._ocr_ready:
            logger.error("Não é possível iniciar: dependências OCR ausentes.")
            return False
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def capture_screenshot(self, region: Region, filename: str):
        """Salva um screenshot de uma região (para calibração)."""
        img = self._capture(region)
        if img:
            img.save(filename)
            logger.info(f"Screenshot salvo: {filename}")
            return True
        return False

    def calibrate(self):
        """
        Modo de calibração: salva screenshots das regiões configuradas
        para verificar se as coordenadas estão corretas.
        """
        logger.info("=== MODO CALIBRAÇÃO ===")
        self.capture_screenshot(self.cfg.tt_region,   "calibracao_tt.png")
        self.capture_screenshot(self.cfg.book_region, "calibracao_book.png")
        logger.info("Imagens salvas. Verifique 'calibracao_tt.png' e 'calibracao_book.png'")
        logger.info("Se as imagens não mostrarem o Book/TT, ajuste as coordenadas em ScreenConfig")
