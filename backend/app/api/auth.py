"""OAuth 2.0 API endpoints."""

import logging
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.services.oauth_service import (
    OAuthProvider,
    create_session,
    exchange_code_for_token,
    fetch_user_info,
    get_authorization_url,
    get_current_user,
    get_user_from_token,
    revoke_session,
    upsert_user_from_oauth,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory state store (dev only). Replace with Redis/cache in production.
_pending_states: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class LoginResponse(BaseModel):
    authorization_url: str


class CallbackResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


class MeResponse(BaseModel):
    id: str
    email: str | None
    display_name: str | None
    avatar_url: str | None


class LogoutResponse(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/api/auth/login/{provider}", response_model=LoginResponse)
async def login(provider: str, request: Request) -> LoginResponse:
    """Initiate OAuth flow by redirecting the user to the provider."""
    try:
        oauth_provider = OAuthProvider(provider.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    state = secrets.token_urlsafe(32)
    _pending_states[state] = {
        "provider": oauth_provider,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    authorization_url = get_authorization_url(oauth_provider, state)
    return LoginResponse(authorization_url=authorization_url)


@router.get("/api/auth/callback/{provider}", response_model=CallbackResponse)
async def callback(
    provider: str,
    code: str = Query(...),
    state: str = Query(...),
) -> CallbackResponse:
    """OAuth callback: exchange code for token, create/update user, return JWT."""
    try:
        oauth_provider = OAuthProvider(provider.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")

    # Validate state (CSRF protection)
    pending = _pending_states.pop(state, None)
    if pending is None or pending.get("provider") != oauth_provider:
        raise HTTPException(status_code=400, detail="Invalid or expired state")

    # Exchange code for token
    token_data = await exchange_code_for_token(oauth_provider, code)
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="No access token in provider response")

    refresh_token = token_data.get("refresh_token")
    expires_at = token_data.get("expires_at") or token_data.get("expires_in")
    if expires_at and "expires_in" in token_data:
        # expires_in is relative seconds
        import time as _time
        expires_at = int(_time.time()) + int(token_data["expires_in"])

    # Fetch user info from provider
    user_info = await fetch_user_info(oauth_provider, access_token)

    # Upsert local user (tokens encrypted before storage)
    user = upsert_user_from_oauth(
        provider=oauth_provider,
        provider_user_id=user_info["provider_user_id"],
        email=user_info.get("email"),
        name=user_info.get("name"),
        avatar_url=user_info.get("avatar_url"),
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
    )

    # Create session and JWT
    jwt_token = create_session(user.id)

    return CallbackResponse(
        access_token=jwt_token,
        token_type="bearer",
        user={
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "avatar_url": user.avatar_url,
        },
    )


@router.get("/api/auth/me", response_model=MeResponse)
async def get_me(current_user = Depends(get_current_user)) -> MeResponse:
    """Return the current authenticated user."""
    return MeResponse(
        id=current_user.id,
        email=current_user.email,
        display_name=current_user.display_name,
        avatar_url=current_user.avatar_url,
    )


@router.post("/api/auth/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    current_user = Depends(get_current_user),
) -> LogoutResponse:
    """Revoke the current session."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.split(" ", 1)[1].strip() if auth_header.startswith("Bearer ") else ""
    revoked = revoke_session(token)
    return LogoutResponse(message="Logged out" if revoked else "No active session")
