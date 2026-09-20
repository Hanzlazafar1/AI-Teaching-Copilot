"""SQLAlchemy ORM models for Brady AI Writing Co-Pilot.

Implements the Hybrid Relational + JSON schema:
- Relational tables for Users, Conversations, Turns, RefreshTokens
- Indexed fields for fast querying, filtering, and tenant isolation
- Native JSON columns for structured lesson payloads (MiniLessons, UnitPlans),
  retrieval groundings, intents, and multi-turn session handshakes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy declarative models."""
    pass


class UserModel(Base):
    """Registered teacher accounts and classroom preferences."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    school_district: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    default_grade: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    default_mode: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    custom_instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    conversations: Mapped[list["ConversationModel"]] = relationship(
        "ConversationModel", back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshTokenModel"]] = relationship(
        "RefreshTokenModel", back_populates="user", cascade="all, delete-orphan"
    )


class ConversationModel(Base):
    """A chat thread containing an append-only log of turns."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Persists SessionHandshakes (pending lesson sequences, active offers, etc.)
    handshakes: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True, nullable=False
    )

    user: Mapped[Optional[UserModel]] = relationship(
        "UserModel", back_populates="conversations"
    )
    turns: Mapped[list["TurnModel"]] = relationship(
        "TurnModel",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="TurnModel.turn_index",
    )


class TurnModel(Base):
    """An individual message turn (user or assistant) within a conversation."""

    __tablename__ = "turns"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" or "assistant"
    text: Mapped[str] = mapped_column(Text, nullable=False)
    request_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    quality: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    lesson_title: Mapped[Optional[str]] = mapped_column(
        String(255), index=True, nullable=True
    )
    structured: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    grounding: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    intent: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    offered_skills: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    clarifying_for: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    conversation: Mapped[ConversationModel] = relationship(
        "ConversationModel", back_populates="turns"
    )


class RefreshTokenModel(Base):
    """Issued refresh tokens for secure session continuity and revocation."""

    __tablename__ = "refresh_tokens"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    user: Mapped[UserModel] = relationship("UserModel", back_populates="refresh_tokens")
