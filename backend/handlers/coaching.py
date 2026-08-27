"""COACHING handler — general writing-instruction Q&A.

Catch-all for open-ended questions that don't fit a more specific
request_type. Examples:
  - "Tell me about the pizza-table strategy"
  - "What's the difference between revising and editing?"
  - "Is the slinky test in the Launch book?"
  - "How do I use the Dissected Web?"

Output shape: 2-4 short markdown paragraphs (250-450 words),
grounded in retrieved chunks, ending with ONE closing question — a
concrete next-step offer if one fits naturally, otherwise "Does this
make sense? Is this helpful?".
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
    SINGLE_CLOSING_QUESTION_RULE,
    SKILL_ORDER_AFFIRM_RULE,
)
from handlers._retrieval import run_retrieval
from schemas import (
    Conversation,
    RequestType,
    Role,
    SessionHandshakes,
    TurnIntent,
    TurnOutcome,
)


_COACHING_RULES = """\
You are Brady's AI Writing Co-Pilot. The teacher has asked an open-
ended writing-instruction question. Produce a tight, grounded answer.

## Output shape

2-4 short markdown paragraphs, roughly 250-450 words total. Teachers
scan coaching responses; walls of prose get skipped. Cover the
highest-leverage points first.

## "We taught it but they still can't"

When the teacher reports they already taught the lesson but students
still can't do it, do NOT jump straight to new guidance. FIRST ask
which facets they struggled with — "Skim the original lesson — where
specifically are they struggling?" — THEN narrow once they answer.

## Grounding

Use the retrieved context as authoritative source material. Paraphrase
or quote it rather than inventing. If the teacher's question is about
a specific Smekens strategy, draw directly from the retrieved chunks
describing that strategy.

## Strategy names

When you name a specific Smekens strategy (pizza-table, road-sign,
slinky test, magnify close-up, dissected web, sticky-dot details,
etc.), include a 1-2 sentence gist. Teachers may not have the Launch
books.

## Citation discipline

Do NOT include a book or page citation — a pointer to the Launch book is
added for you automatically. Never invent a page number or book title.

## Resource-existence discipline (critical)

When the teacher asks about a physical or digital artifact — a graphic
organizer, printable, handout, rubric, template, worksheet, chart,
poster — treat it as a pointer-to-resource question, NOT an invitation
to describe one you'd invent.

Rules:
  1. **Never assert that a resource does not exist.** The co-pilot has
     not indexed every Launch-book digital resource or handout and
     cannot confirm absence. Phrases like "there isn't a specific
     downloadable organizer for…" or "there's no printable version
     of…" are banned.
  2. **If the retrieved context contains a Launch-book chunk** about
     the relevant strategy, direct the teacher to the Launch book and
     its accompanying digital resources: "Check the Launching the
     Writers Workshop [3-12 or K-2] book and its digital resources —
     that's where the organizer lives." Do not describe a DIY
     alternative as the primary answer in that case.
  3. **If you are unsure**, acknowledge it: "I'm not sure whether the
     Launch book includes a dedicated printable organizer for this —
     check the book's digital resources to confirm." THEN you may
     optionally offer a DIY sketch as a fallback.
  4. Never treat "DIY is the answer" as the default. The Launch book
     is the first recourse; DIY is a distant second.

## Forbidden vocabulary

Never use "discuss", "discussion", "activities", "activity",
"I'll listen in", "professional development", "certificate".

## Teacher-facing language (critical)

The teacher is a classroom educator, not a developer. Never expose
internal system vocabulary. The following words are FORBIDDEN in
teacher-facing output — including when you are expressing uncertainty
or citing limits of your knowledge:

  BANNED: "chunks", "retrieved context", "retrieved chunks",
          "indexed chunks", "indexed", "corpus", "retrieval",
          "retrieved material", "the retrieval layer", "trigger"
          (in the system sense — the metaphor-name sense is fine),
          "matched the trigger", "tokens", "embedding".

Use natural teacher-register alternatives instead:
  - instead of "retrieved chunks" → "the Launch book material I have"
  - instead of "from the indexed chunks" → "from the excerpts I can see"
  - instead of "retrieval layer matched" → "(just don't mention it;
    describe the strategy by name)"
  - instead of "I don't have that chunk indexed" → "I can't confirm
    that directly from the book material I have in front of me"
  - instead of "the retrieved context does not include" → "I don't
    have that section of the book available to me right now"

Phrasing uncertainty is fine; exposing the pipeline is not.

## Each skill is its own lesson

When the teacher's question spans multiple skills, steer back to the idea
that each priority skill is its own individual lesson — never bundled into
a single lesson.
"""


def _build_prompt(
    intent: TurnIntent,
    retrieved_context: str,
    conversation: Conversation,
    repair_feedback: Optional[str],
) -> str:
    # PER_CLAIM_SOURCE_MARKER_RULE: same rule object as HOW_TO_TEACH's — these
    # are the two per-claim citation producers (_base_text.py:371-373), so the
    # wording cannot be allowed to fork between them.
    #
    # HONEST PROVENANCE, because it matters for how hard we hold this: Brady's
    # per-claim evidence is HOW_TO_TEACH only (image3, image39). His one
    # COACHING artifact (image11) is a prose pointer with no page, which he
    # praised. Per-claim on COACHING is OUR uniform application of a rule
    # anchored elsewhere — not his ask. We do it because COACHING carries the
    # identical rank-based picker, and its measured 0/10 mis-cite rate is
    # case-mix luck, not a property of the path.
    parts: list[str] = [
        _COACHING_RULES,
        GLOBAL_VOCAB_RULES,
        LIST_FORMAT_RULE,
        SKILL_ORDER_AFFIRM_RULE,
        PER_CLAIM_SOURCE_MARKER_RULE,
        SINGLE_CLOSING_QUESTION_RULE,
    ]

    # Brady SG2/SG3 (C7) — mirror of how_to_teach. A leveled follow-up ("at the
    # picture/label stage") routes to COACHING, not HOW_TO_TEACH, so COACHING
    # needs the SAME early-writer rules: the shared SG2 stage core AND the SG3
    # restate-per-bullet clause (a leveled coaching follow-up can render a
    # bulleted skill list). Gated on writing_level, so normal on-grade coaching
    # is untouched (no-op). Joined with a blank line, the two reproduce the
    # original single rule verbatim — identical splice to how_to_teach.
    if (intent.writing_level or "").strip():
        parts.append(
            f"{EARLY_WRITER_STAGE_RULE}\n\n{EARLY_WRITER_STAGE_PER_BULLET_RULE}"
        )

    # Brady C10 (dogfood C10): validate the emotion FIRST when the teacher voiced
    # frustration. Gated on the deterministic expressed_frustration QU signal —
    # a no-op on a calm turn (byte-identical to before), same conditional-splice
    # pattern as EARLY_WRITER_STAGE_RULE. COACHING carried the ORIGINAL bespoke
    # block; it is now DELETED from _COACHING_RULES and reaches here via this
    # shared splice, exactly like every other text handler.
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
    if intent.skill:
        session_lines.append(f"Skill: {intent.skill.as_stated!r}")
    if intent.required_triggers:
        session_lines.append(
            f"Named Smekens triggers: {', '.join(intent.required_triggers)}"
        )
    if intent.refers_to_prior:
        session_lines.append(
            "NOTE: teacher is following up on the prior assistant turn. "
            "Refer back to what you said before rather than re-introducing "
            "concepts as new."
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


def _retrieval_focus(intent: TurnIntent, conversation: Conversation) -> str:
    """The retrieval label for this coaching turn — "MANAGEMENT" when the
    session's focus is management, else "COACHING_GENERAL".

    Brady (feedback-docx.txt:136-140), on the follow-up to a routines
    overview: "Response listed skills that were not even mentioned in the
    overview!" — "we have a big disconnect here. When 'routines, management,
    start up, writer's workshop, writer habits, expectations, procedures' are
    THE FOCUS, then Co-Pilot must pull from Sections 1-5 in the Launch books."

    "Are the focus" is the operative phrase. A focus persists across a
    follow-up; it is not re-established by each message. QU routes a bare
    "Can you expand on those?" to COACHING, which hard-coded
    COACHING_GENERAL — so the reranker's management scoping
    (DEPRIO_WRONG_MGMT on ch 8-13) silently stopped applying and the answer
    pulled writing-skill lessons out of Sections 6/8. Measured live: 0/3
    sources in Sections 1-5, and skills absent from the overview in 3/4 runs.

    A named skill re-frames — the teacher has moved on, and their words win
    over an inherited focus. That mirrors how a stated grade overrides an
    inherited one, rather than adding a new kind of rule.
    """
    if intent.skill is not None:
        return "COACHING_GENERAL"
    for turn in reversed(conversation.turns):
        if turn.role is Role.USER and turn.intent is not None:
            if turn.intent.request_type is RequestType.MANAGEMENT:
                return "MANAGEMENT"
            return "COACHING_GENERAL"
    return "COACHING_GENERAL"


async def handle_coaching(
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
        query_type_label=_retrieval_focus(intent, conversation),
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
            query_type="COACHING_GENERAL",
            retrieved_context=retrieved_context,
            required_triggers=required_triggers,
        ),
        client=client,
        model=model,
        temperature=0.3,
        log_label="coaching",
        query_type="COACHING_GENERAL",
        # Per-claim citations, resolved from the `Source:` id the generator
        # marked each claim with — the same seam as HOW_TO_TEACH, closed over
        # `context_chunks` (what the model SAW) rather than the raw retrieval
        # list. See _retrieval.run_retrieval's docstring for why the difference
        # is load-bearing.
        #
        # HONEST PROVENANCE (matching _build_prompt's note): per-claim on
        # COACHING is OUR uniform application of a rule anchored on
        # HOW_TO_TEACH, not Brady's ask — his one COACHING artifact (image11)
        # is a page-less prose pointer he praised. We do it because COACHING
        # carried the IDENTICAL rank-based picker, whose measured 0/10 mis-cite
        # rate was case-mix luck rather than a property of the path.
        #
        # What the port preserves: the LLM still never authors a page. That
        # matters because the regex scrubber can only ever be a bounded backstop
        # — "page-66" walked straight past it because a hyphen was not in its
        # separator list. resolve_attribution cites only a page that appears in
        # the assembled context's "Page:" headers, so an unverifiable citation
        # cannot be CONSTRUCTED. Brady's "book + page only at 100% confidence,
        # otherwise stay silent" stays structural instead of something a regex
        # must notice after the fact.
        citation_resolver=lambda text: resolve_markers(
            text, [] if _page_lookup else context_chunks, retrieved_context
        ),
    )
