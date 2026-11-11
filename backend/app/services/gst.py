"""GST computation for purchase documents: intra-state → CGST + SGST (half each), inter-state → IGST."""

from dataclasses import dataclass


@dataclass
class TaxLine:
    taxable: float
    rate: float
    cgst: float
    sgst: float
    igst: float

    @property
    def tax(self) -> float:
        return round(self.cgst + self.sgst + self.igst, 2)

    @property
    def total(self) -> float:
        return round(self.taxable + self.tax, 2)


def is_interstate(business_state: str | None, supplier_state: str | None) -> bool:
    norm = lambda s: (s or "").strip().lower()  # noqa: E731
    return bool(norm(supplier_state)) and norm(business_state) != norm(supplier_state)


def line_tax(qty: float, unit_price: float, rate: float, interstate: bool) -> TaxLine:
    taxable = round(qty * unit_price, 2)
    tax = round(taxable * rate / 100, 2)
    if interstate:
        return TaxLine(taxable, rate, 0.0, 0.0, tax)
    half = round(tax / 2, 2)
    return TaxLine(taxable, rate, half, round(tax - half, 2), 0.0)


@dataclass
class Totals:
    subtotal: float
    cgst: float
    sgst: float
    igst: float

    @property
    def tax(self) -> float:
        return round(self.cgst + self.sgst + self.igst, 2)

    @property
    def total(self) -> float:
        return round(self.subtotal + self.tax, 2)


def totals(lines: list[tuple[float, float, float]], interstate: bool) -> Totals:
    """lines: (qty, unit_price, gst_rate)."""
    tl = [line_tax(q, p, r, interstate) for q, p, r in lines]
    return Totals(
        subtotal=round(sum(x.taxable for x in tl), 2),
        cgst=round(sum(x.cgst for x in tl), 2),
        sgst=round(sum(x.sgst for x in tl), 2),
        igst=round(sum(x.igst for x in tl), 2),
    )


def rate_summary(lines: list[tuple[float, float, float]], interstate: bool) -> list[dict[str, float]]:
    """Per-rate breakdown printed on the PO (taxable value and tax per GST slab)."""
    by_rate: dict[float, list[TaxLine]] = {}
    for q, p, r in lines:
        by_rate.setdefault(r, []).append(line_tax(q, p, r, interstate))
    return [
        {"rate": r, "taxable": round(sum(x.taxable for x in xs), 2), "cgst": round(sum(x.cgst for x in xs), 2),
         "sgst": round(sum(x.sgst for x in xs), 2), "igst": round(sum(x.igst for x in xs), 2)}
        for r, xs in sorted(by_rate.items())
    ]
