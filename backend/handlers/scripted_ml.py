"""SCRIPTED_ML handler — full 4-step mini-lesson generation.

Pipeline:
  1. Library-verbatim precheck — if intent.skill matches a scripted ML
     in the library (+ compatible grade), return verbatim with attribution.
  2. Retrieval — hybrid search using params derived from intent. No
     session-state fallback; everything comes from the TurnIntent.
  3. Prompt construction — consume intent directly. No ledger lookup.
  4. Generate (attempt 1).
  5. Validate: structural policy (banned words, Step 3 phrases, 2B
     depth, skill-focus vocab, etc.) via v3's validate_lesson_policy.
  6. Judge: semantic coherence via judge_v4.
  7. If both pass → deliver quality=VALID. Otherwise retry-with-repair
     up to 2 more attempts. After max retries, deliver best-of-three
     with quality=LOW.

Everything ledger-related in v3 is gone. Grade, skill, mode, trait all
come from intent fields. Active skill inheritance for DEEPEN_PRIOR is
handled upstream — this handler assumes intent.skill is already set.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from openai import AsyncOpenAI

from canonicalizer import Canonicalizer
from generation.lesson import MiniLesson
from handlers.citation import build_soft_citation, resolve_attribution
from handlers.formatting import format_lesson_header
from handlers.scripted_ml_prompt import (
    build_scripted_ml_prompt,
    build_retry_preamble,
)
from llm_params import temperature_kwargs
from schemas import (
    ChunkRef,
    Conversation,
    Quality,
    SessionHandshakes,
    TurnIntent,
    TurnOutcome,
)
from validation.forbidden_words import scrub_forbidden_words
from validation.judge_v4 import JudgeVerdict, judge_scripted_ml
from validation.policy import (
    LessonPolicyResult,
    is_llm_trustable_error,
    scrub_unverifiable_citations,
    validate_lesson_policy,
)

logger = logging.getLogger(__name__)


# How many attempts TOTAL (including first). 3 = first try + 2 retries.
_MAX_ATTEMPTS = 3


# ----------------------------------------------------------------------
# Internal attempt record — one bundle per generation try
# ----------------------------------------------------------------------


@dataclass
class _Attempt:
    """A single generation attempt + its quality outcome."""

    lesson: MiniLesson
    response_text: str
    policy: LessonPolicyResult
    judge: Optional[JudgeVerdict]
    passed: bool

    def failure_count(self) -> int:
        """Total violations across policy + judge — used for
        best-of-three selection when all retries fail."""
        count = len(self.policy.errors)
        if self.judge:
            for dim in (
                self.judge.narrative_coherence,
                self.judge.strategy_gist_present,
                self.judge.step1_structure,
            ):
                if dim.score < 7:
                    count += 1
        return count


# ----------------------------------------------------------------------
# Public handler
# ----------------------------------------------------------------------


async def handle_scripted_ml(
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
    carried_context: Optional[str] = None,
) -> TurnOutcome:
    """Generate a scripted 4-step mini-lesson end-to-end.

    retrieval_fn signature (keyword-only to match v3's hybrid_search):
        async fn(*, query, intent, grade_level, writing_mode,
                 writing_trait, strategy_name, smekens_terms,
                 query_type, top_k) -> list[RetrievedChunk]

    library: optional MLLibrary instance for verbatim precheck. If
        provided AND intent matches a library entry with high
        confidence, we skip LLM generation entirely.

    judge_model: model used for the LLM judge calls (F27 judge split —
        the accept-gate runs on the cheaper judge model, not the
        generation flagship). Falls back to `model` when omitted, so
        callers that don't pass it keep the pre-F27 behavior.

    carried_context: optional prior-turn organizer/approach description
        (Brady C3). When DEEPEN_PRIOR builds a lesson from a turn that
        described a specific organizer/anchor-chart (e.g. "PIE flaps"),
        that description is threaded here so the generated lesson
        incorporates it. None (the default) is a no-op — the direct
        SCRIPTED_ML path never sets it.
    """
    judge_model = judge_model or model
    # --- 1. Library-verbatim precheck -------------------------------------
    lib_result = await _try_library_verbatim(intent, library, new_user_message)
    if lib_result is not None:
        return _finalize_ml_delivery(lib_result, intent)

    # --- 2. Retrieval -----------------------------------------------------
    chunks: list[Any] = []
    if retrieval_fn is not None:
        chunks = await _retrieve(intent, new_user_message, retrieval_fn)

    # ``context_chunks`` — NOT ``chunks`` — is what the model saw: deduped,
    # re-ordered and budget-truncated by the assembler. It is the only list
    # whose ids the generator could have named, so it is the list the citation
    # resolves against at each exit below.
    retrieved_context, context_chunks = _assemble_for_prompt(chunks)

    # NOTE: the soft book-citation is NOT built here. It is built at each
    # delivery exit, AFTER generation — see _citation_for.

    # --- 3. Prompt + 4. Generate + 5. Validate + 6. Judge (with retries) ---
    attempts: list[_Attempt] = []
    repair_feedback: Optional[str] = None
    last_grounding: list[ChunkRef] = [_chunk_to_ref(c) for c in chunks]

    for attempt_idx in range(_MAX_ATTEMPTS):
        attempt = await _single_attempt(
            intent=intent,
            conversation=conversation,
            new_user_message=new_user_message,
            retrieved_context=retrieved_context,
            chunks=chunks,
            repair_feedback=repair_feedback,
            carried_context=carried_context,
            client=client,
            model=model,
            judge_model=judge_model,
        )
        attempts.append(attempt)
        if attempt.passed:
            logger.info(
                "scripted_ml attempt %d/%d passed",
                attempt_idx + 1, _MAX_ATTEMPTS,
            )
            return _finalize_ml_delivery(
                _build_outcome(
                    attempt=attempt,
                    grounding=last_grounding,
                    quality=Quality.VALID,
                    retry_count=attempt_idx,
                    retrieved_context=retrieved_context,
                    book_citation=_citation_for(
                        attempt, context_chunks, retrieved_context
                    ),
                ),
                intent,
            )
        # Trust-the-LLM fallback (§LLM-trustable rules):
        # after ≥1 contextual retry, if the remaining policy errors are
        # all from rules whose final judgment is inherently semantic —
        # forbidden-word register, trigger-usage paraphrase — the LLM has
        # seen the register-aware repair instruction and chosen to keep
        # the response as written. Run the judge (it wasn't run while
        # policy had errors) and ship VALID if the judge agrees the
        # lesson is coherent.
        if attempt_idx >= 1 and attempt.policy.errors and all(
            is_llm_trustable_error(e) for e in attempt.policy.errors
        ):
            judge_verdict = attempt.judge
            if judge_verdict is None:
                try:
                    judge_verdict = await judge_scripted_ml(
                        lesson=attempt.lesson, client=client, model=judge_model
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("judge_v4 call failed on trust path: %s", e)
            if judge_verdict is None or judge_verdict.passes:
                logger.info(
                    "scripted_ml attempt %d/%d — LLM-trustable flags retained "
                    "after retry, trusting LLM judgment, shipping VALID",
                    attempt_idx + 1, _MAX_ATTEMPTS,
                )
                trusted_attempt = _Attempt(
                    lesson=attempt.lesson,
                    response_text=attempt.response_text,
                    policy=attempt.policy,
                    judge=judge_verdict,
                    passed=True,
                )
                return _finalize_ml_delivery(
                    _build_outcome(
                        attempt=trusted_attempt,
                        grounding=last_grounding,
                        quality=Quality.VALID,
                        retry_count=attempt_idx,
                        retrieved_context=retrieved_context,
                        book_citation=_citation_for(
                            trusted_attempt, context_chunks, retrieved_context
                        ),
                    ),
                    intent,
                )
        # Not passing — compose repair feedback for next attempt
        repair_feedback = build_retry_preamble(attempt.policy, attempt.judge)
        logger.info(
            "scripted_ml attempt %d/%d failed — %d policy errors, judge passes=%s",
            attempt_idx + 1, _MAX_ATTEMPTS,
            len(attempt.policy.errors),
            attempt.judge.passes if attempt.judge else "n/a",
        )

    # --- All attempts failed — deliver best-of-three as LOW quality -------
    best = min(attempts, key=_Attempt.failure_count)
    logger.warning(
        "scripted_ml delivering LOW quality after %d attempts (best: %d failures)",
        len(attempts),
        best.failure_count(),
    )
    return _finalize_ml_delivery(
        _build_outcome(
            attempt=best,
            grounding=last_grounding,
            quality=Quality.LOW,
            retry_count=_MAX_ATTEMPTS - 1,
            retrieved_context=retrieved_context,
            # `best`, not the loop's last `attempt` — the citation must be about
            # the lesson this exit actually SHIPS.
            book_citation=_citation_for(best, context_chunks, retrieved_context),
        ),
        intent,
    )


# ----------------------------------------------------------------------
# Library-verbatim precheck
# ----------------------------------------------------------------------


async def _try_library_verbatim(
    intent: TurnIntent,
    library: Optional[Any],
    user_message: str,
) -> Optional[TurnOutcome]:
    """If intent matches a scripted ML in the library with VERBATIM_AUTO
    confidence, return the library entry's complete_ml_text verbatim as
    a TurnOutcome. On weaker matches (ASK_USER / SURFACE_LIST / SKIP)
    we return None and fall through to LLM generation.

    Requires skill + grade on the intent (no embedding-based match
    without them is valuable for a scripted ML) and a loaded library.
    """
    if library is None or intent.skill is None or intent.grade is None:
        return None

    try:
        from retrieval.embedder import embed_query
        from retrieval.library_precheck import (
            PrecheckDecision,
            build_verbatim_response,
            library_precheck,
        )
    except ImportError:
        logger.debug("library_precheck not available; skipping verbatim path")
        return None

    # We embed the teacher's raw message — not just the skill phrase —
    # because the library's HyDE embeddings are tuned against full
    # teacher-like queries ("Give me a lesson on X for Yth graders"),
    # not isolated skill names.
    query_embedding = await embed_query(user_message)

    result = library_precheck(
        library=library,
        query_embedding=query_embedding,
        user_grade=intent.grade.value,
        query_specificity="specific",
        user_skill_phrase=intent.skill.as_stated,
        user_writing_mode=intent.mode.value if intent.mode else None,
    )
    if (
        result.decision is not PrecheckDecision.VERBATIM_AUTO
        or result.best_match is None
    ):
        return None

    match = result.best_match
    verbatim_text = build_verbatim_response(
        match, user_query_skill_phrase=intent.skill.as_stated
    )
    return TurnOutcome(
        response_text=verbatim_text,
        structured={
            "skill_focus": match.entry.skill_title,
            "grade_level": intent.grade.value,
            "source_document": match.entry.source_document,
            "library_ml_id": match.entry.ml_id,
        },
        grounding=[],
        quality=Quality.VALID,
        library_match_id=match.entry.ml_id,
    )


# ----------------------------------------------------------------------
# Retrieval — adapts intent to v3's hybrid_search kwargs
# ----------------------------------------------------------------------


async def _retrieve(
    intent: TurnIntent,
    query_text: str,
    retrieval_fn: Callable[..., Awaitable[Any]],
) -> list[Any]:
    """Call the retrieval function with params derived from intent.

    No fallback to session state — the intent is the single source.
    """
    kwargs: dict[str, Any] = {
        "query": query_text,
        "intent": "lesson",
        "query_type": "SCRIPTED_ML",
    }
    if intent.skill is not None:
        kwargs["strategy_name"] = intent.skill.canonical
    if intent.grade is not None:
        kwargs["grade_level"] = intent.grade.value
    if intent.mode is not None:
        kwargs["writing_mode"] = intent.mode.value
    if intent.trait is not None:
        kwargs["writing_trait"] = intent.trait.value

    try:
        return await retrieval_fn(**kwargs)
    except TypeError:
        # Looser retrieval fn — drop any kwargs it doesn't accept
        result = await retrieval_fn(query=query_text)
        return result


def _assemble_for_prompt(chunks: list[Any]) -> tuple[str, list[Any]]:
    """Build the generation prompt's retrieved-context block AND return the
    chunks that actually went INTO it. Prefer v3's assembler if available —
    otherwise a simple concatenation.

    Both halves are returned because they are not interchangeable, and the
    citation depends on the difference. ``assemble_context`` dedupes by
    chunk_id, re-orders by (source_tier, -score) and truncates to a token
    budget, so the RAW ``chunks`` list is NOT what the model saw. The citation
    resolves the id the generator NAMED, and the only ids it could name are the
    ones in the block above — so it must resolve against THIS list.

    Resolving against the raw list instead would be wrong in both directions:
    ``resolve_attribution`` returns on the FIRST id match, so a page-less
    duplicate that never reached the prompt could silence a citeable citation,
    and a chunk truncated out of the budget could be "resolved" to a page the
    model never had in front of it.

    (Widened from the old ``_format_chunks_for_prompt``, which computed both
    halves and discarded the second. Renamed with it: a same-named function
    that silently starts returning a tuple breaks its callers at a distance,
    whereas a rename breaks them at the import line.)

    The ImportError fallback fails SAFE rather than correct: it labels each
    block ``Source: <source_document>``, not ``Source: <chunk_id>``, so a model
    on that path can only ever name a document name — which matches no chunk_id
    and therefore resolves to silence. Silence is the right failure here, and
    the branch is unreachable in practice (retrieval.assembler is in-package).
    """
    if not chunks:
        return "", []
    try:
        from retrieval.assembler import assemble_context
        return assemble_context(chunks)
    except ImportError:
        included = list(chunks[:8])
        parts: list[str] = []
        for i, c in enumerate(included, start=1):
            header = (
                f"[{i}] Source: {getattr(c, 'source_document', 'unknown')}"
            )
            page = getattr(c, "page_number", None)
            if page:
                header += f" | Page: {page}"
            parts.append(header + "\n" + getattr(c, "content", ""))
        return "\n\n".join(parts), included


def _chunk_to_ref(chunk: Any) -> ChunkRef:
    return ChunkRef(
        chunk_id=getattr(chunk, "chunk_id", ""),
        source_document=getattr(chunk, "source_document", ""),
        page_number=getattr(chunk, "page_number", None),
        source_tier=getattr(chunk, "source_tier", None),
    )


# ----------------------------------------------------------------------
# Single attempt — generate + validate + judge
# ----------------------------------------------------------------------


async def _single_attempt(
    *,
    intent: TurnIntent,
    conversation: Conversation,
    new_user_message: str,
    retrieved_context: str,
    chunks: list[Any],
    repair_feedback: Optional[str],
    client: AsyncOpenAI,
    model: str,
    judge_model: str,
    carried_context: Optional[str] = None,
) -> _Attempt:
    """One generate+validate+judge cycle."""
    system_prompt = build_scripted_ml_prompt(
        intent=intent,
        retrieved_context=retrieved_context,
        conversation=conversation,
        repair_feedback=repair_feedback,
        carried_context=carried_context,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": new_user_message},
    ]

    completion = await client.chat.completions.parse(
        model=model,
        messages=messages,
        response_format=MiniLesson,
        **temperature_kwargs(model, 0.2),
    )
    lesson = completion.choices[0].message.parsed
    if lesson is None:
        # Abort this attempt — build a stub attempt that fails hard
        from generation.lesson import MiniLesson as ML

        stub = ML(
            skill_focus=intent.skill.as_stated if intent.skill else "",
            grade_level=intent.grade.value if intent.grade else "",
            writing_mode=intent.mode.value if intent.mode else "Inform",
            step_1_introduce="",
            step_2a_tell="",
            step_2b_show="",
            step_3_interact="",
            step_4_close="",
        )
        return _Attempt(
            lesson=stub,
            response_text="",
            policy=LessonPolicyResult(errors=["generator returned no lesson"]),
            judge=None,
            passed=False,
        )

    response_text = _lesson_to_free_text(lesson)

    # Structural + policy validators (v3's bundle)
    triggered_triggers = intent.required_triggers if intent.required_triggers else []
    policy = validate_lesson_policy(
        lesson,
        retrieved_context=retrieved_context,
        response_text=response_text,
        user_skill_phrase=intent.skill.as_stated if intent.skill else "",
        triggered_trigger_names=triggered_triggers,
        grade=intent.grade.value if intent.grade else None,
        mode=intent.mode.value if intent.mode else None,
    )

    # Judge runs only if policy has no errors (no point scoring a lesson
    # that already has structural violations — retry on those first)
    judge_verdict: Optional[JudgeVerdict] = None
    if not policy.errors:
        try:
            judge_verdict = await judge_scripted_ml(
                lesson=lesson, client=client, model=judge_model
            )
        except Exception as e:  # noqa: BLE001 — log and continue
            logger.warning("judge_v4 call failed: %s; skipping judge", e)

    passed = not policy.errors and (
        judge_verdict is None or judge_verdict.passes
    )

    return _Attempt(
        lesson=lesson,
        response_text=response_text,
        policy=policy,
        judge=judge_verdict,
        passed=passed,
    )


def _titlecase_first(s: str) -> str:
    """Capitalize only the first character; leave the rest untouched
    (unlike str.title()/str.capitalize(), which would lowercase the
    remainder). Empty string passes through unchanged."""
    return s[:1].upper() + s[1:] if s else s


def _lesson_to_free_text(lesson: MiniLesson) -> str:
    """Flatten a MiniLesson to a single-string form for response_text
    + validators that scan free text (banned words, trigger usage).

    Brady Fm3: the displayed title (first line, from skill_focus) is
    title-cased at this render site only — lesson.skill_focus itself is
    never mutated, so validate_skill_focus_vocab's case-insensitive check
    and the delivered structured/model_dump() payload are unaffected.

    Brady Fm4: the "Grade X | <Mode>" header is NO LONGER rendered here.
    It is applied by _finalize_ml_delivery from the INTENT (never the LLM-authored
    lesson.grade_level/writing_mode) after this text is built — so this
    helper deliberately omits it. The title keeps a trailing blank line
    (\\n\\n) so Step 1 stays its own block, exactly as when the old
    grade/mode line supplied that separation."""
    return (
        f"{_titlecase_first(lesson.skill_focus)}\n\n"
        f"Step 1 — Introduce\n{lesson.step_1_introduce}\n\n"
        f"Step 2A — Tell\n{lesson.step_2a_tell}\n\n"
        f"Step 2B — Show (Think-Aloud)\n{lesson.step_2b_show}\n\n"
        f"Step 3 — Interact\n{lesson.step_3_interact}\n\n"
        f"Step 4 — Close\n{lesson.step_4_close}\n"
    )


def _citation_for(attempt: _Attempt, chunks: list[Any], retrieved_context: str) -> str:
    """Brady Fm5 + citation identity: build the soft citation from the source the
    GENERATOR NAMED, never from rank.

    This is called at each of the three delivery exits rather than once before
    generation, because that is the whole fix: the citation cannot be about "this
    lesson" until the lesson exists. Each exit ships a DIFFERENT attempt (pass /
    LLM-trustable / best-of-three), hence a different lesson, hence potentially a
    different source — one pre-computed value cannot be correct for all three.

    ``chunks`` MUST be the assembled context's chunks (``_assemble_for_prompt``'s
    second half), not the raw retrieval list — see that function's docstring.

    Silence is the default: resolve_attribution returns None unless the named id
    is real, in-context, titled and paged.
    """
    lesson = attempt.lesson
    if lesson is None:
        return ""
    # Direct access, not getattr(..., None): MiniLesson guarantees the field, and
    # _build_outcome already calls lesson.model_dump() on this same object — so a
    # default would defend against nothing the types allow, while making the
    # guard above unreachable and its test unable to fail.
    named = lesson.source_chunk_id
    resolved = resolve_attribution(named, chunks, retrieved_context)
    if named and resolved is None:
        # Silence and a bug look identical from the outside — both deliver no
        # citation. This is the one place the difference is knowable, so record
        # it: the model DID name a block and we could not turn it into a page.
        # Expected occasionally (the model names a non-Launch or page-less
        # chunk); a sustained rate means extraction or assembly drifted.
        logger.info(
            "scripted_ml citation silent: generator named source_chunk_id=%r, "
            "unresolvable against the %d assembled chunk(s)",
            named,
            len(chunks or []),
        )
    return build_soft_citation(*(resolved or (None, None)))


# Brady E2 — every delivered scripted-ML response ends with a short
# customization follow-up so the teacher is prompted to flag whether the
# script needs to be more rigorous or simpler for their student-writers.
# Deterministic append onto the FINAL rendered text only (see _build_outcome
# below) — this is not an LLM instruction and is NOT wired into
# validate_lesson_policy, whose response_text (built in _single_attempt) is
# the pre-append lesson text the structural validators score.
_E2_FOLLOWUP = (
    "Does this script seem appropriate for your student-writers? "
    "Do I need to make anything more rigorous or simpler?"
)


def _finalize_ml_delivery(outcome: TurnOutcome, intent: TurnIntent) -> TurnOutcome:
    """THE delivery seam — the ONE place a SCRIPTED_ML payload is finalized
    with every deterministic Brady transform.

    Why a seam and not N assignments at N sites: api.routes_v4._build_response
    delivers ``outcome.structured`` as the API's ``response`` whenever it is
    non-None — ALWAYS true for a mini-lesson — and DISCARDS ``response_text``.
    So a transform applied only to response_text NEVER reaches the teacher.
    That class bit Fm4, S3 and Fm5 (each patched field-by-field at a different
    site) and silently killed Fm3 + E2 outright: Fm3 shipped 2026-07-09 against
    a structured-takes-priority branch that predated it by ~2.5 months, so it
    never worked for a single day. Its unit tests passed because they scored
    the helper in isolation and response_text — never the delivered payload.
    Every deterministic transform belongs HERE, on ``structured``; the lock in
    tests/unit/test_ml_delivery_contract.py fails a response_text-only one.

    EVERY SCRIPTED_ML return funnels through this function — the library-verbatim
    early return plus the three generated exits — which also covers DEEPEN_PRIOR
    (it delegates to handle_scripted_ml). So both producers get all transforms.

    Applied to the delivered structured payload:
      * source_chunk_id — STRIPPED. An internal generation artifact, not an
        output; see the comment at the pop below.
      * Fm3 — the title, capitalized (first character only).
      * E2  — the teacher-facing customization follow-up, as its own field.
      * Fm4 — the intent-computed 'Grade X | <Mode>' header.
    (Fm5's ``book_citation`` is producer-specific — it needs the retrieved
    chunks / library entry — so each producer puts it on ``structured`` at the
    point it is known; the lock covers it from there.)

    Pure: the MiniLesson is never mutated (``structured`` is already a
    model_dump() copy), so validate_skill_focus_vocab — which reads the lesson
    object, and is case-insensitive regardless — is unaffected. Kept out of
    _build_outcome so that helper's pure-over-_Attempt contract is preserved."""
    structured: dict[str, Any] = {**(outcome.structured or {})}

    # The attribution is an internal generation artifact: it exists to build the
    # citation (_citation_for), and by here its job is done. `structured` IS the
    # delivered payload (routes_v4.py:211-213 ships it and discards response_text),
    # so leaving the id in would ship internal vocabulary the prompt bans
    # outright. No teacher sees it today only because the frontend renders named
    # keys — an accident of the renderer, not a contract.
    structured.pop("source_chunk_id", None)

    # Fm3 — the generator authors skill_focus in the teacher's own (usually
    # lowercase) words. _lesson_to_free_text capitalizes the response_text copy,
    # but that copy is discarded at delivery, so the title must be capitalized
    # HERE too. _titlecase_first is idempotent → applying it at both is safe.
    skill_focus = structured.get("skill_focus")
    if isinstance(skill_focus, str):
        structured["skill_focus"] = _titlecase_first(skill_focus)

    # C1 (Brady: "I love that it's a verb. It's a statement.") — the DISPLAYED
    # title is the model-authored, verb-led ``lesson_title``, kept DISTINCT from
    # ``skill_focus`` (which stays the teacher's exact vocab above, as the
    # step-body anchor + the frontend fallback). Title-cased like skill_focus so
    # its first character is capitalized regardless of the model's casing. NOT
    # popped — unlike source_chunk_id it is a delivered field. Absent on the
    # library-verbatim path (that structured dict carries no lesson_title), where
    # ``.get`` returns None and the frontend falls back to skill_focus.
    lesson_title = structured.get("lesson_title")
    if isinstance(lesson_title, str) and lesson_title:
        structured["lesson_title"] = _titlecase_first(lesson_title)

    # E2 — already appended to response_text by BOTH producers (_build_outcome /
    # build_verbatim_response); surfaced here as its own key so it survives
    # delivery and the frontend can render it as its own closing paragraph.
    # Unconditional: Brady wants it on every delivered scripted ML.
    structured["followup"] = _E2_FOLLOWUP

    # Fm4 — the mode segment comes from ``intent.mode``, NEVER from the
    # LLM-authored ``lesson.writing_mode``. When the teacher stated no mode the
    # lesson's writing_mode is an invented value; surfacing it would fabricate a
    # mode the teacher never asked for, so the header is grade-only ("Grade 4"),
    # and grade-less intents get no header at all. That gate is header-ONLY —
    # the transforms above stay unconditional, or an unknown grade would
    # silently swallow Fm3 + E2 (the very bug this seam exists to prevent).
    header = format_lesson_header(
        intent.grade.value if intent.grade else None,
        intent.mode.value if intent.mode else None,
    )
    text = outcome.response_text
    if header:
        structured["header"] = header
        text = f"{header}\n{text}" if text else header

    return outcome.model_copy(
        update={"structured": structured, "response_text": text}
    )


def _build_outcome(
    *,
    attempt: _Attempt,
    grounding: list[ChunkRef],
    quality: Quality,
    retry_count: int,
    retrieved_context: str = "",
    book_citation: str = "",
) -> TurnOutcome:
    """Compose the final TurnOutcome from an attempt.

    Runs two deterministic scrubs over each step before shipping:
      1. Citation scrub — any page number / book attribution /
         digital-resources mention the generator invented (and retry
         didn't catch) is removed rather than surfaced to the teacher.
         Unverifiable citations are worse than missing citations.
      2. Forbidden-word scrub (Brady April non-negotiable #5: never
         emit "discuss" / "activity" / "I'll listen in" / PD-plug
         language) — the last line of defense after the validator +
         retry loop, in case a forbidden word survives all retries.
    """
    lesson = attempt.lesson
    step_fields = (
        "step_1_introduce",
        "step_2a_tell",
        "step_2b_show",
        "step_3_interact",
        "step_4_close",
    )
    scrubbed_fields: dict[str, str] = {}
    all_removed: list[str] = []
    for field_name in step_fields:
        original = getattr(lesson, field_name, "") or ""
        scrubbed, removed = scrub_unverifiable_citations(
            original, retrieved_context
        )
        scrubbed, fw_removed = scrub_forbidden_words(scrubbed)
        if removed or fw_removed:
            scrubbed_fields[field_name] = scrubbed
            all_removed.extend(removed)
            all_removed.extend(fw_removed)
    # C1 forbidden-word safety net for the model-authored title (Brady non-neg
    # #5). The loop above covers only the step BODIES, and lesson_title is
    # deliberately NOT in response_text (validate_no_forbidden_words never scans
    # it — _lesson_to_free_text titles from skill_focus), so a banned word in the
    # title survives the validator + retry loop and would reach the teacher. Only
    # the forbidden-word scrub applies: a title carries no page/book citation to
    # strip. (skill_focus is intentionally left alone — teacher vocab, validated
    # not rewritten.)
    title = getattr(lesson, "lesson_title", "") or ""
    if title:
        scrubbed_title, title_removed = scrub_forbidden_words(title)
        if title_removed:
            scrubbed_fields["lesson_title"] = scrubbed_title
            all_removed.extend(title_removed)
    if scrubbed_fields:
        lesson = lesson.model_copy(update=scrubbed_fields)
        logger.info(
            "scripted_ml scrubbed %d citation/forbidden-word issue(s): %s",
            len(all_removed),
            all_removed[:3],
        )
    # Brady Fm5 footer: the deterministic soft citation is appended HERE —
    # AFTER the per-step citation scrubber above — so it is never itself
    # re-scrubbed (a full book title with no Teal/K-2 marker in context would
    # otherwise be stripped). rstrip() drops the lesson's own trailing newline
    # so each of body, citation, and the E2 follow-up is its own clean
    # paragraph (exactly ONE blank line, the same boundary _lesson_to_free_text
    # emits between steps) — never a stacked "\n\n\n".
    body = _lesson_to_free_text(lesson).rstrip()
    # soft citation as its own paragraph AFTER the lesson body and BEFORE the
    # E2 follow-up question. Brady E2 follow-up stays last.
    tail = f"{book_citation}\n\n{_E2_FOLLOWUP}" if book_citation else _E2_FOLLOWUP
    response_text = f"{body}\n\n{tail}"

    structured = lesson.model_dump()
    # Surface the soft citation on the structured payload (mirrors how
    # _finalize_ml_delivery surfaces the Fm4 header) so the frontend can render it as
    # its own footer element. Omitted entirely when no citation is known.
    if book_citation:
        structured["book_citation"] = book_citation
    judge_scores: Optional[dict] = None
    if attempt.judge is not None:
        judge_scores = {
            "narrative_coherence": attempt.judge.narrative_coherence.score,
            "strategy_gist_present": attempt.judge.strategy_gist_present.score,
            "step1_structure": attempt.judge.step1_structure.score,
            "passes": attempt.judge.passes,
        }
    return TurnOutcome(
        response_text=response_text,
        structured=structured,
        grounding=grounding,
        quality=quality,
        retry_count=retry_count,
        validation_errors=list(attempt.policy.errors),
        judge_scores=judge_scores,
        retrieved_context=retrieved_context,
    )
