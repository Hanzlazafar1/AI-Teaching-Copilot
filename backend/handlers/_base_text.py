"""Shared retry-with-repair loop for text-based handlers.

The 5 text handlers — HOW_TO_TEACH, COACHING, MANAGEMENT, PLAN_UNIT,
THINK_ALOUD — all share the same outer shape:

  retrieve → generate (text response) → validate → retry-with-repair

Only the prompt + which validators fire + closing-phrase requirement
differs per handler. This module extracts the common loop.

Every text handler calls ``run_text_handler_with_retry`` with:
  * a prompt-builder callable (takes intent + chunks + conversation
    + optional repair_feedback, returns system prompt)
  * a list of validator callables (each takes response_text →
    list[str] error messages)
  * the effective request_type (drives closing-phrase validator)

The loop runs up to 3 attempts, composes structured repair feedback
on each failure, and delivers best-of-three with quality=LOW if all
three attempts fail.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from openai import AsyncOpenAI

from handlers.formatting import format_lesson_header
from handlers.picklist import extract_offered_skills
from llm_params import temperature_kwargs
from schemas import (
    ChunkRef,
    Conversation,
    Quality,
    TurnIntent,
    TurnOutcome,
)
from validation.endings import (
    HOW_TO_TEACH_MULTI_SKILL_CLOSER,
    HOW_TO_TEACH_SINGLE_SKILL_CLOSER_FRAGMENT,
)
from validation.forbidden_words import scrub_forbidden_words
from validation.policy import (
    ends_with_offer_question,
    is_llm_trustable_error,
    is_offer_eligible,
    is_story_narrative_error,
    closer_anchor_phrases,
    required_closing_phrases,
    scrub_unverifiable_citations,
    validate_markdown_response,
)

logger = logging.getLogger(__name__)


_MAX_ATTEMPTS = 3


# Callable signatures
PromptBuilder = Callable[[TurnIntent, str, Conversation, Optional[str]], str]
"""Takes (intent, retrieved_context, conversation, repair_feedback)
and returns a system prompt. repair_feedback is None on first attempt."""

Validator = Callable[[str], list[str]]
"""Takes the response text and returns a list of error messages."""

CitationResolver = Callable[[str], str]
"""Takes the fully formatted response text and returns it with the generator's
`[[src:<chunk_id>]]` source markers resolved into Brady's citation sentences —
handlers.citation.resolve_markers, closed over the turn's own chunks.

A CALLABLE, not a string, and that is the whole point of the seam. A string
citation has to be chosen BEFORE generation runs, which is how "you'll find THIS
lesson on p.N" came to be picked before "this lesson" existed (cited page ==
top-ranked chunk's page, 30/30 measured). A resolver runs on what the model
ACTUALLY wrote, so it can only ever speak about text that exists.

The loop stays generic: it applies a callable and knows nothing about chunks,
books or pages. Each producer closes over its own retrieval, which is what keeps
MANAGEMENT / PLAN_UNIT / THINK_ALOUD out of the citation business without a
single branch on query_type in here. None (the default) is a strict no-op."""


def make_markdown_validators(
    *,
    intent: TurnIntent,
    query_type: str,
    retrieved_context: str,
    required_triggers: list[str],
) -> list[Validator]:
    """Build the markdown-response validator list for a text handler, threading
    the intent's grade + writing mode so Brady N1/N2 are enforced here too.

    Centralized so all five text handlers (COACHING_GENERAL, HOW_TO_TEACH,
    THINK_ALOUD, PLAN_UNIT, MANAGEMENT) share ONE validation-assembly point and
    can't drift apart. grade/mode are read defensively (a missing GradeSpec /
    ModeSpec -> None), and when both are None the N1/N2 rules are inert, so this
    is behavior-preserving for any caller that has no grade/mode yet."""
    grade = intent.grade.value if intent.grade else None
    mode = intent.mode.value if intent.mode else None

    def _validate(text: str) -> list[str]:
        return validate_markdown_response(
            query_type=query_type,
            response_text=text,
            retrieved_context=retrieved_context,
            triggered_trigger_names=required_triggers,
            grade=grade,
            mode=mode,
        )

    return [_validate]


def _is_markdown_trustable_error(error: str) -> bool:
    """Markdown-path trust set = the global trustable rules PLUS Brady N2.

    On free-form prose "story" has legitimate non-narrative uses (metaphor
    "the data tells a story", idiom "the whole story", subject content), so N2
    carries a large false-positive surface. Brady bans mislabeling the PIECE a
    story, not the word itself — so once the LLM has seen the N2 nudge and kept
    the wording, trust it (ship VALID) rather than forcing LOW. Bounded by the
    caller: this only fires after >=1 retry AND only when EVERY remaining error
    is in this set (so N2 is trusted only when it is the lone remaining class).
    N1 is deliberately NOT here — its K-1 "reasons" gate is reliable. The
    global is_llm_trustable_error stays N2-free so SCRIPTED_ML's structured
    path is unaffected."""
    return is_llm_trustable_error(error) or is_story_narrative_error(error)


@dataclass
class TextAttempt:
    """One generation attempt + its validation outcome."""

    response_text: str
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors


async def run_text_handler_with_retry(
    *,
    intent: TurnIntent,
    conversation: Conversation,
    new_user_message: str,
    retrieved_context: str,
    grounding: list[ChunkRef],
    prompt_builder: PromptBuilder,
    validators: list[Validator],
    client: AsyncOpenAI,
    model: str,
    temperature: float = 0.3,
    log_label: str = "text_handler",
    query_type: Optional[str] = None,
    citation_resolver: Optional[CitationResolver] = None,
) -> TurnOutcome:
    """Drive the retrieve-generate-validate-retry loop for a text handler.

    Does NOT handle retrieval or library-verbatim precheck — those are
    the caller's responsibility (per-handler). This function is the
    core loop only.

    ONE citation channel: ``citation_resolver``, threaded to all three delivery
    exits below and inert by default. It replaced a rank-picked ``book_citation``
    STRING, and the type change is the fix, not a refactor — a string citation
    has to be chosen before generation runs, which is how "you'll find THIS
    lesson on p.N" came to be picked before "this lesson" existed. A producer
    that has nothing to say passes nothing, which is how MANAGEMENT / PLAN_UNIT
    / THINK_ALOUD stay uncited without a branch on query_type in here.
    """
    attempts: list[TextAttempt] = []
    repair_feedback: Optional[str] = None
    # Brady Fm4: thread grade/mode from the intent once, here, so every
    # _build_text_outcome call site below (first-attempt pass, LLM-trustable
    # fallback, best-of-three LOW) can prepend the "Grade X | <Mode>" header.
    grade = intent.grade.value if intent.grade else None
    mode = intent.mode.value if intent.mode else None

    for i in range(_MAX_ATTEMPTS):
        attempt = await _single_text_attempt(
            intent=intent,
            conversation=conversation,
            new_user_message=new_user_message,
            retrieved_context=retrieved_context,
            prompt_builder=prompt_builder,
            validators=validators,
            repair_feedback=repair_feedback,
            client=client,
            model=model,
            temperature=temperature,
        )
        attempts.append(attempt)
        if attempt.passed:
            logger.info(
                "%s attempt %d/%d passed",
                log_label, i + 1, _MAX_ATTEMPTS,
            )
            return _build_text_outcome(
                response_text=attempt.response_text,
                grounding=grounding,
                quality=Quality.VALID,
                retry_count=i,
                validation_errors=[],
                retrieved_context=retrieved_context,
                log_label=log_label,
                grade=grade,
                mode=mode,
                query_type=query_type,
                citation_resolver=citation_resolver,
            )
        # Trust-the-LLM fallback (§LLM-trustable rules):
        # after ≥1 contextual retry, if the remaining errors are all from
        # rules whose final judgment is inherently semantic (forbidden-
        # word register, trigger-usage paraphrase, and — on this markdown
        # path only — the Brady N2 "story" rule), the LLM has seen the
        # context-aware repair instruction and kept the response as
        # written. Ship VALID. Retained errors stay in validation_errors
        # for audit. Uses the markdown-scoped trust set (adds N2) so
        # SCRIPTED_ML's structured path is unaffected.
        if i >= 1 and attempt.errors and all(
            _is_markdown_trustable_error(e) for e in attempt.errors
        ):
            logger.info(
                "%s attempt %d/%d — LLM-trustable flags retained after retry, "
                "trusting LLM judgment, shipping VALID",
                log_label, i + 1, _MAX_ATTEMPTS,
            )
            return _build_text_outcome(
                response_text=attempt.response_text,
                grounding=grounding,
                quality=Quality.VALID,
                retry_count=i,
                validation_errors=list(attempt.errors),
                retrieved_context=retrieved_context,
                log_label=log_label,
                grade=grade,
                mode=mode,
                query_type=query_type,
                citation_resolver=citation_resolver,
            )
        repair_feedback = _format_repair_feedback(attempt.errors)
        logger.info(
            "%s attempt %d/%d failed with %d error(s)",
            log_label, i + 1, _MAX_ATTEMPTS, len(attempt.errors),
        )

    # All 3 attempts failed — deliver best-of-three
    best = min(attempts, key=lambda a: len(a.errors))
    logger.warning(
        "%s delivering LOW quality after %d attempts (best had %d errors)",
        log_label, _MAX_ATTEMPTS, len(best.errors),
    )
    return _build_text_outcome(
        response_text=best.response_text,
        grounding=grounding,
        quality=Quality.LOW,
        retry_count=_MAX_ATTEMPTS - 1,
        validation_errors=list(best.errors),
        retrieved_context=retrieved_context,
        log_label=log_label,
        grade=grade,
        mode=mode,
        query_type=query_type,
        citation_resolver=citation_resolver,
    )


# Markdown-rendering normaliser.
#
# Both gpt-4o and gpt-5.4 reliably produce numbered / bulleted content but
# unreliably insert line breaks between the items — they generate
# "sentence. 1. Item 2. Item …" packed into a single paragraph. That
# renders as prose in a Markdown UI, not as a list. This regex normalises
# the known rendering miss without altering content: find an inline list
# marker (N. / - / * / •) preceded by sentence-end punctuation + whitespace
# (NOT preceded by a newline), and insert a blank line before it.
#
# Guards in the patterns:
#   - Must come after sentence-ending punctuation [.!?:)]
#   - Must NOT already have a newline before
#   - The character after the marker must be uppercase letter, bold ** , or
#     an opening quote/paren — so we don't trip on "I read 3. then..."
#   - Numbered form: digit + period + space
#   - Bullet form: dash / asterisk / bullet-char + space
#
# No-op when the LLM already formatted the list with newlines.
_INLINE_NUMBERED_RE = re.compile(
    r"(?<!\n)(?<=[.!?:)])\s+(\d+)\.\s+(?=[A-Z*\"'(])"
)
_INLINE_BULLET_RE = re.compile(
    r"(?<!\n)(?<=[.!?:)])\s+[-*•]\s+(?=[A-Z*\"'(])"
)


def _normalize_inline_lists(text: str) -> str:
    """Insert blank lines before inline numbered/bulleted items so
    Markdown renders them as a list instead of a run-on paragraph."""
    if not text:
        return text
    text = _INLINE_NUMBERED_RE.sub(lambda m: f"\n\n{m.group(1)}. ", text)
    text = _INLINE_BULLET_RE.sub("\n\n- ", text)
    return text


# Brady Fm1: HOW_TO_TEACH bullet normaliser.
#
# A HOW_TO_TEACH outline lists discrete sub-skill OPTIONS (not an ordered
# sequence), so it must render as bullets. The prompt asks for bullets,
# but this seam backstop deterministically converts any stray line-leading
# "N. " markers to "- " for HOW_TO_TEACH only. No-op for every other
# query_type (PLAN_UNIT's numbered scope-and-sequence is intentional).
_NUMBERED_LINE_RE = re.compile(r"^(\s*)\d+\.\s+", re.MULTILINE)


def _bulletize_how_to_teach(text: str, query_type: Optional[str]) -> str:
    """Brady Fm1: a HOW_TO_TEACH outline lists discrete sub-skill OPTIONS,
    not an ordered sequence, so it renders as bullets. Convert line-leading
    "N. " markers to "- " for HOW_TO_TEACH only. No-op for every other type
    (PLAN_UNIT's numbered scope-and-sequence is intentional). Idempotent."""
    if not text or query_type != "HOW_TO_TEACH":
        return text
    return _NUMBERED_LINE_RE.sub(r"\1- ", text)


# Split before a capitalized Smekens step HEADER glued mid-line — "Step 1 —",
# "Step 2A: ", "Step 3 Interact". A header is a capitalized "Step" + number
# (+ optional A/B) followed by either a dash/colon separator or a capitalized
# title word. A mid-sentence back-reference ("As discussed in Step 2, revise…",
# "in Step 2 you modeled…") is NOT a header and is left alone — that phrasing
# occurs in legitimate coaching prose that digs into a prior lesson (Brady §0).
# Lowercase "step N" as a common noun never matches (case-sensitive, no IGNORECASE).
_STEP_BLOCK_RE = re.compile(
    r"(?<!\n)[ \t]+(?=Step \d+[AB]?(?:[ \t]*[—–:-]|[ \t]+[A-Z]))"
)


def _blockify_steps(text: str) -> str:
    """Brady Fm2: any 4-step lesson content on the text path renders in
    paragraph blocks, never one giant paragraph. Insert a blank line before a
    glued capitalized "Step N" header. No-op on already-blocked text, on a
    mid-sentence back-reference ("...in Step 2, ..."), and on lowercase
    "step N". Idempotent. Cosmetic — runs post-validation."""
    if not text:
        return text
    return _STEP_BLOCK_RE.sub("\n\n", text)


_CLOSER_TAIL_WINDOW = 240  # chars from the end where a real closer lives


def _swap_multi_skill_closer(text: str, query_type: Optional[str]) -> str:
    """Brady C8: a HOW_TO_TEACH outline that enumerates MORE THAN ONE sub-skill
    closes with Brady's pick-list question, not the single-skill "...on this
    skill?" closer — "this skill" has no referent once 3-5 skills were listed.

    Deterministic because the count is arithmetic, not the model's job
    (handlers/picklist.py): the rendered outline is enumerated by
    extract_offered_skills, and when it lists >1 skill this replaces the
    trailing single-skill closer with the EXACT multi-skill constant. The prompt
    keeps its single-skill instruction; a single-skill outline (count <= 1) is
    left untouched — so in practice a 3-5-item outline gets the pick-list closer
    and a lone-skill outline keeps "...on this skill?".

    Bounded + fail-safe + idempotent, in the house style of
    _dedupe_closing_question: it can only (a) replace the trailing single-skill
    closer with HOW_TO_TEACH_MULTI_SKILL_CLOSER, or (b) leave the text unchanged
    — never a mangled tail. The single-skill closer's registered fragment opens
    it ("Are you ready ..."); this takes the LAST occurrence inside the tail
    window and replaces from there through end-of-text, so the "...on this
    skill?" trailing the fragment is swapped too (never left dangling) and any
    spurious earlier mention is left alone. If the fragment isn't in the tail,
    the text is returned unchanged. A second pass is a strict no-op — the swap
    removed the single-skill fragment this keys on, and the multi-skill closer
    does not contain it. The next stage (_isolate_closing_question) moves the
    new closer onto its own paragraph: the multi-skill fragment is a registered
    closer anchor (validation.endings), so isolation finds it. Cosmetic — runs
    post-validation."""
    if not text or query_type != "HOW_TO_TEACH":
        return text
    if len(extract_offered_skills(text)) <= 1:
        return text
    tail_start = max(0, len(text) - _CLOSER_TAIL_WINDOW)
    last = None
    for m in re.finditer(
        re.escape(HOW_TO_TEACH_SINGLE_SKILL_CLOSER_FRAGMENT), text, re.IGNORECASE
    ):
        if m.start() >= tail_start:
            last = m
    if last is None:
        return text  # single-skill closer not in the tail -> leave unchanged
    return text[: last.start()] + HOW_TO_TEACH_MULTI_SKILL_CLOSER


def _isolate_closing_question(text: str, query_type: Optional[str]) -> str:
    """Brady E5(a): the response's closing question renders on its own
    paragraph, never glued to the last list item. Find the query_type's
    registered closing phrase near the end; if it is glued to preceding
    content (no blank line before it), insert a paragraph break. No-op if
    the type has no registered closer, the closer isn't in the tail, or it
    is already its own block. Idempotent. Cosmetic — runs post-validation."""
    if not text or not query_type:
        return text
    phrases = closer_anchor_phrases(query_type)
    if not phrases:
        return text
    # Anchor to the EARLIEST anchor-phrase occurrence within the tail
    # window — the START of the closing block. For the two-phrase
    # COACHING_GENERAL/MANAGEMENT closer ("does this make sense" + "is this
    # helpful"), this moves the WHOLE compound onto its own paragraph rather
    # than splitting between the two sentences (which anchoring to the last
    # occurrence would do). Single-phrase closers are unaffected. Matches
    # before the tail window are ignored as mid-body mentions, not the closer.
    tail_start = max(0, len(text) - _CLOSER_TAIL_WINDOW)
    starts = [
        m.start()
        for phrase in phrases
        for m in re.finditer(re.escape(phrase), text, re.IGNORECASE)
        if m.start() >= tail_start
    ]
    if not starts:
        return text  # no closer, or a mid-body mention (not the closer)
    idx = min(starts)
    prefix = text[:idx]
    if prefix.rstrip() == "" or prefix.endswith("\n\n"):
        return text  # already its own block
    return prefix.rstrip() + "\n\n" + text[idx:]


def _is_bare_generic_closer(span: str, phrases: tuple[str, ...]) -> bool:
    """True when `span` is ESSENTIALLY just the registered generic closer
    sentence(s) — after removing the registered phrases and every non-word
    character, nothing substantive remains. Guards _dedupe_closing_question
    against deleting a SUBSTANTIVE trailing question that merely happens to
    contain the generic words ("Does this make sense for how you pace
    things?"): that residue keeps real words, so it is not stripped."""
    residue = span.lower()
    for phrase in phrases:
        residue = residue.replace(phrase, " ")
    return re.sub(r"[^\w]", "", residue) == ""


def _dedupe_closing_question(text: str, query_type: Optional[str]) -> str:
    """Brady E4: a COACHING_GENERAL/MANAGEMENT response closes with a SINGLE
    question. When the generator stacks the generic "Does this make sense? Is
    this helpful?" closer AFTER a concrete offer question, drop the redundant
    generic closer so only the offer question remains.

    Provably bounded — commits the strip ONLY when BOTH hold: (1) what would be
    removed is the BARE generic closer (_is_bare_generic_closer — not a
    substantive trailing question), and (2) the remaining candidate STILL ENDS
    WITH a valid offer question (ends_with_offer_question). So it can only turn
    "valid (two questions)" into "valid (one offer question)", never into an
    invalid/no-closer ending — even when a stray mid-body "does this make
    sense" mention exists (cutting at the tail closer would leave a declarative
    candidate, which fails the offer anchor and is rejected). No-op for
    non-offer-eligible query_types, for a type with no registered closer, and
    when the generic closer is absent from the tail window. Idempotent (a
    second pass finds no generic closer left to strip). Cosmetic-at-worst,
    conformant-at-best; runs before _isolate_closing_question."""
    if not text or not is_offer_eligible(query_type):
        return text
    phrases = required_closing_phrases(query_type)
    if not phrases:
        return text
    # Only treat a generic-closer occurrence inside the tail window as THE
    # closer; earlier mentions are mid-body self-checks, not the ending.
    tail_start = max(0, len(text) - _CLOSER_TAIL_WINDOW)
    starts = [
        m.start()
        for phrase in phrases
        for m in re.finditer(re.escape(phrase), text, re.IGNORECASE)
        if m.start() >= tail_start
    ]
    if not starts:
        return text
    cut = min(starts)
    removed, candidate = text[cut:], text[:cut].rstrip()
    if not _is_bare_generic_closer(removed, phrases):
        return text
    if not ends_with_offer_question(candidate):
        return text
    return candidate


# Grade|Mode header (Brady Fm4). The "Grade X | <Mode adjective>" header is
# prepended to the 5 shared-loop markdown handlers (HOW_TO_TEACH, COACHING,
# MANAGEMENT, PLAN_UNIT, THINK_ALOUD) via the one seam they all run through:
# _build_text_outcome. The header logic now lives in the neutral
# handlers/formatting.py (format_lesson_header) — the single source of truth
# designed to be shared with SCRIPTED_ML (handlers/scripted_ml.py) so both
# handler families converge on one header shape (Brady-confirmed adjective
# form, "Grade 3 | Informative"). SCRIPTED_ML is repointed onto the same
# helper in a following task of this wave.
def _build_text_outcome(
    *,
    response_text: str,
    grounding: list[ChunkRef],
    quality: Quality,
    retry_count: int,
    validation_errors: list[str],
    retrieved_context: str,
    log_label: str,
    grade: Optional[str] = None,
    mode: Optional[str] = None,
    query_type: Optional[str] = None,
    citation_resolver: Optional[CitationResolver] = None,
) -> TurnOutcome:
    """Compose a text-handler TurnOutcome with a final citation scrub,
    inline-list normalisation, closing-question isolation, and a leading
    Grade|Mode header.

    Runs a deterministic citation scrub before shipping so any page
    number / book attribution / digital-resources mention the generator
    invented is removed. Unverifiable citations are worse than missing
    citations.

    Then runs the forbidden-word scrub (Brady April non-negotiable #5:
    never emit "discuss" / "activity" / "I'll listen in" / PD-plug
    language). This is the last line of defense — the generation-time
    validator + retry loop is supposed to catch these, but if a
    forbidden word survives all retries it must still never reach the
    teacher.

    Also normalises inline numbered/bulleted lists into proper Markdown
    list shape — both gpt-4o and gpt-5.4 emit numbered content but often
    fail to insert line breaks between items, yielding paragraphs that
    render as prose instead of scannable lists. The normaliser is a
    no-op when the LLM already formatted with newlines.

    Then, for HOW_TO_TEACH only, converts line-leading numbered markers to
    bullets via _bulletize_how_to_teach (Brady Fm1) — a HOW_TO_TEACH outline
    lists discrete sub-skill options, not an ordered sequence. Then blockifies
    glued Smekens step headers via _blockify_steps (Brady Fm2): inserts a
    blank line before a capitalized "Step N" header glued mid-line so any
    4-step content on the text path renders in paragraph blocks, never one
    giant paragraph. _blockify_steps is query_type-independent and no-ops on
    mid-sentence back-references and already-blocked text.

    Then, for a HOW_TO_TEACH outline that enumerates MORE THAN ONE sub-skill,
    swaps the single-skill closer for Brady's multi-skill pick-list closer via
    _swap_multi_skill_closer (Brady C8) — "Are you ready for a scripted
    mini-lesson on this skill?" has no referent when several skills were just
    listed. Deterministic on the extract_offered_skills count; a single-skill
    outline is left untouched. Bounded like the E4 dedup — it either swaps the
    trailing closer or leaves the text unchanged, never a mangled tail. The
    _isolate_closing_question step below then moves the new closer onto its own
    paragraph (the multi-skill fragment is a registered closer anchor).

    Then, for offer-eligible types (COACHING_GENERAL / MANAGEMENT), dedupes
    a doubled closing question (Brady E4) via _dedupe_closing_question: when
    the generator stacks the generic "Does this make sense? Is this helpful?"
    closer AFTER a concrete offer question, the redundant generic closer is
    dropped so a single closing question remains. Provably bounded — it only
    strips when what remains still ends with a valid offer question, so it
    can never produce an invalid/no-closer ending.

    Then isolates the closing question (Brady E5(a)): if `query_type` has
    a registered closer (validation.endings.required_closing_phrases) and
    it is glued to the preceding content, pushes it onto its own
    paragraph. No-op when `query_type` is None or has no registered
    closer.

    Then applies `citation_resolver` when one was passed (HOW_TO_TEACH
    `how_to_teach.py` and COACHING `coaching.py` both do; MANAGEMENT / PLAN_UNIT
    / THINK_ALOUD pass nothing and stay uncited). It resolves the
    `[[src:<chunk_id>]]` markers the generator attached to its own claims into
    Brady's citation sentences, in place, on the claim that earned each one (his
    image3/image39 shape: several citation sites in one answer, not one footer
    per turn).

    ITS POSITION IN THIS ORDER IS LOAD-BEARING TWICE OVER — this is the
    canonical statement of both constraints; the deleted `_insert_book_citation`
    footer held the first one, and inherited it for the identical reason.

      1. AFTER the scrubs. Anything that BUILDS a citation must never have that
         citation re-fed through `scrub_unverifiable_citations`: the
         title-scrubber strips a full book title when no Teal/K-2 marker is in
         the context, so resolving first yields "If you have the '' book, you'll
         find this lesson on p.64." — a blank title slot. Not hypothetical: a
         blank slot ("on ** **") is what the REVERTED Fm5 prompt-reword actually
         shipped to teachers, and it is why build_soft_citation refuses to emit
         a half-known citation at all. (Locked: test_perclaim_wiring.py::
         test_the_resolver_runs_AFTER_the_scrubs_so_its_citation_is_never_scrubbed.)

      2. BEFORE extract_offered_skills below, so the pick-list is recorded from
         the text the teacher actually reads, citations included. The resolver's
         per-line contract is what makes that safe: a citation joins its claim's
         line, so it can never terminate the list mid-way (see
         handlers/citation.py::_resolve_one_line, and picklist.py's "prose after
         the list does end it").

    None is a strict no-op, which is how the three uncited handlers stay
    uncited.

    Finally, prepends the "Grade X | <Mode adjective>" header (Brady
    Fm4) once the body is fully scrubbed and formatted, so the header
    itself is never a scrub/normalisation target. For MANAGEMENT
    (query_type == "MANAGEMENT") the mode adjective is replaced by the
    "Management" label — a procedure response is headed
    "Grade X | Management", not a writing mode (Brady 36:30/image27).
    Skipped entirely (formatted text unchanged) when grade is unknown.
    """
    scrubbed, removed = scrub_unverifiable_citations(
        response_text, retrieved_context
    )
    if removed:
        logger.info(
            "%s scrubbed %d unverifiable citation(s): %s",
            log_label, len(removed), removed[:3],
        )
    scrubbed, fw_removed = scrub_forbidden_words(scrubbed)
    if fw_removed:
        logger.info(
            "%s scrubbed %d forbidden word(s): %s",
            log_label, len(fw_removed), fw_removed[:3],
        )
    formatted = _normalize_inline_lists(scrubbed)
    formatted = _bulletize_how_to_teach(formatted, query_type)
    formatted = _blockify_steps(formatted)
    formatted = _swap_multi_skill_closer(formatted, query_type)  # Brady C8
    formatted = _dedupe_closing_question(formatted, query_type)  # Brady E4
    formatted = _isolate_closing_question(formatted, query_type)
    # Per-claim citations (Brady image3/image39). AFTER the scrubs (a built
    # citation must never be re-scrubbed) and BEFORE extract_offered_skills (the
    # pick-list is recorded off the text the teacher reads). No branch on
    # query_type — a producer either hands the loop a resolver or it does not.
    if citation_resolver is not None:
        formatted = citation_resolver(formatted)
    header = format_lesson_header(grade, mode, label="Management" if query_type == "MANAGEMENT" else None)
    if header:
        formatted = f"{header}\n\n{formatted}"
    return TurnOutcome(
        response_text=formatted,
        structured=None,
        # Record the pick-list off the FORMATTED text — what the teacher will
        # actually read — not the raw generation, so an ordinal resolves
        # against the same list the teacher counted.
        offered_skills=extract_offered_skills(formatted),
        grounding=grounding,
        quality=quality,
        retry_count=retry_count,
        validation_errors=validation_errors,
        retrieved_context=retrieved_context,
    )


async def _single_text_attempt(
    *,
    intent: TurnIntent,
    conversation: Conversation,
    new_user_message: str,
    retrieved_context: str,
    prompt_builder: PromptBuilder,
    validators: list[Validator],
    repair_feedback: Optional[str],
    client: AsyncOpenAI,
    model: str,
    temperature: float,
) -> TextAttempt:
    """One generate + validate cycle for a text-response handler."""
    system_prompt = prompt_builder(intent, retrieved_context, conversation, repair_feedback)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": new_user_message},
    ]

    completion = await client.chat.completions.create(
        model=model,
        messages=messages,
        **temperature_kwargs(model, temperature),
    )
    response_text = (completion.choices[0].message.content or "").strip()

    errors: list[str] = []
    for v in validators:
        errors.extend(v(response_text))

    return TextAttempt(response_text=response_text, errors=errors)


def _format_repair_feedback(errors: list[str]) -> str:
    """Compose repair feedback string for the retry prompt."""
    if not errors:
        return ""
    lines = ["POLICY VIOLATIONS IN PREVIOUS ATTEMPT:"]
    for err in errors:
        lines.append(f"  - {err}")
    lines.append(
        "Fix ONLY the issues above. Preserve everything else that was working."
    )
    return "\n".join(lines)
