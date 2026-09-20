"""Repository layer for Brady AI Writing Co-Pilot.

Provides clean CRUD operations bridging SQLAlchemy models to domain schemas
(Conversation, Turn, SessionHandshakes, TurnIntent, ChunkRef).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import ConversationModel, TurnModel, UserModel
from schemas import (
    ChunkRef,
    Conversation,
    Quality,
    RequestType,
    Role,
    SessionHandshakes,
    Turn,
    TurnIntent,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# User Repository
# ----------------------------------------------------------------------


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    hashed_password: str,
    full_name: Optional[str] = None,
    school_district: Optional[str] = None,
    default_grade: Optional[str] = None,
    default_mode: Optional[str] = None,
    custom_instructions: Optional[str] = None,
) -> UserModel:
    """Create and persist a new teacher account."""
    user = UserModel(
        id=str(uuid.uuid4()),
        email=email.strip().lower(),
        hashed_password=hashed_password,
        full_name=full_name,
        school_district=school_district,
        default_grade=default_grade,
        default_mode=default_mode,
        custom_instructions=custom_instructions,
    )
    session.add(user)
    await session.flush()
    return user


async def get_user_by_email(session: AsyncSession, email: str) -> Optional[UserModel]:
    """Look up a user by email (case-insensitive)."""
    stmt = select(UserModel).where(UserModel.email == email.strip().lower())
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: str) -> Optional[UserModel]:
    """Look up a user by primary key ID."""
    stmt = select(UserModel).where(UserModel.id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_user_preferences(
    session: AsyncSession,
    user_id: str,
    *,
    full_name: Optional[str] = None,
    school_district: Optional[str] = None,
    default_grade: Optional[str] = None,
    default_mode: Optional[str] = None,
    custom_instructions: Optional[str] = None,
) -> Optional[UserModel]:
    """Update teacher classroom preferences."""
    user = await get_user_by_id(session, user_id)
    if not user:
        return None

    if full_name is not None:
        user.full_name = full_name
    if school_district is not None:
        user.school_district = school_district
    if default_grade is not None:
        user.default_grade = default_grade
    if default_mode is not None:
        user.default_mode = default_mode
    if custom_instructions is not None:
        user.custom_instructions = custom_instructions

    user.updated_at = datetime.utcnow()
    await session.flush()
    return user


# ----------------------------------------------------------------------
# Conversation & Turn Repository
# ----------------------------------------------------------------------


def _turn_model_to_domain(m: TurnModel) -> Turn:
    """Convert database TurnModel to domain Turn schema."""
    intent_obj: Optional[TurnIntent] = None
    if m.intent:
        try:
            intent_obj = TurnIntent.model_validate(m.intent)
        except Exception as e:
            logger.warning("Failed to deserialize TurnIntent for turn %s: %s", m.id, e)

    grounding_objs: list[ChunkRef] = []
    if m.grounding:
        for g in m.grounding:
            try:
                grounding_objs.append(ChunkRef.model_validate(g))
            except Exception as e:
                logger.warning("Failed to deserialize ChunkRef: %s", e)

    role_val = Role(m.role) if m.role in (Role.USER.value, Role.ASSISTANT.value) else Role.USER
    quality_val = (
        Quality(m.quality)
        if m.quality in (Quality.VALID.value, Quality.LOW.value, Quality.FAILED.value)
        else Quality.VALID
    )
    clarifying_for_val = RequestType(m.clarifying_for) if m.clarifying_for else None

    return Turn(
        index=m.turn_index,
        role=role_val,
        text=m.text,
        structured=m.structured,
        offered_skills=m.offered_skills or [],
        clarifying_for=clarifying_for_val,
        grounding=grounding_objs,
        intent=intent_obj,
        quality=quality_val,
        created_at=m.created_at,
    )


async def load_conversation(
    session: AsyncSession,
    session_id: str,
    user_id: Optional[str] = None,
) -> tuple[Conversation, SessionHandshakes]:
    """Load or initialize Conversation and SessionHandshakes from DB.

    Matches ConversationStore.load() interface.
    """
    stmt = (
        select(ConversationModel)
        .options(selectinload(ConversationModel.turns))
        .where(ConversationModel.id == session_id)
    )
    result = await session.execute(stmt)
    conv_model = result.scalar_one_or_none()

    if conv_model is None:
        conv_model = ConversationModel(
            id=session_id,
            user_id=user_id,
            title="New Conversation",
            handshakes=None,
        )
        session.add(conv_model)
        await session.flush()
        domain_conv = Conversation(session_id=session_id, user_id=user_id, turns=[])
        domain_hs = SessionHandshakes()
        return domain_conv, domain_hs

    # Update user ownership if previously anonymous
    if user_id and conv_model.user_id is None:
        conv_model.user_id = user_id

    # Reconstruct domain turns
    domain_turns = [_turn_model_to_domain(tm) for tm in conv_model.turns]
    domain_conv = Conversation(
        session_id=session_id,
        user_id=conv_model.user_id,
        turns=domain_turns,
    )

    # Reconstruct domain handshakes
    domain_hs = SessionHandshakes()
    if conv_model.handshakes:
        try:
            domain_hs = SessionHandshakes.model_validate(conv_model.handshakes)
        except Exception as e:
            logger.warning("Failed to deserialize SessionHandshakes for session %s: %s", session_id, e)

    return domain_conv, domain_hs


async def save_conversation(
    session: AsyncSession,
    session_id: str,
    conversation: Conversation,
    handshakes: SessionHandshakes,
    title: Optional[str] = None,
) -> None:
    """Persist conversation turns and handshakes to DB.

    Matches ConversationStore.save() contract with durability.
    """
    stmt = (
        select(ConversationModel)
        .options(selectinload(ConversationModel.turns))
        .where(ConversationModel.id == session_id)
    )
    result = await session.execute(stmt)
    conv_model = result.scalar_one_or_none()

    if conv_model is None:
        conv_model = ConversationModel(
            id=session_id,
            user_id=conversation.user_id,
            title=title or "New Conversation",
        )
        session.add(conv_model)

    if title:
        conv_model.title = title

    conv_model.handshakes = handshakes.model_dump(mode="json")
    conv_model.updated_at = datetime.utcnow()

    # Sync turns: identify existing turn indices
    existing_indices = {t.turn_index for t in conv_model.turns}

    for turn in conversation.turns:
        if turn.index not in existing_indices:
            # Extract lesson title if structured
            lesson_title = None
            if isinstance(turn.structured, dict):
                lesson_title = turn.structured.get("lesson_title") or turn.structured.get("skill_focus")

            turn_model = TurnModel(
                id=str(uuid.uuid4()),
                conversation_id=session_id,
                turn_index=turn.index,
                role=turn.role.value,
                text=turn.text,
                request_type=turn.intent.request_type.value if turn.intent else None,
                quality=turn.quality.value,
                lesson_title=lesson_title,
                structured=turn.structured,
                grounding=[g.model_dump(mode="json") for g in turn.grounding],
                intent=turn.intent.model_dump(mode="json") if turn.intent else None,
                offered_skills=turn.offered_skills,
                clarifying_for=turn.clarifying_for.value if turn.clarifying_for else None,
                created_at=turn.created_at,
            )
            session.add(turn_model)

    await session.flush()


async def list_conversations(
    session: AsyncSession,
    user_id: str,
    *,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    """Fetch user's conversation threads for sidebar display.

    Sorted with pinned first, then updated_at descending.
    """
    stmt = (
        select(ConversationModel)
        .options(selectinload(ConversationModel.turns))
        .where(ConversationModel.user_id == user_id)
    )
    if not include_archived:
        stmt = stmt.where(ConversationModel.is_archived.is_(False))

    stmt = stmt.order_by(
        ConversationModel.is_pinned.desc(),
        ConversationModel.updated_at.desc(),
    )
    result = await session.execute(stmt)
    convs = result.scalars().all()

    items = []
    for c in convs:
        last_message = c.turns[-1].text[:100] if c.turns else ""
        items.append({
            "id": c.id,
            "title": c.title or "New Conversation",
            "is_pinned": c.is_pinned,
            "is_archived": c.is_archived,
            "turn_count": len(c.turns),
            "last_message": last_message,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
        })
    return items


async def update_conversation_meta(
    session: AsyncSession,
    session_id: str,
    user_id: str,
    *,
    title: Optional[str] = None,
    is_pinned: Optional[bool] = None,
    is_archived: Optional[bool] = None,
) -> Optional[ConversationModel]:
    """Rename, pin, or archive a conversation thread."""
    stmt = select(ConversationModel).where(
        ConversationModel.id == session_id,
        ConversationModel.user_id == user_id,
    )
    result = await session.execute(stmt)
    conv = result.scalar_one_or_none()
    if not conv:
        return None

    if title is not None:
        conv.title = title
    if is_pinned is not None:
        conv.is_pinned = is_pinned
    if is_archived is not None:
        conv.is_archived = is_archived

    conv.updated_at = datetime.utcnow()
    await session.flush()
    return conv


async def delete_conversation(
    session: AsyncSession,
    session_id: str,
    user_id: str,
) -> bool:
    """Delete a conversation thread and cascade delete all its turns."""
    stmt = select(ConversationModel).where(
        ConversationModel.id == session_id,
        ConversationModel.user_id == user_id,
    )
    result = await session.execute(stmt)
    conv = result.scalar_one_or_none()
    if not conv:
        return False

    await session.delete(conv)
    await session.flush()
    return True
