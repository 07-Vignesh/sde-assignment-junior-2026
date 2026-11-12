import base64
import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

KEY_ENV = "PIPELINE_PII_KEY"
KEY_FILE = Path(".pii_key")


def load_master_key():
    """Secret from env var; otherwise from .pii_key (created on first run)."""
    env = os.environ.get(KEY_ENV)
    if env:
        return env.encode()
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip().encode()
    key = secrets.token_hex(32)
    KEY_FILE.write_text(key)
    return key.encode()


class PiiProtector:
    """Two purposes, two keys derived from one master secret."""

    def __init__(self, master_key):
        self._hmac_key = hmac.new(master_key, b"phone-hash", hashlib.sha256).digest()
        fernet_key = hmac.new(master_key, b"field-encryption", hashlib.sha256).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(fernet_key))

    def phone_hash(self, canonical_phone):
        """Deterministic keyed hash, so the same phone always matches."""
        return hmac.new(self._hmac_key, canonical_phone.encode(),
                        hashlib.sha256).hexdigest()

    def encrypt_json(self, obj):
        return self._fernet.encrypt(json.dumps(obj).encode()).decode()

    def decrypt_json(self, token):
        return json.loads(self._fernet.decrypt(token.encode()))