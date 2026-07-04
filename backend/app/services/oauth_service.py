"""OAuth 2.0 service for Google and GitHub login."""

import logging
import os
import time
from typing import Any

import httpx
from jose import jwt
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import (
    SECRET_KEY,
    ALGORITHM,
    create_access_token,
    decode_access_token,
    get_subject_from_token,
    hash_password,
)
from app.models.oauth import OAuthAccount, OAuthProvider, Session, User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider configs (from env)
# ---------------------------------------------------------------------------
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"

FRONTEND_REDIRECT_BASE = os.getenv("FRONTEND_REDIRECT_BASE", "http://localhost:3000")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_provider_config(provider: OAuthProvider) -> dict[str, Any]:
    if provider == OAuthProvider.GOOGLE:
        return {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
        }
    if provider == OAuthProvider.GITHUB:
        return {
            "client_id": GITHUB_CLIENT_ID,
            "client_secret": GITHUB_CLIENT_SECRET,
        }
    raise ValueError(f"Unsupported provider: {provider}")


# ---------------------------------------------------------------------------
# Core OAuth logic
# ---------------------------------------------------------------------------

def get_authorization_url(provider: OAuthProvider, state: str) -> str:
    """Build the provider authorization URL."""
    if provider == OAuthProvider.GOOGLE:
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?client_id={GOOGLE_CLIENT_ID}"
            "&response_type=code"
            f"&redirect_uri={FRONTEND_REDIRECT_BASE}/api/auth/callback/google"
            "&scope=openid email profile"
            f"&state={state}"
            "&access_type=offline"
            "&prompt=consent"
        )
    if provider == OAuthProvider.GITHUB:
        return (
            f"{GITHUB_AUTHORIZE_URL}"
            f"?client_id={GITHUB_CLIENT_ID}"
            f"&redirect_uri={FRONTEND_REDIRECT_BASE}/api/auth/callback/github"
            "&scope=user:email"
            f"&state={state}"
        )
    raise ValueError(f"Unsupported provider: {provider}")


async def exchange_code_for_token(provider: OAuthProvider, code: str) -> dict[str, Any]:
    """Exchange authorization code for access token."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        if provider == OAuthProvider.GOOGLE:
            resp = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "redirect_uri": f"{FRONTEND_REDIRECT_BASE}/api/auth/callback/google",
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()

        if provider == OAuthProvider.GITHUB:
            resp = await client.post(
                GITHUB_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": GITHUB_CLIENT_ID,
                    "client_secret": GITHUB_CLIENT_SECRET,
                    "redirect_uri": f"{FRONTEND_REDIRECT_BASE}/api/auth/callback/github",
                },
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()

        raise ValueError(f"Unsupported provider: {provider}")


async def fetch_google_user_info(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


async def fetch_github_user_info(access_token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            GITHUB_USER_URL,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        user = resp.json()

        # Fetch primary email (may be private)
        email = user.get("email")
        if not email:
            try:
                resp2 = await client.get(
                    GITHUB_EMAILS_URL,
                    headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
                )
                resp2.raise_for_status()
                emails = resp2.json()
                primary = [e for e in emails if e.get("primary")]
                if primary:
                    email = primary[0].get("email")
            except Exception:
                pass

        return {
            "id": str(user["id"]),
            "email": email,
            "name": user.get("name") or user.get("login"),
            "avatar_url": user.get("avatar_url"),
        }


async def fetch_user_info(provider: OAuthProvider, access_token: str) -> dict[str, Any]:
    if provider == OAuthProvider.GOOGLE:
        info = await fetch_google_user_info(access_token)
        return {
            "provider_user_id": info["sub"],
            "email": info.get("email"),
            "name": info.get("name"),
            "avatar_url": info.get("picture"),
        }
    if provider == OAuthProvider.GITHUB:
        return await fetch_github_user_info(access_token)
    raise ValueError(f"Unsupported provider: {provider}")


def upsert_user_from_oauth(
    provider: OAuthProvider,
    provider_user_id: str,
    email: str | None,
    name: str | None,
    avatar_url: str | None,
    access_token: str | None = None,
    refresh_token: str | None = None,
    expires_at: int | None = None,
) -> User:
    """Find or create a local user from OAuth info, link the OAuth account."""
    db = SessionLocal()
    try:
        # Find existing OAuth account
        stmt = (
            select(OAuthAccount)
            .where(
                OAuthAccount.provider == provider,
                OAuthAccount.provider_user_id == str(provider_user_id),
            )
            .limit(1)
        )
        oauth_account = db.execute(stmt).scalar_one_or_none()

        if oauth_account:
            user = db.execute(select(User).where(User.id == oauth_account.user_id).limit(1)).scalar_one()
            # Update linkage
            oauth_account.access_token = access_token or oauth_account.access_token
            oauth_account.refresh_token = refresh_token or oauth_account.refresh_token
            oauth_account.expires_at = expires_at or oauth_account.expires_at
            user.display_name = name or user.display_name
            user.avatar_url = avatar_url or user.avatar_url
            user.last_login_at = time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            # Create new user
            user = User(
                email=email,
                display_name=name,
                avatar_url=avatar_url,
            )
            db.add(user)
            db.flush()

            oauth_account = OAuthAccount(
                user_id=user.id,
                provider=provider,
                provider_user_id=str(provider_user_id),
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=expires_at,
            )
            db.add(oauth_account)

        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


def create_session(user_id: str, expires_in: int = 7 * 24 * 3600) -> str:
    """Create a session and return a JWT access token."""
    db = SessionLocal()
    try:
        token = create_access_token(subject=user_id)
        jti = str(time.time())  # simple unique id; in prod use UUID
        session = Session(
            user_id=user_id,
            token_jti=jti,
            expires_at=int(time.time()) + expires_in,
        )
        db.add(session)
        db.commit()
        return token
    finally:
        db.close()


def revoke_session(token: str) -> bool:
    """Revoke a session by JTI."""
    payload = decode_access_token(token)
    if payload is None:
        return False
    jti = payload.get("jti")
    if not jti:
        return False
    db = SessionLocal()
    try:
        session = db.execute(
            select(Session).where(Session.token_jti == jti).limit(1)
        ).scalar_one_or_none()
        if session and session.revoked_at is None:
            session.revoked_at = time.strftime("%Y-%m-%d %H:%M:%S")
            db.commit()
            return True
        return False
    finally:
        db.close()


def get_user_from_token(token: str) -> User | None:
    """Look up the user associated with a JWT token."""
    subject = get_subject_from_token(token)
    if subject is None:
        return None
    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.id == subject).limit(1)).scalar_one_or_none()
        return user
    finally:
        db.close()
