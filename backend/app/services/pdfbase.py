"""Shared ReportLab setup: a Unicode font with the ₹ glyph, styles and number-to-words for INR."""

from functools import lru_cache
from pathlib import Path

import matplotlib
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

BRAND = colors.HexColor("#047857")
MUTED = colors.HexColor("#64748b")
LINE = colors.HexColor("#cbd5e1")
HEAD_BG = colors.HexColor("#ecfdf5")


@lru_cache
def fonts() -> tuple[str, str]:
    """Register DejaVu Sans (bundled with matplotlib, so identical on every OS) and return (regular, bold)."""
    base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    try:
        pdfmetrics.registerFont(TTFont("DejaVu", str(base / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(base / "DejaVuSans-Bold.ttf")))
        return "DejaVu", "DejaVu-Bold"
    except Exception:  # pragma: no cover - only if matplotlib fonts are missing
        return "Helvetica", "Helvetica-Bold"


def rupee() -> str:
    return "₹" if fonts()[0] == "DejaVu" else "Rs."


def inr(v: float) -> str:
    """Indian digit grouping: 1234567.5 → ₹12,34,567.50"""
    neg = v < 0
    whole, frac = f"{abs(v):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return f"{'-' if neg else ''}{rupee()}{whole}.{frac}"


def styles() -> dict[str, ParagraphStyle]:
    regular, bold = fonts()
    ss = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "t", parent=ss["Title"], fontName=bold, fontSize=16, textColor=BRAND, spaceAfter=4
        ),
        "h2": ParagraphStyle(
            "h2", parent=ss["Heading2"], fontName=bold, fontSize=11, spaceBefore=6, spaceAfter=3
        ),
        "body": ParagraphStyle("b", parent=ss["BodyText"], fontName=regular, fontSize=8.5, leading=11),
        "small": ParagraphStyle(
            "s", parent=ss["BodyText"], fontName=regular, fontSize=7.5, leading=9.5, textColor=MUTED
        ),
        "bold": ParagraphStyle("bb", parent=ss["BodyText"], fontName=bold, fontSize=8.5, leading=11),
        "right": ParagraphStyle(
            "r", parent=ss["BodyText"], fontName=regular, fontSize=8.5, leading=11, alignment=2
        ),
    }


_ONES = [
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _below_hundred(n: int) -> str:
    return _ONES[n] if n < 20 else (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))


def _below_thousand(n: int) -> str:
    h, r = divmod(n, 100)
    parts = []
    if h:
        parts.append(f"{_ONES[h]} Hundred")
    if r:
        parts.append(_below_hundred(r))
    return " ".join(parts)


def amount_in_words(v: float) -> str:
    """Indian system (crore/lakh/thousand): 125430.5 → 'Rupees One Lakh Twenty Five Thousand Four Hundred Thirty and Fifty Paise Only'."""
    rupees = int(round(v * 100)) // 100
    paise = int(round(v * 100)) % 100
    if rupees == 0 and paise == 0:
        return "Rupees Zero Only"
    parts = []
    crore, rest = divmod(rupees, 10_000_000)
    lakh, rest = divmod(rest, 100_000)
    thousand, rest = divmod(rest, 1000)
    if crore:
        parts.append(f"{_below_thousand(crore) if crore < 1000 else str(crore)} Crore")
    if lakh:
        parts.append(f"{_below_hundred(lakh)} Lakh")
    if thousand:
        parts.append(f"{_below_hundred(thousand)} Thousand")
    if rest:
        parts.append(_below_thousand(rest))
    words = "Rupees " + " ".join(parts) if parts else "Rupees Zero"
    if paise:
        words += f" and {_below_hundred(paise)} Paise"
    return words + " Only"
