import pytest

from app.core.permissions import PERMISSIONS, allowed, permissions_for

MANAGER_ROUTES = [
    ("post", "/api/v1/products", {"sku": "X1", "name": "Thing", "cost_price": 1, "selling_price": 2}),
    ("post", "/api/v1/suppliers", {"name": "Some Supplier"}),
    ("get", "/api/v1/suppliers", None),
    ("post", "/api/v1/categories", {"name": "Snacks"}),
    ("post", "/api/v1/stock/adjust", {"batch_id": 1, "new_qty": 1, "reason": "fix count"}),
    ("post", "/api/v1/stock/write-off", {"batch_id": 1, "reason": "damaged"}),
    ("get", "/api/v1/imports/types", None),
    ("get", "/api/v1/settings", None),
]
ADMIN_ROUTES = [
    ("get", "/api/v1/users", None),
    ("post", "/api/v1/users", {"name": "X", "email": "x@x.in", "role": "staff", "password": "Abcdef12"}),
    ("put", "/api/v1/settings", {"ordering_cost_S": 600}),
    ("get", "/api/v1/audit", None),
    ("get", "/api/v1/settings/api-keys", None),
]
INTERNAL_ROUTES = [
    ("get", "/api/v1/products", None),
    ("get", "/api/v1/stock/batches", None),
    ("get", "/api/v1/sales", None),
    ("post", "/api/v1/stock/in", {"product_id": 1, "location_id": 1, "qty": 1}),
    ("get", "/api/v1/locations", None),
]


def call(client, method, url, body, headers):
    return getattr(client, method)(url, headers=headers, **({"json": body} if body is not None else {}))


@pytest.mark.parametrize(("method", "url", "body"), MANAGER_ROUTES + ADMIN_ROUTES)
def test_staff_forbidden_on_manager_and_admin_routes(client, auth, method, url, body):
    r = call(client, method, url, body, auth("staff"))
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "forbidden"


@pytest.mark.parametrize(("method", "url", "body"), MANAGER_ROUTES + ADMIN_ROUTES + INTERNAL_ROUTES)
def test_supplier_forbidden_on_internal_routes(client, auth, method, url, body):
    assert call(client, method, url, body, auth("supplier")).status_code == 403


@pytest.mark.parametrize(("method", "url", "body"), ADMIN_ROUTES)
def test_manager_forbidden_on_admin_routes(client, auth, method, url, body):
    assert call(client, method, url, body, auth("manager")).status_code == 403


def test_admin_allowed_everywhere(client, auth):
    for method, url, _ in [r for r in ADMIN_ROUTES if r[0] == "get"]:
        assert call(client, method, url, None, auth("admin")).status_code == 200


def test_anonymous_is_401(client, world):
    assert client.get("/api/v1/products").status_code == 401


def test_permission_matrix_shape():
    assert allowed("admin", "users.manage") and not allowed("manager", "users.manage")
    assert allowed("staff", "grn.write") and not allowed("staff", "purchasing.approve")
    assert permissions_for("supplier") == sorted(["portal.use", "chat.use"])
    assert all(isinstance(v, tuple) and v for v in PERMISSIONS.values())
