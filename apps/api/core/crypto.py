import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    configured = getattr(settings, "FIELD_ENCRYPTION_KEY", "")
    if configured:
        key = configured.encode()
    else:
        digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_value(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt_value(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Encrypted value cannot be decrypted with the configured key") from exc
