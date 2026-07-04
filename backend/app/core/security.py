"""Security utilities: JWT encode/decode, password hashing, token encryption."""

import hashlib
import hmac
import os
import time
from typing import Any

from cryptography.fernet import Fernet
from jose import JWTError, jwt
from passlib.context import CryptContext

logger = __name__

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_SECONDS = 7 * 24 * 3600  # 7 days

# Token encryption key for OAuth access/refresh tokens (Tier A compliance)
# Must be 32 url-safe base64-encoded bytes
_TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY")
if not _TOKEN_ENCRYPTION_KEY:
    # Generate a persistent key from SECRET_KEY for dev; in prod set explicitly
    _TOKEN_ENCRYPTION_KEY = (
        hashlib.sha256(SECRET_KEY.encode()).digest()[:32]
    )
    import base64
    _TOKEN_ENCRYPTION_KEY = base64.urlsafe_b64encode(_TOKEN_ENCRYPTION_KEY).decode()

_fernet = Fernet(_TOKEN_ENCRYPTION_KEY.encode() if isinstance(_TOKEN_ENCRYPTION_KEY, str) else _TOKEN_ENCRYPTION_KEY)

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


# ---------------------------------------------------------------------------
# Token encryption (Tier A compliance for OAuth tokens)
# ---------------------------------------------------------------------------

def encrypt_token(plaintext: str | None) -> str | None:
    """Encrypt an OAuth token for storage. Returns None if input is None."""
    if not plaintext:
        return None
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str | None) -> str | None:
    """Decrypt an OAuth token from storage. Returns None if input is None."""
    if not ciphertext:
        return None
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except Exception:
        logger.error("Failed to decrypt token")
        return None
