"""Configuración de integraciones (SMTP, webhook). Valores de la BD (editables en la app, secretos cifrados
con Fernet) con respaldo en las variables de entorno."""

from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.ops import IntegrationSetting

KEYS = {
    "smtp_host": False, "smtp_port": False, "smtp_user": False, "smtp_password": True, "smtp_from": False,
    "alert_email_to": False, "webhook_url": True, "webhook_kind": False, "telegram_chat_id": False,
}  # clave -> ¿es secreto?  # fmt: skip
WEBHOOK_KINDS = ("generic", "slack", "teams", "telegram")


def _fernet() -> Fernet:
    return Fernet(get_settings().fernet_key.get_secret_value().encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return ""  # clave de cifrado cambiada: se trata como no configurado


@dataclass
class Integrations:
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    alert_email_to: list[str]
    webhook_url: str
    webhook_kind: str
    telegram_chat_id: str


def stored(db: Session) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in db.execute(select(IntegrationSetting)).scalars():
        out[row.key] = decrypt(row.value_encrypted) if row.is_secret else row.value_encrypted
    return out


def load(db: Session) -> Integrations:
    env = get_settings()
    db_vals = stored(db)

    def pick(key: str, default: str) -> str:
        return db_vals[key] if key in db_vals else default

    try:
        port = int(pick("smtp_port", str(env.smtp_port)))
    except ValueError:
        port = env.smtp_port
    recipients = pick("alert_email_to", env.alert_email_to)
    return Integrations(
        smtp_host=pick("smtp_host", env.smtp_host),
        smtp_port=port,
        smtp_user=pick("smtp_user", env.smtp_user),
        smtp_password=pick("smtp_password", env.smtp_password.get_secret_value()),
        smtp_from=pick("smtp_from", env.smtp_from),
        alert_email_to=[r.strip() for r in recipients.split(",") if r.strip()],
        webhook_url=pick("webhook_url", env.alert_webhook_url.get_secret_value()),
        webhook_kind=pick("webhook_kind", "generic"),
        telegram_chat_id=pick("telegram_chat_id", ""),
    )


def save(db: Session, values: dict[str, str]) -> list[str]:
    """Guarda solo las claves conocidas; un secreto vacío o enmascarado no sobrescribe el existente."""
    changed: list[str] = []
    for key, value in values.items():
        if key not in KEYS:
            continue
        secret = KEYS[key]
        if secret and value in ("", "********"):
            continue
        row = db.get(IntegrationSetting, key) or IntegrationSetting(key=key, is_secret=secret, value_encrypted="")
        row.value_encrypted = encrypt(value) if secret else value
        row.is_secret = secret
        db.add(row)
        changed.append(key)
    db.flush()
    return changed


def masked(db: Session) -> dict[str, str]:
    """Vista para la UI: los secretos nunca salen; solo se indica si están definidos."""
    cfg = load(db)
    return {
        "smtp_host": cfg.smtp_host, "smtp_port": str(cfg.smtp_port), "smtp_user": cfg.smtp_user,
        "smtp_password": "********" if cfg.smtp_password else "", "smtp_from": cfg.smtp_from,
        "alert_email_to": ", ".join(cfg.alert_email_to),
        "webhook_url": "********" if cfg.webhook_url else "", "webhook_kind": cfg.webhook_kind,
        "telegram_chat_id": cfg.telegram_chat_id,
    }  # fmt: skip
