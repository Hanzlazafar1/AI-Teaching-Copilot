"""END-TO-END lock on the deterministic citation WIRING, per handler.

Every citation this system ships is built by code from a Launch chunk's TYPED
metadata — never authored by the LLM. What differs per handler is WHICH source
gets cited and WHERE the sentence lands:

  * ``handle_scripted_ml``   -> ``_citation_for`` -> ``_build_outcome
    (book_citation=...)`` -> footer in ``response_text`` (after Step 4, before
    the E2 follow-up) + ``structured["book_citation"]``. Resolves the source the
    GENERATOR NAMED (``MiniLesson.source_chunk_id`` -> ``resolve_attribution``),
    not the top-ranked chunk: the citation says "THIS lesson", so it cannot be
    picked before the lesson exists. A lesson IS one thing, so ONE footer fits.
  * ``handle_how_to_teach``  -> ``run_text_handler_with_retry(citation_resolver=
    ...)`` -> ``_build_text_outcome`` -> ``resolve_markers`` -> a citation
    sentence INLINE on each claim that earned one. An outline is not one thing:
    Brady's own approved artifacts (image3, image39) carry several citation
    sites per answer — 5 sites across 6 pages in one — so a single footer could
    not reproduce his shape. The generator marks each claim it built from a
    retrieved block with that block's ``Source:`` id; code resolves the markers.
  * ``handle_coaching``      -> same seam as HOW_TO_TEACH. (Per-claim here is
    OUR uniform application of a rule anchored on HOW_TO_TEACH, not Brady's ask
    — see handlers/coaching.py's note. It carried the identical rank-based
    picker.)
  * every OTHER text handler (MANAGEMENT/PLAN_UNIT/THINK_ALOUD) passes NOTHING
    -> resolver defaults to None -> stays uncited.

The rest of the unit suite tests these seams IN ISOLATION (build_soft_citation,
resolve_attribution, resolve_markers, _build_outcome/_build_text_outcome with a
hand-passed citation/resolver). NONE of them drive the REAL handlers on the
citation-PRESENT path, so a future edit dropping the ``citation_resolver=``
argument from a handler call site would pass the whole suite while shipping
RAW ``[[src:...]]`` MARKERS to a teacher — strictly worse than the uncited
lesson the ``book_citation=`` version of this file was written to prevent. That
is not hypothetical: it is the exact state of the tree between the prompt rule
landing and the handlers migrating. So this file locks the wiring
deterministically.

Everything here is network-free: a fake AsyncOpenAI client (canned MiniLesson /
canned text) + a fake ``retrieval_fn`` returning ONE page-verified Launch chunk.
The harnesses mirror test_scripted_ml_header.py (structured path) and
test_handlers_base_text.py (text path).

NON-VACUOUSNESS: the citation asserted on is the REAL delivered string
(``_EXPECTED_CITATION``, pinned + proven citeable by
``test_fixture_chunk_is_citeable``). If any handler dropped its citation wiring
the sentence would never be built — the present-path assertions in (a)/(b)/(c)
reference the concrete non-empty string, so they would fail; (d) references the
same string, so its absence assertion is never vacuous.
"""
from __future__ import annotations

import pytest

import handlers.scripted_ml as scripted_ml_mod
from handlers.citation import (
    build_soft_citation,
    resolve_attribution,
)
from handlers.coaching import handle_coaching
from handlers.how_to_teach import handle_how_to_teach
from handlers.management import handle_management
from handlers.scripted_ml import _E2_FOLLOWUP, handle_scripted_ml
from retrieval.assembler import assemble_context
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
)
from tests.unit._policy_fixtures import _good_lesson
from validation.endings import HOW_TO_TEACH_MULTI_SKILL_CLOSER
from validation.judge_v4 import DimensionScore, JudgeVerdict


# ----------------------------------------------------------------------
# The page-verified Launch chunk + the citation it MUST produce
# ----------------------------------------------------------------------
#
# _full_book_title resolves via the source_document fallback (a "Launching the
# Writers Workshop ..." doc name, book_name left None) and page_number is set,
# so assemble_context emits a "Book: ... | Page: 64" header. That makes
# resolve_attribution fire (page 64 is in the assembled context's Page: headers)
# and build_soft_citation produce the deterministic sentence below.


# The id the generator NAMES as the block it built from — as a MiniLesson field
# in (a), as an inline [[src:...]] marker in (b)/(c). Shared with the chunk
# below so the two cannot drift apart silently.
_CITED_CHUNK_ID = "lww312-s8-ml05"
_MARKER = f"[[src:{_CITED_CHUNK_ID}]]"


def _launch_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=_CITED_CHUNK_ID,
        source_document="Launching the Writers Workshop 3-12.pdf",
        content_type="lesson_script",
        content=(
            "Model a transition between two paragraphs, then have writers add "
            "one to their own draft."
        ),
        grade_level="4",
        writing_trait="organization",
        writing_mode="Inform",
        strategy_name="transitions between paragraphs",
        tier=1,
        step="ml05",
        score=0.95,
        book_name=None,  # force the source_document fallback in _full_book_title
        page_number=64,
        source_tier=0,  # Launch-first tier
    )


# The deterministic string the whole pipeline must deliver for _launch_chunk().
_EXPECTED_CITATION = (
    "If you have the 'Launching the Writers Workshop 3-12' book, "
    "you'll find this lesson on p.64."
)

_HTT_CLOSER = "Are you ready for a scripted mini-lesson on this skill?"


async def _retrieval_fn(**kwargs):
    """Fake hybrid_search: accepts any kwargs the handlers thread (query,
    intent, query_type, strategy_name, grade_level, ...) and returns ONE
    page-verified Launch chunk."""
    return [_launch_chunk()]


def test_fixture_chunk_is_citeable() -> None:
    """Guard the whole file against a silently non-citeable fixture: the shared
    chunk MUST resolve to the pinned (title, page) through BOTH real resolvers
    and produce the exact _EXPECTED_CITATION. If this drifts, (a)/(b) become
    impossible and (c) becomes vacuous — so this is the load-bearing anchor."""
    chunk = _launch_chunk()
    ctx, included = assemble_context([chunk])
    assert "Page: 64" in ctx  # the header the resolver verifies against
    # The ONE path all three citing handlers now share: the id the generator
    # named. _CITED_CHUNK_ID is what (a)'s lesson claims it was built from and
    # what (b)/(c)'s marker points at, so this is what makes their citations
    # possible at all.
    assert resolve_attribution(_CITED_CHUNK_ID, [chunk], ctx) == (
        "Launching the Writers Workshop 3-12",
        64,
    )
    assert build_soft_citation("Launching the Writers Workshop 3-12", 64) == (
        _EXPECTED_CITATION
    )
    assert _EXPECTED_CITATION  # non-empty -> (c)'s "not in" assertion is real


# ======================================================================
# Fake clients (mirrors of the two existing harnesses)
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
    def __init__(self, lesson) -> None:
        self._lesson = lesson

    async def parse(self, **kwargs):  # mirrors AsyncOpenAI chat.completions.parse
        return _FakeGenCompletion(self._lesson)


class _FakeGenChat:
    def __init__(self, lesson) -> None:
        self.completions = _FakeGenCompletions(lesson)


class _FakeGenerationClient:
    """Structured path: chat.completions.parse -> a fixed MiniLesson (mirrors
    test_scripted_ml_header.py)."""

    def __init__(self, lesson) -> None:
        self.chat = _FakeGenChat(lesson)


class _FakeTextMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeTextChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeTextMessage(content)


class _FakeTextCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeTextChoice(content)]


class _FakeTextCompletions:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    async def create(self, **kwargs):  # mirrors AsyncOpenAI chat.completions.create
        if not self._responses:
            raise RuntimeError("fake text client ran out of responses")
        return _FakeTextCompletion(self._responses.pop(0))


class _FakeTextChat:
    def __init__(self, responses: list[str]) -> None:
        self.completions = _FakeTextCompletions(responses)


class _FakeTextClient:
    """Text path: chat.completions.create -> canned text (mirrors
    test_handlers_base_text.py)."""

    def __init__(self, responses: list[str]) -> None:
        self.chat = _FakeTextChat(responses)


@pytest.fixture
def pass_judge(monkeypatch):
    """Deterministic + network-free accept-gate: the judge always passes, so a
    policy-clean lesson ships VALID on the first attempt (mirrors
    test_scripted_ml_header.py)."""

    async def _fake_judge(*, lesson, client, model):
        good = DimensionScore(score=9, violations=[])
        return JudgeVerdict(
            narrative_coherence=good,
            strategy_gist_present=good,
            step1_structure=good,
        )

    monkeypatch.setattr(scripted_ml_mod, "judge_scripted_ml", _fake_judge)


# ======================================================================
# (a) SCRIPTED_ML — citation-PRESENT path, end-to-end through the handler
# ======================================================================


@pytest.mark.asyncio
async def test_scripted_ml_delivers_citation_footer_end_to_end(pass_judge):
    """handle_scripted_ml, driven with the page-verified Launch chunk, must
    surface the deterministic citation on BOTH channels: structured
    ["book_citation"] AND response_text — as a FOOTER after Step 4 and before
    the E2 follow-up.

    SCOPE (corrected): this drives ONE clean, judge-passing attempt, so it locks
    the FIRST delivery exit's book_citation wiring and that one only — it never
    retries, so it cannot reach the LLM-trustable or best-of-three LOW exits.
    The previous docstring claimed to lock "the 3 _build_outcome call sites";
    it never did. The LOW exit is covered in test_citation_identity_wiring.py.

    The lesson names _CITED_CHUNK_ID, because the citation is now built from the
    source the GENERATOR NAMED rather than from rank — a lesson that names
    nothing is correctly uncited (that is its own test in the file above)."""
    intent = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        skill=SkillSpec(
            canonical="transitions between paragraphs",
            as_stated="transitions between paragraphs",
        ),
        grade=GradeSpec(value="4", stated_explicit=True),
        mode=ModeSpec(value="Inform", stated_explicit=True),
    )
    outcome = await handle_scripted_ml(
        intent=intent,
        conversation=Conversation(session_id="s"),
        handshakes=SessionHandshakes(),
        new_user_message="lesson on transitions between paragraphs",
        client=_FakeGenerationClient(_good_lesson(source_chunk_id=_CITED_CHUNK_ID)),
        model="GEN",
        judge_model="JDG",
        canonicalizer=object(),
        retrieval_fn=_retrieval_fn,
        library=None,
    )

    # Delivered VALID (first attempt: clean lesson + stubbed judge).
    assert outcome.quality is Quality.VALID
    # Channel 1 — structured payload.
    assert outcome.structured["book_citation"] == _EXPECTED_CITATION
    # Channel 2 — response_text, positioned as a FOOTER: after Step 4, before E2.
    text = outcome.response_text
    assert _EXPECTED_CITATION in text
    assert text.index("Step 4") < text.index(_EXPECTED_CITATION), (
        "citation must sit AFTER the lesson body (Step 4), not above it"
    )
    assert text.index(_EXPECTED_CITATION) < text.index(_E2_FOLLOWUP), (
        "citation must precede the E2 follow-up so the follow-up stays last"
    )


# ======================================================================
# (b) HOW_TO_TEACH — citation-PRESENT path, end-to-end through the handler
# ======================================================================


@pytest.mark.asyncio
async def test_how_to_teach_delivers_a_per_claim_citation_end_to_end():
    """handle_how_to_teach, driven with the same Launch chunk + an outline whose
    SECOND bullet is marked with the chunk's Source: id, must deliver the
    deterministic citation INLINE on that bullet — and leave the unmarked
    bullets uncited.

    Locks the handler -> run_text_handler_with_retry -> _build_text_outcome
    citation_resolver wiring. Drop the `citation_resolver=` argument and the
    citation is never built AND the raw marker ships to the teacher — both
    asserted here, so either half of that failure turns this red.

    Re-pointed from `test_how_to_teach_delivers_citation_before_closer_end_to_
    end`, which locked the rank-picked FOOTER. That footer is deliberately gone:
    it was chosen from retrieval rank BEFORE generation ran, and one footer per
    turn cannot reproduce Brady's image3/image39 shape."""
    outline = (
        "Here are a few focus skills for teaching transitions between "
        "paragraphs:\n\n"
        "- Signal words: teach connectors like 'however' and 'in addition'.\n"
        f"- Placement: show writers where a transition belongs between ideas. {_MARKER}\n"
        "- Revision: have writers add a transition to a draft they already "
        "wrote.\n\n"
        f"{_HTT_CLOSER}"
    )
    intent = TurnIntent(
        request_type=RequestType.HOW_TO_TEACH,
        skill=SkillSpec(
            canonical="transitions between paragraphs",
            as_stated="transitions between paragraphs",
        ),
    )
    outcome = await handle_how_to_teach(
        intent=intent,
        conversation=Conversation(session_id="s"),
        handshakes=SessionHandshakes(),
        new_user_message="how do I teach transitions between paragraphs?",
        client=_FakeTextClient([outline]),
        model="GEN",
        canonicalizer=None,
        retrieval_fn=_retrieval_fn,
        library=None,
    )

    assert outcome.quality is Quality.VALID
    text = outcome.response_text
    assert _EXPECTED_CITATION in text
    # No marker is EVER teacher-visible.
    assert "[[src:" not in text, f"raw marker shipped to the teacher: {text!r}"
    # PER-CLAIM placement: the citation sits on the line of the claim that
    # earned it. This is the assertion a footer implementation fails — the
    # footer would put it on its own line before the closer.
    cited_lines = [ln for ln in text.splitlines() if _EXPECTED_CITATION in ln]
    assert len(cited_lines) == 1, f"expected exactly one cited line, got {cited_lines!r}"
    assert cited_lines[0].startswith("- Placement:"), (
        f"citation must land on ITS OWN claim's line, not as a footer: {cited_lines[0]!r}"
    )
    # ...and only on that claim. An unmarked claim stays uncited (Brady's
    # image39 is silent on point 1) — this kills a blanket "cite everything".
    assert "Signal words" not in cited_lines[0]
    # Brady C8: this 3-skill outline closes with the multi-skill pick-list
    # closer (swapped at the seam), not the single-skill closer — still last
    # (E5a). The per-claim citation sits mid-outline on the "Placement" line,
    # well before the closer, so the swap never touches it.
    assert text.rstrip().endswith(HOW_TO_TEACH_MULTI_SKILL_CLOSER), (
        "the multi-skill closer must stay last (C8 + E5a)"
    )


# ======================================================================
# (c) COACHING — citation-PRESENT path, end-to-end through the handler
# ======================================================================
#
# COACHING was the LAST text handler still letting the LLM author its own
# citation ("you MAY cite: (Launching the Writers Workshop 3-12, page 64)"),
# with a regex scrubber as the ONLY thing standing between an invented page
# and a teacher. That is the design flaw Fm5 exists to remove: a scrubber can
# only ever be a bounded BACKSTOP, and the "page-66" defect proved it — one
# separator nobody enumerated and the invented page shipped.
#
# Now COACHING builds its citation the same way HOW_TO_TEACH does: from the
# top Launch chunk's TYPED metadata, page-verified against the assembled
# context's "Page:" headers. build_soft_citation returns "" unless BOTH title
# and page are known, so a blank slot or a leaked page cannot be CONSTRUCTED —
# Brady's "better to stay silent than lie" becomes structural rather than
# something a regex has to catch after the fact.


@pytest.mark.asyncio
async def test_coaching_delivers_a_per_claim_citation_end_to_end():
    """handle_coaching, driven with the same page-verified Launch chunk and a
    marked claim, must deliver the deterministic citation INLINE on that claim.
    Locks the handler -> run_text_handler_with_retry -> _build_text_outcome
    citation_resolver wiring (drop it -> no citation AND a raw marker ships).

    Re-pointed from `test_coaching_delivers_citation_before_closer_end_to_end`
    (the rank-picked footer, deliberately gone)."""
    coaching = (
        "Transitions between paragraphs help readers follow your thinking. "
        f"Model one or two connectors and show writers where they belong. {_MARKER}\n\n"
        "Does this make sense? Is this helpful?"
    )
    intent = TurnIntent(
        request_type=RequestType.COACHING,
        skill=SkillSpec(
            canonical="transitions between paragraphs",
            as_stated="transitions between paragraphs",
        ),
    )
    outcome = await handle_coaching(
        intent=intent,
        conversation=Conversation(session_id="s"),
        handshakes=SessionHandshakes(),
        new_user_message="tell me about transitions between paragraphs",
        client=_FakeTextClient([coaching]),
        model="GEN",
        canonicalizer=None,
        retrieval_fn=_retrieval_fn,
        library=None,
    )

    text = outcome.response_text
    assert _EXPECTED_CITATION in text
    assert "[[src:" not in text, f"raw marker shipped to the teacher: {text!r}"
    # PER-CLAIM: on the marked claim's own line, not on a line of its own.
    cited_lines = [ln for ln in text.splitlines() if _EXPECTED_CITATION in ln]
    assert len(cited_lines) == 1, f"expected exactly one cited line, got {cited_lines!r}"
    assert cited_lines[0].startswith("Transitions between paragraphs help"), (
        f"citation must land on ITS OWN claim's line, not as a footer: {cited_lines[0]!r}"
    )
    assert text.rstrip().endswith("Is this helpful?"), "the closer must stay last (E5a)"


@pytest.mark.asyncio
async def test_coaching_page_is_never_llm_authored():
    """The POINT of the whole design, stated as an invariant: whatever page the
    LLM writes, the delivered page is the one the RETRIEVED CHUNK declares.

    The fake LLM here invents "page 113" (not the fixture chunk's page 64) —
    exactly the hallucination Brady's rule targets — while POINTING at the
    chunk it actually built from. The invented page must not reach the teacher;
    the citation the teacher DOES see must be the deterministic, page-verified
    one. Non-vacuous: 113 is a real page number the model really emitted, and 64
    is the only verifiable page.

    BONUS COVERAGE, worth keeping: this canned response fails validation on all
    3 attempts, so it delivers through the best-of-three LOW exit — the only
    test in this file that drives the resolver wiring on that exit through the
    REAL handler."""
    coaching = (
        "Transitions between paragraphs help readers follow your thinking. "
        f"You'll find the anchor chart on page 113 of the Teal book. {_MARKER}\n\n"
        "Does this make sense? Is this helpful?"
    )
    intent = TurnIntent(
        request_type=RequestType.COACHING,
        skill=SkillSpec(
            canonical="transitions between paragraphs",
            as_stated="transitions between paragraphs",
        ),
    )
    outcome = await handle_coaching(
        intent=intent,
        conversation=Conversation(session_id="s"),
        handshakes=SessionHandshakes(),
        new_user_message="tell me about transitions between paragraphs",
        client=_FakeTextClient([coaching] * 3),  # 3 attempts: the loop may retry
        model="GEN",
        canonicalizer=None,
        retrieval_fn=_retrieval_fn,
        library=None,
    )

    text = outcome.response_text
    assert "113" not in text, f"LLM-invented page reached the teacher: {text!r}"
    assert "Teal book" not in text
    assert _EXPECTED_CITATION in text  # the verified page-64 pointer, built not written
    assert "[[src:" not in text, f"raw marker shipped to the teacher: {text!r}"


# ======================================================================
# (d) MANAGEMENT — sibling text handler stays UNCITED on the same chunk
# ======================================================================


@pytest.mark.asyncio
async def test_management_stays_uncited_on_the_same_launch_chunk():
    """The negative half of the wiring lock: the citation is OPT-IN per
    handler, not an accident of retrieval.

    MANAGEMENT passes NO book_citation to the shared loop, so even when
    retrieval surfaces the SAME citeable Launch chunk that (a)/(b)/(c) cite,
    the delivered response carries none — correctly: a classroom-procedure
    answer is not "this lesson", so a "you'll find this lesson on p.N" pointer
    would be a lie about what the teacher is reading.
    (test_fixture_chunk_is_citeable proves the chunk IS citeable, so this
    absence is non-vacuous.)"""
    management = (
        "Set up a predictable writing block: five minutes to gather materials, "
        "then a ten-minute mini-lesson, then independent writing time.\n\n"
        "This was an overview. Which ONE area or SINGLE routine would you like "
        "to start with?"
    )
    intent = TurnIntent(
        request_type=RequestType.MANAGEMENT,
        skill=SkillSpec(
            canonical="transitions between paragraphs",
            as_stated="transitions between paragraphs",
        ),
    )
    outcome = await handle_management(
        intent=intent,
        conversation=Conversation(session_id="s"),
        handshakes=SessionHandshakes(),
        new_user_message="how do I run my writing block?",
        client=_FakeTextClient([management]),
        model="GEN",
        canonicalizer=None,
        retrieval_fn=_retrieval_fn,
        library=None,
    )

    text = outcome.response_text
    # No full citation, and no fragment of the Fm5 template, reached the teacher.
    assert _EXPECTED_CITATION not in text
    assert "If you have the" not in text
    assert "you'll find this lesson on p." not in text
    # Text handlers carry no structured payload, so there is no book_citation key.
    assert not (outcome.structured or {}).get("book_citation")
