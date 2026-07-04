"""Security utilities: JWT encode/decode, password hashing."""

import hashlib
import hmac
import os
import time
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

logger = __name__

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_SECONDS = 7 * 24 * 3600  # 7 days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def create_access_token(
    subject: str,
    expires_delta: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT access token."""
    expire = int(time.time()) + (expires_delta or ACCESS_TOKEN_EXPIRE_SECONDS)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "iat": int(time.time()),
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return token


def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and validate a JWT token. Returns None on failure."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def get_subject_from_token(token: str) -> str | None:
    """Extract the subject claim from a JWT token."""
    payload = decode_access_token(token)
    if payload is None:
        return None
    return payload.get("sub")
