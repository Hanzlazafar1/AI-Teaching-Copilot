"""The citation names the lesson's OWN source, not whatever ranked first.

Spec §3.3. The defect this locks out: ``handlers/scripted_ml.py`` built
``book_citation`` from retrieval RANK *before* the generation loop ran — so
"you'll find THIS LESSON on p.N" was chosen before "this lesson" existed, and
the top retrieval attractor won regardless of what the model actually wrote.
Measured live on the pre-fix code: cited page == top-ranked chunk's page 30/30,
and the wrong page shipped to teachers 10/30.

The fix is a source change, not a threshold: each delivery exit builds its
citation AFTER generation, from the id the generator NAMED
(``MiniLesson.source_chunk_id`` -> ``handlers.citation.resolve_attribution``).

SCOPE — what this file adds over test_fm5_citation_wiring.py:
  That file's (a) docstring CLAIMED to lock "the 3 _build_outcome call sites",
  but it drives ONE clean, judge-passing attempt: it reaches exit #1 and only
  exit #1 (docstring corrected there). The LOW best-of-three exit — live, and
  the one v1 of this plan forgot — is covered here, twice: that it cites at all,
  and that it cites the attempt it ACTUALLY SHIPS.

  The LLM-trustable exit (#2) is driven too — for ONE of the two defect classes
  there. They are not alike, and the earlier "no test at all" call here conflated
  them:
    * WRONG-VARIABLE (passing ``attempt`` where ``trusted_attempt`` belongs) is
      genuinely undetectable. ``trusted_attempt`` is rebuilt FROM
      ``attempt.lesson`` — the same object — so ``_citation_for`` reads the same
      ``source_chunk_id`` and returns the same string either way. No test can
      fail on it, and a test that cannot fail is worse than no test at all. That
      class stays untested, deliberately.
    * DROPPED-WIRING (the ``book_citation=`` argument deleted, or emptied) is
      fully detectable, and exit #2 was the ONE exit no test reached: deleting
      that argument left the whole suite green — an UNCITED lesson shipped live,
      1873 passed. ``_build_outcome`` defaults ``book_citation=""`` and then
      omits the key, so the failure is silent by construction. That is exactly
      the class test_fm5_citation_wiring.py's docstring says it exists to
      prevent, so the gap is closed below by
      test_the_LLM_trustable_exit_still_cites_the_named_source (the sibling
      handler family already locks its own third call site the same way — see
      test_handlers_base_text.py's
      test_run_text_handler_threads_header_on_llm_trustable_path).
"""
from __future__ import annotations

from typing import Optional

import handlers.scripted_ml as scripted_ml_mod
from generation.lesson import MiniLesson
from handlers.scripted_ml import _Attempt, _citation_for, handle_scripted_ml
from retrieval.search import RetrievedChunk
from schemas import (
    Conversation,
    GradeSpec,
    ModeSpec,
    Quality,
    RequestType,
    SessionHandshakes,
    SkillSpec,
    TurnIntent,
    TurnOutcome,
)
from tests.unit._policy_fixtures import _good_lesson
from validation.policy import LessonPolicyResult, is_llm_trustable_error

import pytest

from validation.judge_v4 import DimensionScore, JudgeVerdict

_TEAL = "Launching the Writers Workshop 3-12.pdf"
_TEAL_TITLE = "Launching the Writers Workshop 3-12"

# The two ids the fixtures below name. The "attractor" is the chunk that WINS on
# rank; the "real" one is what a lesson claims it was built from.
_ATTRACTOR_ID = "lww312-s9-ml15-informative-introductions"
_ATTRACTOR_PAGE = 92
_REAL_ID = "lww312-s8-ml05"
_REAL_PAGE = 64


def _chunk(chunk_id: str, page: int, *, score: float = 0.9) -> RetrievedChunk:
    """A CITEABLE Launch chunk.

    ``book_name=None`` forces ``_full_book_title``'s source_document fallback
    (the doc name already carries the full title), and ``page_number`` is the
    page the citation must name. Both halves are required or
    ``resolve_attribution`` returns None and every assertion here goes vacuous —
    ``test_fixtures_are_citeable`` guards exactly that.
    """
    return RetrievedChunk(
        chunk_id=chunk_id,
        source_document=_TEAL,
        content_type="lesson_script",
        content="body",
        grade_level="4",
        writing_trait="organization",
        writing_mode="Inform",
        strategy_name="transitions between paragraphs",
        tier=1,
        step="ml05",
        score=score,
        book_name=None,
        page_number=page,
        source_tier=0,
    )


def _ctx(*pages: int) -> str:
    """A stand-in for the assembled context. Only its ``Page: N`` headers are
    load-bearing: ``resolve_attribution`` matches ids against the CHUNK OBJECTS
    and uses the context solely to confirm the page was really retrieved."""
    return "\n".join(
        f"[{i}] Source: s{i} | Book: {_TEAL_TITLE} | Page: {p}\nbody"
        for i, p in enumerate(pages, 1)
    )


def _lesson(source_chunk_id: Optional[str] = None) -> MiniLesson:
    return MiniLesson(
        skill_focus="Add leg sentences to a table-top reason",
        grade_level="4",
        writing_mode="Inform",
        step_1_introduce="a",
        step_2a_tell="b",
        step_2b_show="c",
        step_3_interact="d",
        step_4_close="e",
        source_chunk_id=source_chunk_id,
    )


def _attempt(
    source_chunk_id: Optional[str] = None, lesson_missing: bool = False
) -> _Attempt:
    return _Attempt(
        lesson=None if lesson_missing else _lesson(source_chunk_id),
        response_text="",
        policy=LessonPolicyResult(errors=[]),
        judge=None,
        passed=True,
    )


def _intent(*, grade: Optional[str] = "4", mode: Optional[str] = "Inform") -> TurnIntent:
    """SCRIPTED_ML intent whose skill matches ``_good_lesson()``'s skill_focus so
    validate_skill_focus_vocab is not an incidental extra failure."""
    return TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        skill=SkillSpec(
            canonical="transitions between paragraphs",
            as_stated="transitions between paragraphs",
        ),
        grade=GradeSpec(value=grade, stated_explicit=True) if grade else None,
        mode=ModeSpec(value=mode, stated_explicit=True) if mode else None,
    )


def test_fixtures_are_citeable() -> None:
    """The load-bearing anchor: both fixture chunks MUST resolve through the real
    resolver. If this drifts, every "cites p.64" assertion becomes impossible and
    every "92 not in" assertion becomes vacuous."""
    from handlers.citation import resolve_attribution

    chunks = [_chunk(_ATTRACTOR_ID, _ATTRACTOR_PAGE), _chunk(_REAL_ID, _REAL_PAGE)]
    ctx = _ctx(_ATTRACTOR_PAGE, _REAL_PAGE)
    assert resolve_attribution(_REAL_ID, chunks, ctx) == (_TEAL_TITLE, _REAL_PAGE)
    assert resolve_attribution(_ATTRACTOR_ID, chunks, ctx) == (
        _TEAL_TITLE,
        _ATTRACTOR_PAGE,
    )


# ======================================================================
# _citation_for — the unit
# ======================================================================


def test_citation_comes_from_the_named_chunk_not_the_top_ranked():
    """THE fix. The attractor is FIRST, so rank would cite p.92."""
    attractor = _chunk(_ATTRACTOR_ID, _ATTRACTOR_PAGE)
    real = _chunk(_REAL_ID, _REAL_PAGE)
    out = _citation_for(
        _attempt(_REAL_ID), [attractor, real], _ctx(_ATTRACTOR_PAGE, _REAL_PAGE)
    )
    assert "p.64." in out
    assert "92" not in out


def test_citation_silent_when_the_model_named_nothing():
    """Non-vacuous: the chunk IS citeable, so the pre-fix rank build would have
    returned the p.64 pointer here. Naming nothing must yield silence, not rank."""
    c = _chunk(_REAL_ID, _REAL_PAGE)
    assert _citation_for(_attempt(None), [c], _ctx(_REAL_PAGE)) == ""


def test_citation_silent_on_a_fabricated_id():
    """Same shape: a citeable chunk is present, so falling back to rank on an
    unresolvable id would produce p.64. Silence is the only correct answer —
    the model named a block it did not get."""
    c = _chunk(_REAL_ID, _REAL_PAGE)
    assert _citation_for(_attempt("hallucinated"), [c], _ctx(_REAL_PAGE)) == ""


def test_no_lesson_no_citation():
    """A lesson-less attempt cites NOTHING, and does not raise.

    Locks the ``if lesson is None`` guard: without it, ``lesson.source_chunk_id``
    raises AttributeError (verified by mutation) — a footer taking down the whole
    turn. It also pins the direction of failure: a rank fallback on this path
    would confidently cite p.64 for a lesson that does not exist.

    CORRECTED from the brief, which passed ``[], ""``: with no chunks and no
    context EVERY implementation returns "" — including the rank-based one this
    plan removes — so that version could not fail for any reason. Handing it the
    citeable chunk is what makes both halves above real."""
    c = _chunk(_REAL_ID, _REAL_PAGE)
    assert _citation_for(_attempt(lesson_missing=True), [c], _ctx(_REAL_PAGE)) == ""


# ======================================================================
# The delivery seam — `structured` IS the API response
# ======================================================================


def test_the_attribution_is_stripped_from_the_delivered_payload():
    """`structured` IS the API response — routes_v4.py:211-213 ships it and
    DISCARDS response_text. The attribution is an internal generation artifact:
    once the citation is built its job is done. Shipping the id would put
    internal vocabulary (scripted_ml_prompt.py:209-213 bans "chunks"/"retrieved")
    into the teacher's payload."""
    from handlers.scripted_ml import _finalize_ml_delivery

    outcome = TurnOutcome(
        response_text="x",
        structured=_lesson(_REAL_ID).model_dump(),
        quality=Quality.VALID,
    )
    # Non-vacuous: the id really is in the model_dump the producer builds.
    assert "source_chunk_id" in outcome.structured

    delivered = _finalize_ml_delivery(outcome, _intent())
    assert "source_chunk_id" not in delivered.structured


# ======================================================================
# End-to-end: the delivery exits
# ======================================================================


class _FakeGenMessage:
    def __init__(self, parsed) -> None:
        self.parsed = parsed


class _FakeGenChoice:
    def __init__(self, parsed) -> None:
        self.message = _FakeGenMessage(parsed)


class _FakeGenCompletion:
    def __init__(self, parsed) -> None:
        self.choices = [_FakeGenChoice(parsed)]


class _FakeGenCompletions:
    """One scripted MiniLesson per attempt, in order. Raises when it runs out —
    so a change to _MAX_ATTEMPTS is loud here rather than silently reusing a
    lesson these tests depend on being distinct."""

    def __init__(self, lessons) -> None:
        self._lessons = list(lessons)
        self.calls = 0

    async def parse(self, **kwargs):  # mirrors AsyncOpenAI chat.completions.parse
        if not self._lessons:
            raise RuntimeError("fake generation client ran out of lessons")
        self.calls += 1
        return _FakeGenCompletion(self._lessons.pop(0))


class _FakeGenChat:
    def __init__(self, lessons) -> None:
        self.completions = _FakeGenCompletions(lessons)


class _FakeGenerationClient:
    def __init__(self, lessons) -> None:
        self.chat = _FakeGenChat(lessons)


@pytest.fixture
def pass_judge(monkeypatch):
    """Network-free accept-gate.

    LOAD-BEARING on the trust exit: the loop only ever arrives there with policy
    errors outstanding, so ``attempt.judge`` is None and the branch calls the
    judge ITSELF — this verdict is what turns a flagged lesson into a VALID
    delivery. Inert on the LOW paths below (the judge is not run while policy has
    errors, and their errors are not trustable so the branch never opens), where
    it only guarantees a fixture drift can never turn into a live network call."""

    async def _fake_judge(*, lesson, client, model):
        good = DimensionScore(score=9, violations=[])
        return JudgeVerdict(
            narrative_coherence=good,
            strategy_gist_present=good,
            step1_structure=good,
        )

    monkeypatch.setattr(scripted_ml_mod, "judge_scripted_ml", _fake_judge)


# A Step 3 that PARAPHRASES all four required Smekens phrases instead of using
# them. validate_step_3_phrases flags it, and that error is NOT
# is_llm_trustable_error() — so the loop CANNOT take the trust exit and must
# fall through all _MAX_ATTEMPTS to the best-of-three LOW delivery.
_PARAPHRASED_STEP_3 = (
    "Now let's work on the next sentence together. "
    "Chat with your partner about where a transition would go. "
    "When you return, share what you decided. "
    "Here is an example of what you might say: 'However, my favorite flavor "
    "is chocolate.'"
)

# Drops the 3-12 grade-band close ("Now it's your turn!") -> one MORE
# non-trustable error, which is how the best-of-three below is made to have a
# unique, deterministic winner.
_WRONG_BAND_CLOSE = (
    "Today you practiced using transitions to link your ideas. "
    "Go ahead and try writing three sentences with a transition in your "
    "notebook."
)

# The MIRROR IMAGE of _PARAPHRASED_STEP_3: a teacher-voice sentence carrying a
# forbidden word (Brady non-negotiable #5). validate_no_forbidden_words' error
# IS is_llm_trustable_error(), and it is the ONLY error this lesson scores (the
# unmodified _good_lesson() scores zero — measured, not assumed), so `all(...)`
# in the trust branch holds and from attempt 2 the loop exits there rather than
# falling through to best-of-three. Appended to Step 2A, whose length is bounded
# only from BELOW (≥2× Step 1), so the extra sentence cannot trip depth/balance
# and smuggle in a non-trustable error that would close the branch again.
_FORBIDDEN_WORD_STEP_2A = (
    _good_lesson().step_2a_tell
    + " Later, you and your partner will discuss which transition fits best."
)


async def _retrieval_fn(**kwargs):
    """Fake hybrid_search: the ATTRACTOR ranks first (higher score), exactly as
    it did in the live measurement. Both chunks are citeable, so a wrong pick
    produces a CONFIDENT WRONG page (p.92) rather than silence — the real defect
    shape."""
    return [
        _chunk(_ATTRACTOR_ID, _ATTRACTOR_PAGE, score=0.95),
        _chunk(_REAL_ID, _REAL_PAGE, score=0.80),
    ]


async def _run(lessons) -> TurnOutcome:
    return await handle_scripted_ml(
        intent=_intent(),
        conversation=Conversation(session_id="s"),
        handshakes=SessionHandshakes(),
        new_user_message="lesson on transitions between paragraphs",
        client=_FakeGenerationClient(lessons),
        model="GEN",
        judge_model="JDG",
        canonicalizer=object(),
        retrieval_fn=_retrieval_fn,
        library=None,
    )


async def test_the_citation_resolves_against_the_chunks_the_MODEL_SAW(pass_judge):
    """The resolver must see the ASSEMBLED list, not the raw retrieval list.

    ``_assemble_for_prompt`` dedupes by chunk_id (keeping the better
    (source_tier, -score)), so the raw list is NOT what the model saw. Here the
    same id appears twice: a PAGE-LESS copy ranked first, and the citeable p.64
    copy that outscores it. The assembler keeps the citeable one — that is the
    single block the model read and named.

    ``resolve_attribution`` returns on the FIRST id match, so resolving against
    the raw list hits the page-less copy and goes silent: a citeable citation
    destroyed by a duplicate the model never saw. This is the ONLY test that
    separates the two lists — everywhere else they hold the same chunks."""
    pageless = _chunk(_REAL_ID, _REAL_PAGE, score=0.50)
    pageless.page_number = None  # same id, ranked FIRST, cannot be cited

    async def _dup_retrieval_fn(**kwargs):
        return [pageless, _chunk(_REAL_ID, _REAL_PAGE, score=0.90)]

    lesson = _good_lesson(source_chunk_id=_REAL_ID)
    outcome = await handle_scripted_ml(
        intent=_intent(),
        conversation=Conversation(session_id="s"),
        handshakes=SessionHandshakes(),
        new_user_message="lesson on transitions between paragraphs",
        client=_FakeGenerationClient([lesson]),
        model="GEN",
        judge_model="JDG",
        canonicalizer=object(),
        retrieval_fn=_dup_retrieval_fn,
        library=None,
    )

    assert outcome.quality is Quality.VALID
    assert "p.64." in (outcome.structured or {}).get("book_citation", "")


async def test_the_LLM_trustable_exit_still_cites_the_named_source(pass_judge):
    """Exit #2 (scripted_ml.py:225-237) — the exit a passing attempt and a LOW
    best-of-three both skip, and the only one no test reached.

    Covers the DROPPED-WIRING class only; the module docstring says why the
    wrong-variable class is unreachable by ANY test. Load-bearing, verified by
    mutation rather than asserted: hard-coding that exit's ``book_citation`` to
    "" turns THIS test red and leaves the other 1873 green.

    Shape: the lesson keeps a forbidden word through a contextual retry, the
    judge agrees it is coherent anyway, and the loop ships VALID on the LLM's
    say-so — with the flag still on the outcome. The attractor still ranks
    FIRST, so a rank-built citation would confidently say p.92 here."""
    trustable = _good_lesson(
        step_2a_tell=_FORBIDDEN_WORD_STEP_2A, source_chunk_id=_REAL_ID
    )
    # Exactly two: the trust exit fires on attempt 2, so a third would mean the
    # branch never opened — _FakeGenCompletions raises rather than let this test
    # quietly grade a different exit.
    outcome = await _run([trustable, trustable])

    # Proof the loop reached exit #2 — without it this test proves nothing about
    # the exit it names. VALID rules out the LOW best-of-three; errors RETAINED
    # on a VALID delivery is the trust exit's signature and rules out the pass
    # exit, where `passed = not policy.errors and ...` makes them empty BY
    # DEFINITION. retry_count pins the `attempt_idx >= 1` gate that is the only
    # reason the branch is reachable at all.
    assert outcome.quality is Quality.VALID
    assert outcome.retry_count == 1
    assert outcome.validation_errors
    assert all(is_llm_trustable_error(e) for e in outcome.validation_errors)

    # THE ASSERTION: the exit cites, and cites the source the model NAMED.
    assert "p.64." in (outcome.structured or {}).get("book_citation", "")
    assert "92" not in (outcome.structured or {}).get("book_citation", "")


async def test_the_LOW_exit_still_cites_the_named_source(pass_judge):
    """Spec §7 decision #12: lesson quality is ORTHOGONAL to citation truth. A
    LOW lesson built from a real chunk is still on that page, and 6 of 12 real
    low_quality deliveries in drive-cache.jsonl carry Brady's pointer today — so
    this exit is live, not hypothetical.

    The attractor ranks FIRST, so the pre-fix rank build cited p.92 here."""
    failing = _good_lesson(
        step_3_interact=_PARAPHRASED_STEP_3, source_chunk_id=_REAL_ID
    )
    outcome = await _run([failing, failing, failing])

    # The loop really reached the LOW exit — without this the test proves
    # nothing about the exit it claims to cover.
    assert outcome.quality is Quality.LOW
    assert "p.64." in outcome.structured["book_citation"]
    assert "92" not in outcome.structured["book_citation"]


async def test_the_LOW_exit_cites_the_attempt_it_actually_ships(pass_judge):
    """The LOW exit ships ``best`` (fewest failures), NOT the loop's last
    ``attempt``. Passing the wrong variable there re-introduces the whole defect
    in miniature: a citation about a lesson the teacher never received.

    This is the ONLY test that can catch it. Every other end-to-end test in the
    suite feeds one repeated lesson, so `best is attempts[-1]` and the two
    variables are indistinguishable. Here attempt 1 has strictly the fewest
    errors and names p.64, while attempts 2-3 name the p.92 attractor — so
    `_citation_for(attempt, ...)` at that exit cites p.92 while shipping the
    p.64 lesson, and this fails."""
    best = _good_lesson(  # 1 error (Step 3 phrases)
        step_3_interact=_PARAPHRASED_STEP_3, source_chunk_id=_REAL_ID
    )
    worse = _good_lesson(  # 2 errors (Step 3 phrases + E1 grade-band close)
        step_3_interact=_PARAPHRASED_STEP_3,
        step_4_close=_WRONG_BAND_CLOSE,
        source_chunk_id=_ATTRACTOR_ID,
    )
    outcome = await _run([best, worse, worse])

    assert outcome.quality is Quality.LOW
    # The shipped lesson is `best` — its Step 4 keeps the 3-12 band close...
    assert "Now it's your turn!" in outcome.structured["step_4_close"]
    # ...so the citation must name `best`'s source, not the last attempt's.
    assert "p.64." in outcome.structured["book_citation"]
    assert "92" not in outcome.structured["book_citation"]
