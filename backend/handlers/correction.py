"""CORRECTION meta-handler — re-run prior handler with corrected fields.

The teacher just corrected something we said or wrote:
  - "Actually, make it 4th grade"
  - "No, transitions not sensory"
  - "I meant narrative, not persuasive"

QU has already parsed the correction into the current TurnIntent (the
`grade`/`mode`/`skill` field now reflects the corrected value). The
CORRECTION handler's job is to:

1. Identify which handler the teacher is correcting (look at the
   preceding user turn's `request_type`).
2. Merge current intent's corrected fields onto the prior intent.
3. Delegate to that same handler.

This is distinct from DEEPEN_PRIOR:
  - DEEPEN_PRIOR: teacher wants MORE of / a DIFFERENT form of the prior
    response (switches request_type).
  - CORRECTION: teacher wants the SAME form with a fixed parameter
    (keeps request_type).

If there is no prior user turn with a meaningful request_type (no
content history to correct), we fall back to COACHING — treating the
correction as a fresh question.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from openai import AsyncOpenAI

from canonicalizer import Canonicalizer
from schemas import (
    Conversation,
    RequestType,
    Role,
    SessionHandshakes,
    TurnIntent,
    TurnOutcome,
)


# Request types that CORRECTION can target. CORRECTION never re-dispatches
# to another CORRECTION or META (those aren't content-producing), and it
# never re-dispatches to DEEPEN_PRIOR (that would hide the original target).
_CORRECTABLE: frozenset[RequestType] = frozenset({
    RequestType.SCRIPTED_ML,
    RequestType.HOW_TO_TEACH,
    RequestType.PLAN_UNIT,
    RequestType.THINK_ALOUD,
    RequestType.COACHING,
    RequestType.MANAGEMENT,
})


def _find_prior_content_intent(
    conversation: Conversation,
) -> Optional[TurnIntent]:
    """Return the most-recent EFFECTIVE content intent — the base content
    intent with every intervening CORRECTION's delta folded onto it, in
    turn order.

    Walk user turns backward: the first ``_CORRECTABLE`` intent is the base
    (the original content-producing turn); every CORRECTION turn seen before
    reaching it is an intervening correction. We then fold those corrections
    onto the base oldest-first (chronological order) so a chain of
    corrections ACCUMULATES instead of reverting to the original.

    Without this fold a 2nd correction would re-anchor on the base and
    silently drop the 1st correction's delta (finding F7): "3rd-grade lesson
    on X" -> "make it 4th grade" -> "make it narrative" would yield a
    3rd-grade narrative lesson. META / DEEPEN_PRIOR turns are transparent to
    the walk (neither base nor fold), preserving prior behavior. Returns
    ``None`` when there is no base content intent to correct."""
    base: Optional[TurnIntent] = None
    intervening: list[TurnIntent] = []  # newest-first as collected
    for t in reversed(conversation.turns):
        if t.role is not Role.USER or t.intent is None:
            continue
        if t.intent.request_type in _CORRECTABLE:
            base = t.intent
            break
        if t.intent.request_type is RequestType.CORRECTION:
            intervening.append(t.intent)

    if base is None:
        return None

    # Fold oldest-first so a later correction wins over an earlier one for
    # any overlapping field. Reuse the exact same merge rules the handler
    # applies to the current correction — never duplicate field-merge logic.
    effective = base
    for correction in reversed(intervening):
        effective = _merge_correction(correction, effective)
    return effective


def _merge_correction(
    current: TurnIntent,
    prior: TurnIntent,
) -> TurnIntent:
    """Return a new TurnIntent based on ``prior``, with ``current``'s
    populated fields overriding.

    The prior turn's request_type is preserved. Current intent's
    corrections (grade/mode/trait/skill/required_triggers) win when
    present; otherwise we keep the prior value so fields the teacher
    didn't touch stay stable.
    """
    merged = prior.model_dump()
    cur = current.model_dump()

    # request_type always comes from prior — that's the whole point.
    # But preserve correction-signal fields from the current turn.
    merged["refers_to_prior"] = cur.get("refers_to_prior", False)
    merged["reuse_example_from_prior"] = cur.get("reuse_example_from_prior", False)
    merged["prior_turn_ref"] = cur.get("prior_turn_ref")

    for field in ("grade", "mode", "trait", "skill"):
        if cur.get(field) is not None:
            merged[field] = cur[field]

    # required_triggers: if the teacher named new triggers, use them;
    # otherwise carry prior forward.
    if cur.get("required_triggers"):
        merged["required_triggers"] = list(cur["required_triggers"])

    # Clarification/ambiguity/confirmation: all come from the current
    # turn's QU pass — the prior values are stale.
    merged["needs_confirmation"] = cur.get("needs_confirmation", False)
    merged["confirmation_reason"] = cur.get("confirmation_reason")
    merged["missing_required"] = list(cur.get("missing_required", []))
    merged["ambiguities"] = list(cur.get("ambiguities", []))

    return TurnIntent(**merged)


async def handle_correction(
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
    prior = _find_prior_content_intent(conversation)

    # Late imports — avoid package-level circular import.
    from handlers.coaching import handle_coaching
    from handlers.how_to_teach import handle_how_to_teach
    from handlers.management import handle_management
    from handlers.plan_unit import handle_plan_unit
    from handlers.scripted_ml import handle_scripted_ml
    from handlers.think_aloud import handle_think_aloud

    _ROUTE: dict[RequestType, Callable[..., Awaitable[TurnOutcome]]] = {
        RequestType.SCRIPTED_ML: handle_scripted_ml,
        RequestType.HOW_TO_TEACH: handle_how_to_teach,
        RequestType.PLAN_UNIT: handle_plan_unit,
        RequestType.THINK_ALOUD: handle_think_aloud,
        RequestType.COACHING: handle_coaching,
        RequestType.MANAGEMENT: handle_management,
    }

    if prior is None:
        # Nothing to correct — treat as a fresh coaching question.
        fallback = intent.model_copy(update={"request_type": RequestType.COACHING})
        return await handle_coaching(
            intent=fallback,
            conversation=conversation,
            handshakes=handshakes,
            new_user_message=new_user_message,
            client=client,
            model=model,
            canonicalizer=canonicalizer,
            retrieval_fn=retrieval_fn,
            library=library,
        )

    mutated = _merge_correction(intent, prior)
    target_handler = _ROUTE[prior.request_type]

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
    # F27 judge split: of the correctable targets, only handle_scripted_ml runs
    # the LLM judge (and only it accepts judge_model). Forward the cheaper judge
    # model when the chosen target IS handle_scripted_ml; the other targets
    # (how_to_teach / plan_unit / think_aloud / coaching / management) don't
    # accept the kwarg, so never pass it to them. The no-prior COACHING
    # fallback above likewise never receives it.
    if target_handler is handle_scripted_ml:
        delegate_kwargs["judge_model"] = judge_model
    return await target_handler(**delegate_kwargs)
