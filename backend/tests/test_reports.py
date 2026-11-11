import io
import shutil

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.models import ReportSchedule
from app.services import backup, mailer, reports, sales, scheduled
from tests.factories import in_days, make_batch


@pytest.fixture()
def trading(world, db):
    rice, milk = world.products
    make_batch(db, rice, world.store, 50, in_days(200))
    make_batch(db, milk, world.store, 20, in_days(10))
    sales.create_sale(db, location_id=world.store.id, lines=[{"product_id": rice.id, "qty": 5}, {"product_id": milk.id, "qty": 4}],
                      channel="manual", user=world.users["staff"])
    return world


def test_dashboard_per_role(client, auth, trading):
    m = client.get("/api/v1/dashboard", headers=auth("manager")).json()
    assert m["role"] == "manager"
    assert {"stock_value", "below_rop", "out_of_stock", "near_expiry_value", "pending_approvals", "open_pos", "late_deliveries",
            "month_purchases", "inventory_turnover", "ai_acceptance_pct"} <= m["kpis"].keys()
    assert m["kpis"]["stock_value"] == 45 * 90 + 16 * 24
    assert {"sales_vs_forecast", "stock_value_trend", "fast_movers", "expiry_by_week", "supplier_on_time"} <= m["charts"].keys()
    assert m["charts"]["fast_movers"][0]["product"] == "Basmati Rice 1kg"
    assert len(m["charts"]["stock_value_trend"]) == 90 and m["charts"]["stock_value_trend"][-1]["value"] == m["kpis"]["stock_value"]
    s = client.get("/api/v1/dashboard", headers=auth("staff")).json()
    assert s["role"] == "staff" and {"receive", "counts", "expiring", "summary"} <= s["staff"].keys()
    sup = client.get("/api/v1/dashboard", headers=auth("supplier")).json()
    assert sup["role"] == "supplier" and "open_orders" in sup["supplier"]


@pytest.mark.parametrize("name", list(reports.REPORTS))
def test_every_report_exports_json_pdf_xlsx(client, auth, trading, name):
    h = auth("manager")
    j = client.get(f"/api/v1/reports/{name}", headers=h)
    assert j.status_code == 200, j.text
    body = j.json()
    assert body["columns"] and isinstance(body["rows"], list)
    pdf = client.get(f"/api/v1/reports/{name}", headers=h, params={"fmt": "pdf"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    x = client.get(f"/api/v1/reports/{name}", headers=h, params={"fmt": "xlsx"})
    ws = load_workbook(io.BytesIO(x.content)).active
    assert ws["A1"].value == body["title"]


def test_sales_and_gst_numbers(db, trading):
    r = reports.build(db, "sales")
    assert r.totals["revenue"] == 5 * 120 + 4 * 28
    gst = reports.build(db, "gst_summary")
    five = next(row for row in gst.rows if row["rate"] == "5%")
    assert five["out_tax"] == pytest.approx(600 * 5 / 105, abs=0.01)
    zero = next(row for row in gst.rows if row["rate"] == "0%")
    assert zero["out_tax"] == 0


def test_report_validation_and_permissions(client, auth, trading):
    assert client.get("/api/v1/reports/sales", headers=auth("staff")).status_code == 403
    assert client.get("/api/v1/reports/nope", headers=auth("manager")).status_code == 404
    bad = client.get("/api/v1/reports/sales", headers=auth("manager"), params={"date_from": "2026-12-01", "date_to": "2026-11-01"})
    assert bad.status_code == 422


def test_schedules_and_scheduled_emails(client, auth, db, trading):
    h = auth("manager")
    r = client.post("/api/v1/report-schedules", headers=h, json={"report": "sales", "frequency": "daily",
                                                                  "recipients": ["owner@shop.in"], "fmt": "both"})
    assert r.status_code == 201
    sid = r.json()["id"]
    mailer.OUTBOX.clear()
    sent = client.post(f"/api/v1/report-schedules/{sid}/send", headers=h).json()
    assert sent["sent"] == 1
    names = [a[0] for a in mailer.OUTBOX[0].attachments]
    assert any(n.endswith(".pdf") for n in names) and any(n.endswith(".xlsx") for n in names)
    s = db.get(ReportSchedule, sid)
    assert not scheduled.due(s)  # already sent today
    mailer.OUTBOX.clear()
    assert scheduled.daily_summary(db) == 1 and "daily summary" in mailer.OUTBOX[0].subject
    mailer.OUTBOX.clear()
    assert scheduled.weekly_report(db) == 1 and len(mailer.OUTBOX[0].attachments) == 6
    assert client.delete(f"/api/v1/report-schedules/{sid}", headers=h).status_code == 200
    assert db.scalar(select(ReportSchedule)) is None


def test_backup_listing_and_validation(client, auth, tmp_path, monkeypatch):
    monkeypatch.setattr(backup.env, "BACKUP_DIR", str(tmp_path))
    for i in range(16):
        (tmp_path / f"smartstock_2026010{i:02d}.dump").write_bytes(b"x")
    assert backup.prune(keep=14) == 2 and len(backup.list_all()) == 14
    assert client.get("/api/v1/backups", headers=auth("manager")).status_code == 403
    assert len(client.get("/api/v1/backups", headers=auth("admin")).json()) == 14
    bad = client.post("/api/v1/backups/../../etc/restore", headers=auth("admin"), json={"confirm": "RESTORE"})
    assert bad.status_code in (404, 422)
    no = client.post("/api/v1/backups/smartstock_202601010.dump/restore", headers=auth("admin"), json={"confirm": "yes"})
    assert no.status_code == 422


@pytest.mark.skipif(shutil.which("pg_dump") is None and not __import__("pathlib").Path(
    r"C:\Program Files\PostgreSQL\16\bin\pg_dump.exe").exists(), reason="pg_dump not available")
def test_real_backup_file(tmp_path, monkeypatch):
    monkeypatch.setattr(backup.env, "BACKUP_DIR", str(tmp_path))
    info = backup.create()
    assert info["name"].startswith("smartstock_") and info["size"] > 1000
