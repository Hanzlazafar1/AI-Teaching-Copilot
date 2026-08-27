"""THINK_ALOUD handler — Step 2B-style monologue alone.

The teacher asked explicitly for a think-aloud (not a full lesson). We
produce the monologue a teacher would say out loud while modelling a
writerly decision — a window into the writer's head, NOT a wrapped
4-step mini-lesson.

Examples:
  - "Show me a think-aloud for adding sensory details"
  - "Model your thinking for picking a stronger verb"
  - "What would the think-aloud sound like for this skill?"

Output shape: narrative prose in first-person voice, 180-320 words,
ending with an offer to wrap it in a full lesson (so the teacher can
pivot to SCRIPTED_ML without re-stating the skill).
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from openai import AsyncOpenAI

from canonicalizer import Canonicalizer
from handlers._base_text import (
    make_markdown_validators,
    run_text_handler_with_retry,
)
from handlers._prompt_rules import FRUSTRATION_VALIDATION_RULE, GLOBAL_VOCAB_RULES
from handlers._retrieval import run_retrieval
from schemas import (
    Conversation,
    SessionHandshakes,
    TurnIntent,
    TurnOutcome,
)


_THINK_ALOUD_RULES = """\
You are Brady's AI Writing Co-Pilot. The teacher has asked for a
THINK-ALOUD alone — the internal monologue a writer speaks aloud while
making one concrete writerly choice. NOT a full 4-step mini-lesson.

## Output shape & length

A single block of first-person narrative prose.

**Length is determined by what the teacher asked for.** First decide
which case applies, then write to that length — do NOT default to a
shorter response because "that's usually how long think-alouds are."

CASE 1 — Teacher specified a duration (minutes) or a period/class:
  Teachers speak at ~150 words per minute. The monologue MUST hit at
  least that word count — a FLOOR, not a target. Err toward MORE
  detail, MORE weighing of alternatives, MORE self-correction, MORE
  grappling with word choice. Fill the time with thinking, not filler.
  Over-writing is fine here — a teacher can trim during delivery but
  cannot invent more teacher-thinking on the fly.
    • "five minutes"        → at least 700 words (aim 700-800)
    • "ten minutes" / "full period" → at least 1400 words
    • "a couple minutes"    → ~300 words
    • "thirty seconds"      → ~75 words

CASE 2 — Teacher gave a qualitative length signal (no minutes):
  A brief monologue must FEEL noticeably shorter than the default.
  An in-depth one noticeably longer. Honor the teacher's steer.
    • "brief" / "short" / "quick"       → ~100-180 words (one paragraph)
    • "in depth" / "longer" / "thorough" → ~500-700 words

CASE 3 — No length signal at all:
    • ~180-320 words (~1.5 minutes). This is the default.

Pick the case that matches the teacher's message and write to that
length. The duration/qualitative signal always wins over the default.

The monologue must show a writer THINKING OUT LOUD while making ONE
concrete decision tied to the skill. Use first-person writerly voice:
"I could say ___, but that feels flat. What if I tried ___?" — the
weighing, discarding, and choosing of specific word/phrase options.

NO bullet points. NO numbered steps. NO "Step 1 / Step 2" headers.
NO "In this lesson we will" meta-narration. Just the monologue.

## Specificity (Brady's hard rule)

The monologue must model a SPECIFIC choice with SPECIFIC words or
phrases — not abstract method. Good: "I wrote 'the dog was sad.' Sad
is a thin word. What if I showed it? 'The dog's tail drooped and he
slid under the couch.'" Bad: "Writers think about word choice and
revise their sentences."

## Named strategies

If you name a specific Smekens strategy (pizza-table, sensory-language,
sticky-dot details, road-sign transitions, magnify close-up, etc.),
include a 1-2 sentence gist. Teachers may not have the Launch books.

## Grounding

Draw from the retrieved chunks when they include example think-alouds or
the skill's teaching script. Do NOT invent Smekens strategies not in the
retrieved context.

## Closing

END with EXACTLY this line (no variation):

  Want me to wrap this in a scripted mini-lesson?

## Forbidden vocabulary

Never use "discuss", "discussion", "activities", "activity",
"I'll listen in", "professional development", "certificate".

## Teacher-facing language

The teacher is a classroom educator, not a developer. Never expose
internal system vocabulary — BANNED: "chunks", "retrieved context",
"retrieved chunks", "indexed", "corpus", "retrieval", "retrieved
material", "trigger" (in the system sense), "embedding". When you
need to express uncertainty or refer to your source material, use
teacher-register phrasing: "the Launch book material I have", "from
the excerpts I can see", "I can't confirm that directly from what
I have in front of me". Phrasing limits is fine; exposing pipeline
terminology is not.

## Do NOT produce

  * A 4-step lesson structure — that's SCRIPTED_ML
  * A bulleted/numbered list of strategies — that's HOW_TO_TEACH
  * Teacher-voice narration about the writer ("the writer notices…") —
    this is FIRST-PERSON, the writer speaking to themselves
"""


def _build_prompt(
    intent: TurnIntent,
    retrieved_context: str,
    conversation: Conversation,
    repair_feedback: Optional[str],
) -> str:
    parts: list[str] = [_THINK_ALOUD_RULES, GLOBAL_VOCAB_RULES]

    # Brady C10 (dogfood C10): validate the emotion FIRST when the teacher voiced
    # frustration. Gated on the deterministic expressed_frustration QU signal —
    # a no-op on a calm turn (same conditional-splice pattern as the other text
    # handlers).
    if intent.expressed_frustration:
        parts.append(FRUSTRATION_VALIDATION_RULE)

    session_lines: list[str] = ["=== SESSION CONTEXT ==="]
    if intent.grade:
        session_lines.append(f"Grade: {intent.grade.value}")
    if intent.mode:
        session_lines.append(f"Writing mode: {intent.mode.value}")
    if intent.trait:
        session_lines.append(f"Writing trait: {intent.trait.value}")
    if intent.skill:
        session_lines.append(f"Skill (teacher vocab): {intent.skill.as_stated!r}")
        session_lines.append(f"Canonical: {intent.skill.canonical!r}")
    if intent.required_triggers:
        session_lines.append(
            f"Named Smekens triggers: {', '.join(intent.required_triggers)}"
        )
    if intent.refers_to_prior:
        session_lines.append(
            "NOTE: teacher is following up on the prior turn; align with "
            "that skill/example rather than re-introducing."
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


async def handle_think_aloud(
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
        query_type_label="THINK_ALOUD",
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
            query_type="THINK_ALOUD",
            retrieved_context=retrieved_context,
            required_triggers=required_triggers,
        ),
        client=client,
        model=model,
        temperature=0.3,
        log_label="think_aloud",
        query_type="THINK_ALOUD",
    )
