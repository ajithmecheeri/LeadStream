"""Passwords (Argon2id), access tokens (EdDSA JWT) and opaque refresh tokens."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.core.config import get_settings

_hasher = PasswordHasher()  # argon2id with library defaults (t=3, m=64 MiB, p=4)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


@lru_cache
def _keys() -> tuple[str, str]:
    s = get_settings()
    if s.jwt_private_key and s.jwt_public_key:
        return s.jwt_private_key.replace("\\n", "\n"), s.jwt_public_key.replace("\\n", "\n")
    if s.env == "prod":
        raise RuntimeError("JWT_PRIVATE_KEY and JWT_PUBLIC_KEY must be set in prod")
    key = Ed25519PrivateKey.generate()
    priv = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    pub = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return priv, pub


def create_access_token(user_id: UUID, role: str, access_until: datetime | None = None) -> tuple[str, int]:
    s = get_settings()
    now = datetime.now(UTC)
    ttl = s.access_token_minutes * 60
    claims = {
        "sub": str(user_id),
        "role": role,
        # The job seeker's plan or coupon runs until (epoch seconds); checked by require_access.
        "acc": int(access_until.timestamp()) if access_until else None,
        "iss": s.jwt_issuer,
        "iat": now,
        "exp": now + timedelta(seconds=ttl),
    }
    return jwt.encode(claims, _keys()[0], algorithm="EdDSA"), ttl


def decode_access_token(token: str) -> dict:
    s = get_settings()
    return jwt.decode(
        token, _keys()[1], algorithms=["EdDSA"], issuer=s.jwt_issuer, options={"require": ["exp", "sub"]}
    )


def new_refresh_token() -> tuple[str, str]:
    """Return (token sent to the client, sha256 stored in the database)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_inbound_token() -> str:
    # 10 chars of lowercase base32: short enough to type, ~50 bits of entropy.
    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))
