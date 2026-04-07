"""Encrypted field tests."""

import pytest


class TestEncryption:
    def test_encrypt_decrypt_roundtrip(self, app):
        with app.app_context():
            from app.utils.encryption import encrypt_value, decrypt_value
            plaintext = "123 Main St, Springfield"
            encrypted = encrypt_value(plaintext)
            assert encrypted != plaintext
            decrypted = decrypt_value(encrypted)
            assert decrypted == plaintext

    def test_encrypt_none(self, app):
        with app.app_context():
            from app.utils.encryption import encrypt_value, decrypt_value
            assert encrypt_value(None) is None
            assert decrypt_value(None) is None

    def test_mask_value(self, app):
        with app.app_context():
            from app.utils.encryption import mask_value
            assert mask_value("1234567890", 4) == "******7890"
            assert mask_value(None) is None
