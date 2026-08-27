"""MANAGEMENT handler — classroom routines + workshop logistics.

Brady's directive: management questions pull chapters 1-7 of the Launch
books first (routines, procedures, pacing — distinct from the
skill-focused chapters 8+).

Examples:
  - "How do I set up writers' workshop routines?"
  - "What procedures help kids stay on task during writing time?"
  - "How often should I conference with students?"

Output shape: same prose-with-closing pattern as COACHING. The
difference is retrieval bias toward management content and the
conversation-context prompt about Brady's pacing principles.
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
    LIST_FORMAT_RULE,
    MANAGEMENT_CLOSING_QUESTION_RULE,
)
from handlers._retrieval import run_retrieval
from schemas import (
    Conversation,
    SessionHandshakes,
    TurnIntent,
    TurnOutcome,
)


_MANAGEMENT_RULES = """\
You are Brady's AI Writing Co-Pilot. The teacher has asked about
classroom routines, workshop setup, or the logistics of teaching
writing (not a specific writing skill). Produce grounded guidance.

## Output shape

2-4 short markdown paragraphs, roughly 250-450 words total. Speak to
the concrete routine or procedure the teacher is asking about. Favor
specifics over platitudes: name the actual moves teachers take.

## Grounding

Prioritize content from Launching the Writers Workshop chapters 1-7
(routines, schedules, conferences, pacing). If the retrieved context
names a specific Smekens routine (e.g., "Help! tent", "Done list",
"Eyeball peepers"), draw from that directly.

## Named routines

When you name a specific Smekens routine or tool by name (Help tent,
Done list, writing folder system, etc.), include a 1-2 sentence gist.
Teachers may not have the Launch books.

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

  * A scripted 4-step mini-lesson — that's SCRIPTED_ML
  * A skill-teaching outline — that's HOW_TO_TEACH

This is about MANAGEMENT, not pedagogy.
"""


def _build_prompt(
    intent: TurnIntent,
    retrieved_context: str,
    conversation: Conversation,
    repair_feedback: Optional[str],
) -> str:
    parts: list[str] = [
        _MANAGEMENT_RULES,
        GLOBAL_VOCAB_RULES,
        LIST_FORMAT_RULE,
        MANAGEMENT_CLOSING_QUESTION_RULE,  # Brady E3 overview closer (not the generic one)
    ]

    # Brady C10 (dogfood C10): validate the emotion FIRST when the teacher voiced
    # frustration (e.g. "I can't get them to settle during writing time"). Gated
    # on the deterministic expressed_frustration QU signal — a no-op on a calm
    # turn (same conditional-splice pattern as the other text handlers).
    if intent.expressed_frustration:
        parts.append(FRUSTRATION_VALIDATION_RULE)

    session_lines: list[str] = ["=== SESSION CONTEXT ==="]
    if intent.grade:
        session_lines.append(f"Grade: {intent.grade.value}")
    if intent.required_triggers:
        session_lines.append(
            f"Named Smekens routines: {', '.join(intent.required_triggers)}"
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


async def handle_management(
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
        query_type_label="MANAGEMENT",
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
            query_type="MANAGEMENT",
            retrieved_context=retrieved_context,
            required_triggers=required_triggers,
        ),
        client=client,
        model=model,
        temperature=0.3,
        log_label="management",
        query_type="MANAGEMENT",
    )
