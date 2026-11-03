"""Canales de notificación: correo SMTP y webhook (Slack, Teams, Telegram o genérico)."""

import smtplib
from email.message import EmailMessage
from typing import Any

import httpx

from app.services.integrations import Integrations

TIMEOUT = 15


class NotifyError(RuntimeError):
    pass


def send_email(cfg: Integrations, subject: str, body: str) -> None:
    if not cfg.alert_email_to:
        raise NotifyError("Sin destinatarios de correo configurados")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.smtp_from
    msg["To"] = ", ".join(cfg.alert_email_to)
    msg.set_content(body)  # texto plano: el contenido de fuentes externas no se interpreta como HTML
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=TIMEOUT) as smtp:
            if cfg.smtp_user:
                smtp.starttls()
                smtp.login(cfg.smtp_user, cfg.smtp_password)
            smtp.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        raise NotifyError(f"SMTP: {e.__class__.__name__}: {e}"[:300]) from None


def webhook_payload(cfg: Integrations, text: str) -> dict[str, Any]:
    if cfg.webhook_kind == "telegram":
        return {"chat_id": cfg.telegram_chat_id, "text": text[:4000]}
    return {"text": text[:4000]}  # Slack, Teams (webhook de flujo) y genérico aceptan "text"


def send_webhook(cfg: Integrations, text: str) -> None:
    if not cfg.webhook_url:
        raise NotifyError("Webhook no configurado")
    if cfg.webhook_kind == "telegram" and not cfg.telegram_chat_id:
        raise NotifyError("Telegram requiere chat_id")
    try:
        r = httpx.post(cfg.webhook_url, json=webhook_payload(cfg, text), timeout=TIMEOUT)
        r.raise_for_status()
    except httpx.HTTPError as e:
        # no se incluye la URL: puede contener el token del bot
        raise NotifyError(f"Webhook: {e.__class__.__name__}") from None
