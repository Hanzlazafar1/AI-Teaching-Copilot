"""Turn, Conversation, ChunkRef — the Layer 1 source of truth.

The conversation is the only persistent pedagogical memory in v4.
Everything downstream (QU, handlers, validators) derives from it.

Structured responses (SCRIPTED_ML, PLAN_UNIT, etc.) are stored in
``Turn.structured`` so later turns can inspect specific fields
(skill_focus, step_2b_show, etc.) without re-parsing text.

Grounding chunk-refs are stored lightweight (IDs only, no chunk text).
Handlers that need full chunk content fetch by ID from Qdrant on demand.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, ConfigDict, Field

from schemas.intent import RequestType

if TYPE_CHECKING:
    from schemas.intent import TurnIntent


class Role(str, Enum):
    """Speaker of a turn."""

    USER = "user"
    ASSISTANT = "assistant"


class Quality(str, Enum):
    """Validation outcome for an assistant turn.

    Drives two behaviors:
      * Quality=LOW does NOT block the response reaching the user, but
        prevents downstream DEEPEN_PRIOR from treating this turn's
        example as canonical (we don't want to propagate a bad example).
      * Quality=FAILED means no response was delivered (generation
        aborted). The turn is recorded for audit but treated as if the
        user message was never answered.
    """

    VALID = "valid"
    LOW = "low"
    FAILED = "failed"


class ChunkRef(BaseModel):
    """Lightweight reference to a retrieval chunk.

    Stored on Turn.grounding to track which chunks informed the
    response. Handlers that need the full chunk text fetch by ID.
    """

    model_config = ConfigDict(frozen=True)

    chunk_id: str
    source_document: str
    page_number: Optional[int] = None
    source_tier: Optional[int] = None


class Turn(BaseModel):
    """A single message in the conversation.

    User turns carry the ``intent`` that QU extracted. Assistant turns
    carry ``structured`` (for typed responses like MiniLesson),
    ``grounding`` (what chunks were used), and ``quality`` (validator
    outcome).

    ``text`` is the flattened, LLM-visible rendering of the turn. For
    SCRIPTED_ML responses, this is the human-readable lesson body;
    ``structured`` preserves the typed fields for programmatic access.
    """

    model_config = ConfigDict(validate_assignment=True)

    index: int = Field(ge=0, description="0-based position in conversation")
    role: Role
    text: str
    structured: Optional[dict] = None
    # Assistant turns only: the pick-list this turn put in front of the
    # teacher, in rendered order. The next turn's "number 4" / "the third
    # one" resolves against THIS, so it must be what was actually shown.
    offered_skills: list[str] = Field(default_factory=list)
    # Assistant turns only: this turn was an open clarifying QUESTION, asked on
    # behalf of the request_type named here. The next user message is its
    # ANSWER, so QU restores this type rather than re-classifying a bare
    # "8th grade" from scratch (query/qu_v4.py::apply_clarify_resume). None
    # means the turn was an answer — nothing is outstanding.
    clarifying_for: Optional[RequestType] = None
    grounding: list[ChunkRef] = Field(default_factory=list)
    intent: Optional["TurnIntent"] = None  # set on user turns only
    quality: Quality = Quality.VALID
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Conversation(BaseModel):
    """Append-only log of turns for a single session.

    Session-scoped; not shared across teachers. Retrieval, QU, and
    handlers all read from this one object.
    """

    model_config = ConfigDict(validate_assignment=True)

    session_id: str
    user_id: Optional[str] = None
    turns: list[Turn] = Field(default_factory=list)

    def append(self, turn: Turn) -> None:
        """Append a turn, enforcing monotonic index."""
        expected_index = len(self.turns)
        if turn.index != expected_index:
            raise ValueError(
                f"Turn index {turn.index} does not match expected "
                f"{expected_index} (conversation has {len(self.turns)} turns)"
            )
        self.turns.append(turn)

    def last_assistant_turn(self) -> Optional[Turn]:
        """Return the most recent assistant turn, or None if there is
        no assistant turn yet. Used by DEEPEN_PRIOR to locate the
        target of ``refers_to_prior``."""
        for turn in reversed(self.turns):
            if turn.role is Role.ASSISTANT:
                return turn
        return None

    def last_scripted_ml_turn(self) -> Optional[Turn]:
        """Return the most recent assistant turn whose structured body
        was a scripted ML (has ``skill_focus``). The history-eviction
        policy pins this turn so DEEPEN_PRIOR stays reliable even in
        long sessions."""
        for turn in reversed(self.turns):
            if (
                turn.role is Role.ASSISTANT
                and isinstance(turn.structured, dict)
                and "skill_focus" in turn.structured
                and turn.quality is Quality.VALID
            ):
                return turn
        return None


# Rebuild forward ref after TurnIntent import
# (done in __init__.py import ordering; if imported directly, users must
# call Turn.model_rebuild() themselves)
