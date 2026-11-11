"""Courier tracking behind a provider interface (spec 7.6).

COURIER_PROVIDER=mock (default) simulates statuses; COURIER_PROVIDER=shiprocket tracks the PO's tracking/AWB number
through the Shiprocket API and falls back to the mock when it is not configured or a call fails.
"""

import logging
import time
from datetime import date, datetime
from typing import Any

import httpx

from app.core.config import settings as env
from app.core.timeutil import now, today
from app.models.purchasing import PurchaseOrder

log = logging.getLogger(__name__)


class CourierProvider:
    name = "base"

    def status(self, po: PurchaseOrder) -> str | None:
        raise NotImplementedError


class MockCourierProvider(CourierProvider):
    """Advances a dispatched PO through realistic courier states based on dispatch time and ETA."""

    name = "mock"

    def status(self, po: PurchaseOrder) -> str | None:
        if po.delivered_at or not po.dispatched_at:
            return po.courier_status
        eta: date = po.supplier_eta or po.predicted_date or po.expected_date or today()
        hours = (now() - po.dispatched_at).total_seconds() / 3600
        t = today()
        if t > eta:
            return "Delayed in transit"
        if t == eta:
            return "Out for delivery"
        if hours < 6:
            return "Picked up"
        if (eta - t).days <= 1:
            return "Reached destination hub"
        return "In transit"


class ShiprocketProvider(CourierProvider):
    """Shiprocket tracking by AWB (tracking_ref). Token from the API-user login is cached for 9 days (valid 10)."""

    name = "shiprocket"
    TOKEN_TTL = 9 * 24 * 3600
    _token: tuple[str, float] | None = None

    def __init__(self, client: httpx.Client | None = None, fallback: CourierProvider | None = None) -> None:
        self.base = env.SHIPROCKET_BASE_URL.rstrip("/")
        self.client = client or httpx.Client(timeout=10)
        self.fallback = fallback or MockCourierProvider()

    def _auth(self) -> str:
        cached = ShiprocketProvider._token
        if cached and cached[1] > time.time():
            return cached[0]
        r = self.client.post(f"{self.base}/auth/login",
                             json={"email": env.SHIPROCKET_EMAIL, "password": env.SHIPROCKET_PASSWORD})
        r.raise_for_status()
        token = str(r.json()["token"])
        ShiprocketProvider._token = (token, time.time() + self.TOKEN_TTL)
        return token

    @staticmethod
    def parse(data: dict[str, Any]) -> str | None:
        td = data.get("tracking_data") or {}
        if td.get("error"):
            return None
        tracks = td.get("shipment_track") or []
        if tracks and tracks[0].get("current_status"):
            return str(tracks[0]["current_status"]).strip().capitalize()
        acts = td.get("shipment_track_activities") or []
        if acts and acts[0].get("activity"):
            return str(acts[0]["activity"]).strip()
        return None

    def status(self, po: PurchaseOrder) -> str | None:
        if po.delivered_at or not po.dispatched_at or not po.tracking_ref:
            return self.fallback.status(po)
        try:
            r = self.client.get(f"{self.base}/courier/track/awb/{po.tracking_ref}",
                                headers={"Authorization": f"Bearer {self._auth()}"})
            if r.status_code == 401:
                ShiprocketProvider._token = None
            r.raise_for_status()
            found = self.parse(r.json())
            if found:
                return found
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("Shiprocket tracking failed for %s (%s); using simulated status", po.po_no, e)
        return self.fallback.status(po)


def provider() -> CourierProvider:
    if env.courier_enabled:
        return ShiprocketProvider()
    return MockCourierProvider()


def describe() -> dict[str, str]:
    return {"provider": env.COURIER_PROVIDER, "active": provider().name, "checked_at": datetime.now().isoformat()}
