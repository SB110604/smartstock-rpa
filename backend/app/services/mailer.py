"""SMTP email (Mailpit in development). In APP_ENV=test messages are captured in OUTBOX instead of sent."""

import base64
import logging
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid

from app.core.config import settings
from app.core.logging import log_ctx

logger = logging.getLogger("app.mailer")


@dataclass
class SentMail:
    to: list[str]
    subject: str
    html: str
    attachments: list[tuple[str, bytes, str]] = field(default_factory=list)


OUTBOX: list[SentMail] = []


def send_email(
    to: str | list[str],
    subject: str,
    html: str,
    text: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> bool:
    """Send an email; returns False (and logs) on failure so callers never crash on SMTP problems."""
    recipients = [to] if isinstance(to, str) else [r for r in to if r]
    if not recipients:
        return False
    attachments = attachments or []
    if settings.is_test:
        OUTBOX.append(SentMail(recipients, subject, html, attachments))
        return True
    if settings.EMAIL_ASYNC:
        try:
            from app.tasks.celery_app import celery_app

            celery_app.send_task("jobs.send_email", kwargs={
                "to": recipients, "subject": subject, "html": html, "text": text,
                "attachments": [(n, base64.b64encode(d).decode(), m) for n, d, m in attachments]})
            return True
        except Exception as exc:  # broker unavailable → deliver now
            logger.warning("email queue unavailable, sending inline", extra=log_ctx(error=str(exc)))
    return deliver(recipients, subject, html, text, attachments)


def deliver(recipients: list[str], subject: str, html: str, text: str | None,
            attachments: list[tuple[str, bytes, str]]) -> bool:
    """Synchronous SMTP delivery (used by the Celery worker and as fallback)."""
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain="smartstock.local")
    msg.set_content(text or "This message requires an HTML capable email client.")
    msg.add_alternative(html, subtype="html")
    for filename, data, mime in attachments:
        maintype, subtype = mime.split("/", 1)
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
            if settings.SMTP_TLS:
                smtp.starttls()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.send_message(msg)
        logger.info("email sent", extra=log_ctx(to=recipients, subject=subject))
        return True
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning("email failed", extra=log_ctx(to=recipients, subject=subject, error=str(exc)))
        return False


def layout(title: str, body_html: str, business_name: str = "SmartStock RPA") -> str:
    """Consistent, inline-styled HTML wrapper for every outgoing email."""
    return f"""<!doctype html><html><body style="margin:0;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:24px 12px">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:10px;overflow:hidden">
<tr><td style="background:#047857;color:#fff;padding:16px 20px;font-size:18px;font-weight:bold">{business_name}</td></tr>
<tr><td style="padding:20px;color:#0f172a;font-size:14px;line-height:1.5">
<h2 style="margin:0 0 12px;font-size:18px">{title}</h2>{body_html}</td></tr>
<tr><td style="padding:12px 20px;color:#64748b;font-size:12px;border-top:1px solid #e2e8f0">
Sent automatically by SmartStock RPA.</td></tr></table></td></tr></table></body></html>"""


def button(url: str, label: str, color: str = "#047857") -> str:
    return (
        f'<a href="{url}" style="display:inline-block;background:{color};color:#fff;text-decoration:none;'
        f'padding:10px 18px;border-radius:6px;font-weight:bold;margin:4px 8px 4px 0">{label}</a>'
    )
