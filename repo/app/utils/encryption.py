"""Reusable encrypted field abstraction using Fernet symmetric encryption."""

import base64
from cryptography.fernet import Fernet
from flask import current_app


def _get_fernet():
    key = current_app.config.get("FIELD_ENCRYPTION_KEY", "")
    if not key:
        raw_key = current_app.config["SECRET_KEY"].encode()[:32].ljust(32, b"\0")
        key = base64.urlsafe_b64encode(raw_key).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    f = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext: str | None) -> str | None:
    if ciphertext is None:
        return None
    f = _get_fernet()
    return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def mask_value(value: str | None, visible_chars: int = 4) -> str | None:
    if value is None:
        return None
    if len(value) <= visible_chars:
        return "*" * len(value)
    return "*" * (len(value) - visible_chars) + value[-visible_chars:]
