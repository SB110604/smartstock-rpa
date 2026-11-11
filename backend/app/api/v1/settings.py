from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import llm
from app.core.config import settings as env
from app.core.deps import DB, CurrentUser, require
from app.core.errors import NotFound
from app.core.security import hash_token, new_token
from app.models.core import ApiKey, User
from app.services import audit, courier, ocr
from app.services import settings as settings_svc

router = APIRouter(prefix="/settings", tags=["settings"])
Admin = Annotated[User, Depends(require("settings.manage"))]
Reader = Annotated[User, Depends(require("settings.read"))]


def features() -> dict[str, Any]:
    return {
        "llm_provider": env.LLM_PROVIDER,
        "telegram": env.telegram_enabled,
        "imap": env.imap_enabled,
        "courier_provider": courier.provider().name,
        "llm": llm.status(),
        "ocr": ocr.available(),
    }


@router.get("/public")
def public_settings(user: CurrentUser, db: DB) -> dict[str, Any]:
    """Non-sensitive values every logged-in user needs (business header, feature flags)."""
    all_ = settings_svc.get_all(db)
    return {
        "business": all_["business"],
        "features": features(),
        "expiry_thresholds": all_["expiry_thresholds"],
    }


@router.get("")
def get_settings(user: Reader, db: DB) -> dict[str, Any]:
    return {"values": settings_svc.get_all(db), "features": features()}


@router.put("")
def update_settings(body: dict[str, Any], admin: Admin, db: DB) -> dict[str, Any]:
    return {"values": settings_svc.set_many(db, body, admin), "features": features()}


class ApiKeyIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    location_id: int | None = None


@router.get("/api-keys")
def list_api_keys(admin: Admin, db: DB) -> list[dict[str, Any]]:
    keys = db.scalars(select(ApiKey).order_by(ApiKey.id.desc()))
    return [
        {
            "id": k.id,
            "name": k.name,
            "prefix": k.prefix,
            "location_id": k.location_id,
            "is_active": k.is_active,
            "last_used_at": k.last_used_at,
            "created_at": k.created_at,
        }
        for k in keys
    ]


@router.post("/api-keys", status_code=201)
def create_api_key(body: ApiKeyIn, admin: Admin, db: DB) -> dict[str, Any]:
    raw, _ = new_token()
    key = f"ssk_{raw}"
    rec = ApiKey(
        name=body.name,
        prefix=key[:10],
        key_hash=hash_token(key),
        location_id=body.location_id,
        created_by=admin.id,
    )
    db.add(rec)
    audit.created(db, admin, rec)
    db.commit()
    return {
        "id": rec.id,
        "name": rec.name,
        "prefix": rec.prefix,
        "key": key,
        "note": "Copy this key now — it is shown only once.",
    }


@router.delete("/api-keys/{key_id}")
def revoke_api_key(key_id: int, admin: Admin, db: DB) -> dict[str, str]:
    rec = db.get(ApiKey, key_id)
    if not rec:
        raise NotFound("API key not found")
    audit.apply_update(db, admin, rec, {"is_active": False})
    db.commit()
    return {"detail": "API key revoked"}
