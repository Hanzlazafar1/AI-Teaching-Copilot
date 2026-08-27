"""Per-request-type handlers + the dispatcher that routes to them.

The architecture: QU produces a TurnIntent with a `request_type`.
The dispatcher picks the matching handler. Each handler is a pure
function of (intent, conversation, handshakes) — no shared state,
no cross-handler coupling.

All nine handlers are now wired:

  META          → handle_meta           (canned responses)
  SCRIPTED_ML   → handle_scripted_ml    (full 4-step MiniLesson)
  HOW_TO_TEACH  → handle_how_to_teach   (numbered sub-skill outline)
  PLAN_UNIT     → handle_plan_unit      (priority-skill sequence)
  THINK_ALOUD   → handle_think_aloud    (Step 2B-style monologue)
  COACHING      → handle_coaching       (open-ended writing Q&A)
  MANAGEMENT    → handle_management     (classroom routines / workshop)
  DEEPEN_PRIOR  → handle_deepen_prior   (meta: inherit prior, delegate)
  CORRECTION    → handle_correction     (meta: re-run prior w/ corrections)
"""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Optional

from openai import AsyncOpenAI

from api.models import ModelSet
from canonicalizer import Canonicalizer
from handlers._prompt_rules import FRUSTRATION_VALIDATION_CLARIFY
from handlers.clarify import clarify_question, effective_missing_required
from handlers.coaching import handle_coaching
from handlers.correction import handle_correction
from handlers.deepen_prior import handle_deepen_prior
from handlers.formatting import format_one_skill_guard
from handlers.how_to_teach import handle_how_to_teach
from handlers.management import handle_management
from handlers.meta import handle_meta
from handlers.plan_unit import handle_plan_unit
from handlers.scripted_ml import handle_scripted_ml
from handlers.think_aloud import handle_think_aloud
from schemas import (
    Conversation,
    Quality,
    RequestType,
    Role,
    SessionHandshakes,
    TurnIntent,
    TurnOutcome,
)


HandlerFn = Callable[..., Awaitable[TurnOutcome]]


# Per-field clarifying questions. Phrased the way Brady speaks — no
# jargon, no bureaucratic "please provide". Short enough to read fast.
_CLARIFY_QUESTIONS: dict[str, str] = {
    "grade": (
        "Which grade level are you teaching? That will help me give you "
        "the most relevant guidance."
    ),
    "skill": (
        "Which specific writing skill did you have in mind? "
        "For example: topic sentences, sensory details, transitions, "
        "magnify close-up details, etc."
    ),
    "mode": (
        "Which writing mode are you working in — informative, persuasive, "
        "or narrative (entertain)?"
    ),
}


def _offered_pick_list(conversation: Conversation) -> list[str]:
    """The pick-list currently on the teacher's screen, or nothing.

    ONLY the most recent assistant turn counts. The previous helper scanned
    BACKWARD until it found any turn containing a list, so a list from
    several turns ago — long since scrolled past, and not what the teacher
    is looking at — was re-surfaced under the words "the list I just
    shared", which was then literally false.

    Reads the recorded list rather than re-parsing the turn's markdown:
    the offering handler already recorded exactly what it rendered
    (picklist.extract_offered_skills), and one home for that fact means the
    re-surfaced list and the resolved ordinal can never disagree.
    """
    for turn in reversed(conversation.turns):
        if turn.role is Role.ASSISTANT:
            return list(turn.offered_skills)
    return []


def _clarify_outcome(text: str, intent: Optional[TurnIntent] = None) -> TurnOutcome:
    """Wrap a clarifying question as a VALID, content-free TurnOutcome.

    Brady C10 (dogfood ④): when the teacher voiced frustration
    (``intent.expressed_frustration``), OPEN with the deterministic validation
    sentence before the question. The clarify short-circuits happen in
    ``dispatch()`` BEFORE any handler/LLM runs, so the generation-prompt
    instruction ``FRUSTRATION_VALIDATION_RULE`` never fires on a first-contact
    frustrated turn — this is its clarify-path counterpart, and being at the ONE
    seam every clarify short-circuit flows through, it covers grade / skill /
    mode / mgmt / SG1 / SG2 / pick-list / fallback alike.

    ``intent`` defaults to None (and ``expressed_frustration`` defaults False), so
    every calm clarify is byte-identical to before — the prepend is strictly
    additive, gated on the existing signal.

    Being that ONE seam is also why the PENDING REQUEST TYPE is recorded here:
    this function knows, for free, which request_type it is holding open, and
    the teacher's next message is that question's answer. Recording it lets QU
    resume the request deterministically instead of re-classifying a bare
    "8th grade" from scratch (query/qu_v4.py::apply_clarify_resume). Deriving it
    downstream from the question's WORDING is not an option: HOW_TO_TEACH and
    THINK_ALOUD emit a byte-identical grade question, as do SCRIPTED_ML and
    PLAN_UNIT — the wording genuinely does not identify the category.
    """
    if intent is not None and intent.expressed_frustration:
        text = f"{FRUSTRATION_VALIDATION_CLARIFY}\n\n{text}"
    return TurnOutcome(
        response_text=text,
        structured=None,
        clarifying_for=intent.request_type if intent is not None else None,
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
    )


def _clarify_missing(
    intent: TurnIntent,
    conversation: Conversation,
) -> TurnOutcome:
    """Return a clarifying question for the missing required field(s).

    QU already decided the field is genuinely needed; we just phrase the
    question. The teacher's answer feeds QU on the next turn, which then
    routes again with the field populated.

    U3 (Brady 38:50): when the ``request_type`` is one Brady named
    (SCRIPTED_ML / PLAN_UNIT / MANAGEMENT), phrase the question in his
    per-category wording — composed from the fields STILL missing so a
    field the teacher already stated is never re-asked. For a category
    Brady did not name, fall back to the generic per-field ask below (we
    do not invent wording he didn't give).

    Retained from before U3: for a SCRIPTED_ML turn whose ONLY gap is skill
    AND a prior assistant turn offered a numbered skill list, re-surface
    that list (pick-by-number) — a strictly more helpful ask than a bare
    open question in that specific context.
    """
    # SG1 (Brady 56:00) — an unrecognized subgroup acronym is the highest-
    # priority clarify: ask Brady's "What does that acronym stand for?" before
    # any grade/skill/list ask. clarify_question() already returns that wording
    # when the QU signal is set, so route through the same U3 seam (single
    # source of the phrasing). Empty/None signal falls through untouched.
    if (intent.unknown_subgroup_acronym or "").strip():
        return _clarify_outcome(clarify_question(intent), intent)

    # SG2 (Brady 57:30) — a RECOGNIZED subgroup context with NO writing level
    # stated asks the developmental WRITING LEVEL, ahead of the grade/skill/list
    # asks below (for a subgroup, grade level doesn't matter — capture the stage
    # instead). clarify_question() owns the exact wording (single source).
    if (intent.subgroup or "").strip() and not (intent.writing_level or "").strip():
        return _clarify_outcome(clarify_question(intent), intent)

    # SG2 / §F — the fields still worth ASKING about (a stated writing level
    # supplants the grade requirement). Every ask-site below reads THIS, not
    # intent.missing_required, so the rule can't leak past one of them.
    missing = effective_missing_required(intent)

    if (
        intent.request_type is RequestType.SCRIPTED_ML
        and missing == {"skill"}
        and _offered_pick_list(conversation)
    ):
        return _clarify_outcome(_skill_clarification(conversation), intent)

    # U3 per-category open-question wording.
    per_category = clarify_question(intent)
    if per_category is not None:
        return _clarify_outcome(per_category, intent)

    # Generic per-field fallback — Brady-impact order: grade > skill > mode.
    for field in ("grade", "skill", "mode"):
        if field not in missing:
            continue
        if field == "skill":
            question = _skill_clarification(conversation)
        else:
            question = _CLARIFY_QUESTIONS[field]
        return _clarify_outcome(question, intent)

    # Fallback — shouldn't reach here; missing_required was checked by caller
    return _clarify_outcome(
        "Could you give me a bit more detail so I can give you "
        "the most useful response?",
        intent,
    )


def _skill_clarification(conversation: Conversation) -> str:
    """Compose a skill-clarification question. If the prior assistant
    turn had a numbered/bulleted skill list, include the list so the
    teacher can pick by number or name. Otherwise fall back to generic."""
    items = _offered_pick_list(conversation)
    if not items:
        return _CLARIFY_QUESTIONS["skill"]
    numbered = "\n".join(f"  {i + 1}. {item}" for i, item in enumerate(items))
    return (
        "Which skill from the list I just shared would you like a "
        "lesson for? Reply with the number or the skill name.\n\n"
        f"{numbered}"
    )


_HANDLERS: dict[RequestType, HandlerFn] = {
    RequestType.META: handle_meta,
    RequestType.SCRIPTED_ML: handle_scripted_ml,
    RequestType.HOW_TO_TEACH: handle_how_to_teach,
    RequestType.PLAN_UNIT: handle_plan_unit,
    RequestType.THINK_ALOUD: handle_think_aloud,
    RequestType.COACHING: handle_coaching,
    RequestType.MANAGEMENT: handle_management,
    RequestType.DEEPEN_PRIOR: handle_deepen_prior,
    RequestType.CORRECTION: handle_correction,
}


# Brady S3 — the ONLY request types that generate a single focused mini-lesson,
# and thus the only ones where cramming a SECOND skill is scope-creep. The
# one-skill guard fires exclusively here (SCRIPTED_ML generates one; DEEPEN_PRIOR
# extends the prior one). This scoping is a deliberate FALSE-POSITIVE reducer:
# PLAN_UNIT / HOW_TO_TEACH / COACHING enumerate many skills by design, so the
# guard must never fire on them even if QU happened to populate additional_skills.
_LESSON_SHAPED: frozenset[RequestType] = frozenset(
    {RequestType.SCRIPTED_ML, RequestType.DEEPEN_PRIOR}
)


async def dispatch(
    intent: TurnIntent,
    conversation: Conversation,
    handshakes: SessionHandshakes,
    new_user_message: str = "",
    *,
    client: AsyncOpenAI,
    models: ModelSet,
    canonicalizer: Canonicalizer,
    retrieval_fn: Optional[Callable[..., Awaitable[Any]]] = None,
    library: Optional[Any] = None,
) -> TurnOutcome:
    """Route a TurnIntent to its handler and return the TurnOutcome.

    Args:
      intent: QU-produced TurnIntent for the current turn.
      conversation: prior turns (does NOT include the current user
        message — that's passed via new_user_message).
      handshakes: current SessionHandshakes state.
      new_user_message: the current user message text. Handlers use
        this for prompt construction and META marker matching.
      client: OpenAI client for LLM calls.
      models: the turn's ModelSet (generation/query/judge). Every handler
        receives models.generation as `model`. SCRIPTED_ML, DEEPEN_PRIOR,
        and CORRECTION additionally receive models.judge as `judge_model`
        (F27 judge split) — SCRIPTED_ML runs the LLM judge directly, and the
        two meta-handlers can delegate to it, so all three thread the cheaper
        judge model to the accept-gate instead of the generation flagship.
        Other handlers don't invoke the judge, so they don't receive it.
      canonicalizer: for skill/trigger canonicalization in handlers.
      retrieval_fn: optional async callable for retrieval. Handlers
        that don't need retrieval (META) ignore it. For SCRIPTED_ML,
        required (handler will produce LOW-quality outcome otherwise).
      library: optional MLLibrary for verbatim precheck.

    Raises: KeyError if an unknown request_type is dispatched (the
      enum guards against this, but explicit failure beats silent
      routing to a default).
    """
    # --- Missing-required gate ------------------------------------------
    # QU sets intent.missing_required when it can't determine a field
    # that the requested handler genuinely needs.  Rather than generating
    # content that ignores the gap, we return a clarifying question so the
    # teacher can supply the missing info on the next turn.
    # META, COACHING, and MANAGEMENT are grade-optional so they bypass
    # grade clarification. SCRIPTED_ML and THINK_ALOUD additionally
    # require a concrete skill — if QU couldn't resolve an ambiguous
    # list-pick ("yes", "do it", "lesson on this"), we re-surface the
    # offered list so the teacher picks by number or name.
    _GRADE_REQUIRED = {
        RequestType.SCRIPTED_ML,
        RequestType.HOW_TO_TEACH,
        RequestType.PLAN_UNIT,
        RequestType.THINK_ALOUD,
    }
    _SKILL_REQUIRED = {
        RequestType.SCRIPTED_ML,
        RequestType.THINK_ALOUD,
        # DEEPEN_PRIOR must also gate on skill — it inherits from the prior
        # turn, but if QU set skill=None + missing_required=['skill'] (umbrella-
        # topic case from OFFERED-SKILL PICKUP), we have to ask rather than
        # silently inherit the umbrella and generate an over-broad lesson.
        RequestType.DEEPEN_PRIOR,
    }
    # U3: PLAN_UNIT needs a writing mode to sequence a unit, so Brady's "Are you
    # preparing for a persuasive, informative, or narrative unit?" must reach
    # the teacher instead of the handler silently sequencing with
    # "mode: (not specified)".
    #
    # This comment used to read "QU emits missing_required=['mode'] for a
    # mode-less plan (qu_v4_prompt 'mode' rule)" — MEASURED FALSE. QU flags mode
    # on only ~half of mode-less unit asks and never when grade is also absent
    # (campaign/recert/probe_u3_qu_mode.py), so consuming QU's set alone left
    # exactly the silent-sequencing hole this comment claimed to have closed.
    # The gap is now DERIVED from intent.mode in clarify.effective_missing_required
    # (_STRUCTURAL_PREREQS); this set still scopes WHICH types gate on it.
    _MODE_REQUIRED = {RequestType.PLAN_UNIT}
    # SG2 — the writing-level clarify is scoped to the lesson/outline request
    # types ONLY: producing a lesson/outline FOR a subgroup is what makes the
    # developmental writing level load-bearing (grade doesn't matter for a
    # subgroup — capture the developmental stage instead). This set is CURRENTLY
    # identical to _GRADE_REQUIRED, but is named separately on purpose:
    # "grade-required" and "writing-level-gated" are distinct concerns that may
    # diverge later, and conflating them would obscure the intent.
    _WRITING_LEVEL_GATED = {
        RequestType.SCRIPTED_ML,
        RequestType.HOW_TO_TEACH,
        RequestType.PLAN_UNIT,
        RequestType.THINK_ALOUD,
    }
    # SG2 / §F — the fields still worth ASKING about. A stated developmental
    # writing level SUPPLANTS the grade requirement (Brady: "Not always a grade
    # level … but current writing level"), so 'grade' is dropped here rather
    # than special-cased in the branch below — every consumer of `missing` then
    # inherits the rule. handlers/clarify.py::effective_missing_required owns
    # the single definition; _clarify_missing consults the same function, so
    # the gate's decision and the question's wording can never disagree.
    missing = effective_missing_required(intent)
    # SG1 — an unrecognized subgroup acronym forces a clarify regardless of
    # request_type (COACHING/HOW_TO_TEACH/etc. don't gate on grade/skill/mode,
    # but Brady still wants "what does that acronym stand for?" asked first).
    has_unknown_acronym = bool((intent.unknown_subgroup_acronym or "").strip())
    # SG2 — a RECOGNIZED subgroup context with no writing level stated forces a
    # clarify, but ONLY on a lesson/outline request_type (_WRITING_LEVEL_GATED):
    # for those Brady wants the current WRITING LEVEL asked (grade doesn't matter
    # for a subgroup — teach grade-level skills at the developmental stage). A
    # plain COACHING/MANAGEMENT turn that merely mentions a subgroup is NOT
    # producing a leveled lesson, so asking its writing level would be a
    # non-sequitur — it reaches its handler instead. The unrecognized-acronym
    # case is handled above and, via clarify_question()'s ordering, wins if both
    # are set. (SG1 stays request_type-agnostic; only SG2 is scoped here.)
    needs_writing_level = (
        bool((intent.subgroup or "").strip())
        and not (intent.writing_level or "").strip()
        and intent.request_type in _WRITING_LEVEL_GATED
    )
    needs_clarification = (
        has_unknown_acronym
        or needs_writing_level
        or ("grade" in missing and intent.request_type in _GRADE_REQUIRED)
        or ("skill" in missing and intent.request_type in _SKILL_REQUIRED)
        or ("mode" in missing and intent.request_type in _MODE_REQUIRED)
        # MANAGEMENT is grade-optional and area-based (no grade/skill/mode gate),
        # but if QU flags ANY required field as missing on a management turn we
        # ask Brady's "What area of management…" question rather than guess.
        or (intent.request_type is RequestType.MANAGEMENT and bool(missing))
    )
    if needs_clarification:
        return _clarify_missing(intent, conversation)

    handler = _HANDLERS.get(intent.request_type)
    if handler is None:  # defensive — RequestType enum should cover all
        raise KeyError(
            f"No handler registered for request_type={intent.request_type.value}"
        )
    handler_kwargs = dict(
        intent=intent,
        conversation=conversation,
        handshakes=handshakes,
        new_user_message=new_user_message,
        client=client,
        model=models.generation,
        canonicalizer=canonicalizer,
        retrieval_fn=retrieval_fn,
        library=library,
    )
    # F27 judge split — the LLM accept-gate must run on the (cheaper) judge
    # model, never the flagship generation model. SCRIPTED_ML runs the judge
    # directly; DEEPEN_PRIOR and CORRECTION can DELEGATE to handle_scripted_ml
    # (and thus reach the judge), so they must receive judge_model too and
    # forward it onward when — and only when — they delegate there. Handlers
    # that never reach the judge don't accept the kwarg, so we pass it to only
    # these three.
    if intent.request_type in (
        RequestType.SCRIPTED_ML,
        RequestType.DEEPEN_PRIOR,
        RequestType.CORRECTION,
    ):
        handler_kwargs["judge_model"] = models.judge
    outcome = await handler(**handler_kwargs)

    # --- Brady S3: one-skill-per-mini-lesson guard ----------------------
    # Structurally parallel to the missing-required gate above, but fired
    # AFTER generation: when QU flagged scope-creep (the teacher tried to
    # cram a SECOND distinct, independently-teachable skill into ONE mini-
    # lesson), prepend Brady's deterministic guard as a preface to the
    # lesson we just generated on the PRIMARY skill — guard leads, the
    # correct single-skill lesson follows. Scoped to _LESSON_SHAPED only
    # (a false-positive reducer). The guard is a CODE template, never LLM
    # text (the anti-Fm5 pattern); empty additional_skills — the back-compat
    # default — renders to '' and leaves the response untouched.
    if intent.request_type in _LESSON_SHAPED:
        guard = format_one_skill_guard(intent.additional_skills)
        if guard:
            outcome.response_text = f"{guard}\n\n{outcome.response_text}"
            # Delivery: the two _LESSON_SHAPED handlers return a MiniLesson dict
            # as outcome.structured, and api.routes_v4._build_response delivers
            # THAT dict as the API `response` — dropping response_text whenever
            # structured is non-None. So the response_text prepend above never
            # reaches the teacher on the lesson path. Surface the guard in the
            # structured payload too, as a NEW key. This guard stays HERE rather
            # than in scripted_ml._finalize_ml_delivery (the seam that owns the
            # SCRIPTED_ML-internal transforms — Fm3/Fm4/E2) because it is scoped
            # to _LESSON_SHAPED at the dispatch level, which is broader than the
            # scripted-ML handler: DEEPEN_PRIOR can route elsewhere and must
            # still get the guard. New key only —
            # existing lesson fields are never overwritten; and because this is
            # gated on a non-empty guard, a normal single-skill lesson (empty
            # additional_skills) leaves structured untouched (back-compat).
            if isinstance(outcome.structured, dict):
                outcome.structured["one_skill_guard"] = guard
    return outcome


__all__ = [
    "dispatch",
    "handle_coaching",
    "handle_correction",
    "handle_deepen_prior",
    "handle_how_to_teach",
    "handle_management",
    "handle_meta",
    "handle_plan_unit",
    "handle_scripted_ml",
    "handle_think_aloud",
]
