"""Look of the customer report: fonts, colours, sizes.

Colours follow a validated data-viz palette (print = light surface only):
one blue carries every single-series chart, magnitude uses that blue's
sequential ramp, text never wears a series colour, and good/bad deltas use
the reserved status steps next to an arrow, never colour alone.
"""

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONTS = Path(__file__).resolve().parents[2] / "assets" / "fonts"

FONT = "NotoSans"
FONT_BOLD = "NotoSans-Bold"

INK = HexColor("#0b0b0b")
INK_2 = HexColor("#52514e")
MUTED = HexColor("#8a8983")
GRID = HexColor("#e7e6e1")
RULE = HexColor("#d9d8d2")
PANEL = HexColor("#f6f5f2")
WHITE = HexColor("#ffffff")

ACCENT = HexColor("#2a78d6")
ACCENT_DARK = HexColor("#184f95")
REFERENCE = HexColor("#8a8983")

GOOD = HexColor("#0ca30c")
CRITICAL = HexColor("#d03b3b")

#: Sequential blue, near-zero to most. Zero itself is EMPTY_CELL.
SEQUENTIAL = [
    HexColor(h)
    for h in ("#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b")
]
EMPTY_CELL = HexColor("#f1f0ec")

_registered = False


def register_fonts() -> None:
    """Embed Noto Sans once per process (OFL; see assets/fonts)."""
    global _registered
    if _registered:
        return
    pdfmetrics.registerFont(TTFont(FONT, str(FONTS / "NotoSans-Regular.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONTS / "NotoSans-Bold.ttf")))
    pdfmetrics.registerFontFamily(FONT, normal=FONT, bold=FONT_BOLD, italic=FONT, boldItalic=FONT_BOLD)
    _registered = True
