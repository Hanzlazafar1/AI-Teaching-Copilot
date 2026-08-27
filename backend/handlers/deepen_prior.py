"""DEEPEN_PRIOR meta-handler — inherit + delegate.

DEEPEN_PRIOR is the request_type QU emits when the teacher references
the prior assistant turn ("put this in a lesson", "show me just the
think-aloud", "use the example you wrote", "now for 4th graders").

This handler does two things:

1. **Inherit** pedagogical fields from the most recent VALID assistant
   turn — skill, mode, grade, trait — so the teacher never has to
   re-state what's already on screen.

2. **Delegate** to the real content handler based on what the teacher
   is asking FOR this turn:
     * "put this in a lesson", "scripted ML for this" → SCRIPTED_ML
     * "show me just the think-aloud", "model your thinking"  → THINK_ALOUD
     * "how do I teach this", "outline", "strategies"         → HOW_TO_TEACH
     * "plan a unit", "what skills next"                      → PLAN_UNIT
     * anything else (default / "expand", "elaborate")        → SCRIPTED_ML

The handler does NOT itself call the LLM for content. It mutates the
intent and invokes the downstream handler.

Invariants:
  - If there is no prior assistant turn, we fall back to COACHING with
    the teacher's literal message (safest — DEEPEN_PRIOR without a
    target is just an open question).
  - LOW-quality prior turns are skipped via
    ``Conversation.last_scripted_ml_turn()`` — we never inherit the
    example from a low-quality lesson.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from openai import AsyncOpenAI

from canonicalizer import Canonicalizer
from schemas import (
    Conversation,
    Quality,
    RequestType,
    Role,
    SessionHandshakes,
    TurnIntent,
    TurnOutcome,
)


# Keyword buckets — lowercase, substring match on the user message.
_LESSON_WORDS = (
    "lesson", "scripted", "mini-lesson", "minilesson", "mini lesson",
    "full lesson", "write the lesson",
    # Brady Fm2 / TS03: "put the think-aloud into a 4-step ML" contains no
    # "lesson" substring, so it fell through to the think-aloud bucket below
    # and returned prose instead of a structured MiniLesson. These two tokens
    # are what make lesson intent win. Phrasings like "into a lesson" need no
    # token — the bare "lesson" above already matches them (substring match).
    # Do NOT add a bare "ml" (it matches "html") or a bare "step".
    "4-step", "four-step",
)
_THINK_ALOUD_WORDS = (
    "think-aloud", "think aloud", "thinking out loud", "model your thinking",
    "monologue", "internal monologue",
)
_OUTLINE_WORDS = (
    "how do i teach", "how to teach", "outline", "strategies for",
    "approach to", "sub-skills", "sub skills",
)
_UNIT_PLAN_WORDS = (
    "plan a unit", "unit plan", "scope and sequence", "what skills next",
    "priority skills", "year plan",
)


def _pick_target_request_type(
    user_message: str, prior: Optional["_PriorContext"]
) -> RequestType:
    """Decide which handler DEEPEN_PRIOR should delegate to."""
    msg = (user_message or "").lower()
    if any(w in msg for w in _LESSON_WORDS):
        return RequestType.SCRIPTED_ML
    if any(w in msg for w in _THINK_ALOUD_WORDS):
        return RequestType.THINK_ALOUD
    if any(w in msg for w in _UNIT_PLAN_WORDS):
        return RequestType.PLAN_UNIT
    if any(w in msg for w in _OUTLINE_WORDS):
        return RequestType.HOW_TO_TEACH
    # Brady (feedback-docx.txt:136), on the follow-up to a routines overview:
    # "Response listed skills that were not even mentioned in the overview!" —
    # "we have a big disconnect here. When 'routines, management, start up,
    # writer's workshop, writer habits, expectations, procedures' are the
    # focus, then Co-Pilot must pull from Sections 1-5 in the Launch books."
    #
    # The default below presumes teaching content, so a bare follow-up to a
    # MANAGEMENT overview silently became a writing-SKILL lesson — his exact
    # complaint. Management is a FOCUS that persists across the follow-up; it
    # is not re-established by each message. Checked after the explicit
    # re-frame keywords above, so a teacher who asks for a unit or an outline
    # still gets one.
    if prior is not None and prior.request_type is RequestType.MANAGEMENT:
        return RequestType.MANAGEMENT
    # Default: if the prior turn was a HOW_TO_TEACH outline, the teacher
    # most likely wants a full lesson (the common Brady flow: outline →
    # "give me that one as a lesson"). Otherwise stay in SCRIPTED_ML —
    # the "deepen" intent presumes teaching content.
    if prior is not None and prior.request_type is RequestType.HOW_TO_TEACH:
        return RequestType.SCRIPTED_ML
    return RequestType.SCRIPTED_ML


class _PriorContext:
    """Snapshot of what we inherit from the last VALID assistant turn.

    Separate class (not a Pydantic model) because this is an in-handler
    working object, not a persisted schema.
    """

    __slots__ = ("intent", "request_type", "structured", "text", "quality")

    def __init__(
        self,
        intent: Optional[TurnIntent],
        request_type: Optional[RequestType],
        structured: Optional[dict],
        quality: Quality,
        text: str = "",
    ) -> None:
        self.intent = intent
        self.request_type = request_type
        self.structured = structured
        self.text = text
        self.quality = quality


def _find_prior_context(conversation: Conversation) -> Optional[_PriorContext]:
    """Walk conversation backward to find the last VALID assistant turn
    plus the user turn that triggered it. Return None if no such pair."""
    last_valid_assistant = None
    last_valid_index = None
    for i in range(len(conversation.turns) - 1, -1, -1):
        t = conversation.turns[i]
        if (
            t.role is Role.ASSISTANT
            and t.quality is Quality.VALID
        ):
            last_valid_assistant = t
            last_valid_index = i
            break
    if last_valid_assistant is None:
        return None
    # The intent lives on the PRIOR user turn (role=USER, index just
    # before this assistant turn). Find it.
    prior_user_intent: Optional[TurnIntent] = None
    for i in range(last_valid_index - 1, -1, -1):
        t = conversation.turns[i]
        if t.role is Role.USER and t.intent is not None:
            prior_user_intent = t.intent
            break
    req_type: Optional[RequestType] = (
        prior_user_intent.request_type if prior_user_intent else None
    )
    return _PriorContext(
        intent=prior_user_intent,
        request_type=req_type,
        structured=last_valid_assistant.structured,
        text=last_valid_assistant.text or "",
        quality=last_valid_assistant.quality,
    )


def _carried_organizer(prior: Optional["_PriorContext"]) -> Optional[str]:
    """Brady C3 — the prior VALID assistant turn's DESCRIPTION to carry into a
    DEEPEN_PRIOR-generated lesson.

    When the previous turn *described* a specific organizer / anchor-chart /
    approach (a coaching answer, an outline, a think-aloud — anything that is
    NOT itself a finished scripted mini-lesson) and the teacher now says "give
    me a mini-lesson for that", the generator must build the lesson AROUND that
    description instead of inventing a different tool. We thread the prior
    turn's rendered text through as an explicit, must-incorporate block rather
    than letting it survive only as generic conversation history the model may
    ignore.

    Returns None (a no-op) when:
      * there is no prior VALID assistant turn, or
      * the prior turn was ITSELF a scripted mini-lesson (its structured body
        carries ``skill_focus``) — there is no separate organizer to fold in;
        continuity already flows through the inherited skill/grade/mode fields.
    """
    if prior is None:
        return None
    if "skill_focus" in (prior.structured or {}):
        return None
    text = (prior.text or "").strip()
    return text or None


def _merge_intent(
    current: TurnIntent,
    prior_intent: Optional[TurnIntent],
    target: RequestType,
    conversation: Optional[Conversation] = None,
    canon: Optional[Canonicalizer] = None,
) -> TurnIntent:
    """Return a NEW TurnIntent that:
      * has request_type = target
      * fills missing grade/mode/trait/skill from prior_intent
      * preserves everything else the current intent already specified
      * resolves a deictic that leaked into skill.as_stated

    The skill inheritance above only fires when ``skill`` is None. A deictic
    ("that", "those paragraphs") is NOT None, so it survives that gate and would
    reach the prompt as the lesson title / Step-1 text. After merging we hand
    the result to ``resolve_deictic_skill`` (the same helper QU runs) so both
    the SCRIPTED_ML and DEEPEN_PRIOR routings behave identically. Runs after
    inheritance so a deictic is resolved against the prior scripted-ML turn even
    when the model also inherited context. ``conversation``/``canon`` default to
    None so the legacy 3-arg call still works (resolution is then a no-op unless
    the merged skill is a deictic, in which case the default canonicalizer is
    used). The import is function-level to match this module's cycle-avoidance
    convention.
    """
    data = current.model_dump()
    data["request_type"] = target
    if prior_intent is not None:
        prior = prior_intent.model_dump()
        for field in ("grade", "mode", "trait", "skill"):
            if data.get(field) is None and prior.get(field) is not None:
                data[field] = prior[field]
        # Preserve required_triggers from prior if current has none —
        # the teacher is still talking about the same Smekens tools.
        if not data.get("required_triggers") and prior.get("required_triggers"):
            data["required_triggers"] = list(prior["required_triggers"])
    merged = TurnIntent(**data)
    if merged.skill is None:
        return merged
    from query.qu_v4 import resolve_deictic_skill

    if canon is None:
        from canonicalizer import get_canonicalizer

        canon = get_canonicalizer()
    return resolve_deictic_skill(
        merged, conversation, canon, prior_intent=prior_intent
    )


async def handle_deepen_prior(
    intent: TurnIntent,
    conversation: Conversation,
    handshakes: SessionHandshakes,
    new_user_message: str,
    *,
    client: AsyncOpenAI,
    model: str,
    judge_model: Optional[str] = None,
    canonicalizer: Canonicalizer,
    retrieval_fn: Optional[Callable[..., Awaitable[Any]]] = None,
    library: Optional[Any] = None,
) -> TurnOutcome:
    prior = _find_prior_context(conversation)

    target = _pick_target_request_type(new_user_message, prior)

    prior_intent = prior.intent if prior is not None else None
    mutated = _merge_intent(
        intent, prior_intent, target,
        conversation=conversation, canon=canonicalizer,
    )

    # Delegate — import inside to avoid circular package imports (this
    # module is imported by handlers/__init__.py).
    from handlers.coaching import handle_coaching
    from handlers.how_to_teach import handle_how_to_teach
    from handlers.management import handle_management
    from handlers.plan_unit import handle_plan_unit
    from handlers.scripted_ml import handle_scripted_ml
    from handlers.think_aloud import handle_think_aloud

    target_handler: Callable[..., Awaitable[TurnOutcome]]
    if target is RequestType.SCRIPTED_ML:
        target_handler = handle_scripted_ml
    elif target is RequestType.THINK_ALOUD:
        target_handler = handle_think_aloud
    elif target is RequestType.HOW_TO_TEACH:
        target_handler = handle_how_to_teach
    elif target is RequestType.PLAN_UNIT:
        target_handler = handle_plan_unit
    elif target is RequestType.MANAGEMENT:
        # MANAGEMENT was the ONE request type this could not reach: it fell
        # through to coaching, whose retrieval is labelled COACHING_GENERAL,
        # so the reranker's management scoping (DEPRIO_WRONG_MGMT on ch 8-13)
        # silently stopped applying and the follow-up pulled writing-skill
        # lessons out of Sections 6/8 — measured live, and exactly what Brady
        # reported. Same shape as s4: the rule existed and one handler was
        # missing from the list that reaches it.
        target_handler = handle_management
    else:
        target_handler = handle_coaching

    delegate_kwargs: dict[str, Any] = dict(
        intent=mutated,
        conversation=conversation,
        handshakes=handshakes,
        new_user_message=new_user_message,
        client=client,
        model=model,
        canonicalizer=canonicalizer,
        retrieval_fn=retrieval_fn,
        library=library,
    )
    # F27 judge split: only handle_scripted_ml runs the LLM judge (and only it
    # accepts judge_model). When we delegate there, forward the cheaper judge
    # model so the accept-gate doesn't run on the flagship generation model;
    # never pass it to a target handler that doesn't accept the kwarg.
    #
    # Brady C3: likewise, only handle_scripted_ml accepts carried_context. When
    # the prior turn described an organizer/approach and we're building a lesson
    # from it, thread that description in so the generated lesson incorporates
    # it. Gated to the scripted_ml delegate (the other targets don't take the
    # kwarg) and omitted entirely when there is nothing to carry (no-op).
    if target_handler is handle_scripted_ml:
        delegate_kwargs["judge_model"] = judge_model
        carried = _carried_organizer(prior)
        if carried:
            delegate_kwargs["carried_context"] = carried
    return await target_handler(**delegate_kwargs)
