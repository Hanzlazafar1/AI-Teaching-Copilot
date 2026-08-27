"""HOW_TO_TEACH handler — high-level instructional outline.

Brady's G2 requirement: "How do I teach X?" returns a BULLETED LIST of
3-5 sub-skills / strategies the teacher could focus on, each a discrete
mini-lesson topic. Ends with an offer to produce a scripted mini-lesson.

Shape:
  1. Opening sentence naming the skill + a Smekens trigger if retrieval
     surfaced one.
  2. 3-5 bulleted sub-skill points; each 1-2 sentences.
  3. Closing: "Are you ready for a scripted mini-lesson on this skill?"

NOT a full 4-step lesson. That's SCRIPTED_ML.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from openai import AsyncOpenAI

from canonicalizer import Canonicalizer
from handlers._base_text import (
    make_markdown_validators,
    run_text_handler_with_retry,
)
from handlers.citation import is_location_lookup, resolve_markers
from handlers._prompt_rules import (
    EARLY_WRITER_STAGE_PER_BULLET_RULE,
    EARLY_WRITER_STAGE_RULE,
    FRUSTRATION_VALIDATION_RULE,
    GLOBAL_VOCAB_RULES,
    LIST_FORMAT_RULE,
    PER_CLAIM_SOURCE_MARKER_RULE,
)
from handlers._retrieval import run_retrieval
from schemas import (
    Conversation,
    SessionHandshakes,
    TurnIntent,
    TurnOutcome,
)


# Stable-prefix rules — cache-friendly
_HOW_TO_TEACH_RULES = """\
You are Brady's AI Writing Co-Pilot. The teacher has asked HOW to teach
a specific writing skill. Produce a HIGH-LEVEL INSTRUCTIONAL OUTLINE —
NOT a full 4-step mini-lesson.

## Output shape (strictly)

1. ONE opening sentence that names the skill in the teacher's vocabulary
   AND references a Smekens trigger/strategy from the retrieved context
   if one exists (e.g. "tables and legs", "road sign", "slinky test",
   "pizza table", "done list", "magnify close-up details").

2. A BULLETED LIST of 3-5 high-level instructional points. Each point
   is a discrete sub-skill or concept that could become its own mini-
   lesson — NOT a step of ONE lesson. Keep each point to 1-2 sentences.

3. END with EXACTLY this line (no variation, no period change):

   Are you ready for a scripted mini-lesson on this skill?

## Each skill is its own lesson

The points above are separate skills, not steps of one lesson. Keep coming
back to the idea that each priority skill is its own individual lesson.
Never bundle several skills into a single lesson.

## Strategy names

When you name a specific Smekens strategy (pizza-table, dissected web,
road-sign, slinky test, magnify close-up, sticky-dot details, etc.),
include a 1-2 sentence gist of what the strategy IS. Teachers may not
have the Launch books — never drop a named tool without explanation.

## Forbidden vocabulary

Never use:
  * "discuss" / "discussion"
  * "activity" / "activities"
  * "I'll listen in"
  * "professional development" / "certificate" — no PD plug

## Teacher-facing language

The teacher is a classroom educator, not a developer. Never expose
internal system vocabulary — BANNED: "chunks", "retrieved context",
"retrieved chunks", "indexed", "corpus", "retrieval", "retrieved
material", "trigger" (in the system sense), "embedding". Use teacher-
register phrasing when expressing uncertainty or referring to source
material: "the Launch book material I have", "from the excerpts I
can see", "I can't confirm that directly from what I have in front
of me". Phrasing limits is fine; exposing pipeline terminology is not.

## Citation discipline

Do NOT include a book or page citation — a pointer to the Launch book is
added for you automatically. Never invent a page number or book title.

## Do NOT produce

  * step_1_introduce / step_2a_tell / step_2b_show / step_3_interact /
    step_4_close — that's SCRIPTED_ML territory
  * A paragraph of prose — use the bulleted-list format
  * A daily unit calendar — that's PLAN_UNIT
"""


def _build_prompt(
    intent: TurnIntent,
    retrieved_context: str,
    conversation: Conversation,
    repair_feedback: Optional[str],
) -> str:
    """Cache-friendly prompt assembly."""
    # PER_CLAIM_SOURCE_MARKER_RULE is spliced UNCONDITIONALLY, into the stable
    # cache prefix: it is self-limiting ("append nothing when a claim was not
    # built from a retrieved block"), so a turn with no retrieval is a natural
    # no-op rather than a case to branch on. Gating it on retrieved_context
    # would fork the cache prefix for nothing.
    parts: list[str] = [
        _HOW_TO_TEACH_RULES,
        GLOBAL_VOCAB_RULES,
        LIST_FORMAT_RULE,
        PER_CLAIM_SOURCE_MARKER_RULE,
    ]

    # Brady SG2/SG3 — only when the teacher gave a developmental writing level
    # (subgroup / early writer). Splicing conditionally keeps normal on-grade
    # outlines untouched (no-op) and the prompt lean. SG2's core is shared with
    # the SCRIPTED_ML builder; SG3's restate-per-bullet clause is outline-only
    # (a 4-step lesson has no bulleted skill list). Joined with a blank line,
    # the two reproduce the original single rule verbatim.
    if (intent.writing_level or "").strip():
        parts.append(
            f"{EARLY_WRITER_STAGE_RULE}\n\n{EARLY_WRITER_STAGE_PER_BULLET_RULE}"
        )

    # Brady C10 (dogfood C10): a frustrated "how do I teach X?" routes HERE, not
    # to COACHING — the exact case the old COACHING-only rule missed. Validate the
    # emotion first, gated on the deterministic expressed_frustration QU signal;
    # a no-op on a calm turn (same conditional-splice pattern as the SG2 rule).
    if intent.expressed_frustration:
        parts.append(FRUSTRATION_VALIDATION_RULE)

    session_lines: list[str] = ["=== SESSION CONTEXT ==="]
    if intent.grade:
        session_lines.append(f"Grade: {intent.grade.value}")
    if (intent.writing_level or "").strip():
        session_lines.append(
            f"Current writing level (developmental stage): {intent.writing_level}"
        )
    if (intent.subgroup or "").strip():
        session_lines.append(f"Subgroup: {intent.subgroup}")
    if intent.mode:
        session_lines.append(f"Writing mode: {intent.mode.value}")
    if intent.trait:
        session_lines.append(f"Writing trait: {intent.trait.value}")
    if intent.skill:
        session_lines.append(f"Skill (teacher vocab): {intent.skill.as_stated!r}")
        session_lines.append(f"Canonical: {intent.skill.canonical!r}")
    if intent.required_triggers:
        session_lines.append(
            f"Named Smekens triggers to surface + explain: "
            f"{', '.join(intent.required_triggers)}"
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
        parts.append("=== PREVIOUS ATTEMPT FAILED — FIX THESE ISSUES ===")
        parts.append(repair_feedback)
        parts.append("Fix ONLY the issues above.")
        parts.append("=== END REPAIR ===")

    return "\n\n".join(parts)


async def handle_how_to_teach(
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
    context_chunks, retrieved_context, grounding = await run_retrieval(
        intent=intent,
        query_text=new_user_message,
        query_type_label="HOW_TO_TEACH",
        retrieval_fn=retrieval_fn,
    )

    required_triggers = list(intent.required_triggers)

    # Bug C2 — fail-safe SILENCE on a deictic page-lookup follow-up ("what page
    # is that lesson on?"). Such a turn is referent-less, so retrieval above
    # re-ran on it and returned GENERIC chunks (a paraphrase, the TOC) — never
    # the lesson being asked about. If the model marks a framing claim, resolving
    # it against those chunks would print a CONFIDENT WRONG page right after the
    # model hedged it "can't confirm the exact page". So resolve the markers
    # against EMPTY chunks: resolve_markers still SWEEPS every marker (nothing
    # raw leaks) but has nothing to cite, so it stays silent — Brady's "better to
    # stay silent than lie." Gated on refers_to_prior AND is_location_lookup so a
    # FRESH page lookup, which retrieved its own lesson, still cites correctly.
    _page_lookup = intent.refers_to_prior and is_location_lookup(new_user_message)

    return await run_text_handler_with_retry(
        intent=intent,
        conversation=conversation,
        new_user_message=new_user_message,
        retrieved_context=retrieved_context,
        grounding=grounding,
        prompt_builder=_build_prompt,
        validators=make_markdown_validators(
            intent=intent,
            query_type="HOW_TO_TEACH",
            retrieved_context=retrieved_context,
            required_triggers=required_triggers,
        ),
        client=client,
        model=model,
        temperature=0.3,
        log_label="how_to_teach",
        query_type="HOW_TO_TEACH",
        # Brady image3/image39: his approved outlines carry a citation on EACH
        # claim that earned one (5 sites across 6 pages in one), not a single
        # footer per turn. The generator marks each claim it built from a
        # retrieved block with that block's `Source:` id
        # (PER_CLAIM_SOURCE_MARKER_RULE); this resolves those markers, in place,
        # from the named chunk's TYPED metadata. The model never writes a book
        # or a page — the rule the reverted Fm5 prompt-reword broke.
        #
        # Closed over `context_chunks` — what the model SAW — never the raw
        # retrieval list: those are the only ids it could have named, and
        # resolve_attribution returns on the first id match (see
        # _retrieval.run_retrieval's docstring).
        #
        # This REPLACES the rank-picked Fm5 footer. The footer was chosen from
        # retrieval rank BEFORE generation ran, so "you'll find THIS LESSON on
        # p.N" was picked before "this lesson" existed.
        citation_resolver=lambda text: resolve_markers(
            text, [] if _page_lookup else context_chunks, retrieved_context
        ),
    )
