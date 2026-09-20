"""Conversation sidebar and history management routes."""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from auth.dependencies import get_current_user
from db.models import UserModel
from db.repository import (
    delete_conversation,
    list_conversations,
    load_conversation,
    save_conversation,
    update_conversation_meta,
)
from db.session import get_db_session

router = APIRouter(prefix="/api/conversations", tags=["Conversations"])


class CreateConversationRequest(BaseModel):
    title: Optional[str] = "New Conversation"


class UpdateConversationRequest(BaseModel):
    title: Optional[str] = None
    is_pinned: Optional[bool] = None
    is_archived: Optional[bool] = None


@router.get("", summary="List all conversation threads for sidebar")
async def get_conversations(
    include_archived: bool = False,
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    """Retrieve all chats owned by the teacher, sorted with pinned first, newest updated."""
    return await list_conversations(
        session, current_user.id, include_archived=include_archived
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a new conversation thread")
async def create_new_conversation(
    req: CreateConversationRequest = CreateConversationRequest(),
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Start a fresh chat thread with a new session_id."""
    session_id = str(uuid.uuid4())
    conv, hs = await load_conversation(session, session_id, user_id=current_user.id)
    await save_conversation(session, session_id, conv, hs, title=req.title)

    return {
        "session_id": session_id,
        "title": req.title or "New Conversation",
        "user_id": current_user.id,
    }


@router.get("/{session_id}", summary="Load past thread history")
async def get_conversation_history(
    session_id: str,
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Fetch full message turns and metadata for a past conversation."""
    conv, _ = await load_conversation(session, session_id, user_id=current_user.id)

    # Multi-tenant security check: ensure the thread belongs to this teacher
    if conv.user_id and conv.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: this conversation belongs to another teacher.",
        )

    turns_data = [
        {
            "index": t.index,
            "role": t.role.value,
            "text": t.text,
            "structured": t.structured,
            "quality": t.quality.value,
            "offered_skills": t.offered_skills,
            "created_at": t.created_at.isoformat(),
        }
        for t in conv.turns
    ]

    return {
        "session_id": conv.session_id,
        "user_id": conv.user_id,
        "turns": turns_data,
    }


@router.patch("/{session_id}", summary="Rename, pin, or archive a conversation")
async def modify_conversation(
    session_id: str,
    req: UpdateConversationRequest,
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Update title, pinned status, or archive state of a chat thread."""
    conv = await update_conversation_meta(
        session,
        session_id,
        current_user.id,
        title=req.title,
        is_pinned=req.is_pinned,
        is_archived=req.is_archived,
    )
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied.",
        )

    return {
        "session_id": conv.id,
        "title": conv.title,
        "is_pinned": conv.is_pinned,
        "is_archived": conv.is_archived,
        "updated_at": conv.updated_at.isoformat(),
    }


@router.delete("/{session_id}", summary="Delete an old chat thread cleanly")
async def remove_conversation(
    session_id: str,
    current_user: UserModel = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Permanently delete a conversation and all its message turns."""
    deleted = await delete_conversation(session, session_id, current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied.",
        )

    return {"deleted": True, "session_id": session_id}
