"""Generates tests/fixtures/sample_bill.png — a clean, printed-style supplier tax invoice used by the OCR tests.

Run: python tests/fixtures/make_sample_bill.py"""

from pathlib import Path

import matplotlib
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
FONT = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSansMono.ttf"
BOLD = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSansMono-Bold.ttf"

LINES = [
    ("Toor Dal 1kg", "0713", 20, "pack", 128.00),
    ("Sugar 1kg", "1701", 50, "pack", 41.00),
    ("Tata Salt 1kg", "2501", 25, "pack", 22.00),
    ("Fortune Sunflower Oil 1L", "1512", 12, "pack", 128.00),
]


def make(path: Path = HERE / "sample_bill.png") -> Path:
    img = Image.new("RGB", (1700, 1300), "white")
    d = ImageDraw.Draw(img)
    big, reg, bold = ImageFont.truetype(str(BOLD), 44), ImageFont.truetype(str(FONT), 30), ImageFont.truetype(str(BOLD), 30)
    y = 50
    d.text((60, y), "AGARWAL WHOLESALE TRADERS", font=big, fill="black")
    y += 70
    d.text((60, y), "Market Yard, Gultekdi, Pune 411037", font=reg, fill="black")
    y += 45
    d.text((60, y), "GSTIN: 27AABFA4321L1Z2", font=reg, fill="black")
    y += 80
    d.text((60, y), "TAX INVOICE", font=bold, fill="black")
    y += 55
    d.text((60, y), "Invoice No: AWT/26/0457", font=reg, fill="black")
    d.text((1000, y), "Date: 02-11-2026", font=reg, fill="black")
    y += 45
    d.text((60, y), "Bill To: Shree Ganesh SuperMart, Kothrud, Pune", font=reg, fill="black")
    y += 80
    d.text((60, y), f"{'Item':<28}{'HSN':<7}{'Qty':>5} {'Unit':<5}{'Rate':>9}{'Amount':>12}", font=bold, fill="black")
    y += 15
    d.line((60, y + 35, 1640, y + 35), fill="black", width=2)
    y += 55
    subtotal = 0.0
    for name, hsn, qty, unit, rate in LINES:
        amount = qty * rate
        subtotal += amount
        d.text((60, y), f"{name:<28}{hsn:<7}{qty:>5} {unit:<5}{rate:>9.2f}{amount:>12.2f}", font=reg, fill="black")
        y += 50
    d.line((60, y, 1640, y), fill="black", width=2)
    y += 30
    tax = round(subtotal * 0.05, 2)
    for label, value in (("Sub Total", subtotal), ("CGST 2.5%", tax / 2), ("SGST 2.5%", tax / 2), ("Grand Total", subtotal + tax)):
        d.text((1000, y), f"{label:<14}{value:>12.2f}", font=bold if label == "Grand Total" else reg, fill="black")
        y += 45
    img.save(path)
    return path


if __name__ == "__main__":
    print(make())
