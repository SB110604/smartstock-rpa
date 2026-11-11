"""Single source of truth for who may do what (spec section 4). Enforced by `require(...)` on every route."""

from app.models.core import Role

A, M, S, SUP = Role.ADMIN, Role.MANAGER, Role.STAFF, Role.SUPPLIER
INTERNAL = (A, M, S)
MGMT = (A, M)

PERMISSIONS: dict[str, tuple[str, ...]] = {
    # master data
    "products.read": INTERNAL,
    "products.write": MGMT,
    "suppliers.read": MGMT,
    "suppliers.write": MGMT,
    "masters.read": INTERNAL,  # locations, categories
    "masters.write": MGMT,
    # stock
    "stock.read": INTERNAL,
    "stock.move": INTERNAL,  # stock-in / stock-out / counts / transfer request, dispatch, receive
    "stock.adjust": MGMT,
    "stock.approve": MGMT,  # approve transfers, complete counts with adjustments, write-offs, markdowns
    "sales.read": INTERNAL,
    "sales.write": INTERNAL,
    "labels.print": INTERNAL,
    "imports.run": MGMT,
    # purchasing workflow
    "purchasing.read": MGMT,
    "purchasing.write": MGMT,
    "purchasing.approve": MGMT,
    "po.read": INTERNAL,  # staff need POs to receive goods
    "po.write": MGMT,
    "grn.write": INTERNAL,
    "invoice.write": MGMT,
    "match.resolve": MGMT,
    "returns.manage": MGMT,
    "rfq.manage": MGMT,
    # alerts / ai
    "alerts.read": INTERNAL,
    "alerts.write": INTERNAL,
    "insights.read": MGMT,
    "agents.run": MGMT,  # operational agents; the learning agent (retraining) additionally needs models.retrain
    "models.retrain": (A,),
    "simulator.use": MGMT,
    "reports.read": MGMT,
    # administration
    "users.manage": (A,),
    "settings.read": MGMT,
    "settings.manage": (A,),
    "audit.read": (A,),
    # supplier portal
    "portal.use": (SUP,),
    # everyone
    "chat.use": (A, M, S, SUP),
}


def allowed(role: str, permission: str) -> bool:
    return role in PERMISSIONS.get(permission, ())


def permissions_for(role: str) -> list[str]:
    return sorted(p for p, roles in PERMISSIONS.items() if role in roles)
