"""v4 Query Understanding — reads full conversation, outputs TurnIntent.

Single entry point: ``understand()``. Takes the conversation, the new
user message, and pending handshakes. Produces a typed TurnIntent that
downstream handlers consume directly — no side ledger, no rules layer.

Design:
  - ONE LLM call per turn
  - Cheap query-sibling model (e.g. gpt-5.4-nano), NOT the generation
    flagship — intent extraction/classification runs fine on the small
    model, and keeping QU off the flagship is the F27 cost fix; do not
    "restore" it to the generation model
  - Temperature 0 + structured output (OpenAI Pydantic response_format)
  - Prompt caching: system prompt is stable; history grows append-only;
    new user message is the only fresh content
  - Post-processing: canonicalize skill, canonicalize grade — safety
    nets that run after the LLM's structured output, never the other
    way around
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from openai import AsyncOpenAI
from pydantic import ValidationError

from canonicalizer import Canonicalizer, ResolutionKind, canonicalize_grade
from handlers.formatting import MODE_ADJECTIVES
from handlers.picklist import resolve_ordinal_pick, skill_name_from_offer
from llm_params import call_params, temperature_kwargs
from query.qu_v4_prompt import get_system_prompt
from schemas import (
    Conversation,
    PendingLessonSequence,
    RequestType,
    Role,
    SessionHandshakes,
    SkillSpec,
    Turn,
    TurnIntent,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------


async def understand(
    conversation: Conversation,
    new_user_message: str,
    *,
    client: AsyncOpenAI,
    model: str,
    handshakes: Optional[SessionHandshakes] = None,
    canonicalizer: Optional[Canonicalizer] = None,
) -> TurnIntent:
    """Produce a TurnIntent for the user's new message.

    Args:
      conversation: the full structured conversation up to (but not
        including) the new user message. The new message is added only
        AFTER this function succeeds, by the caller.
      new_user_message: the text the teacher just sent.
      client: an AsyncOpenAI client, already configured.
      model: the model identifier (e.g., "gpt-4o").
      handshakes: pending multi-turn handshakes (library offer, ML
        confirmation, clarification). None means no handshake pending.
      canonicalizer: for post-processing skill / trigger names. If
        None, uses the default singleton.

    Returns: a TurnIntent validated by Pydantic.

    Raises: openai errors if the API call fails; pydantic ValidationError
      if the LLM emits structurally invalid output (should be rare
      because structured output enforces schema).
    """
    if canonicalizer is None:
        from canonicalizer import get_canonicalizer
        canonicalizer = get_canonicalizer()

    messages = _build_messages(
        conversation=conversation,
        new_user_message=new_user_message,
        handshakes=handshakes or SessionHandshakes(),
    )

    completion = await client.chat.completions.parse(
        model=model,
        messages=messages,
        response_format=TurnIntent,
        **call_params(model, 0, max_tokens=2048),
    )

    intent = completion.choices[0].message.parsed
    if intent is None:
        refusal = completion.choices[0].message.refusal
        logger.warning(
            "QU returned no parsed TurnIntent (refusal=%r); falling back to META",
            refusal,
        )
        return TurnIntent(request_type=RequestType.META)

    # Post-process: canonicalize skill + sanity-check grade.
    intent = _postprocess(intent, canonicalizer)
    # Swap any bare deictic that leaked into skill.as_stated ("that", "those
    # paragraphs") for the referent it points at. A sibling of apply_ordinal_pick
    # so it fires regardless of routing — a follow-up QU sends to SCRIPTED_ML
    # directly is covered as well as one it routes through DEEPEN_PRIOR (which
    # resolves again in _merge_intent). Runs BEFORE the ordinal pick so the
    # deterministic pick's result is final and never second-guessed as a pointer
    # (an ordinal message carries no deictic here, so this is a no-op for it).
    intent = resolve_deictic_skill(intent, conversation, canonicalizer)
    # Then let arithmetic overrule the model on ordinal picks (see below).
    intent = apply_ordinal_pick(
        intent, new_user_message, conversation, canonicalizer
    )
    # Lesson-sequence continuation: when an active sequence is pending and the
    # teacher accepts the next lesson, fill the skill deterministically from the
    # sequence rather than asking QU to infer it. Same pattern as
    # apply_ordinal_pick — arithmetic/data over LLM judgment. Runs after the
    # ordinal pick (so an explicit ordinal wins) and before clarify_resume (so
    # a bare "yes" is interpreted as a continuation, not re-classified).
    intent = apply_lesson_sequence_continuation(
        intent, new_user_message, handshakes or SessionHandshakes(), canonicalizer, conversation
    )
    # Last: if the previous turn was a QUESTION we asked, a bare answer to it
    # belongs to the request that asked — not to a freshly-guessed one. Runs
    # after the two skill resolvers because it only ever rewrites request_type,
    # so it can neither disturb nor be disturbed by their result.
    intent = apply_clarify_resume(
        intent, new_user_message, conversation, canonicalizer
    )
    return intent


def apply_ordinal_pick(
    intent: TurnIntent,
    new_user_message: str,
    conversation: Conversation,
    canon: Canonicalizer,
) -> TurnIntent:
    """Resolve an ordinal pick against the list we actually offered.

    "Give me a lesson on number 4" is arithmetic over a list we rendered and
    recorded — not a judgment call. Leaving it to the model shipped item 3 to
    a teacher under a confident, correctly-titled lesson with no signal
    anything was wrong (drive session 16a8e8a5; a7ed9561 got the same input
    right, which is what a coin flip looks like).

    So when the message names exactly one in-range position, that item wins
    over whatever the model resolved. Everything else is left alone: a name
    or fuzzy title ("Snapple details") is genuine semantic matching and stays
    the model's call.

    ``as_stated`` becomes the offered item's own text. It is defined as the
    teacher's words for the skill, and a deictic is a pointer rather than
    vocabulary — the words they pointed at are the ones we put on screen.
    That also stops "Number 4" from being rendered as the lesson's title.
    """
    offered = _last_offered_skills(conversation)
    if not offered:
        return intent
    picked = resolve_ordinal_pick(new_user_message, offered)
    if picked is None:
        return intent
    # A HOW_TO_TEACH bullet is phrased at the teacher ("Teach students to
    # build a paragraph"); the skill it names is what belongs in the lesson.
    name = skill_name_from_offer(picked)
    return intent.model_copy(update={
        "skill": SkillSpec(
            canonical=canon.canonicalize_skill(name),
            as_stated=name,
        ),
        # We now know the skill, so it is no longer a gap to ask about.
        "missing_required": [f for f in intent.missing_required if f != "skill"],
    })


def _last_offered_skills(conversation: Conversation) -> list[str]:
    """The pick-list from the most recent assistant turn — and only that one.

    Deliberately NOT a backwards scan for the newest turn that happens to
    have a list: an ordinal refers to the list on screen, and scavenging
    history is what let "the list I just shared" be literally false.
    """
    for turn in reversed(conversation.turns):
        if turn.role is Role.ASSISTANT:
            return list(turn.offered_skills)
    return []


# ----------------------------------------------------------------------
# Clarify resume — an answer belongs to the question that asked for it
# ----------------------------------------------------------------------
#
# When the app asks "What grade level do you teach? What writing skill are you
# working on?" and the teacher replies "8th grade", QU re-classifies that bare
# answer FROM SCRATCH. It lands in COACHING (prompt rule 9 makes COACHING the
# catch-all for "ANY terse follow-up referencing a prior writing-related turn"),
# which is in neither _GRADE_REQUIRED nor _SKILL_REQUIRED — so the clarify gate
# never re-runs and the teacher gets coaching prose that INVENTS a skill instead
# of the lesson they were being asked to specify.
#
# Nothing pinned the answer to the question: SessionHandshakes.clarification is
# dead code (constructed only in tests), so QU's PENDING HANDSHAKES block is
# always empty. And the classification is a knife's edge — the same input routes
# SCRIPTED_ML via the live endpoint but COACHING 63/63 through a direct
# understand() call — so a prompt tweak could not fix it.
#
# "The last assistant turn was a question, and this message answers it" is a
# FACT. Same seam as apply_ordinal_pick: the emitting code records what it did
# (TurnOutcome.clarifying_for -> Turn.clarifying_for) and code, not the model,
# reads it back.

# A bare field answer is a short noun phrase — "8th grade", "topic sentences",
# "I teach 8th grade". Roomy enough for a natural echo of the question's own
# phrasing, far short of a request.
_MAX_BARE_ANSWER_WORDS = 6

# Brady's mode question ("Are you preparing for a persuasive, informative, or
# narrative unit?") is answered with one of its own three adjectives. Derived
# from the shared MODE_ADJECTIVES map rather than re-typed, so the answer
# vocabulary can never drift from the mode vocabulary the rest of the app uses.
_MODE_ADJECTIVE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(a) for a in sorted(MODE_ADJECTIVES.values())) + r")\b",
    re.IGNORECASE,
)

# The shapes that mean "this is a NEW REQUEST, not an answer".
#
# Deliberately PHRASES ("give me", "can you") and wh-words rather than bare
# verbs: the clarify questions contain "teach" ("What grade level do you
# TEACH?") and the most natural real answer echoes it ("I teach 8th grade"), so
# blocking the verb alone would reject the very message this rule exists to
# catch. A question mark or a wh-word, by contrast, is never part of a bare
# field answer — the teacher answering a question does not ask one back.
_NEW_REQUEST_MARKERS = re.compile(
    r"\?"
    r"|\b(?:how|what|why|when|where|which|who|whose)\b"
    r"|\b(?:actually|instead|nevermind)\b"
    r"|\bnever\s+mind\b"
    r"|\bforget\b"
    r"|\b(?:give|show|send|make|write|create|build|find)\s+me\b"
    r"|\b(?:can|could|would|will)\s+you\b"
    r"|\bi\s+(?:need|want|would\s+like)\b"
    r"|\bhelp\s+me\b"
    r"|\b(?:plan|outline|design)\s+(?:a|an|the|me)\b",
    re.IGNORECASE,
)


def _pending_clarify_type(
    conversation: Optional[Conversation],
) -> Optional[RequestType]:
    """The request_type the most recent assistant turn left hanging, or None.

    ONLY the most recent assistant turn counts, for the same reason the offered
    pick-list does: a question two turns ago has already been answered or
    abandoned, and resuming it would hijack the teacher's current message.
    """
    if conversation is None:
        return None
    last = conversation.last_assistant_turn()
    return last.clarifying_for if last is not None else None


def _supplies_a_field(message: str, canon: Canonicalizer) -> bool:
    """True when the message states a grade, a writing mode, or a known skill.

    Each check is deterministic and reuses the module that already owns that
    vocabulary — canonicalize_grade, MODE_ADJECTIVES, the Canonicalizer — so
    this adds no third opinion about what a grade or a skill is.

    The skill check is an exact resolution, which makes it NARROW on purpose: a
    skill the canonicalizer doesn't know ("using strong verbs") fails it and the
    turn is simply left to QU, exactly as today. Brady's asymmetry — silence is
    cheap, a wrong route is a lie — says to fail this way.
    """
    if canonicalize_grade(message) is not None:
        return True
    if _MODE_ADJECTIVE_RE.search(message):
        return True
    return canon.resolve(message).kind in (
        ResolutionKind.SKILL,
        ResolutionKind.TRIGGER,
    )


def _is_bare_field_answer(message: str, canon: Canonicalizer) -> bool:
    """True when the message is an ANSWER to a field question and nothing else.

    Three conditions, all required, mirroring resolve_ordinal_pick's "when in
    doubt, return None": it is SHORT, it carries no marker of a new request,
    and it actually supplies one of the fields a clarify asks about.
    """
    text = (message or "").strip()
    if not text:
        return False
    if len(text.split()) > _MAX_BARE_ANSWER_WORDS:
        return False
    if _NEW_REQUEST_MARKERS.search(text):
        return False
    return _supplies_a_field(text, canon)


def apply_clarify_resume(
    intent: TurnIntent,
    new_user_message: str,
    conversation: Conversation,
    canon: Canonicalizer,
) -> TurnIntent:
    """Restore the request_type a pending clarify was asked on behalf of.

    Fires only when a clarify is genuinely outstanding AND the teacher's reply
    is a bare field answer. On a match ONLY ``request_type`` is rewritten: the
    dispatcher's gate then re-runs and asks for whatever is STILL missing, or
    proceeds. Everything else — which grade, which skill — stays QU's job; it
    reads the whole conversation and is good at extraction. The defect is in
    ROUTING, and that is all this corrects.

    Generic by construction: the pending type is whatever the clarify recorded,
    so SCRIPTED_ML, HOW_TO_TEACH, PLAN_UNIT and MANAGEMENT are all covered by
    the same three lines — no per-type branch to forget.

    Worst case on a false negative is the status quo (the reply is left to QU).
    Worst case on a false positive is that the gate re-asks the same question,
    which is honest — as opposed to today's failure, which invents a skill.
    """
    pending = _pending_clarify_type(conversation)
    if pending is None or intent.request_type is pending:
        return intent
    if not _is_bare_field_answer(new_user_message, canon):
        return intent
    return intent.model_copy(update={"request_type": pending})


# ----------------------------------------------------------------------
# Lesson-sequence continuation — next skill is data, not inference
# ----------------------------------------------------------------------
#
# When an active PendingLessonSequence is present (the teacher requested a
# multi-lesson plan and at least one lesson has been delivered), a bare
# acceptance of the "Ready for Lesson N+1?" offer should route directly to
# SCRIPTED_ML with the NEXT skill already filled in. Leaving this to QU's
# LLM classification risks it being routed to COACHING (bare "yes" is a
# catch-all for the LLM) or asking for a skill that is already known.
#
# Same pattern as apply_ordinal_pick: the data is on hand (sequence.skills),
# and using code instead of the LLM makes the rule provably correct.

# Bare acceptances that mean "yes, generate the next lesson in the sequence".
# Deliberately narrow — a new request ("give me a lesson on X") must not match.
_SEQUENCE_ACCEPTANCE_RE = re.compile(
    r"^\s*(?:yes|yeah|yep|sure|ok|okay|ready|let'?s?\s+(?:do\s+)?(?:that|it)|go|go\s+ahead|sounds?\s+good|great|do\s+it|next|let'?s\s+go|continue|proceed)\s*[!.]?\s*$",
    re.IGNORECASE,
)

# Explicit next-lesson requests — e.g. "generate the next lesson plan", "next lesson", "continue with the next skill".
_EXPLICIT_NEXT_LESSON_RE = re.compile(
    r"\b(?:next\s+(?:mini[- ]?)?lesson(?:\s+plan)?|next\s+skill|next\s+one|next\s+step|"
    r"continue\s+(?:with\s+)?(?:the\s+)?(?:next\s+)?(?:sequence|lesson|plan|skill)|"
    r"move\s+(?:on\s+)?to\s+(?:the\s+)?next\s+(?:lesson|skill|plan)|"
    r"(?:give|generate|show|write|make)\s+(?:me\s+)?(?:the\s+)?next\s+(?:mini[- ]?)?lesson(?:\s+plan)?|"
    r"second\s+lesson|third\s+lesson|fourth\s+lesson|fifth\s+lesson|"
    r"lesson\s+[2-9]\b)\b",
    re.IGNORECASE,
)

_GENERIC_NEXT_PHRASES = frozenset({"next skill", "next lesson", "the next skill", "the next lesson", "next"})


def apply_lesson_sequence_continuation(
    intent: TurnIntent,
    new_user_message: str,
    handshakes: SessionHandshakes,
    canon: Canonicalizer,
    conversation: Optional[Conversation] = None,
) -> TurnIntent:
    """Fill intent.skill from the active lesson sequence when the teacher
    accepts or requests the next-lesson offer.

    Fires when:
      1. A PendingLessonSequence is active in the session handshakes.
      2. There is a next lesson to deliver (current_index + 1 < total).
      3. EITHER:
         (a) The teacher explicitly requests the next lesson/skill
             ("generate the next lesson plan", "next skill", "continue sequence").
             This works EVEN IF an intervening turn occurred.
         (b) The teacher provides a bare acceptance ("yes", "sure", "ready")
             AND the last assistant turn was a sequence prompt.

    When it fires, it rewrites the intent to SCRIPTED_ML with the next
    skill already set, so the dispatcher routes straight to generation
    without any clarify gate. When it does NOT fire, the intent is
    returned unchanged.
    """
    seq = handshakes.lesson_sequence
    if seq is None:
        return intent

    msg = (new_user_message or "").strip()
    is_explicit = bool(_EXPLICIT_NEXT_LESSON_RE.search(msg))
    is_bare_accept = bool(_SEQUENCE_ACCEPTANCE_RE.fullmatch(msg))

    if not is_explicit and not is_bare_accept:
        return intent

    # If QU already extracted an explicit skill from the user message that differs from
    # the expected sequence skill, do NOT override it with sequence continuation —
    # UNLESS the extracted skill is just a generic pointer like "next skill".
    if intent.skill is not None and intent.skill.as_stated:
        as_stated_clean = intent.skill.as_stated.strip().lower()
        if as_stated_clean not in _GENERIC_NEXT_PHRASES and not _EXPLICIT_NEXT_LESSON_RE.search(as_stated_clean):
            next_idx = seq.current_index + 1
            if 0 <= next_idx < seq.total:
                exp_skill = seq.skills[next_idx]
                if canon.canonicalize_skill(intent.skill.as_stated) != canon.canonicalize_skill(exp_skill):
                    return intent

    # For a bare acceptance ("yes", "sure"), verify that the LAST assistant turn was actually
    # prompting for the sequence next lesson. If an intervening turn occurred where the assistant
    # asked a different question (e.g. coaching), a bare "yes" belongs to THAT latest question.
    # An explicit request ("generate the next lesson plan") is unambiguous and does not require this check.
    if not is_explicit and conversation is not None:
        last_turn = conversation.last_assistant_turn()
        if last_turn is not None and last_turn.text:
            last_text = last_turn.text.lower()
            is_seq_prompt = any(
                phrase in last_text
                for phrase in (
                    "ready for lesson",
                    "of 2.",
                    "of 3.",
                    "of 4.",
                    "of 5.",
                    "of 6.",
                    "of 7.",
                    "of 8.",
                    "of 9.",
                    "of 10.",
                    "scripting these",
                    "start scripting",
                )
            )
            if not is_seq_prompt:
                return intent

    next_index = seq.current_index + 1
    if next_index >= seq.total:
        # Last lesson was already delivered — nothing more to fill in.
        return intent
    next_skill_text = seq.skills[next_index]
    canonical = canon.canonicalize_skill(next_skill_text)
    return intent.model_copy(update={
        "request_type": RequestType.SCRIPTED_ML,
        "skill": SkillSpec(
            canonical=canonical,
            as_stated=next_skill_text,
        ),
        "refers_to_prior": True,
        # The skill is unambiguous — no confirmation or clarification needed.
        "needs_confirmation": False,
        "missing_required": [],
    })


# ----------------------------------------------------------------------
# Deictic resolution — a pointer is not vocabulary
# ----------------------------------------------------------------------
#
# On a DEEPEN_PRIOR follow-up ("give me more on that") QU sometimes writes the
# bare deictic into ``skill.as_stated`` while ``canonical`` stays resolved.
# scripted_ml_prompt renders as_stated verbatim into ``skill_focus`` and Step 1
# ("Today we're going to focus on that."), and the vocab safety net certifies it
# (`"that" in "that"`). A deictic points at the prior lesson; it is not the
# teacher's word for a skill. We swap it for the referent BEFORE generation.

# The tight set. A bare pointer is one of these words alone; a *leading*
# determiner ("those paragraphs", "that skill") is a pointer only when the whole
# phrase does not canonicalize to a known skill/trigger (checked below). "it" is
# a bare pointer only — never a determiner phrase.
_DEICTIC_DETERMINERS: frozenset[str] = frozenset({"that", "this", "these", "those"})
_BARE_DEICTICS: frozenset[str] = _DEICTIC_DETERMINERS | {"it"}

# A deictic noun phrase is short — a determiner + a light head, maybe a modifier
# or two ("those two short paragraphs"). A longer clause that merely opens with a
# determiner ("Those transition words matter for readers") is a real skill
# objective, not a pointer, so it is NEVER rewritten. This bounds the one place
# the resolver could clobber a legitimate skill — e.g. a determiner-led item a
# teacher just picked by ordinal off a list. Measured: without this, "number 2"
# → "Those transition words…" was silently rewritten to the prior lesson's skill.
_DEICTIC_PHRASE_MAX_WORDS = 4

_GENERIC_POINTER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:above|provided|mentioned|listed|previous|prior|next\s+skill|next\s+lesson)\b", re.IGNORECASE),
    re.compile(r"^\s*(?:the\s+)?(?:skills?|lessons?|plans?|strategy|strategies)(?:\s+(?:you\s+)?(?:provide[ds]?|mention(?:ed)?|list(?:ed)?|above))*\s*$", re.IGNORECASE),
)


def _normalize_deictic(text: Optional[str]) -> str:
    """Lowercase, collapse whitespace, and drop surrounding punctuation so
    "That." and " those " compare cleanly. Internal hyphens/apostrophes are
    preserved (they belong to real skill phrases)."""
    collapsed = " ".join((text or "").lower().split())
    return collapsed.strip(".,!?;:\"'()[]")


def _is_deictic_pointer(text: Optional[str], canon: Canonicalizer) -> bool:
    """True when ``text`` is a bare deictic pointer, a leading deictic-
    determiner phrase, or a generic backward-referencing pointer phrase
    ("the skills you provide above", "the mentioned skills", etc.) that
    names no known skill/trigger."""
    norm = _normalize_deictic(text)
    if not norm:
        return False
    if norm in _BARE_DEICTICS:
        return True
    if any(p.search(norm) for p in _GENERIC_POINTER_PATTERNS):
        resolution = canon.resolve(norm)
        if resolution.kind not in (ResolutionKind.SKILL, ResolutionKind.TRIGGER):
            return True
    tokens = norm.split()
    if (
        1 < len(tokens) <= _DEICTIC_PHRASE_MAX_WORDS
        and tokens[0] in _DEICTIC_DETERMINERS
    ):
        resolution = canon.resolve(norm)
        return resolution.kind not in (
            ResolutionKind.SKILL,
            ResolutionKind.TRIGGER,
        )
    return False


def _last_user_intent(conversation: Optional[Conversation]) -> Optional[TurnIntent]:
    """The most recent user turn's intent, or None. Used as a secondary
    referent source when there is no scripted-ML turn to inherit from."""
    if conversation is None:
        return None
    for turn in reversed(conversation.turns):
        if turn.role is Role.USER and turn.intent is not None:
            return turn.intent
    return None


def _resolve_deictic_referent(
    intent: TurnIntent,
    conversation: Optional[Conversation],
    canon: Canonicalizer,
    prior_intent: Optional[TurnIntent],
) -> Optional[str]:
    """Find the skill a deictic points at, in priority order:

      1. the prior scripted-ML turn's ``skill_focus`` (the actual lesson on screen),
      2. the prior assistant turn's first offered skill (if an outline was on screen),
      3. the prior user turn's ``skill.as_stated`` if non-deictic,
      4. this turn's own ``skill.canonical`` if it stayed resolved.

    Returns None when nothing non-deictic is available — the caller then leaves
    the pointer rather than inventing a skill.
    """
    # 1. prior scripted-ML turn's skill_focus
    if conversation is not None:
        prior_ml = conversation.last_scripted_ml_turn()
        if prior_ml is not None:
            skill_focus = (prior_ml.structured or {}).get("skill_focus")
            if (
                isinstance(skill_focus, str)
                and skill_focus.strip()
                and not _is_deictic_pointer(skill_focus, canon)
            ):
                return skill_focus

    # 2. prior assistant turn's offered_skills (if prior turn was outline/list)
    if conversation is not None and conversation.turns:
        last_ast = conversation.last_assistant_turn()
        if last_ast is not None and last_ast.offered_skills:
            first_offered = last_ast.offered_skills[0]
            if (
                isinstance(first_offered, str)
                and first_offered.strip()
                and not _is_deictic_pointer(first_offered, canon)
            ):
                from handlers.picklist import skill_name_from_offer
                return skill_name_from_offer(first_offered)

    # 3. prior user turn's intent skill (when no scripted ML turn)
    pi = prior_intent if prior_intent is not None else _last_user_intent(conversation)
    if pi is not None and pi.skill is not None:
        prior_as_stated = pi.skill.as_stated
        if (
            isinstance(prior_as_stated, str)
            and prior_as_stated.strip()
            and not _is_deictic_pointer(prior_as_stated, canon)
        ):
            return prior_as_stated

    # 4. this turn's own canonical, if it did not also degrade to a deictic
    canonical = intent.skill.canonical if intent.skill is not None else None
    if (
        isinstance(canonical, str)
        and canonical.strip()
        and not _is_deictic_pointer(canonical, canon)
    ):
        return canonical

    return None


def resolve_deictic_skill(
    intent: TurnIntent,
    conversation: Optional[Conversation],
    canon: Canonicalizer,
    *,
    prior_intent: Optional[TurnIntent] = None,
) -> TurnIntent:
    """Replace a deictic ``skill.as_stated`` with the skill it points at.

    A no-op unless ``skill.as_stated`` is a bare deictic pointer (or a leading
    deictic phrase that names no skill) AND a non-deictic referent exists. When
    no referent is resolvable the intent is returned unchanged — we never invent
    a skill from a bare pointer.

    ``prior_intent`` lets the DEEPEN_PRIOR handler pass the prior user intent it
    already located; otherwise it is derived from ``conversation``.
    """
    if intent.skill is None:
        return intent
    if not _is_deictic_pointer(intent.skill.as_stated, canon):
        return intent
    referent = _resolve_deictic_referent(intent, conversation, canon, prior_intent)
    if referent is None:
        return intent
    return intent.model_copy(
        update={
            "skill": SkillSpec(
                canonical=canon.canonicalize_skill(referent),
                as_stated=referent,
                stated_turn=intent.skill.stated_turn,
                confidence=intent.skill.confidence,
            )
        }
    )


# ----------------------------------------------------------------------
# Message construction — kept small + pure for unit-testability
# ----------------------------------------------------------------------


def _build_messages(
    *,
    conversation: Conversation,
    new_user_message: str,
    handshakes: SessionHandshakes,
) -> list[dict[str, str]]:
    """Compose the system + user message pair for the LLM call.

    Ordering matters for prompt caching: the stable system prompt goes
    first, followed by the conversation history (stable after each
    turn), followed by the new user message (always fresh). OpenAI's
    automatic cache requires this prefix stability.
    """
    system = {"role": "system", "content": get_system_prompt()}

    user_content_parts: list[str] = []

    # Conversation history (flattened)
    if conversation.turns:
        user_content_parts.append("=== CONVERSATION HISTORY ===")
        user_content_parts.append(_render_conversation(conversation))

    # Pending handshakes
    if not handshakes.is_empty():
        user_content_parts.append("=== PENDING HANDSHAKES ===")
        user_content_parts.append(_render_handshakes(handshakes))

    # The new user message
    user_content_parts.append("=== NEW USER MESSAGE ===")
    user_content_parts.append(new_user_message)
    user_content_parts.append(
        f"=== INSTRUCTION ===\n"
        f"Produce a TurnIntent for this new user message. Current turn "
        f"index would be {len(conversation.turns)}. Use conversation "
        f"context to inherit fields (grade, skill) when the teacher "
        f"already stated them in earlier turns. Output ONLY the "
        f"TurnIntent per the schema."
    )

    user = {"role": "user", "content": "\n\n".join(user_content_parts)}
    return [system, user]


def _render_conversation(conversation: Conversation) -> str:
    """Flatten conversation turns into LLM-readable text.

    For assistant turns with structured bodies (SCRIPTED_ML, HOW_TO_TEACH
    with offered_skills), we include BOTH the rendered text AND a
    compact JSON summary of the structured fields. QU needs to see
    structured.skill_focus for DEEPEN_PRIOR inheritance and
    structured.offered_skills for pickup-matching.
    """
    parts: list[str] = []
    for turn in conversation.turns:
        header = f"[Turn {turn.index}] {turn.role.value.upper()}"
        if turn.quality.value != "valid":
            header += f" (quality={turn.quality.value})"
        parts.append(header)
        parts.append(turn.text)

        if turn.role is Role.ASSISTANT and turn.offered_skills:
            # The pick-list this turn actually showed, numbered as the teacher
            # saw it. QU resolves ordinals against this instead of re-counting
            # markdown. Deterministic resolution runs anyway (picklist.py) —
            # this keeps QU's own view honest for name/fuzzy picks.
            import json
            parts.append(
                f"[Turn {turn.index} offered_skills] "
                f"{json.dumps(turn.offered_skills)}"
            )

        if turn.role is Role.ASSISTANT and turn.structured:
            # Compact structured summary — just the fields QU needs.
            # NOTE: "offered_skills" is deliberately absent here. No handler
            # has ever written it into `structured`, and a key that nothing
            # populates reads as a live feature while carrying no data — the
            # exact defect this module's offered_skills field replaces.
            summary_fields = {}
            for key in ("skill_focus", "grade", "mode",
                        "trait", "trigger", "cited_page"):
                if key in turn.structured:
                    summary_fields[key] = turn.structured[key]
            if summary_fields:
                import json
                parts.append(f"[Turn {turn.index} structured] {json.dumps(summary_fields)}")

        parts.append("")  # blank line between turns
    return "\n".join(parts)


def _render_handshakes(handshakes: SessionHandshakes) -> str:
    """Render pending handshakes as plain text. QU uses these to
    interpret the user's new message correctly (e.g., 'yes' as a
    confirmation answer rather than an independent intent)."""
    parts: list[str] = []
    if handshakes.library_offer:
        lo = handshakes.library_offer
        parts.append(
            f"- Library offer pending: ml_id={lo.ml_id}, skill={lo.skill}, "
            f"grade={lo.grade}, offered at turn {lo.offered_at_turn}"
        )
    if handshakes.ml_confirmation:
        mc = handshakes.ml_confirmation
        parts.append(
            f"- ML confirmation pending: skill={mc.skill}, grade={mc.grade}, "
            f"mode={mc.mode}, asked at turn {mc.asked_at_turn}"
        )
    if handshakes.clarification:
        cl = handshakes.clarification
        parts.append(
            f"- Clarification pending: waiting_for={cl.waiting_for}, "
            f"asked at turn {cl.asked_at_turn}"
        )
    if handshakes.lesson_sequence:
        seq = handshakes.lesson_sequence
        next_idx = seq.current_index + 1
        if next_idx < seq.total:
            next_skill = seq.skills[next_idx]
            if seq.current_index == -1:
                # No lesson delivered yet — plan was just offered
                parts.append(
                    f"- Active lesson sequence: {seq.total}-lesson plan just generated. "
                    f"NO lessons delivered yet. Lesson 1 is: {next_skill!r}. "
                    f"If the teacher says yes/sure/ready or asks for the next lesson plan, route to SCRIPTED_ML "
                    f"with skill={next_skill!r}. Do NOT ask for grade or skill."
                )
            else:
                parts.append(
                    f"- Active lesson sequence: {seq.total}-lesson plan, "
                    f"Lesson {seq.current_index + 1} of {seq.total} just delivered. "
                    f"Next (Lesson {next_idx + 1}) is: {next_skill!r}. "
                    f"If the teacher says yes/sure/ready, asks for the next lesson, or says continue/next skill, "
                    f"route to SCRIPTED_ML with skill={next_skill!r}. Do NOT ask for grade or skill. "
                    f"If the teacher asks to revise/simplify or asks questions about the current lesson, "
                    f"address that lesson while keeping this sequence active."
                )
        else:
            parts.append(
                f"- Lesson sequence COMPLETE: all {seq.total} lessons delivered."
            )
    return "\n".join(parts)


# ----------------------------------------------------------------------
# Post-processing — safety nets run after the LLM
# ----------------------------------------------------------------------


def _postprocess(intent: TurnIntent, canon: Canonicalizer) -> TurnIntent:
    """Canonicalize skill names, validate meta-technique exclusion.

    Run AFTER the LLM produces a TurnIntent. These are safety nets for
    when the LLM emits a non-canonical form or accidentally puts a
    meta-technique in skill despite the prompt rule.
    """
    # Skill: re-canonicalize and reject meta-techniques
    if intent.skill is not None:
        raw = intent.skill.canonical
        resolution = canon.resolve(raw)

        if resolution.kind is ResolutionKind.META_TECHNIQUE:
            # LLM emitted a meta-technique as skill — null it out.
            # DEEPEN_PRIOR handler should inherit skill from prior turn.
            logger.warning(
                "QU emitted meta-technique %r as skill; nulling. "
                "request_type=%s should inherit from prior turn.",
                raw,
                intent.request_type,
            )
            # Use model_copy to mutate the frozen SkillSpec indirectly
            intent = intent.model_copy(update={"skill": None})
        else:
            # Normalize to canonical form
            canonical = resolution.canonical
            if canonical != raw:
                new_skill = SkillSpec(
                    canonical=canonical,
                    as_stated=intent.skill.as_stated,
                    stated_turn=intent.skill.stated_turn,
                    confidence=intent.skill.confidence,
                )
                intent = intent.model_copy(update={"skill": new_skill})

    # Required triggers: canonicalize each entry, drop unresolved
    if intent.required_triggers:
        canon_triggers: list[str] = []
        for raw_trigger in intent.required_triggers:
            resolved = canon.canonicalize_trigger(raw_trigger)
            if resolved:
                canon_triggers.append(resolved)
            else:
                logger.debug(
                    "QU emitted unrecognized trigger %r; dropping",
                    raw_trigger,
                )
        if canon_triggers != intent.required_triggers:
            intent = intent.model_copy(
                update={"required_triggers": canon_triggers}
            )

    return intent
