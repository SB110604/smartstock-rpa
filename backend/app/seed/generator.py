"""Deterministic demo-data generator (spec section 11). Fixed RNG seed → identical data on every run.

Pipeline: masters → 15 months of daily demand → sales → 12-month (s, Q) purchasing simulation producing
POs/GRNs/batches/invoices/3-way matches consistent with the sales → purchase-request history → current
stock across every expiry bucket → warehouse transfers, a stock count and injected anomalies."""

import math
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.core.timeutil import TZ, today
from app.models import (
    Approval,
    ApprovalRule,
    AuditLog,
    Batch,
    Category,
    Feedback,
    Festival,
    GoodsReceipt,
    GrnLine,
    Location,
    OrderStatusHistory,
    PoLine,
    Product,
    PurchaseOrder,
    PurchaseRequest,
    Sale,
    SaleLine,
    Setting,
    StatusHistory,
    StockCount,
    StockCountLine,
    StockMovement,
    StockTransfer,
    StockTransferLine,
    Supplier,
    SupplierInvoice,
    SupplierInvoiceLine,
    SupplierProduct,
    SupplierReturn,
    SupplierReturnLine,
    ThreeWayMatch,
    User,
)
from app.seed import catalog as C  # noqa: N812

SEED = 42
SALES_DAYS = 456  # ~15 months
PURCHASE_DAYS = 365
DOW = np.array([0.88, 0.90, 0.93, 0.97, 1.05, 1.22, 1.30])  # Mon..Sun
SKU_PREFIX = {"Staples": "STP", "Dairy": "DRY", "Beverages": "BEV", "Snacks": "SNK", "Personal Care": "PER",
              "Household": "HHD", "Packaged Food": "PKF", "Fruits & Vegetables": "FNV"}
FORCE_OUT = {"Harpic Toilet Cleaner 1L", "Bournvita 500g"}


def at(d: date, h: int = 10, m: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)


def ean13(n: int) -> str:
    body = f"890{n:09d}"
    s = sum(int(c) * (3 if i % 2 else 1) for i, c in enumerate(body))
    return body + str((10 - s % 10) % 10)


class Numbers:
    """Document numbers PREFIX-YYYYMM-NNNN in chronological order (matches services.numbering)."""

    def __init__(self) -> None:
        self.seq: dict[tuple[str, str], int] = defaultdict(int)

    def __call__(self, prefix: str, d: date) -> str:
        k = (prefix, f"{d:%Y%m}")
        self.seq[k] += 1
        return f"{prefix}-{k[1]}-{self.seq[k]:04d}"


@dataclass
class P:
    id: int
    name: str
    category: str
    unit: str
    gst: float
    cost: float
    mrp: float
    base: float
    shelf: int | None
    perishable: bool
    pack: float
    moq: float
    hsn: str
    suppliers: list[int] = field(default_factory=list)  # supplier indices


def bulk(db: Session, model: Any, rows: list[dict[str, Any]], returning: bool = False) -> list[int]:
    if not rows:
        return []
    if returning:
        res = db.execute(insert(model).returning(model.id, sort_by_parameter_order=True), rows)
        return list(res.scalars())
    db.execute(insert(model), rows)
    return []


def wipe(db: Session) -> None:
    tables = db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'"))
    names = ", ".join(f'"{t}"' for (t,) in tables)
    if names:
        db.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


class Generator:
    def __init__(self, db: Session, log: Any = print, sales_days: int = SALES_DAYS,
                 purchase_days: int = PURCHASE_DAYS) -> None:
        self.db = db
        self.sales_days = sales_days
        self.purchase_days = purchase_days
        self.log = log
        self.rng = np.random.default_rng(SEED)
        self.today = today()
        self.start = self.today - timedelta(days=self.sales_days)
        self.days = [self.start + timedelta(days=i) for i in range(self.sales_days)]
        self.num = Numbers()
        self.products: list[P] = []
        self.supplier_ids: list[int] = []
        self.sp_price: dict[tuple[int, int], tuple[float, int]] = {}  # (product_id, sup_idx) -> (price, lead)
        self.users: dict[str, int] = {}
        self.store_id = 0
        self.warehouse_id = 0
        self.receipts: list[tuple[int, int, float, date, date | None]] = []
        self.po_lines: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
        self.po_rows: dict[int, dict[str, Any]] = {}
        self.damaged: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ masters
    def masters(self) -> None:
        db = self.db
        bulk(db, Setting, [{"key": "business", "value": C.BUSINESS}])
        bulk(db, ApprovalRule, [{"min_amount": a, "max_amount": b, "approver_role": r, "auto_approve": auto}
                                for a, b, r, auto in C.APPROVAL_RULES])
        bulk(db, Festival, [{"name": n, "date": d, "impact": C.FESTIVAL_EFFECT[n][0]}
                            for n, ds in C.FESTIVAL_DATES.items() for d in ds])
        locs = bulk(db, Location, [{"name": n, "type": t, "address": a} for n, t, a in C.LOCATIONS], returning=True)
        self.store_id, self.warehouse_id = locs
        cat_ids = dict(zip(C.CATEGORIES, bulk(db, Category, [{"name": c} for c in C.CATEGORIES], returning=True), strict=True))
        self.supplier_ids = bulk(db, Supplier, [
            {"name": s[0], "contact_name": s[1], "state": s[2], "gstin": s[3], "payment_terms_days": s[10],
             "email": f"orders@{s[0].split()[0].lower()}{i + 1}.example.in", "phone": f"98{22000000 + i * 1373:08d}",
             "address": f"{s[2]} (GST {s[3][:2]})"}
            for i, s in enumerate(C.SUPPLIERS)
        ], returning=True)
        rows, meta = [], []
        n = 0
        for cat, items in C.PRODUCTS.items():
            prefix = SKU_PREFIX[cat]
            for i, (name, unit, hsn, gst, cost, mrp, base, shelf, per, pack, moq) in enumerate(items, start=1):
                n += 1
                rows.append({"sku": f"{prefix}-{i:03d}", "barcode": ean13(100000 + n * 37), "name": name,
                             "category_id": cat_ids[cat], "unit": unit, "hsn_code": hsn, "gst_rate": gst,
                             "cost_price": cost, "selling_price": mrp, "is_perishable": per, "shelf_life_days": shelf,
                             "pack_size": pack, "min_order_qty": moq})
                meta.append((cat, name, unit, gst, cost, mrp, base, shelf, per, pack, moq, hsn))
        ids = bulk(db, Product, rows, returning=True)
        for pid, (cat, name, unit, gst, cost, mrp, base, shelf, per, pack, moq, hsn) in zip(ids, meta, strict=True):
            self.products.append(P(pid, name, cat, unit, gst, cost, mrp, base, shelf, per, pack, moq, hsn))
        # supplier assortment: every product from 2-3 eligible suppliers with its own price and lead time
        sp_rows = []
        for p in self.products:
            eligible = [i for i, s in enumerate(C.SUPPLIERS) if p.category in s[9]]
            k = min(len(eligible), 3 if len(eligible) >= 3 and self.rng.random() < 0.5 else 2)
            p.suppliers = sorted(self.rng.choice(eligible, size=k, replace=False).tolist())
            for si in p.suppliers:
                s = C.SUPPLIERS[si]
                price = round(p.cost * s[4] * self.rng.uniform(0.97, 1.03), 2)
                lead = int(s[5] + self.rng.integers(0, 2))
                self.sp_price[(p.id, si)] = (price, lead)
                sp_rows.append({"supplier_id": self.supplier_ids[si], "product_id": p.id, "unit_price": price,
                                "lead_time_days": lead, "min_order_qty": p.moq,
                                "valid_till": self.today + timedelta(days=int(self.rng.integers(60, 240)))})
        bulk(db, SupplierProduct, sp_rows)
        user_rows = [{"name": n, "email": e, "password_hash": hash_password(pw), "role": r, "language": "en",
                      "supplier_id": self.supplier_ids[si] if si is not None else None, "phone": f"9850{i:06d}"}
                     for i, (n, e, pw, r, si) in enumerate(C.USERS)]
        for (_, e, _, _r, _), uid in zip(C.USERS, bulk(db, User, user_rows, returning=True), strict=True):
            self.users[e.split("@")[0]] = uid

    # ------------------------------------------------------------------ demand
    def demand(self) -> np.ndarray:
        n_days = len(self.days)
        dow = np.array([DOW[d.weekday()] for d in self.days])
        dom = np.array([d.day for d in self.days])
        month = np.array([d.month for d in self.days])
        salary = np.where(dom <= 7, 1.13, np.where(dom >= 25, 0.94, 1.0))
        fest = {cat: np.ones(n_days) for cat in C.CATEGORIES}
        diwali = np.ones(n_days)
        idx = {d: i for i, d in enumerate(self.days)}
        for name, dates in C.FESTIVAL_DATES.items():
            peak, build, cats = C.FESTIVAL_EFFECT[name]
            for fd in dates:
                for k in range(build + 1):
                    d = fd - timedelta(days=k)
                    if d in idx:
                        mult = 1 + (peak - 1) * (1 - k / (build + 1))
                        for cat in cats or C.CATEGORIES:
                            fest[cat][idx[d]] = max(fest[cat][idx[d]], mult)
                        if name == "Diwali":
                            diwali[idx[d]] = max(diwali[idx[d]], 1 + 5 * (1 - k / (build + 1)))
                after = fd + timedelta(days=1)
                if after in idx:
                    for cat in cats:
                        fest[cat][idx[after]] = min(fest[cat][idx[after]], 0.85)
        out = np.zeros((len(self.products), n_days))
        t = np.arange(n_days)
        for i, p in enumerate(self.products):
            lam = p.base * self.rng.uniform(0.85, 1.15) * dow * salary * fest[p.category]
            if p.category == "Beverages":
                lam = lam * np.where(np.isin(month, [4, 5, 6]), 1.35, np.where(np.isin(month, [12, 1]), 0.9, 1.0))
            if p.category == "Fruits & Vegetables" and "Mango" in p.name:
                lam = lam * np.where(np.isin(month, [4, 5]), 3.0, 1.0)
            if any(w in p.name for w in ("Diya", "Rangoli", "Kaju Katli")):
                lam = lam * diwali
            up, down = n_days // 3, int(n_days * 0.45)  # trend change points
            if p.name in C.TREND_UP:
                lam = lam * np.where(t < up, 0.8, 0.8 + 0.6 * (t - up) / (n_days - up))
            if p.name in C.TREND_DOWN:
                lam = lam * np.where(t < down, 1.15, 1.15 - 0.55 * (t - down) / (n_days - down))
            if p.name in C.DEAD_STOCK:
                lam = np.where(t >= n_days - 80, 0.0, lam)
            sales = self.rng.poisson(np.maximum(lam, 0))
            if p.name == "Coca-Cola 750ml":
                sales[-3] = int(sales[-3] * 5 + 40)  # injected sales spike (anomaly agent)
            out[i] = sales
        return out

    # ------------------------------------------------------------------ sales
    def sales(self, d: np.ndarray) -> None:
        db = self.db
        sale_rows: list[dict[str, Any]] = []
        line_buf: list[tuple[int, dict[str, Any]]] = []
        mov_rows: list[dict[str, Any]] = []
        for j, day in enumerate(self.days):
            active = [(i, int(d[i, j])) for i in range(len(self.products)) if d[i, j] > 0]
            if not active:
                continue
            n_inv = max(15, int(sum(q for _, q in active) / 9))
            base_idx = len(sale_rows)
            minutes = np.sort(self.rng.integers(8 * 60, 22 * 60, size=n_inv))
            for k in range(n_inv):
                sale_rows.append({"invoice_no": self.num("INV", day), "location_id": self.store_id,
                                  "sold_at": at(day, int(minutes[k] // 60), int(minutes[k] % 60)), "channel": "pos_api",
                                  "subtotal": 0.0, "tax": 0.0, "total": 0.0, "user_id": None,
                                  "created_at": at(day, int(minutes[k] // 60), int(minutes[k] % 60))})
            for i, qty in active:
                p = self.products[i]
                chunks = min(qty, int(self.rng.integers(1, 5)))
                parts = np.full(chunks, qty // chunks)
                parts[: qty % chunks] += 1
                for part in parts:
                    inv = base_idx + int(self.rng.integers(0, n_inv))
                    total = round(float(part) * p.mrp, 2)
                    tax = round(total * p.gst / (100 + p.gst), 2)
                    s = sale_rows[inv]
                    s["total"] = round(s["total"] + total, 2)
                    s["tax"] = round(s["tax"] + tax, 2)
                    line_buf.append((inv, {"product_id": p.id, "qty": float(part), "unit_price": p.mrp,
                                           "gst_rate": p.gst, "line_total": total, "created_at": s["sold_at"]}))
                mov_rows.append({"product_id": p.id, "location_id": self.store_id, "type": "sale_out", "qty": -float(qty),
                                 "unit_cost": p.cost, "reference_type": "sales_day", "note": "Daily POS sales",
                                 "created_at": at(day, 21, 30)})
        keep = [i for i, s in enumerate(sale_rows) if s["total"] > 0]
        remap = {old: new for new, old in enumerate(keep)}
        sale_rows = [sale_rows[i] for i in keep]
        for s in sale_rows:
            s["subtotal"] = round(s["total"] - s["tax"], 2)
        ids: list[int] = []
        for c in range(0, len(sale_rows), 5000):
            ids += bulk(db, Sale, sale_rows[c:c + 5000], returning=True)
        lines = [{**ln, "sale_id": ids[remap[inv]]} for inv, ln in line_buf]
        for c in range(0, len(lines), 10000):
            bulk(db, SaleLine, lines[c:c + 10000])
        for c in range(0, len(mov_rows), 10000):
            bulk(db, StockMovement, mov_rows[c:c + 10000])
        self.log(f"  sales: {len(sale_rows)} invoices, {len(lines)} lines")

    # ------------------------------------------------------------------ purchasing
    def purchasing(self, d: np.ndarray) -> dict[int, float]:
        """Simulate replenishment for the last 365 days; returns ending on-hand per product."""
        rng = self.rng
        offset = self.sales_days - self.purchase_days
        orders: list[dict[str, Any]] = []
        group_lead: dict[tuple[int, int], tuple[int, int]] = {}
        ending: dict[int, float] = {}
        for i, p in enumerate(self.products):
            demand = d[i]
            mean0 = max(demand[:offset].mean(), 0.05)
            primary = min(p.suppliers, key=lambda si: self.sp_price[(p.id, si)][0])
            lead0 = self.sp_price[(p.id, primary)][1]
            inv = mean0 * (lead0 + 16)
            pipeline: list[tuple[int, float, float]] = []  # (arrival_day, qty, damaged)
            for t in range(offset, self.sales_days):
                for arr in [x for x in pipeline if x[0] == t]:
                    inv += arr[1] - arr[2]
                    pipeline.remove(arr)
                inv = max(0.0, inv - demand[t])
                window = demand[max(0, t - 28):t]
                mean_d = max(window.mean() if len(window) else mean0, 0.05)
                si = primary if rng.random() < 0.6 else int(rng.choice(p.suppliers))
                price, lead = self.sp_price[(p.id, si)]
                rop = mean_d * (lead + 2)
                if p.perishable and p.shelf:
                    q = max(p.moq, mean_d * min(p.shelf, 7) * 0.8)
                else:
                    q = max(p.moq, mean_d * 14)
                q = math.ceil(q / p.pack) * p.pack
                blocked = (p.name in FORCE_OUT and t > self.sales_days - 25) or (p.name in C.DEAD_STOCK and t > self.sales_days - 120)
                position = inv + sum(x[1] for x in pipeline)
                if position <= rop and not blocked and t < self.sales_days:
                    key = (si, t)
                    if key not in group_lead:
                        s = C.SUPPLIERS[si]
                        actual = max(1, int(round(rng.normal(s[5], s[6]))))
                        if rng.random() < s[7]:
                            actual += int(rng.integers(2, 6))
                        group_lead[key] = (actual, s[5])
                    actual, stated = group_lead[key]
                    damaged = float(rng.binomial(int(q), C.SUPPLIERS[si][8])) if q >= 1 else 0.0
                    pipeline.append((t + actual, q, damaged))
                    orders.append({"p": p, "si": si, "t": t, "qty": q, "price": round(price * rng.uniform(0.99, 1.01), 2),
                                   "arrival": t + actual, "stated": stated, "damaged": damaged})
            if p.name in FORCE_OUT:
                inv = 0.0
            ending[p.id] = round(inv, 0)
        self._write_purchasing(orders)
        return ending

    def _write_purchasing(self, orders: list[dict[str, Any]]) -> None:
        db = self.db
        rng = self.rng
        groups: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for o in orders:
            groups[(o["si"], o["t"])].append(o)
        keys = sorted(groups, key=lambda k: (k[1], k[0]))
        today_idx = self.sales_days
        recent_closed = [k for k in keys if today_idx - 25 <= max(o["arrival"] for o in groups[k]) < today_idx - 3]
        mismatch = set(rng.choice(len(recent_closed), size=min(2, len(recent_closed)), replace=False).tolist())
        mismatch_keys = {recent_closed[i] for i in mismatch}
        arrived_open = [k for k in keys if today_idx - 2 <= max(o["arrival"] for o in groups[k]) < today_idx]
        partial_key = arrived_open[0] if arrived_open else None
        in_transit = [k for k in keys if max(o["arrival"] for o in groups[k]) >= today_idx]
        unconfirmed_key = next((k for k in in_transit if today_idx - k[1] >= 2), None)

        po_rows, meta = [], []
        for key in keys:
            si, t = key
            lines = groups[key]
            od = self.days[t]
            arrival = max(o["arrival"] for o in lines)
            stated = lines[0]["stated"]
            sup = C.SUPPLIERS[si]
            inter = sup[2] != "Maharashtra"
            sub = round(sum(o["qty"] * o["price"] for o in lines), 2)
            tax = round(sum(o["qty"] * o["price"] * o["p"].gst / 100 for o in lines), 2)
            arr_d = self.start + timedelta(days=arrival)
            if arrival < today_idx - 2 or (arrival < today_idx and key != partial_key):
                status = "INVOICED" if key in mismatch_keys else ("RECEIVED" if arrival >= today_idx - 2 else "CLOSED")
            elif key == partial_key:
                status = "PARTIALLY_RECEIVED"
            elif key == unconfirmed_key:
                status = "SENT"
            elif t == today_idx - 1 or arrival - today_idx > 3:
                status = "CONFIRMED"
            else:
                status = "DISPATCHED"
            delivered = status in ("CLOSED", "INVOICED", "RECEIVED", "PARTIALLY_RECEIVED")
            po_rows.append({
                "po_no": self.num("PO", od), "supplier_id": self.supplier_ids[si], "location_id": self.store_id,
                "status": status, "order_date": od, "expected_date": od + timedelta(days=stated),
                "predicted_date": od + timedelta(days=stated), "is_interstate": inter, "subtotal": sub,
                "cgst": 0.0 if inter else round(tax / 2, 2), "sgst": 0.0 if inter else round(tax / 2, 2),
                "igst": tax if inter else 0.0, "total": round(sub + tax, 2),
                "sent_at": at(od, 10, 30), "confirmed_at": None if status == "SENT" else at(od, 13, 15),
                "dispatched_at": at(arr_d - timedelta(days=1), 16) if status not in ("SENT", "CONFIRMED") else None,
                "supplier_eta": arr_d if status in ("CONFIRMED", "DISPATCHED") else None,
                "tracking_ref": f"TRK{self.supplier_ids[si]:02d}{t:04d}" if status not in ("SENT", "CONFIRMED") else None,
                "courier_name": "Own vehicle" if sup[2] == "Maharashtra" else "VRL Logistics",
                "courier_status": "Delivered" if delivered else ("In transit" if status == "DISPATCHED" else None),
                "delivered_at": at(arr_d, 11) if delivered else None,
                "closed_at": at(arr_d + timedelta(days=3), 17) if status == "CLOSED" else None,
                "created_by": self.users["manager"], "created_at": at(od, 10, 25),
            })
            meta.append((key, status, arr_d, lines))
        po_ids = bulk(db, PurchaseOrder, po_rows, returning=True)

        line_rows, line_meta = [], []
        hist = []
        for po_id, (_key, status, arr_d, lines), po in zip(po_ids, meta, po_rows, strict=True):
            for o in lines:
                p = o["p"]
                received = o["qty"] - o["damaged"] if po["delivered_at"] else 0.0
                damaged = o["damaged"] if po["delivered_at"] else 0.0
                if status == "PARTIALLY_RECEIVED":
                    received = math.floor(o["qty"] * 0.6)
                    damaged = 0.0
                line_rows.append({"po_id": po_id, "product_id": p.id, "qty": o["qty"], "unit_price": o["price"],
                                  "gst_rate": p.gst, "hsn_code": p.hsn, "received_qty": received, "damaged_qty": damaged,
                                  "created_at": po["created_at"]})
                line_meta.append((po_id, o, received, damaged))
            steps = ["CREATED", "SENT", "CONFIRMED", "DISPATCHED", "RECEIVED", "INVOICED", "CLOSED"]
            if status == "PARTIALLY_RECEIVED":
                steps = ["CREATED", "SENT", "CONFIRMED", "DISPATCHED", "PARTIALLY_RECEIVED"]
            else:
                steps = steps[: steps.index(status) + 1]
            od = po["order_date"]
            stamps = {"CREATED": at(od, 10, 25), "SENT": at(od, 10, 30), "CONFIRMED": at(od, 13, 15),
                      "DISPATCHED": po["dispatched_at"] or at(od, 18), "RECEIVED": at(arr_d, 11),
                      "PARTIALLY_RECEIVED": at(arr_d, 11), "INVOICED": at(arr_d + timedelta(days=1), 12),
                      "CLOSED": at(arr_d + timedelta(days=3), 17)}
            actor = {"CREATED": ("agent", None), "SENT": ("system", None), "CONFIRMED": ("supplier", None),
                     "DISPATCHED": ("supplier", None), "RECEIVED": ("user", self.users["staff"]),
                     "PARTIALLY_RECEIVED": ("user", self.users["staff"]), "INVOICED": ("user", self.users["manager"]),
                     "CLOSED": ("system", None)}
            prev = None
            for s in steps:
                hist.append({"po_id": po_id, "from_status": prev, "to_status": s, "actor_type": actor[s][0],
                             "actor_id": actor[s][1], "created_at": stamps[s],
                             "note": "Auto-created from approved purchase requests" if s == "CREATED" else None})
                prev = s
        line_ids = bulk(db, PoLine, line_rows, returning=True)
        bulk(db, OrderStatusHistory, hist)

        # GRNs, batches, purchase_in movements
        grn_groups: dict[int, list[int]] = defaultdict(list)
        for idx, (po_id, _, received, damaged) in enumerate(line_meta):
            if received + damaged > 0:
                grn_groups[po_id].append(idx)
        po_by_id = dict(zip(po_ids, po_rows, strict=True))
        grn_rows, grn_po = [], []
        for po_id, _idxs in grn_groups.items():
            d0 = po_by_id[po_id]["delivered_at"].date()
            grn_rows.append({"grn_no": self.num("GRN", d0), "po_id": po_id, "location_id": self.store_id,
                             "received_by": self.users["staff"], "received_at": at(d0, 11, 20), "created_at": at(d0, 11, 20)})
            grn_po.append(po_id)
        grn_ids = bulk(db, GoodsReceipt, grn_rows, returning=True)
        grn_of_po = dict(zip(grn_po, grn_ids, strict=True))
        gl_rows, gl_meta = [], []
        for po_id, idxs in grn_groups.items():
            d0 = po_by_id[po_id]["delivered_at"].date()
            for idx in idxs:
                _, o, received, damaged = line_meta[idx]
                p = o["p"]
                expiry = d0 + timedelta(days=max(1, int(p.shelf * rng.uniform(0.8, 0.95)))) if p.shelf else None
                gl_rows.append({"grn_id": grn_of_po[po_id], "po_line_id": line_ids[idx], "product_id": p.id,
                                "received_qty": received, "damaged_qty": damaged,
                                "batch_no": f"{p.id:03d}{d0:%y%m%d}{o['si']}", "expiry_date": expiry,
                                "created_at": at(d0, 11, 20)})
                gl_meta.append((idx, d0, o, received, expiry))
        gl_ids = bulk(db, GrnLine, gl_rows, returning=True)
        batch_rows = [{"product_id": o["p"].id, "location_id": self.store_id, "batch_no": gl_rows[k]["batch_no"],
                       "expiry_date": expiry, "qty_on_hand": 0.0, "cost_price": o["price"], "received_at": at(d0, 11, 20),
                       "grn_line_id": gl_ids[k], "supplier_id": self.supplier_ids[o["si"]], "created_at": at(d0, 11, 20)}
                      for k, (_, d0, o, _, expiry) in enumerate(gl_meta)]
        batch_ids = bulk(db, Batch, batch_rows, returning=True)
        self.damaged = [{"po_id": line_rows[idx]["po_id"], "si": o["si"], "p": o["p"], "price": o["price"], "d0": d0,
                         "qty": line_meta[idx][3], "batch_id": batch_ids[k]}
                        for k, (idx, d0, o, _, _) in enumerate(gl_meta) if line_meta[idx][3] > 0]
        self.receipts = [(o["p"].id, batch_ids[k], received, d0, expiry) for k, (_, d0, o, received, expiry) in enumerate(gl_meta)]
        bulk(db, StockMovement, [
            {"product_id": o["p"].id, "batch_id": batch_ids[k], "location_id": self.store_id, "type": "purchase_in",
             "qty": received, "unit_cost": o["price"], "reference_type": "grn", "reference_id": gl_rows[k]["grn_id"],
             "user_id": self.users["staff"], "created_at": at(d0, 11, 25)}
            for k, (_, d0, o, received, _) in enumerate(gl_meta) if received > 0
        ])

        # supplier invoices + 3-way matches for every invoiced/closed PO
        inv_rows, inv_meta = [], []
        for po_id, (key, status, arr_d, _), _po in zip(po_ids, meta, po_rows, strict=True):
            if status not in ("CLOSED", "INVOICED"):
                continue
            idxs = [i for i, m in enumerate(line_meta) if m[0] == po_id]
            si = key[0]
            bump = 1.06 if key in mismatch_keys else 1.0
            sub = tax = 0.0
            lines = []
            for n, i in enumerate(idxs):
                _, o, received, _ = line_meta[i]
                price = round(o["price"] * (bump if n == 0 else 1.0), 2)
                lines.append({"po_line_id": line_ids[i], "product_id": o["p"].id, "description": o["p"].name,
                              "qty": received, "unit_price": price, "gst_rate": o["p"].gst})
                sub += received * price
                tax += received * price * o["p"].gst / 100
            initials = "".join(w[0] for w in C.SUPPLIERS[si][0].split()[:2]).upper()
            inv_rows.append({"invoice_no": f"{initials}/{arr_d:%y}/{po_id:05d}", "supplier_id": self.supplier_ids[si],
                             "po_id": po_id, "invoice_date": arr_d, "subtotal": round(sub, 2), "tax": round(tax, 2),
                             "total": round(sub + tax, 2), "source": "manual",
                             "status": "mismatch" if key in mismatch_keys else "matched",
                             "created_by": self.users["manager"], "created_at": at(arr_d + timedelta(days=1), 12)})
            inv_meta.append((po_id, lines, key in mismatch_keys))
        inv_ids = bulk(db, SupplierInvoice, inv_rows, returning=True)
        line_by_id = dict(zip(line_ids, line_rows, strict=True))
        il_rows, match_rows = [], []
        for inv_id, (po_id, lines, bad) in zip(inv_ids, inv_meta, strict=True):
            il_rows += [{**ln, "invoice_id": inv_id} for ln in lines]
            details = []
            for ln in lines:
                pl = line_by_id[ln["po_line_id"]]
                diff = round((ln["unit_price"] - pl["unit_price"]) / pl["unit_price"] * 100, 2)
                ok = abs(diff) <= 2.0 and ln["qty"] == pl["received_qty"]
                details.append({"product_id": ln["product_id"], "product": ln["description"], "po_qty": pl["qty"],
                                "grn_qty": pl["received_qty"], "invoice_qty": ln["qty"], "po_price": pl["unit_price"],
                                "invoice_price": ln["unit_price"], "price_diff_pct": diff, "qty_ok": True,
                                "price_ok": abs(diff) <= 2.0, "status": "matched" if ok else "mismatch"})
            match_rows.append({"po_id": po_id, "grn_id": grn_of_po.get(po_id), "invoice_id": inv_id,
                               "status": "mismatch" if bad else "matched",
                               "details_json": {"lines": details, "tolerance": {"qty_pct": 0, "price_pct": 2}},
                               "created_at": at(po_by_id[po_id]["delivered_at"].date() + timedelta(days=1), 12, 5)})
        bulk(db, SupplierInvoiceLine, il_rows)
        bulk(db, ThreeWayMatch, match_rows)
        self.po_lines = list(zip(line_ids, line_rows, [m[1] for m in line_meta], strict=True))
        self.po_rows = dict(zip(po_ids, po_rows, strict=True))
        self.log(f"  purchasing: {len(po_ids)} POs, {len(line_ids)} lines, {len(grn_ids)} GRNs, {len(inv_ids)} invoices "
                 f"({len(mismatch_keys)} mismatches)")

    # ------------------------------------------------------------------ stock on hand
    def current_stock(self, ending: dict[int, float]) -> None:
        db = self.db
        by_product: dict[int, list[tuple[int, float, date, date | None]]] = defaultdict(list)
        for pid, bid, received, d0, expiry in self.receipts:
            by_product[pid].append((bid, received, d0, expiry))
        updates: dict[int, float] = {}
        for p in self.products:
            left = ending.get(p.id, 0.0)
            for bid, received, _, expiry in sorted(by_product[p.id], key=lambda x: x[2], reverse=True):
                if left <= 0:
                    break
                if expiry and expiry <= self.today:
                    continue  # expired stock would have been written off
                take = min(left, received)
                updates[bid] = take
                left -= take
        for bid, qty in updates.items():
            db.execute(text("UPDATE batches SET qty_on_hand=:q WHERE id=:id"), {"q": qty, "id": bid})
        # make sure every expiry bucket is represented (spec: "every expiry bucket has items")
        byname = {p.name: p for p in self.products}
        forced = [("Amul Masti Dahi 400g", -1, 14), ("Chitale Shrikhand 500g", -2, 6), ("Tomato (kg)", -1, 12),
                  ("Amul Fresh Paneer 200g", 2, 18), ("Kaju Katli 250g", 5, 9), ("Nestle a+ Lassi 200ml", 4, 30),
                  ("Chitale Bakarwadi 250g", 18, 25), ("Britannia Good Day 200g", 12, 60), ("Oreo Chocolate 120g", 26, 40),
                  ("Real Mixed Fruit Juice 1L", 21, 35)]
        rows = []
        for name, days, qty in forced:
            p = byname[name]
            rows.append({"product_id": p.id, "location_id": self.store_id, "batch_no": f"EXP{p.id:03d}{days + 50}",
                         "expiry_date": self.today + timedelta(days=days), "qty_on_hand": float(qty), "cost_price": p.cost,
                         "received_at": at(self.today - timedelta(days=max(3, (p.shelf or 30) - days)), 11),
                         "supplier_id": self.supplier_ids[p.suppliers[0]]})
        for name in sorted(C.DEAD_STOCK):  # slow movers bought ~100 days ago that stopped selling
            p = byname[name]
            got = self.today - timedelta(days=100)
            rows.append({"product_id": p.id, "location_id": self.store_id, "batch_no": f"DS{p.id:03d}{got:%y%m%d}",
                         "expiry_date": got + timedelta(days=p.shelf) if p.shelf else None, "qty_on_hand": p.pack * 2,
                         "cost_price": p.cost, "received_at": at(got, 11),
                         "supplier_id": self.supplier_ids[p.suppliers[0]]})
        ids = bulk(db, Batch, rows, returning=True)
        bulk(db, StockMovement, [{"product_id": r["product_id"], "batch_id": bid, "location_id": self.store_id,
                                  "type": "purchase_in", "qty": r["qty_on_hand"], "unit_cost": r["cost_price"],
                                  "reference_type": "manual_in", "user_id": self.users["staff"],
                                  "created_at": r["received_at"]} for r, bid in zip(rows, ids, strict=True)])

    # ------------------------------------------------------------------ warehouse, transfers, count
    def warehouse(self, d: np.ndarray) -> None:
        db = self.db
        rng = self.rng
        staples = [p for p in self.products if p.category in ("Staples", "Household") and p.name not in C.DEAD_STOCK][:14]
        opened = self.today - timedelta(days=45)
        rows = []
        for p in staples:
            i = self.products.index(p)
            qty = float(math.ceil(d[i, -60:].mean() * 21 / p.pack) * p.pack)
            rows.append({"product_id": p.id, "location_id": self.warehouse_id, "batch_no": f"WH{p.id:03d}{opened:%y%m}",
                         "expiry_date": opened + timedelta(days=p.shelf) if p.shelf else None, "qty_on_hand": qty,
                         "cost_price": p.cost, "received_at": at(opened, 9), "supplier_id": self.supplier_ids[p.suppliers[0]]})
        ids = bulk(db, Batch, rows, returning=True)
        bulk(db, StockMovement, [{"product_id": r["product_id"], "batch_id": b, "location_id": self.warehouse_id,
                                  "type": "adjustment", "qty": r["qty_on_hand"], "unit_cost": r["cost_price"],
                                  "reference_type": "opening_stock", "note": "Warehouse opening stock",
                                  "user_id": self.users["manager"], "created_at": r["received_at"]}
                                 for r, b in zip(rows, ids, strict=True)])
        transfers = []
        for k, (days_ago, status) in enumerate([(30, "RECEIVED"), (12, "RECEIVED"), (1, "REQUESTED")]):
            d0 = self.today - timedelta(days=days_ago)
            transfers.append({"transfer_no": self.num("TR", d0), "from_location_id": self.warehouse_id,
                              "to_location_id": self.store_id, "status": status, "requested_by": self.users["staff"],
                              "approved_by": self.users["manager"] if status != "REQUESTED" else None,
                              "dispatched_at": at(d0, 15) if status == "RECEIVED" else None,
                              "received_at": at(d0, 18) if status == "RECEIVED" else None,
                              "note": "Weekly store refill" if k < 2 else "Diwali stock-up for the store",
                              "created_at": at(d0, 10)})
        tids = bulk(db, StockTransfer, transfers, returning=True)
        tl, mv, hist = [], [], []
        for (tid, tr), bid_row in zip(zip(tids, transfers, strict=True), [ids[:4], ids[4:8], ids[8:12]], strict=True):
            for bid in bid_row:
                b = rows[ids.index(bid)]
                qty = float(b["qty_on_hand"] // 4 or 1)
                tl.append({"transfer_id": tid, "product_id": b["product_id"], "batch_id": bid, "qty": qty})
                if tr["status"] == "RECEIVED":
                    mv.append({"product_id": b["product_id"], "batch_id": bid, "location_id": self.warehouse_id,
                               "type": "transfer_out", "qty": -qty, "unit_cost": b["cost_price"], "reference_type": "transfer",
                               "reference_id": tid, "user_id": self.users["staff"], "created_at": tr["dispatched_at"]})
                    mv.append({"product_id": b["product_id"], "location_id": self.store_id, "type": "transfer_in",
                               "qty": qty, "unit_cost": b["cost_price"], "reference_type": "transfer", "reference_id": tid,
                               "user_id": self.users["staff"], "created_at": tr["received_at"]})
                    db.execute(text("UPDATE batches SET qty_on_hand = qty_on_hand - :q WHERE id=:id"), {"q": qty, "id": bid})
            steps = ["REQUESTED", "APPROVED", "DISPATCHED", "RECEIVED"] if tr["status"] == "RECEIVED" else ["REQUESTED"]
            prev = None
            for s in steps:
                hist.append({"entity": "stock_transfer", "entity_id": tid, "from_status": prev, "to_status": s,
                             "actor_type": "user", "actor_id": self.users["manager" if s == "APPROVED" else "staff"],
                             "created_at": tr["created_at"]})
                prev = s
        bulk(db, StockTransferLine, tl)
        bulk(db, StockMovement, mv)
        bulk(db, StatusHistory, hist)
        # one completed cycle count 20 days ago (personal care) with two variances
        d0 = self.today - timedelta(days=20)
        cid = bulk(db, StockCount, [{"location_id": self.store_id, "status": "completed", "note": "Monthly personal-care count",
                                     "started_by": self.users["staff"], "completed_at": at(d0, 19), "created_at": at(d0, 17)}],
                   returning=True)[0]
        pcare = [p for p in self.products if p.category == "Personal Care"][:6]
        lines = []
        for k, p in enumerate(pcare):
            sys_q = float(rng.integers(20, 60))
            var = -2.0 if k == 1 else (1.0 if k == 4 else 0.0)
            lines.append({"count_id": cid, "product_id": p.id, "system_qty": sys_q, "counted_qty": sys_q + var, "variance": var})
        bulk(db, StockCountLine, lines)

    # ------------------------------------------------------------------ purchase-request history (learning)
    def requests(self) -> None:
        db = self.db
        rng = self.rng
        cutoff = self.today - timedelta(days=120)
        pr_rows, meta = [], []
        for _line_id, ln, o in self.po_lines:
            po = self.po_rows[ln["po_id"]]
            if po["order_date"] < cutoff:
                continue
            edited = rng.random() < 0.25
            factor = float(rng.uniform(0.8, 1.25)) if edited else 1.0
            suggested = max(o["p"].pack, round(ln["qty"] / factor / o["p"].pack) * o["p"].pack)
            total = round(ln["qty"] * ln["unit_price"], 2)
            created = at(po["order_date"], 6, 5)
            pr_rows.append({
                "product_id": o["p"].id, "location_id": self.store_id, "suggested_qty": suggested, "final_qty": ln["qty"],
                "suggested_supplier_id": po["supplier_id"], "final_supplier_id": po["supplier_id"],
                "est_unit_price": ln["unit_price"], "est_total": total, "status": "ORDERED", "created_by": "agent",
                "required_levels": 0 if total <= 5000 else (1 if total <= 50000 else 2), "po_id": ln["po_id"],
                "reason_text": f"Reorder point reached; suggested {suggested:g} {o['p'].unit} (history).",
                "reason_json": {"source": "seed-history", "suggested_qty": suggested}, "submitted_at": created,
                "created_at": created,
            })
            meta.append((edited, total, created))
        # rejected suggestions for the rejection-learning rule
        for k, p in enumerate([p for p in self.products if p.category == "Snacks"][:5]):
            d0 = self.today - timedelta(days=int(10 + 7 * k))
            price, _ = self.sp_price[(p.id, p.suppliers[0])]
            pr_rows.append({
                "product_id": p.id, "location_id": self.store_id, "suggested_qty": p.pack * 6, "final_qty": None,
                "suggested_supplier_id": self.supplier_ids[p.suppliers[0]], "est_unit_price": price,
                "est_total": round(price * p.pack * 6, 2), "status": "REJECTED", "created_by": "agent",
                "required_levels": 1, "rejection_reason": "Enough stock in the warehouse",
                "reason_text": "Forecast demand above stock (history).", "reason_json": {"source": "seed-history"},
                "submitted_at": at(d0, 6, 5), "created_at": at(d0, 6, 5),
            })
            meta.append((None, pr_rows[-1]["est_total"], at(d0, 6, 5)))
        ids = bulk(db, PurchaseRequest, pr_rows, returning=True)
        appr, fb = [], []
        for pr_id, row, (edited, _total, created) in zip(ids, pr_rows, meta, strict=True):
            rejected = row["status"] == "REJECTED"
            decided = created + timedelta(hours=float(rng.uniform(1, 20)))
            if row["required_levels"] == 0 and not rejected:
                appr.append({"purchase_request_id": pr_id, "level": 1, "approver_role": "manager", "decision": "approved",
                             "via": "auto", "decided_at": created, "comment": "Auto-approved (≤ ₹5,000)", "created_at": created})
            else:
                for lvl in range(1, max(1, row["required_levels"]) + 1):
                    role = "manager" if lvl == 1 else "admin"
                    appr.append({"purchase_request_id": pr_id, "level": lvl, "approver_role": role,
                                 "approver_id": self.users[role], "decision": "rejected" if rejected else "approved",
                                 "via": str(rng.choice(["web", "email_link", "web"])), "decided_at": decided,
                                 "comment": row.get("rejection_reason"), "created_at": created})
                    if rejected:
                        break
            fb.append({"purchase_request_id": pr_id, "product_id": row["product_id"], "suggested_qty": row["suggested_qty"],
                       "final_qty": row["final_qty"], "decision": "rejected" if rejected else ("edited" if edited else "approved"),
                       "reason": row.get("rejection_reason"), "user_id": self.users["manager"], "created_at": decided})
        bulk(db, Approval, appr)
        bulk(db, Feedback, fb)
        self.log(f"  purchase requests: {len(ids)} historical")

    # ------------------------------------------------------------------ supplier returns (damaged goods)
    def returns(self) -> None:
        recent = sorted(self.damaged, key=lambda x: x["d0"], reverse=True)[:4]
        statuses = ["CREDIT_RECEIVED", "DISPATCHED", "APPROVED", "PENDING_APPROVAL"]
        rows, hist = [], []
        for r, status in zip(recent, statuses, strict=False):
            sub = round(r["qty"] * r["price"], 2)
            tax = round(sub * r["p"].gst / 100, 2)
            approved = status != "PENDING_APPROVAL"
            rows.append({"return_no": self.num("RET", r["d0"]), "supplier_id": self.supplier_ids[r["si"]], "po_id": r["po_id"],
                         "location_id": self.store_id, "status": status, "reason": "Damaged on delivery (from GRN)",
                         "subtotal": sub, "tax": tax, "total": round(sub + tax, 2),
                         "debit_note_no": self.num("DN", r["d0"]) if approved else None,
                         "credit_note_ref": f"CN-{r['po_id']}" if status == "CREDIT_RECEIVED" else None,
                         "created_by": self.users["staff"], "created_at": at(r["d0"], 12)})
        ids = bulk(self.db, SupplierReturn, rows, returning=True)
        lines = [{"return_id": rid, "product_id": r["p"].id, "batch_id": r["batch_id"], "qty": r["qty"],
                  "unit_price": r["price"], "gst_rate": r["p"].gst, "reason": "Damaged"}
                 for rid, r in zip(ids, recent, strict=False)]
        bulk(self.db, SupplierReturnLine, lines)
        order = ["DRAFT", "PENDING_APPROVAL", "APPROVED", "DISPATCHED", "CREDIT_RECEIVED"]
        for rid, row in zip(ids, rows, strict=True):
            prev = None
            for st in order[: order.index(row["status"]) + 1]:
                hist.append({"entity": "supplier_return", "entity_id": rid, "from_status": prev, "to_status": st,
                             "actor_type": "user", "actor_id": self.users["manager" if st == "APPROVED" else "staff"],
                             "created_at": row["created_at"]})
                prev = st
        bulk(self.db, StatusHistory, hist)

    # ------------------------------------------------------------------ anomalies
    def anomalies(self) -> None:
        db = self.db
        rng = self.rng
        staff, manager = self.users["staff"], self.users["manager"]
        byname = {p.name: p for p in self.products}
        mv = []
        # normal background corrections (small) so the 3σ rule has a baseline
        for k in range(40):
            p = self.products[int(rng.integers(0, len(self.products)))]
            d0 = self.today - timedelta(days=int(rng.integers(20, 300)))
            mv.append({"product_id": p.id, "location_id": self.store_id, "type": "adjustment",
                       "qty": float(rng.choice([-2, -1, 1, 2])), "unit_cost": p.cost, "reference_type": "adjustment",
                       "user_id": manager if k % 3 else staff, "note": "Shelf recount", "created_at": at(d0, 18, 10)})
        for k in range(6):  # baseline for the specific product used in the big adjustment below
            mv.append({"product_id": byname["Cadbury Dairy Milk Silk 60g"].id, "location_id": self.store_id,
                       "type": "adjustment", "qty": float(rng.choice([-1, 1, -2])), "unit_cost": 70,
                       "reference_type": "adjustment", "user_id": manager, "note": "Recount",
                       "created_at": at(self.today - timedelta(days=60 + 15 * k), 18)})
        # 1) adjustment far beyond 3σ, at an odd hour
        mv.append({"product_id": byname["Cadbury Dairy Milk Silk 60g"].id, "location_id": self.store_id, "type": "adjustment",
                   "qty": -36.0, "unit_cost": 70, "reference_type": "adjustment", "user_id": staff,
                   "note": "Stock mismatch", "created_at": at(self.today - timedelta(days=3), 2, 35)})
        # 2) repeated manual corrections by the same user within a few days
        for k, name in enumerate(["Lay's Classic Salted 52g", "Kurkure Masala Munch 90g", "Oreo Chocolate 120g",
                                  "Britannia Good Day 200g", "Parle-G Biscuits 800g", "Maggi 2-Minute Noodles 280g"]):
            mv.append({"product_id": byname[name].id, "location_id": self.store_id, "type": "adjustment", "qty": -3.0,
                       "unit_cost": byname[name].cost, "reference_type": "adjustment", "user_id": staff,
                       "note": "Correction", "created_at": at(self.today - timedelta(days=1 + k % 4), 20, 5 + k)})
        bulk(db, StockMovement, mv)
        # 3) cost price jump > 20% (audit trail is what the anomaly agent inspects)
        oil = byname["Fortune Sunflower Oil 1L"]
        new_cost = round(oil.cost * 1.26, 2)
        db.execute(text("UPDATE products SET cost_price=:c WHERE id=:id"), {"c": new_cost, "id": oil.id})
        logs = [{"user_id": manager, "action": "update", "entity": "products", "entity_id": str(oil.id),
                 "before_json": {"cost_price": oil.cost}, "after_json": {"cost_price": new_cost}, "ip": "192.168.1.24",
                 "created_at": at(self.today - timedelta(days=2), 11, 40)}]
        # 4) negative-stock attempts
        for k in range(3):
            p = byname["Harpic Toilet Cleaner 1L"]
            logs.append({"user_id": staff, "action": "negative_stock_attempt", "entity": "products", "entity_id": str(p.id),
                         "after_json": {"location_id": self.store_id, "requested": 2 + k,
                                        "message": "Insufficient stock: requested more than available"},
                         "ip": "192.168.1.31", "created_at": at(self.today - timedelta(days=k + 1), 19, 12)})
        bulk(db, AuditLog, logs)

    # ------------------------------------------------------------------ run
    def run(self) -> dict[str, Any]:
        t0 = time.perf_counter()
        wipe(self.db)
        self.masters()
        self.log(f"  masters: {len(self.products)} products, {len(self.supplier_ids)} suppliers")
        d = self.demand()
        self.sales(d)
        ending = self.purchasing(d)
        self.current_stock(ending)
        self.warehouse(d)
        self.requests()
        self.returns()
        self.anomalies()
        # keep sequences/timestamps consistent and finish
        self.db.commit()
        return {"seconds": round(time.perf_counter() - t0, 1), "products": len(self.products),
                "from": self.start.isoformat(), "to": (self.today - timedelta(days=1)).isoformat()}


def generate(db: Session, log: Any = print, **kw: int) -> dict[str, Any]:
    return Generator(db, log, **kw).run()

