"""OAuth / auth models."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.database import Base


class OAuthProvider(str, enum.Enum):
    GOOGLE = "google"
    GITHUB = "github"


class User(Base):
    """Local user record linked to one or more OAuth accounts."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(255))
    avatar_url: Mapped[Optional[str]] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class OAuthAccount(Base):
    """OAuth provider linkage for a user."""

    __tablename__ = "oauth_accounts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    provider: Mapped[OAuthProvider] = mapped_column(Enum(OAuthProvider), index=True)
    provider_user_id: Mapped[str] = mapped_column(String(255), index=True)
    access_token: Mapped[Optional[str]] = mapped_column(String(1024))
    refresh_token: Mapped[Optional[str]] = mapped_column(String(1024))
    expires_at: Mapped[Optional[int]] = mapped_column()  # unix timestamp
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    """Server-side session for authenticated users (optional, for revocation)."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    token_jti: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    expires_at: Mapped[int] = mapped_column()  # unix timestamp
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
