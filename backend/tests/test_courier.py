from datetime import timedelta
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

from app.core.config import settings as env
from app.core.timeutil import now, today
from app.models.purchasing import PurchaseOrder
from app.services import courier


def _po(**kw: Any) -> PurchaseOrder:
    base = {"po_no": "PO-T-1", "delivered_at": None, "dispatched_at": now() - timedelta(hours=30),
            "tracking_ref": "AWB123", "supplier_eta": today() + timedelta(days=3), "predicted_date": None,
            "expected_date": None, "courier_status": None}
    base.update(kw)
    return cast(PurchaseOrder, SimpleNamespace(**base))


@pytest.fixture(autouse=True)
def _reset_token() -> None:
    courier.ShiprocketProvider._token = None


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_mock_provider_states() -> None:
    m = courier.MockCourierProvider()
    assert m.status(_po()) == "In transit"
    assert m.status(_po(supplier_eta=today())) == "Out for delivery"
    assert m.status(_po(supplier_eta=today() - timedelta(days=1))) == "Delayed in transit"
    assert m.status(_po(dispatched_at=None, courier_status="x")) == "x"


def test_shiprocket_login_track_and_token_cache() -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        if req.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"token": "tok"})
        assert req.headers["Authorization"] == "Bearer tok"
        assert req.url.path.endswith("/courier/track/awb/AWB123")
        return httpx.Response(200, json={"tracking_data": {"track_status": 1,
                                                           "shipment_track": [{"current_status": "OUT FOR DELIVERY"}]}})

    p = courier.ShiprocketProvider(client=_client(handler))
    assert p.status(_po()) == "Out for delivery"
    assert p.status(_po()) == "Out for delivery"
    assert sum(c.endswith("/auth/login") for c in calls) == 1


def test_shiprocket_falls_back_on_error_and_unknown_awb() -> None:
    def down(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    assert courier.ShiprocketProvider(client=_client(down)).status(_po()) == "In transit"

    def unknown(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"token": "tok"})
        return httpx.Response(200, json={"tracking_data": {"track_status": 0, "error": "Aahh! There is no activities found"}})

    assert courier.ShiprocketProvider(client=_client(unknown)).status(_po()) == "In transit"
    assert courier.ShiprocketProvider.parse({"tracking_data": {"shipment_track_activities": [{"activity": "Picked"}]}}) == "Picked"


def test_provider_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    assert courier.provider().name == "mock"
    monkeypatch.setattr(env, "COURIER_PROVIDER", "shiprocket")
    assert courier.provider().name == "mock"  # no credentials -> fallback
    monkeypatch.setattr(env, "SHIPROCKET_EMAIL", "api@example.com")
    monkeypatch.setattr(env, "SHIPROCKET_PASSWORD", "secret")
    assert courier.provider().name == "shiprocket"
