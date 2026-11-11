"""Notifications: in-app rows always; email and Telegram per business settings and configuration."""

import logging
from collections.abc import Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings as env
from app.core.logging import log_ctx
from app.core.timeutil import now
from app.models.ai import Notification
from app.models.core import User
from app.services import mailer
from app.services import settings as settings_svc

logger = logging.getLogger("app.notify")
TELEGRAM_SENT: list[tuple[str, str]] = []  # test capture (APP_ENV=test)


def users_with_roles(db: Session, roles: Iterable[str]) -> list[User]:
    return list(db.scalars(select(User).where(User.role.in_(list(roles)), User.is_active.is_(True)).order_by(User.id)))


def send_telegram(chat_id: str, text: str) -> bool:
    if not env.telegram_enabled or not chat_id:
        return False
    if env.is_test:
        TELEGRAM_SENT.append((chat_id, text))
        return True
    try:
        r = httpx.post(f"https://api.telegram.org/bot{env.TELEGRAM_BOT_TOKEN}/sendMessage",
                       json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True},
                       timeout=10)
        return r.status_code == 200
    except httpx.HTTPError as exc:
        logger.warning("telegram failed", extra=log_ctx(error=str(exc)))
        return False


def notify(
    db: Session,
    users: Iterable[User],
    title: str,
    body: str,
    *,
    link: str | None = None,
    alert_id: int | None = None,
    email_html: str | None = None,
    telegram_text: str | None = None,
    channels: set[str] | None = None,
) -> int:
    """Create in-app notifications and fan out to email/Telegram. Returns number of recipients."""
    enabled = settings_svc.get(db, "notification_channels")
    wanted = channels or {"in_app", "email", "telegram"}
    business = settings_svc.get(db, "business")["name"]
    count = 0
    for u in {u.id: u for u in users}.values():
        db.add(Notification(user_id=u.id, channel="in_app", alert_id=alert_id, title=title, body=body, link=link,
                            sent_at=now()))
        if "email" in wanted and enabled.get("email", True) and u.email:
            html = email_html or mailer.layout(title, f"<p>{body}</p>" + (
                mailer.button(f"{env.FRONTEND_URL}{link}", "Open in SmartStock") if link else ""), business)
            ok = mailer.send_email(u.email, title, html, text=body)
            db.add(Notification(user_id=u.id, channel="email", alert_id=alert_id, title=title, body=body, link=link,
                                sent_at=now() if ok else None, error=None if ok else "send failed"))
        if "telegram" in wanted and enabled.get("telegram") and u.telegram_chat_id and env.telegram_enabled:
            ok = send_telegram(u.telegram_chat_id, telegram_text or f"<b>{title}</b>\n{body}")
            db.add(Notification(user_id=u.id, channel="telegram", alert_id=alert_id, title=title, body=body,
                                link=link, sent_at=now() if ok else None, error=None if ok else "send failed"))
        count += 1
    db.flush()
    return count


def notify_roles(db: Session, roles: Iterable[str], title: str, body: str, **kw: object) -> int:
    return notify(db, users_with_roles(db, roles), title, body, **kw)  # type: ignore[arg-type]
