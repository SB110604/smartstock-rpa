from fastapi import APIRouter

from app.api.v1 import (
    alerts,
    auth,
    health,
    insights,
    intelligence,
    masters,
    operations,
    orders,
    portal,
    products,
    purchasing,
    reports,
    settings,
    stock,
    suppliers,
    tools,
    users,
)

api_router = APIRouter(prefix="/api/v1")
for module in (health, auth, users, settings, masters, products, suppliers, stock, operations, tools, purchasing, orders,
               portal, alerts, insights, intelligence, reports):
    api_router.include_router(module.router)
