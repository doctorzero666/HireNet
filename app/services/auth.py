"""
JWT minimal auth — TIER 1.

Demo only. Production gaps explicitly NOT covered here:
  - password hashing uses pbkdf2_hmac(sha256, 200k); switch to bcrypt / argon2
  - JWT_SECRET defaults to a known string; require env var in prod
  - no token revocation list, no refresh tokens, no rate limit on /login
  - no email verification, no 2FA, no password reset

The hash functions are stdlib-only so this module stays cheap to import; the
JWT helpers require PyJWT and the request-scoped helpers require Flask.
"""
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import jsonify, request


# Default >= 32 bytes so PyJWT does not warn about weak HS256 keys in dev.
# This is still a known string — override with HIRENET_JWT_SECRET in prod.
JWT_SECRET = os.getenv(
    "HIRENET_JWT_SECRET",
    "dev-secret-change-me-not-for-production-use",
)
JWT_ALG = "HS256"
JWT_EXP_HOURS = 24
PBKDF2_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    """Return `salt_hex$digest_hex`. Salt is 16 random bytes per password."""
    if not isinstance(password, str) or not password:
        raise ValueError("password must be a non-empty string")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time compare. Returns False for malformed stored values."""
    if not isinstance(password, str) or not isinstance(stored, str):
        return False
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(expected, actual)


def create_token(user_id: str, role: str) -> str:
    """Sign an HS256 JWT carrying sub=user_id, role, exp (24h), iat."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=JWT_EXP_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def verify_token(token: str) -> dict | None:
    """Decode and validate. Returns the payload dict, or None on any failure."""
    if not isinstance(token, str) or not token:
        return None
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError:
        return None


def _read_bearer() -> str | None:
    """Pull the raw token from `Authorization: Bearer <token>`."""
    raw = request.headers.get("Authorization", "")
    if raw.startswith("Bearer "):
        token = raw[7:].strip()
        return token or None
    return None


def get_jwt_user() -> dict | None:
    """Return {id, role} from a valid Bearer token. None when missing/invalid.

    Soft — never raises. Callers that want a 401 wrap with @login_required;
    callers that want fallback behavior (e.g. get_current_identity) check the
    return value themselves.
    """
    tok = _read_bearer()
    if not tok:
        return None
    payload = verify_token(tok)
    if payload is None:
        return None
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        return None
    return {"id": sub, "role": payload.get("role", "")}


def login_required(fn):
    """Strict decorator: 401 if no valid JWT. Sets request.current_user."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_jwt_user()
        if user is None:
            return jsonify({"error": "Authentication required"}), 401
        request.current_user = user
        return fn(*args, **kwargs)
    return wrapper
