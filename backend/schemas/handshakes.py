"""SessionHandshakes — the only state that isn't derivable from the
conversation itself.

In v3 the ledger held ~20 fields, many of them "continuity" signals
(last_trigger_mentioned, last_book_page_reference, last_think_aloud_text,
etc.) that were attempts to cache what the conversation already knew.
v4 deletes those — the conversation IS that memory.

What remains is a narrow set of "the system promised to do X" signals
that genuinely can't be derived from user-visible turns alone. These
are flags that span 2+ turns because the system initiated a handshake
that the user needs to confirm or decline.

Keep this struct small. If you're tempted to add a field here that
describes something the user said or something the assistant wrote,
it belongs in the conversation (Layer 1), not here.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field




class PendingLibraryOffer(BaseModel):
    """The assistant offered a library-matched scripted ML and is
    waiting for the user to accept or decline.

    The library_precheck handler produces these when a fuzzy match
    suggests a scripted ML but the match confidence is below the
    auto-surface threshold. Next turn's user response ("yes, that one"
    / "no, something else") resolves the handshake.
    """

    model_config = ConfigDict(frozen=True)

    ml_id: str
    skill: str
    grade: str
    offered_at_turn: int = Field(ge=0)


class PendingMLConfirmation(BaseModel):
    """The assistant asked the user to confirm before generating a
    scripted ML with specific parameters.

    This is the "So you want this skill, this grade, in 4-step mini-
    lesson format — correct?" handshake Brady asked for. Next user
    turn's yes/no resolves it.
    """

    model_config = ConfigDict(frozen=True)

    skill: str
    grade: str
    mode: Optional[str] = None
    asked_at_turn: int = Field(ge=0)


class PendingClarification(BaseModel):
    """The assistant asked the user for a missing required field
    (grade, skill, mode, trait) and is waiting for the answer.

    The next user turn is interpreted as the answer to this specific
    question. E.g. if ``waiting_for == "grade"`` and the user says
    "third", that resolves to grade=3 and the clarification is cleared.
    """

    model_config = ConfigDict(frozen=True)

    waiting_for: Literal["grade", "skill", "mode", "trait"]
    asked_at_turn: int = Field(ge=0)


class PendingLessonSequence(BaseModel):
    """Active multi-lesson sequence — e.g. a 10-day plan.

    Created when the teacher requests a multi-lesson plan and Brady
    generates the skill list. Incremented each time SCRIPTED_ML delivers
    a lesson in the sequence. Cleared when the final lesson is delivered.

    ``skills`` is the ordered list of skill names (teacher's words) for
    every lesson in the plan. ``current_index`` is the 0-based index of
    the lesson that was JUST delivered — so the NEXT lesson to generate
    is skills[current_index + 1]. A value of -1 means no lesson has been
    delivered yet (the plan was just generated and is waiting for the
    teacher's first "yes").
    """

    model_config = ConfigDict(frozen=True)

    skills: list[str]
    total: int = Field(ge=1)
    current_index: int = Field(ge=-1)  # -1 = plan offered, no lesson delivered yet
    grade: str
    mode: Optional[str] = None
    started_at_turn: int = Field(ge=0)


class SessionHandshakes(BaseModel):
    """Transient multi-turn handshake state.

    Everything NOT here is in the conversation (Layer 1). This struct
    should never grow beyond these four fields — if a new handshake
    emerges, add a field and document it. If "session state" tempts
    you to add something else, it probably belongs in the conversation.
    """

    model_config = ConfigDict(validate_assignment=True)

    library_offer: Optional[PendingLibraryOffer] = None
    ml_confirmation: Optional[PendingMLConfirmation] = None
    clarification: Optional[PendingClarification] = None
    # Multi-lesson sequence (e.g. a 10-day plan). Set when the teacher
    # requests a multi-lesson plan and Brady produces the skill list.
    # Incremented each time SCRIPTED_ML delivers a lesson. Cleared
    # when the final lesson is delivered or the teacher starts a new topic.
    lesson_sequence: Optional[PendingLessonSequence] = None

    def is_empty(self) -> bool:
        """True when no handshake is pending. Fast check for handlers
        that only care whether the session owes a resolution."""
        return (
            self.library_offer is None
            and self.ml_confirmation is None
            and self.clarification is None
            and self.lesson_sequence is None
        )

    def clear(self) -> "SessionHandshakes":
        """Return a fresh empty SessionHandshakes. Used after a turn
        resolves whatever was pending."""
        return SessionHandshakes()
