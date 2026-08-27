"""PLAN_UNIT handler — sequenced priority-skill list for a mode/grade.

NOT a daily calendar. NOT a lesson. Produces a numbered list of skills a
teacher can use as a scope-and-sequence for the year or quarter, with
mini-unit framing. Ends with an offer to produce a lesson on one of them.

Examples:
  - "Plan a 4th grade persuasive unit"
  - "What skills should I focus on for 2nd grade narrative?"
  - "Scope and sequence for informational writing in 3rd grade?"
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from openai import AsyncOpenAI

from canonicalizer import Canonicalizer
from handlers._base_text import (
    make_markdown_validators,
    run_text_handler_with_retry,
)
from handlers._prompt_rules import (
    FRUSTRATION_VALIDATION_RULE,
    GLOBAL_VOCAB_RULES,
    SKILL_ORDER_AFFIRM_RULE,
)
from handlers.formatting import MODE_ADJECTIVES, format_unit_opening
from handlers._retrieval import run_retrieval
from schemas import (
    Conversation,
    SessionHandshakes,
    TurnIntent,
    TurnOutcome,
)


# Brady S4 is about EXCLUSIVITY — a LESSON covers ONE SKILL — never cardinality.
# The "Each skill is its own lesson" block below deliberately does NOT say "one
# lesson per skill" or "taught one at a time". We shipped that gloss, and it is
# the CONVERSE of his rule:
#
#   S4 (47:00, doc 191), verbatim: "Our response needs to always come back to
#   the idea that each priority skill is its own individual lesson."
#   On what a lesson covers (transcript @29143): "mini-lessons are focused on
#   one skill, one aspect, one ingredient... adding in the why would come in a
#   second or future mini-lesson."
#
# Both constrain what ONE LESSON may contain. Neither caps how many lessons a
# skill gets — and the converse contradicts his #1 new ask, the mini-lesson
# SERIES: "1 skill requires 2-4 days (most commonly 3)" (doc 434), and @32152
# "determine the strongest side... on another day... So I have three days for
# that same skill."
#
# A skill may need several lessons. What it must never do is share one with
# another skill. `test_prompts_never_invert_bradys_one_skill_rule` locks the
# direction; handlers/formatting.py's S3 guard ("one skill at a time") is the
# correct phrasing of the same rule.
_PLAN_UNIT_RULES = """\
You are Brady's AI Writing Co-Pilot producing a PRIORITY-SKILL SEQUENCE
for a writing unit. You are NOT writing a unit plan with daily
breakdowns. You are producing a numbered skill list the teacher can use
as scope-and-sequence.

## Output shape (strictly)

Your opening sentence is given to you verbatim under OPENING SENTENCE
below. Use it EXACTLY as written — do not add a grade, a writing mode, or
any other detail to it. It already names everything the teacher told us,
and nothing they didn't.

Then a NUMBERED LIST (3-7 items) of Smekens priority skills drawn from
retrieved context. Each item is ONE skill name; optional half-sentence
gloss only if the skill name is unfamiliar.

After the list, one framing paragraph (1-2 sentences) along the lines of:
"These are taught in mini-units of 1-2 weeks each, focusing on 1-2 skills
per unit, layered and spiraled across the year."

END with EXACTLY:

  Is this helpful? Would you like a general outline of this unit?

## Grounding

Use the retrieved Smekens Essential Skills / PIE / scope-and-sequence
content to select priority skills. Do NOT invent skills not present in
retrieval. If the mode is persuasive/informational/narrative, prefer the
trait-organized skill list for that mode.

## Forbidden vocabulary

Never use "discuss", "discussion", "activities", "activity",
"I'll listen in", "professional development", "certificate".

## Teacher-facing language

The teacher is a classroom educator, not a developer. Never expose
internal system vocabulary — BANNED: "chunks", "retrieved context",
"retrieved chunks", "indexed", "corpus", "retrieval", "retrieved
material", "trigger" (in the system sense), "embedding". Use teacher-
register phrasing: "the Launch book material I have", "from the
excerpts I can see", "I can't confirm that directly from what I have
in front of me".

## Do NOT produce

  * A daily calendar ("Day 1: X, Day 2: Y") — this is SCOPE, not a calendar
  * A scripted mini-lesson — that's SCRIPTED_ML
  * A HOW_TO_TEACH outline for one skill — that's a different request_type
  * A paragraph of prose instead of a numbered list

## Each skill is its own lesson (always)

Whenever multiple skills are in play, keep coming back to the idea that
each priority skill is its own individual lesson. Never bundle several
skills into a single lesson.

## Stay consistent with your prior overview

On a follow-up, keep the skills consistent with the overview you just
gave and reference the same named skills. When the teacher asked about
skills, keep talking about skills — do NOT silently drift to units.
"""


def _build_prompt(
    intent: TurnIntent,
    retrieved_context: str,
    conversation: Conversation,
    repair_feedback: Optional[str],
) -> str:
    parts: list[str] = [_PLAN_UNIT_RULES, SKILL_ORDER_AFFIRM_RULE, GLOBAL_VOCAB_RULES]

    # Brady C10 (dogfood C10): validate the emotion FIRST when the teacher voiced
    # frustration. Gated on the deterministic expressed_frustration QU signal —
    # a no-op on a calm turn (same conditional-splice pattern as the shared
    # rules above). Orthogonal to request_type, so it covers a frustrated
    # unit-planning ask that lands here instead of COACHING.
    if intent.expressed_frustration:
        parts.append(FRUSTRATION_VALIDATION_RULE)

    # The opening is CONSTRUCTED, not substituted: it names only what the
    # teacher actually gave, so an unknown grade/mode cannot be invented into it
    # (see handlers/formatting.py::format_unit_opening for the measured defect).
    parts.append(
        "=== OPENING SENTENCE (use verbatim, add nothing) ===\n"
        + format_unit_opening(
            intent.grade.value if intent.grade else None,
            intent.mode.value if intent.mode else None,
        )
    )

    session_lines: list[str] = ["=== SESSION CONTEXT ==="]
    if intent.grade:
        session_lines.append(f"Grade: {intent.grade.value}")
    else:
        session_lines.append("Grade: (not specified)")
    if intent.mode:
        # Brady's Fm4 rule: the teacher never sees the internal token. The raw
        # ModeSpec enum ("Persuade") leaked straight into prose ("For K-2
        # persuade writing") whenever the model improvised this sentence.
        session_lines.append(
            f"Writing mode: {MODE_ADJECTIVES.get(intent.mode.value, intent.mode.value)}"
        )
    else:
        session_lines.append("Writing mode: (not specified)")
    if intent.trait:
        session_lines.append(f"Writing trait: {intent.trait.value}")
    if intent.required_triggers:
        session_lines.append(
            f"Named Smekens triggers: {', '.join(intent.required_triggers)}"
        )
    session_lines.append("=== END SESSION CONTEXT ===")
    parts.append("\n".join(session_lines))

    if conversation.turns:
        parts.append("=== CONVERSATION (recent turns) ===")
        for t in conversation.turns:
            body = (t.text or "").strip()
            parts.append(f"[Turn {t.index}] {t.role.value.upper()}: {body}")
        parts.append("=== END CONVERSATION ===")

    if retrieved_context:
        parts.append("=== RETRIEVED CONTEXT ===")
        parts.append(retrieved_context)
        parts.append("=== END RETRIEVED CONTEXT ===")

    if repair_feedback:
        parts.append("=== PREVIOUS ATTEMPT FAILED ===")
        parts.append(repair_feedback)
        parts.append("=== END REPAIR ===")

    return "\n\n".join(parts)


async def handle_plan_unit(
    intent: TurnIntent,
    conversation: Conversation,
    handshakes: SessionHandshakes,
    new_user_message: str,
    *,
    client: AsyncOpenAI,
    model: str,
    canonicalizer: Canonicalizer,
    retrieval_fn: Optional[Callable[..., Awaitable[Any]]] = None,
    library: Optional[Any] = None,
) -> TurnOutcome:
    _, retrieved_context, grounding = await run_retrieval(
        intent=intent,
        query_text=new_user_message,
        query_type_label="PLAN_UNIT",
        retrieval_fn=retrieval_fn,
    )

    required_triggers = list(intent.required_triggers)

    return await run_text_handler_with_retry(
        intent=intent,
        conversation=conversation,
        new_user_message=new_user_message,
        retrieved_context=retrieved_context,
        grounding=grounding,
        prompt_builder=_build_prompt,
        validators=make_markdown_validators(
            intent=intent,
            query_type="PLAN_UNIT",
            retrieved_context=retrieved_context,
            required_triggers=required_triggers,
        ),
        client=client,
        model=model,
        temperature=0.3,
        log_label="plan_unit",
        query_type="PLAN_UNIT",
    )
