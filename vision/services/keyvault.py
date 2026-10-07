"""Encryption for the few secrets VISION has to keep on disk (portal passwords, browser sessions).

One Fernet key, made on first use and kept in the macOS Keychain (service "vision-visa-watcher"), never in the
repo, .env or the database. The database and the session files are useless without it.
"""

from __future__ import annotations

from cryptography.fernet import Fernet

SERVICE, NAME = "vision-visa-watcher", "fernet-key"


def _key() -> bytes:
    import keyring
    key = keyring.get_password(SERVICE, NAME)
    if not key:
        key = Fernet.generate_key().decode()
        keyring.set_password(SERVICE, NAME, key)
    return key.encode()


def seal(data: str | bytes) -> str:
    return Fernet(_key()).encrypt(data.encode() if isinstance(data, str) else data).decode()


def unseal(token: str) -> bytes:
    return Fernet(_key()).decrypt(token.encode())
