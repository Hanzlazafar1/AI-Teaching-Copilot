"""TurnOutcome — what a handler delivers after processing a turn.

Every handler returns one of these. The caller (api/routes_v4.py in
production, test harnesses during development) uses TurnOutcome to:
  - append a new Turn to the conversation (with grounding + quality)
  - update SessionHandshakes (if the handler opened or closed one)
  - produce the ChatResponse for the user
  - log audit data (validation errors, judge scores, retry count)

This is the ONLY legal return type from a handler. No tuples, no dicts,
no side channels.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from schemas.handshakes import SessionHandshakes
from schemas.intent import RequestType
from schemas.turn import ChunkRef, Quality


class TurnOutcome(BaseModel):
    """Everything a handler produces for a single turn.

    Load-bearing invariants:
      * response_text is ALWAYS populated (empty str means handler
        failed — set quality=FAILED).
      * structured is populated for SCRIPTED_ML (MiniLesson dict) ONLY.
        It is None for every text/markdown handler — PLAN_UNIT,
        HOW_TO_TEACH, COACHING, MANAGEMENT, THINK_ALOUD and META all
        ship prose via response_text.
        ⚠️ Its presence is the DELIVERY SWITCH: routes_v4._build_response
        ships `structured` as the body and DISCARDS response_text when it
        is not None. Setting it on a text handler would replace the
        teacher's answer with a JSON blob labelled "mini_lesson". Do not
        use it to carry side-band fields; add a field like offered_skills
        instead.
      * grounding lists chunks that materially contributed. Empty for
        library-verbatim paths (the library entry is its own grounding).
      * quality reflects validator+judge outcome:
          VALID  → all checks passed or passed after retry
          LOW    → retries exhausted with remaining violations; best
                   attempt delivered
          FAILED → generation error or abort; response_text may be a
                   canned fallback
      * handshake_updates: when non-None, replaces the session's
        SessionHandshakes entirely (None = no change).
      * retry_count: debugging/auditing; 0 on first-try success.
    """

    model_config = ConfigDict(validate_assignment=True)

    response_text: str
    structured: Optional[dict[str, Any]] = None
    # The skills THIS response offered the teacher to pick from, in the order
    # rendered. Populated by the offering handlers (PLAN_UNIT / HOW_TO_TEACH);
    # empty everywhere else. An ordinal reply ("number 4") is resolved against
    # this record of what the teacher actually saw, rather than by asking the
    # LLM to re-count markdown — which shipped item 3 for "number 4".
    offered_skills: list[str] = Field(default_factory=list)
    # THIS response is an open clarifying QUESTION, asked on behalf of the
    # request_type named here — the request the teacher's next message is
    # answering. Set at the ONE clarify constructor
    # (handlers.__init__._clarify_outcome); None (the overwhelming default)
    # means the response is an ANSWER and nothing is outstanding.
    #
    # It exists because "the teacher answered the question we just asked" is a
    # FACT the emitting code already knows, and re-deriving it later from the
    # question's wording cannot work: HOW_TO_TEACH and THINK_ALOUD emit a
    # byte-identical grade question, as do SCRIPTED_ML and PLAN_UNIT. QU reads
    # it (via Turn.clarifying_for) to pin a bare answer back to the pending
    # request instead of re-classifying it from scratch into COACHING.
    clarifying_for: Optional[RequestType] = None
    grounding: list[ChunkRef] = Field(default_factory=list)
    quality: Quality = Quality.VALID
    handshake_updates: Optional[SessionHandshakes] = None

    # Audit / debugging metadata
    retry_count: int = Field(default=0, ge=0)
    validation_errors: list[str] = Field(default_factory=list)
    judge_scores: Optional[dict[str, Any]] = None
    sources: list[ChunkRef] = Field(default_factory=list)
    # Assembled retrieval context passed into the generation prompt. Surfaced
    # so the diagnostics panel can show exactly what the LLM saw. Empty for
    # handlers that don't retrieve (META) or for the library-verbatim path.
    retrieved_context: str = ""

    # For library-verbatim path — identifies the reused ML
    library_match_id: Optional[str] = None
