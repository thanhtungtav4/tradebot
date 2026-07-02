"""Security primitives: password hashing, constant-time compare, token hashing."""

import hashlib
import hmac

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_ph = PasswordHasher()


def verify_password(password_hash: str, password: str) -> bool:
    """Verify a plaintext password against an argon2 hash. False on any mismatch."""
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, Exception):  # noqa: BLE001
        return False


def hash_password(password: str) -> str:
    """Argon2 hash for a plaintext password (used by tooling to mint ADMIN_PASSWORD_HASH)."""
    return _ph.hash(password)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def sha256_hex(value: str) -> str:
    """One-way hash for webhook token / body secret matching against stored hashes."""
    return hashlib.sha256(value.encode()).hexdigest()
