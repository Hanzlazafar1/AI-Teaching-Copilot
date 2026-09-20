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

import re
from typing import Any, Awaitable, Callable, Optional

from openai import AsyncOpenAI

from canonicalizer import Canonicalizer
from handlers._base_text import (
    make_markdown_validators,
    run_text_handler_with_retry,
)
from handlers._prompt_rules import (
    FRUSTRATION_VALIDATION_RULE,
    FULFILL_OFFERED_DELIVERABLES_RULE,
    GLOBAL_VOCAB_RULES,
    SKILL_ORDER_AFFIRM_RULE,
)
from handlers.formatting import MODE_ADJECTIVES, format_unit_opening
from handlers._retrieval import run_retrieval
from handlers.picklist import extract_offered_skills
from schemas import (
    Conversation,
    PendingLessonSequence,
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

Then a NUMBERED LIST of Smekens priority skills drawn from retrieved context
(typically 3-7 items, unless a specific N-day or N-lesson plan is requested
under LESSON COUNT below, in which case produce EXACTLY N items). Each item
is ONE skill name; optional half-sentence gloss only if the skill name is unfamiliar.

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

  * A daily calendar ("Day 1: X, Day 2: Y") — unless the teacher explicitly requested or accepted a chart/table/calendar breakdown of the plan
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
    parts: list[str] = [
        _PLAN_UNIT_RULES,
        SKILL_ORDER_AFFIRM_RULE,
        GLOBAL_VOCAB_RULES,
        FULFILL_OFFERED_DELIVERABLES_RULE,
    ]

    # Look for requested lesson/day count in conversation history or intent
    lesson_count = None
    if conversation and conversation.turns:
        for turn in reversed(conversation.turns):
            if turn.role.value == "user" and turn.text:
                count = _extract_lesson_count(turn.text)
                if count is not None:
                    lesson_count = count
                    break

    if lesson_count is not None:
        parts.append(
            f"=== LESSON COUNT / PLAN DURATION ===\n"
            f"The teacher explicitly requested a {lesson_count}-lesson / {lesson_count}-day plan.\n"
            f"Produce a numbered list of EXACTLY {lesson_count} priority skills/lessons mapped sequentially across the unit.\n"
            f"=== END LESSON COUNT ==="
        )

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


_WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "a": 1, "an": 1,
}

# Detect "10-day", "10 day", "10-lesson", "one week", "5-day", "7 days", "one month" etc.
# in the teacher's message so we know to create a lesson sequence.
_LESSON_COUNT_RE = re.compile(
    r"\b(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|a|an)[\s-]*(day|lesson|week|month)[s]?\b",
    re.IGNORECASE,
)


def _extract_lesson_count(message: str) -> Optional[int]:
    """Return the N in a 'N-day / N-lesson / N-week / N-month' plan request, or None.

    Deliberately narrow: only fires on a plausible lesson-count (2–30).
    Converts 'one week' / '1 week' -> 5 school days.
    Converts 'one month' / '1 month' -> 20 school days.
    """
    m = _LESSON_COUNT_RE.search(message or "")
    if m is None:
        return None
    raw_num, unit = m.group(1).lower(), m.group(2).lower()
    if raw_num.isdigit():
        val = int(raw_num)
    else:
        val = _WORD_TO_NUM.get(raw_num, 0)
    if val <= 0:
        return None
    if unit == "week":
        val *= 5
    elif unit == "month":
        val *= 20
    return val if 2 <= val <= 30 else None


def _trim_plan_to_lesson_count(text: str, lesson_count: int) -> str:
    """Deterministically trim a numbered plan list if the generator emitted
    more items than requested (e.g. 10 items when 5 were requested)."""
    if not text or lesson_count <= 0:
        return text
    
    lines = text.split("\n")
    trimmed_lines: list[str] = []
    item_counter = 0
    in_list = False
    
    for line in lines:
        m = re.match(r"^(\s*)(\d+)\.\s+(.*)$", line)
        if m:
            in_list = True
            num = int(m.group(2))
            if num > lesson_count:
                # Drop items numbered past lesson_count
                continue
            item_counter += 1
            trimmed_lines.append(line)
        else:
            if in_list and item_counter >= lesson_count:
                # Drop blank lines right after dropped list items until trailing content
                if not line.strip():
                    continue
            trimmed_lines.append(line)

    return "\n".join(trimmed_lines)


def _build_prompt(
    intent: TurnIntent,
    retrieved_context: str,
    conversation: Conversation,
    repair_feedback: Optional[str],
    new_user_message: str = "",
) -> str:
    parts: list[str] = [
        _PLAN_UNIT_RULES,
        SKILL_ORDER_AFFIRM_RULE,
        GLOBAL_VOCAB_RULES,
        FULFILL_OFFERED_DELIVERABLES_RULE,
    ]

    # Look for requested lesson/day count in new_user_message or conversation history
    lesson_count = _extract_lesson_count(new_user_message)
    if lesson_count is None and conversation and conversation.turns:
        for turn in reversed(conversation.turns):
            if turn.role.value == "user" and turn.text:
                count = _extract_lesson_count(turn.text)
                if count is not None:
                    lesson_count = count
                    break

    if lesson_count is not None:
        parts.append(
            f"=== LESSON COUNT / PLAN DURATION ===\n"
            f"The teacher explicitly requested a {lesson_count}-lesson / {lesson_count}-day plan.\n"
            f"Produce a numbered list of EXACTLY {lesson_count} priority skills/lessons mapped sequentially across the unit.\n"
            f"=== END LESSON COUNT ==="
        )

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

    prompt_builder = lambda intent, ctx, conv, fb: _build_prompt(
        intent, ctx, conv, fb, new_user_message=new_user_message
    )

    outcome = await run_text_handler_with_retry(
        intent=intent,
        conversation=conversation,
        new_user_message=new_user_message,
        retrieved_context=retrieved_context,
        grounding=grounding,
        prompt_builder=prompt_builder,
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

    # Multi-lesson sequence detection: if the teacher requested an N-day or
    # N-lesson plan (or Co-Pilot generated a list of priority skills), create a
    # PendingLessonSequence so each subsequent "yes" routes directly to
    # SCRIPTED_ML with the next skill pre-filled.
    lesson_count = _extract_lesson_count(new_user_message)
    if lesson_count is None and conversation and conversation.turns:
        for turn in reversed(conversation.turns):
            if turn.role.value == "user" and turn.text:
                count = _extract_lesson_count(turn.text)
                if count is not None:
                    lesson_count = count
                    break

    # If lesson_count is set, trim response text to lesson_count items if generator produced more
    response_text = outcome.response_text
    if lesson_count is not None:
        response_text = _trim_plan_to_lesson_count(response_text, lesson_count)
        if response_text != outcome.response_text:
            outcome = outcome.model_copy(update={"response_text": response_text})

    if intent.grade is not None:
        skills = extract_offered_skills(outcome.response_text)
        if skills:
            if lesson_count is not None:
                skills = skills[:lesson_count]
            first_skill = skills[0] if skills else ""
            sequence = PendingLessonSequence(
                skills=skills,
                total=len(skills),
                current_index=-1,  # No lesson delivered yet; first "yes" -> index 0
                grade=intent.grade.value,
                mode=intent.mode.value if intent.mode else None,
                started_at_turn=len(conversation.turns),
            )
            updated_handshakes = handshakes.model_copy(
                update={"lesson_sequence": sequence}
            )
            # Append a prompt that tells the teacher we're ready to script
            # the first lesson, so "yes" will be clearly understood.
            offer = (
                f"\n\nWant me to start scripting these one lesson at a time? "
                f"I\'ll begin with Lesson 1 — {first_skill}."
            )
            return outcome.model_copy(update={
                "response_text": outcome.response_text.rstrip() + offer,
                "handshake_updates": updated_handshakes,
            })

    return outcome

