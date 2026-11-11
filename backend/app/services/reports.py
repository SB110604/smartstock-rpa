"""Reports (spec 9.15): stock valuation, sales, purchases, supplier performance, expiry/wastage, GST summary.

Each report builds one table model rendered as JSON (screen), PDF (ReportLab) or Excel (openpyxl)."""

import io
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings as env
from app.core.errors import NotFound, ValidationFailed
from app.core.timeutil import start_of_day, today
from app.services import settings as settings_svc
from app.services import supplier_scoring
from app.services.pdfbase import BRAND, HEAD_BG, LINE, fonts, inr, styles


@dataclass
class Col:
    key: str
    label: str
    kind: str = "text"  # text | int | qty | money | pct | date


@dataclass
class Report:
    name: str
    title: str
    columns: list[Col]
    rows: list[dict[str, Any]]
    totals: dict[str, Any] = field(default_factory=dict)
    summary: list[tuple[str, str]] = field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None


def _range(date_from: date | None, date_to: date | None, default_days: int = 30) -> tuple[date, date]:
    d_to = date_to or today()
    d_from = date_from or d_to - timedelta(days=default_days - 1)
    if d_from > d_to:
        raise ValidationFailed("'From' date must be before 'To' date")
    return d_from, d_to


def _q(db: Session, sql: str, **params: Any) -> list[Any]:
    return list(db.execute(text(sql), {"tz": env.TZ, **params}).mappings())


def stock_valuation(db: Session, date_from: date | None, date_to: date | None, location_id: int | None) -> Report:
    rows = _q(db, """
        SELECT p.sku, p.name, c.name AS category, p.abc_class AS abc, SUM(b.qty_on_hand) AS qty,
               SUM(b.qty_on_hand * b.cost_price) AS value, p.selling_price
        FROM batches b JOIN products p ON p.id = b.product_id LEFT JOIN categories c ON c.id = p.category_id
        WHERE b.qty_on_hand > 0 AND b.is_blocked = false AND (b.expiry_date IS NULL OR b.expiry_date > :today)
          AND (CAST(:loc AS INTEGER) IS NULL OR b.location_id = :loc)
        GROUP BY p.sku, p.name, c.name, p.abc_class, p.selling_price ORDER BY value DESC""", today=today(), loc=location_id)
    out = [{**r, "qty": float(r["qty"]), "value": float(r["value"]), "avg_cost": float(r["value"]) / float(r["qty"]) if r["qty"] else 0,
            "retail_value": float(r["qty"]) * float(r["selling_price"])} for r in rows]
    total = sum(r["value"] for r in out)
    return Report("stock_valuation", f"Stock valuation as of {today():%d-%m-%Y}",
                  [Col("sku", "SKU"), Col("name", "Product"), Col("category", "Category"), Col("abc", "ABC"),
                   Col("qty", "Qty", "qty"), Col("avg_cost", "Avg cost", "money"), Col("value", "Value (cost)", "money"),
                   Col("retail_value", "Value (MRP)", "money")],
                  out, {"value": total, "retail_value": sum(r["retail_value"] for r in out)},
                  [("Products in stock", str(len(out))), ("Stock value at cost", inr(total))])


def sales(db: Session, date_from: date | None, date_to: date | None, location_id: int | None) -> Report:
    d1, d2 = _range(date_from, date_to)
    rows = _q(db, """
        SELECT p.sku, p.name, c.name AS category, SUM(l.qty) qty, SUM(l.line_total) revenue,
               SUM(l.line_total * l.gst_rate / (100 + l.gst_rate)) tax, SUM(l.qty * p.cost_price) cost
        FROM sale_lines l JOIN sales s ON s.id = l.sale_id JOIN products p ON p.id = l.product_id
        LEFT JOIN categories c ON c.id = p.category_id
        WHERE s.sold_at >= :a AND s.sold_at < :b AND (CAST(:loc AS INTEGER) IS NULL OR s.location_id = :loc)
        GROUP BY 1, 2, 3 ORDER BY revenue DESC""", a=start_of_day(d1), b=start_of_day(d2 + timedelta(days=1)), loc=location_id)
    out = [{**r, "qty": float(r["qty"]), "revenue": float(r["revenue"]), "tax": float(r["tax"]),
            "margin": float(r["revenue"]) - float(r["tax"]) - float(r["cost"])} for r in rows]
    bills = _q(db, "SELECT COUNT(*) n FROM sales WHERE sold_at >= :a AND sold_at < :b", a=start_of_day(d1),
               b=start_of_day(d2 + timedelta(days=1)))[0]["n"]
    rev = sum(r["revenue"] for r in out)
    return Report("sales", f"Sales {d1:%d-%m-%Y} to {d2:%d-%m-%Y}",
                  [Col("sku", "SKU"), Col("name", "Product"), Col("category", "Category"), Col("qty", "Qty", "qty"),
                   Col("revenue", "Revenue (incl. GST)", "money"), Col("tax", "GST", "money"), Col("margin", "Gross margin", "money")],
                  out, {"revenue": rev, "tax": sum(r["tax"] for r in out), "margin": sum(r["margin"] for r in out)},
                  [("Bills", str(bills)), ("Revenue", inr(rev)), ("Average bill", inr(rev / bills) if bills else "—")], d1, d2)


def purchases(db: Session, date_from: date | None, date_to: date | None, location_id: int | None) -> Report:
    d1, d2 = _range(date_from, date_to)
    rows = _q(db, """
        SELECT po.po_no, po.order_date, s.name supplier, po.status, po.subtotal, po.cgst + po.sgst + po.igst tax, po.total,
               po.expected_date, (po.delivered_at AT TIME ZONE :tz)::date delivered
        FROM purchase_orders po JOIN suppliers s ON s.id = po.supplier_id
        WHERE po.order_date BETWEEN :a AND :b AND po.status NOT IN ('CANCELLED', 'REJECTED_BY_SUPPLIER')
          AND (CAST(:loc AS INTEGER) IS NULL OR po.location_id = :loc)
        ORDER BY po.order_date DESC, po.po_no DESC""", a=d1, b=d2, loc=location_id)
    out = [{**r, "subtotal": float(r["subtotal"]), "tax": float(r["tax"]), "total": float(r["total"])} for r in rows]
    total = sum(r["total"] for r in out)
    return Report("purchases", f"Purchases {d1:%d-%m-%Y} to {d2:%d-%m-%Y}",
                  [Col("po_no", "PO"), Col("order_date", "Date", "date"), Col("supplier", "Supplier"), Col("status", "Status"),
                   Col("expected_date", "Due", "date"), Col("delivered", "Delivered", "date"), Col("subtotal", "Taxable", "money"),
                   Col("tax", "GST", "money"), Col("total", "Total", "money")],
                  out, {"subtotal": sum(r["subtotal"] for r in out), "tax": sum(r["tax"] for r in out), "total": total},
                  [("Purchase orders", str(len(out))), ("Total purchases", inr(total))], d1, d2)


def supplier_performance(db: Session, date_from: date | None, date_to: date | None, location_id: int | None) -> Report:
    d1, d2 = _range(date_from, date_to, 90)
    rows = _q(db, """
        SELECT s.id, s.name, s.state, COUNT(po.id) pos, COALESCE(SUM(po.total), 0) value,
               AVG(CASE WHEN po.delivered_at IS NOT NULL THEN ((po.delivered_at AT TIME ZONE :tz)::date - po.order_date) END) lead,
               100.0 * SUM(CASE WHEN po.delivered_at IS NOT NULL AND (po.delivered_at AT TIME ZONE :tz)::date <= po.expected_date
                                THEN 1 ELSE 0 END) / NULLIF(SUM(CASE WHEN po.delivered_at IS NOT NULL THEN 1 ELSE 0 END), 0) on_time
        FROM suppliers s LEFT JOIN purchase_orders po ON po.supplier_id = s.id AND po.order_date BETWEEN :a AND :b
        GROUP BY s.id, s.name, s.state ORDER BY value DESC""", a=d1, b=d2)
    dmg = {r["supplier_id"]: r for r in _q(db, """
        SELECT po.supplier_id, SUM(l.damaged_qty) d, SUM(l.received_qty + l.damaged_qty) t FROM po_lines l
        JOIN purchase_orders po ON po.id = l.po_id WHERE po.order_date BETWEEN :a AND :b GROUP BY 1""", a=d1, b=d2)}
    scores = {s.supplier_id: s for s in supplier_scoring.compute_scores(db, persist=False)}
    out = []
    for r in rows:
        d = dmg.get(r["id"])
        sc = scores.get(r["id"])
        out.append({"name": r["name"], "state": r["state"], "pos": r["pos"], "value": float(r["value"]),
                    "on_time": float(r["on_time"]) if r["on_time"] is not None else None,
                    "lead": float(r["lead"]) if r["lead"] is not None else None,
                    "reject": 100 * float(d["d"]) / float(d["t"]) if d and d["t"] else 0.0,
                    "score": sc.total_score if sc else None})
    return Report("supplier_performance", f"Supplier performance {d1:%d-%m-%Y} to {d2:%d-%m-%Y}",
                  [Col("name", "Supplier"), Col("state", "State"), Col("pos", "POs", "int"), Col("value", "Value", "money"),
                   Col("on_time", "On-time %", "pct"), Col("lead", "Avg lead (days)", "qty"), Col("reject", "Damaged %", "pct"),
                   Col("score", "Score", "qty")], out, {"value": sum(r["value"] for r in out)}, [], d1, d2)


def expiry_wastage(db: Session, date_from: date | None, date_to: date | None, location_id: int | None) -> Report:
    d1, d2 = _range(date_from, date_to)
    rows = _q(db, """
        SELECT (m.created_at AT TIME ZONE :tz)::date d, p.name, b.batch_no, m.type, -m.qty qty, -m.qty * m.unit_cost value, m.note
        FROM stock_movements m JOIN products p ON p.id = m.product_id LEFT JOIN batches b ON b.id = m.batch_id
        WHERE m.type IN ('write_off', 'return_out') AND m.created_at >= :a AND m.created_at < :b
          AND (CAST(:loc AS INTEGER) IS NULL OR m.location_id = :loc)
        ORDER BY m.created_at DESC""", a=start_of_day(d1), b=start_of_day(d2 + timedelta(days=1)), loc=location_id)
    out = [{**r, "qty": float(r["qty"]), "value": float(r["value"]), "type": "Write-off" if r["type"] == "write_off" else "Returned"}
           for r in rows]
    expired = _q(db, """SELECT COALESCE(SUM(qty_on_hand * cost_price), 0) v FROM batches
                        WHERE qty_on_hand > 0 AND expiry_date <= :today""", today=today())[0]["v"]
    wasted = sum(r["value"] for r in out if r["type"] == "Write-off")
    return Report("expiry_wastage", f"Expiry & wastage {d1:%d-%m-%Y} to {d2:%d-%m-%Y}",
                  [Col("d", "Date", "date"), Col("name", "Product"), Col("batch_no", "Batch"), Col("type", "Action"),
                   Col("qty", "Qty", "qty"), Col("value", "Value", "money"), Col("note", "Reason")],
                  out, {"value": sum(r["value"] for r in out)},
                  [("Written off", inr(wasted)), ("Returned to suppliers", inr(sum(r["value"] for r in out) - wasted)),
                   ("Expired stock still on shelves", inr(float(expired)))], d1, d2)


def gst_summary(db: Session, date_from: date | None, date_to: date | None, location_id: int | None) -> Report:
    d1, d2 = _range(date_from, date_to)
    out_rows = {float(r["rate"]): r for r in _q(db, """
        SELECT l.gst_rate rate, SUM(l.line_total - l.line_total * l.gst_rate / (100 + l.gst_rate)) taxable,
               SUM(l.line_total * l.gst_rate / (100 + l.gst_rate)) tax
        FROM sale_lines l JOIN sales s ON s.id = l.sale_id WHERE s.sold_at >= :a AND s.sold_at < :b GROUP BY 1""",
                                                    a=start_of_day(d1), b=start_of_day(d2 + timedelta(days=1)))}
    in_rows = {float(r["rate"]): r for r in _q(db, """
        SELECT l.gst_rate rate, SUM(l.qty * l.unit_price) taxable,
               SUM(CASE WHEN po.is_interstate THEN 0 ELSE l.qty * l.unit_price * l.gst_rate / 100 END) cgst_sgst,
               SUM(CASE WHEN po.is_interstate THEN l.qty * l.unit_price * l.gst_rate / 100 ELSE 0 END) igst
        FROM supplier_invoice_lines l JOIN supplier_invoices i ON i.id = l.invoice_id JOIN purchase_orders po ON po.id = i.po_id
        WHERE i.invoice_date BETWEEN :a AND :b GROUP BY 1""", a=d1, b=d2)}
    out = []
    for rate in sorted(set(out_rows) | set(in_rows)):
        o, i = out_rows.get(rate), in_rows.get(rate)
        out_tax = float(o["tax"]) if o else 0.0
        in_tax = (float(i["cgst_sgst"]) + float(i["igst"])) if i else 0.0
        out.append({"rate": f"{rate:g}%", "out_taxable": float(o["taxable"]) if o else 0.0, "out_tax": out_tax,
                    "in_taxable": float(i["taxable"]) if i else 0.0, "in_cgst_sgst": float(i["cgst_sgst"]) if i else 0.0,
                    "in_igst": float(i["igst"]) if i else 0.0, "net": out_tax - in_tax})
    net = sum(r["net"] for r in out)
    keys = ("out_taxable", "out_tax", "in_taxable", "in_cgst_sgst", "in_igst", "net")
    return Report("gst_summary", f"GST summary {d1:%d-%m-%Y} to {d2:%d-%m-%Y}",
                  [Col("rate", "GST rate"), Col("out_taxable", "Sales taxable", "money"), Col("out_tax", "Output GST", "money"),
                   Col("in_taxable", "Purchases taxable", "money"), Col("in_cgst_sgst", "Input CGST+SGST", "money"),
                   Col("in_igst", "Input IGST", "money"), Col("net", "Net payable", "money")],
                  out, {k: sum(r[k] for r in out) for k in keys},
                  [("Output GST", inr(sum(r["out_tax"] for r in out))),
                   ("Input tax credit", inr(sum(r["in_cgst_sgst"] + r["in_igst"] for r in out))),
                   ("Net GST payable" if net >= 0 else "Net GST credit", inr(abs(net)))], d1, d2)


REPORTS = {"stock_valuation": ("Stock valuation", stock_valuation), "sales": ("Sales", sales),
           "purchases": ("Purchases", purchases), "supplier_performance": ("Supplier performance", supplier_performance),
           "expiry_wastage": ("Expiry & wastage", expiry_wastage), "gst_summary": ("GST summary", gst_summary)}


def build(db: Session, name: str, date_from: date | None = None, date_to: date | None = None,
          location_id: int | None = None) -> Report:
    if name not in REPORTS:
        raise NotFound(f"Unknown report '{name}'")
    return REPORTS[name][1](db, date_from, date_to, location_id)


def _cell(v: Any, kind: str) -> str:
    if v is None:
        return "—"
    if kind == "money":
        return inr(float(v))
    if kind == "pct":
        return f"{float(v):.1f}%"
    if kind == "qty":
        return f"{float(v):,.2f}".rstrip("0").rstrip(".")
    if kind == "date":
        return v.strftime("%d-%m-%Y") if hasattr(v, "strftime") else str(v)
    return str(v)


def to_json(r: Report) -> dict[str, Any]:
    return {"name": r.name, "title": r.title, "columns": [c.__dict__ for c in r.columns], "rows": r.rows, "totals": r.totals,
            "summary": [{"label": a, "value": b} for a, b in r.summary],
            "date_from": r.date_from, "date_to": r.date_to}


def to_pdf(db: Session, r: Report) -> bytes:
    regular, bold = fonts()
    st = styles()
    business = settings_svc.get(db, "business")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=r.title)
    story: list[Any] = [Paragraph(business.get("name", ""), st["title"]), Paragraph(r.title, st["h2"])]
    if r.summary:
        story.append(Paragraph(" · ".join(f"{a}: <b>{b}</b>" for a, b in r.summary), st["body"]))
    story.append(Spacer(1, 6))
    head = [c.label for c in r.columns]
    data: list[list[Any]] = [head] + [[Paragraph(_cell(row.get(c.key), c.kind), st["body"]) if c.kind == "text"
                                       else _cell(row.get(c.key), c.kind) for c in r.columns] for row in r.rows]
    if r.totals:
        data.append(["Total" if i == 0 else (_cell(r.totals[c.key], c.kind) if c.key in r.totals else "")
                     for i, c in enumerate(r.columns)])
    width = (landscape(A4)[0] - 24 * mm) / len(r.columns)
    t = Table(data, colWidths=[width] * len(r.columns), repeatRows=1)
    style = [("FONT", (0, 0), (-1, -1), regular, 7.5), ("FONT", (0, 0), (-1, 0), bold, 7.5),
             ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG), ("TEXTCOLOR", (0, 0), (-1, 0), BRAND),
             ("GRID", (0, 0), (-1, -1), 0.3, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
    for i, c in enumerate(r.columns):
        if c.kind in ("money", "qty", "int", "pct"):
            style.append(("ALIGN", (i, 0), (i, -1), "RIGHT"))
    if r.totals:
        style += [("FONT", (0, -1), (-1, -1), bold, 7.5), ("BACKGROUND", (0, -1), (-1, -1), HEAD_BG)]
    t.setStyle(TableStyle(style))
    story.append(t if r.rows else Paragraph("No data for this period.", st["body"]))
    doc.build(story)
    return buf.getvalue()


def to_xlsx(r: Report) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = r.name[:30]
    ws.append([r.title])
    ws["A1"].font = Font(bold=True, size=13)
    for a, b in r.summary:
        ws.append([a, b])
    ws.append([])
    ws.append([c.label for c in r.columns])
    hr = ws.max_row
    for i in range(1, len(r.columns) + 1):
        cell = ws.cell(row=hr, column=i)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="ECFDF5")
        cell.alignment = Alignment(horizontal="center")
    fmt = {"money": '"₹"#,##,##0.00', "pct": '0.0"%"', "qty": "#,##0.###", "int": "0", "date": "DD-MM-YYYY"}
    for row in r.rows:
        ws.append([row.get(c.key) for c in r.columns])
        for i, c in enumerate(r.columns, start=1):
            if c.kind in fmt:
                ws.cell(row=ws.max_row, column=i).number_format = fmt[c.kind]
    if r.totals:
        ws.append(["Total" if i == 0 else r.totals.get(c.key) for i, c in enumerate(r.columns)])
        for i, c in enumerate(r.columns, start=1):
            cell = ws.cell(row=ws.max_row, column=i)
            cell.font = Font(bold=True)
            if c.kind in fmt:
                cell.number_format = fmt[c.kind]
    for i, c in enumerate(r.columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(12, min(40, len(c.label) + 6))
    ws.freeze_panes = ws.cell(row=hr + 1, column=1)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def period_for(frequency: str) -> tuple[date, date]:
    """Previous complete period for scheduled sends: yesterday / last 7 days / previous calendar month."""
    t = today()
    if frequency == "daily":
        return t - timedelta(days=1), t - timedelta(days=1)
    if frequency == "weekly":
        return t - timedelta(days=7), t - timedelta(days=1)
    first = t.replace(day=1)
    last_prev = first - timedelta(days=1)
    return last_prev.replace(day=1), last_prev
