import pyotp
import pytest

from app.core import ratelimit
from app.core.config import settings
from app.services import mailer
from tests.factories import PASSWORD


@pytest.fixture(autouse=True)
def _clear_limits(world):
    for email in ("admin@test.in", "manager@test.in", "staff@test.in", "nobody@test.in"):
        ratelimit.reset(f"login:testclient:{email}")
    ratelimit.reset("forgot:testclient")


def login(client, email, password=PASSWORD, **extra):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password, **extra})


def test_login_success_returns_tokens_and_permissions(client):
    r = login(client, "manager@test.in")
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["user"]["role"] == "manager"
    assert "purchasing.approve" in body["user"]["permissions"]
    assert "users.manage" not in body["user"]["permissions"]


def test_login_wrong_password(client):
    r = login(client, "manager@test.in", "wrong-pass1")
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


def test_login_disabled_user(client, world, db):
    world.users["staff"].is_active = False
    db.commit()
    r = login(client, "staff@test.in")
    assert r.status_code == 401
    assert r.json()["code"] == "account_disabled"


def test_login_rate_limited(client, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_RATE_LIMIT_PER_MINUTE", 3)
    codes = [login(client, "nobody@test.in", "bad-pass1").status_code for _ in range(5)]
    assert codes[:3] == [401, 401, 401]
    assert codes[3] == 429


def test_me_requires_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401 and r.json()["code"] == "token_invalid"


def test_refresh_and_logout_invalidate(client):
    tokens = login(client, "staff@test.in").json()
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get("/api/v1/auth/me", headers=h).status_code == 200
    assert client.post("/api/v1/auth/logout", headers=h).status_code == 200
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401


def test_refresh_rejects_access_token(client):
    tokens = login(client, "staff@test.in").json()
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["access_token"]}).status_code == 401


def test_totp_flow_for_admin(client, auth):
    h = auth("admin")
    setup = client.post("/api/v1/auth/2fa/setup", headers=h)
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert setup.json()["qr_png_base64"]
    assert client.post("/api/v1/auth/2fa/enable", headers=h, json={"code": "000000"}).status_code == 422
    r = client.post("/api/v1/auth/2fa/enable", headers=h, json={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200 and r.json()["totp_enabled"] is True

    r = login(client, "admin@test.in")
    assert r.status_code == 401 and r.json()["code"] == "totp_required"
    r = login(client, "admin@test.in", totp_code="123456")
    assert r.status_code == 401 and r.json()["code"] == "totp_invalid"
    r = login(client, "admin@test.in", totp_code=pyotp.TOTP(secret).now())
    assert r.status_code == 200


def test_totp_only_for_admin(client, auth):
    assert client.post("/api/v1/auth/2fa/setup", headers=auth("staff")).status_code == 403


def test_forgot_and_reset_password_single_use(client):
    r = client.post("/api/v1/auth/forgot-password", json={"email": "staff@test.in"})
    assert r.status_code == 200
    assert client.post("/api/v1/auth/forgot-password", json={"email": "ghost@test.in"}).json() == r.json()
    assert len(mailer.OUTBOX) == 1
    html = mailer.OUTBOX[0].html
    token = html.split("reset-password?token=")[1].split('"')[0]
    r = client.post("/api/v1/auth/reset-password", json={"token": token, "password": "NewPass@2026"})
    assert r.status_code == 200
    again = client.post("/api/v1/auth/reset-password", json={"token": token, "password": "Other@2026x"})
    assert again.status_code == 422
    assert login(client, "staff@test.in", "NewPass@2026").status_code == 200


def test_reset_password_rejects_weak(client):
    r = client.post("/api/v1/auth/reset-password", json={"token": "x", "password": "short"})
    assert r.status_code == 422


def test_change_password_requires_current(client, auth):
    h = auth("manager")
    bad = client.post("/api/v1/auth/change-password", headers=h,
                      json={"current_password": "nope", "new_password": "Brand@New99"})
    assert bad.status_code == 422
    ok = client.post("/api/v1/auth/change-password", headers=h,
                     json={"current_password": PASSWORD, "new_password": "Brand@New99"})
    assert ok.status_code == 200
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401  # old token revoked


def test_update_profile_language(client, auth):
    r = client.patch("/api/v1/auth/me", headers=auth("staff"), json={"language": "mr"})
    assert r.status_code == 200 and r.json()["language"] == "mr"
    assert client.patch("/api/v1/auth/me", headers=auth("staff"), json={"language": "fr"}).status_code == 422
