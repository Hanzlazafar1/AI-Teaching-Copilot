"""Typed schemas for QU-driven architecture (v4).

The contracts QU produces and handlers consume. No runtime logic —
only data shapes. See docs/architecture/QU-DRIVEN-DESIGN.md for the
pedagogical rationale behind each field.
"""

from schemas.handshakes import (
    PendingClarification,
    PendingLibraryOffer,
    PendingMLConfirmation,
    SessionHandshakes,
)
from schemas.intent import (
    GradeSpec,
    ModeSpec,
    RequestType,
    SkillSpec,
    TraitSpec,
    TurnIntent,
)
from schemas.outcome import TurnOutcome
from schemas.turn import (
    ChunkRef,
    Conversation,
    Quality,
    Role,
    Turn,
)

# Resolve Turn's forward reference to TurnIntent now that both are imported.
# Consumers who import from the package root get fully-rebuilt models.
Turn.model_rebuild()
Conversation.model_rebuild()

__all__ = [
    # intent
    "GradeSpec",
    "ModeSpec",
    "RequestType",
    "SkillSpec",
    "TraitSpec",
    "TurnIntent",
    # turn
    "ChunkRef",
    "Conversation",
    "Quality",
    "Role",
    "Turn",
    # handshakes
    "PendingClarification",
    "PendingLibraryOffer",
    "PendingMLConfirmation",
    "SessionHandshakes",
    # outcome
    "TurnOutcome",
]
