"""The `_base_text` seam: a RESOLVER, not a string — locked at all THREE exits.

Task 3 built ``resolve_markers`` and Task 4 made HOW_TO_TEACH + COACHING emit
``[[src:<id>]]`` markers. Neither is worth anything until the shared loop
applies one to the other: until it does, the markers have NO consumer and ship
raw to a teacher. This file locks the seam that consumes them.

WHY EVERY EXIT GETS ITS OWN TEST — the hole plan (1) left here.

``run_text_handler_with_retry`` has THREE delivery exits with distinct
``Quality`` / ``retry_count`` / ``validation_errors`` semantics: the
first-attempt pass, the LLM-trustable fallback, and the best-of-three LOW. They
are separate ``_build_text_outcome`` call sites, so citation wiring must be
threaded to each one INDEPENDENTLY — and dropping it from any one of them fails
SILENTLY BY CONSTRUCTION: ``_build_text_outcome`` defaults the citation to
absent and nothing raises. Plan (1) shipped exactly that on the sibling handler
family's exit #2 and the suite stayed green at 1873 passed, with an uncited
lesson live. Each test below therefore proves it REACHED the exit it names
(that is what the quality/retry_count/errors assertions are for — without them
a test proves nothing about the exit in its own title), and each was verified by
MUTATION: delete that exit's ``citation_resolver=`` argument and that test, and
only that test, goes red.

Precedent + house style: ``test_citation_identity_wiring.py`` (plan (1)'s
per-exit locks) and ``test_handlers_base_text.py``'s three header-threading
tests, which lock the same three call sites for Fm4.

WHAT IS DELIBERATELY *NOT* TESTED HERE — the wrong-attempt class. Plan (1) needed
``test_the_LOW_exit_cites_the_attempt_it_actually_ships`` because its exit built
the citation from an ``_Attempt`` OBJECT, so passing ``attempt`` where ``best``
belonged cited a lesson the teacher never received. That class cannot exist on
this seam: the resolver's only input is the text being shipped, so it is not
possible to resolve markers from an attempt other than the delivered one. A test
for it could not fail, and a test that cannot fail is worse than no test.
"""
from __future__ import annotations

import pytest

from handlers._base_text import _build_text_outcome, run_text_handler_with_retry
from handlers.citation import build_soft_citation, resolve_attribution, resolve_markers
from handlers.management import handle_management
from handlers.plan_unit import handle_plan_unit
from handlers.think_aloud import handle_think_aloud
from schemas import (
    Conversation,
    Quality,
    RequestType,
    SessionHandshakes,
    SkillSpec,
    TurnIntent,
)
from tests.unit.test_citation import _Chunk, _ctx, _TEAL, _TEAL_TITLE
from tests.unit.test_fm5_citation_wiring import (
    _EXPECTED_CITATION,
    _FakeTextClient,
    _retrieval_fn,
)
from tests.unit.test_handlers_base_text import _make_client, _prompt_builder
from validation.policy import is_llm_trustable_error

# ----------------------------------------------------------------------
# Fixture — two Launch chunks, only one of which the model ever names.
# ----------------------------------------------------------------------
#
# Helpers are IMPORTED, never re-declared: a second _Chunk stand-in would drift
# from RetrievedChunk on its own schedule (the reasoning test_citation_markers.py
# records, and the reason _MARKER_RE/_MARKER_SWEEP_RE are split by contract).
#
# The ATTRACTOR exists so "the citation appeared" cannot be satisfied by citing
# whatever was lying around: p.92 is the page the pre-fix rank-based picker
# confidently shipped for three unrelated queries. Every assertion below names
# p.64 — the page of the chunk the model actually POINTED at.

_CITED_ID = "lww312-s8-ml05"
_CITED_PAGE = 64
_ATTRACTOR_ID = "lww312-s9-ml15-informative-introductions"
_ATTRACTOR_PAGE = 92

_CTX = _ctx(_CITED_PAGE, _ATTRACTOR_PAGE)

_HTT_CLOSER = "Are you ready for a scripted mini-lesson on this skill?"


def _chunks() -> list[_Chunk]:
    return [
        _Chunk(source_document=_TEAL, page_number=_CITED_PAGE, chunk_id=_CITED_ID),
        _Chunk(
            source_document=_TEAL,
            page_number=_ATTRACTOR_PAGE,
            chunk_id=_ATTRACTOR_ID,
        ),
    ]


def _resolver():
    """What Task 6 will hand the loop: a callable closed over THIS turn's chunks.

    The loop stays generic — it applies a callable and knows nothing about
    chunks, books or pages. That is what keeps MANAGEMENT / PLAN_UNIT /
    THINK_ALOUD out of the citation business without a single branch on
    query_type inside the shared loop.
    """
    chunks = _chunks()
    return lambda text: resolve_markers(text, chunks, _CTX)


def _intent() -> TurnIntent:
    return TurnIntent(
        request_type=RequestType.HOW_TO_TEACH,
        skill=SkillSpec(canonical="transitions", as_stated="transitions"),
    )


def _outline(cited_id: str = _CITED_ID) -> str:
    """A minimal HOW_TO_TEACH outline whose first bullet points at a source."""
    return (
        "Here are a few focus skills for teaching transitions:\n\n"
        f"- **Signal words**: teach connectors like 'however'. [[src:{cited_id}]]\n"
        "- **Placement**: show writers where a transition belongs.\n\n"
        f"{_HTT_CLOSER}"
    )


def test_the_fixture_is_really_citeable_through_the_REAL_resolver() -> None:
    """The load-bearing anchor: if the fixture silently stopped being citeable,
    every "the citation appeared" assertion below would become IMPOSSIBLE rather
    than merely failing, and the absence assertions would become vacuous.

    Proven through the real resolve_attribution + build_soft_citation, so this
    pins the exact delivered string rather than a reconstruction of it, and
    proves the attractor is citeable too (so citing p.64 is a CHOICE the seam
    makes, not the only thing available)."""
    chunks = _chunks()
    assert resolve_attribution(_CITED_ID, chunks, _CTX) == (_TEAL_TITLE, _CITED_PAGE)
    assert resolve_attribution(_ATTRACTOR_ID, chunks, _CTX) == (
        _TEAL_TITLE,
        _ATTRACTOR_PAGE,
    )
    assert build_soft_citation(_TEAL_TITLE, _CITED_PAGE) == _EXPECTED_CITATION
    assert _EXPECTED_CITATION  # non-empty -> the "not in" assertions are real


# ======================================================================
# The three exits
# ======================================================================


@pytest.mark.asyncio
async def test_exit_1_the_first_attempt_pass_resolves_its_markers() -> None:
    """Exit #1 — ``_base_text.py`` first-attempt pass.

    Kills: dropping ``citation_resolver=`` from that exit (the markers then ship
    RAW to the teacher and no citation is built)."""
    outcome = await run_text_handler_with_retry(
        intent=_intent(),
        conversation=Conversation(session_id="s"),
        new_user_message="how do I teach transitions?",
        retrieved_context=_CTX,
        grounding=[],
        prompt_builder=_prompt_builder,
        validators=[lambda _t: []],  # clean first attempt
        client=_make_client([_outline()]),  # type: ignore[arg-type]
        model="m",
        log_label="t",
        query_type="HOW_TO_TEACH",
        citation_resolver=_resolver(),
    )

    # Proof we reached exit #1 and not another: a clean attempt ships VALID with
    # NO retries and NO retained errors. The other two exits cannot produce this
    # triple (exit #2 retains errors, exit #3 is LOW).
    assert outcome.quality is Quality.VALID
    assert outcome.retry_count == 0
    assert outcome.validation_errors == []

    assert _EXPECTED_CITATION in outcome.response_text
    assert "[[src:" not in outcome.response_text


@pytest.mark.asyncio
async def test_exit_2_the_LLM_trustable_fallback_resolves_its_markers() -> None:
    """Exit #2 — the LLM-trustable fallback. THE exit plan (1) shipped broken
    and green, on the sibling family, for the same reason: nothing reached it.

    Shape: attempt 1 fails on a non-trustable rule (forcing the ``i >= 1`` gate
    open), attempt 2 leaves only a trustable flag, so the loop trusts the LLM
    and ships VALID with the flag retained.

    Kills: dropping ``citation_resolver=`` from that exit."""
    counter = {"n": 0}

    def _validator(_text: str) -> list[str]:
        counter["n"] += 1
        if counter["n"] == 1:
            return ["missing closing phrase"]
        return ["Forbidden word 'discuss' used in a coaching tip."]

    # Exactly two responses: the trust exit must fire on attempt 2. A third call
    # would mean the branch never opened, and _make_client raises rather than let
    # this test quietly grade a different exit.
    outcome = await run_text_handler_with_retry(
        intent=_intent(),
        conversation=Conversation(session_id="s"),
        new_user_message="how do I teach transitions?",
        retrieved_context=_CTX,
        grounding=[],
        prompt_builder=_prompt_builder,
        validators=[_validator],
        client=_make_client([_outline(), _outline()]),  # type: ignore[arg-type]
        model="m",
        log_label="t",
        query_type="HOW_TO_TEACH",
        citation_resolver=_resolver(),
    )

    # Proof we reached exit #2. VALID rules out the LOW best-of-three; errors
    # RETAINED on a VALID delivery is this exit's signature and rules out exit #1,
    # where a pass means the error list is empty BY DEFINITION. retry_count pins
    # the `i >= 1` gate that is the only reason the branch is reachable at all.
    assert outcome.quality is Quality.VALID
    assert outcome.retry_count == 1
    assert outcome.validation_errors
    assert all(is_llm_trustable_error(e) for e in outcome.validation_errors)

    assert _EXPECTED_CITATION in outcome.response_text
    assert "[[src:" not in outcome.response_text


@pytest.mark.asyncio
async def test_exit_3_the_best_of_three_LOW_resolves_its_markers() -> None:
    """Exit #3 — best-of-three LOW.

    A LOW response is still delivered to a teacher, and answer quality is
    ORTHOGONAL to citation truth: a weak answer built from a real block is still
    on that block's page. So this exit cites too.

    The fixture makes the assertion prove WHICH text was resolved, not merely
    that something was: only the winning attempt names p.64 — attempts 1 and 3
    name the p.92 attractor — so a seam that resolved any other attempt's text
    would produce a citation this assertion rejects.

    Kills: dropping ``citation_resolver=`` from that exit."""
    counter = {"n": 0}

    def _validator(_text: str) -> list[str]:
        counter["n"] += 1
        # Attempt 2 has strictly the fewest errors -> it is `best`.
        return {1: ["e1", "e2"], 2: ["e1"], 3: ["e1", "e2", "e3"]}[counter["n"]]

    outcome = await run_text_handler_with_retry(
        intent=_intent(),
        conversation=Conversation(session_id="s"),
        new_user_message="how do I teach transitions?",
        retrieved_context=_CTX,
        grounding=[],
        prompt_builder=_prompt_builder,
        validators=[_validator],
        client=_make_client(  # type: ignore[arg-type]
            [_outline(_ATTRACTOR_ID), _outline(_CITED_ID), _outline(_ATTRACTOR_ID)]
        ),
        model="m",
        log_label="t",
        query_type="HOW_TO_TEACH",
        citation_resolver=_resolver(),
    )

    # Proof we reached exit #3: LOW after all three attempts failed.
    assert outcome.quality is Quality.LOW
    assert outcome.retry_count == 2

    assert _EXPECTED_CITATION in outcome.response_text
    assert "[[src:" not in outcome.response_text


# ======================================================================
# The seam's POSITION in the order — after the scrubs
# ======================================================================


def test_the_resolver_runs_AFTER_the_scrubs_so_its_citation_is_never_scrubbed() -> None:
    """``_build_text_outcome``'s docstring states the constraint this locks: a
    citation we BUILD is never re-fed through scrub_unverifiable_citations —
    the title-scrubber would strip a full book title when no Teal/K-2 marker is
    in the context. (That rationale was the deleted ``_insert_book_citation``
    footer's; it moved to the function that enforces the order, rather than
    dying with the one that first obeyed it. The resolver inherits it verbatim,
    because it builds the same sentence from the same metadata.)

    MEASURED, not argued. Resolving BEFORE the scrub on this exact input yields:

        "... If you have the '' book, you'll find this lesson on p.64."

    — a blank title slot. That is not a hypothetical failure mode: a blank slot
    ("on ** **") is what the REVERTED Fm5 prompt-reword actually shipped, and
    avoiding it is why build_soft_citation refuses to emit a half-known citation
    at all.

    HONEST ABOUT REACH: `_ctx` carries filler Source ids, so `has_teal_chunk` is
    False here and the title scrub is armed. A normal assembled context carries
    the marker inside its real `Source: lww312-...` ids, so the scrub would leave
    the title alone — this ordering is a GUARANTEE rather than a coincidence, and
    the condition is reachable whenever a chunk resolves while no chunk of its
    book survived into the assembled context (the raw-list-vs-`included` gap Task
    6 closes).

    Kills: moving the resolver above ``scrub_unverifiable_citations`` in
    ``_build_text_outcome``.
    """
    out = _build_text_outcome(
        response_text=f"Build a paragraph like a table. [[src:{_CITED_ID}]]",
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
        retrieved_context=_CTX,
        log_label="t",
        query_type="HOW_TO_TEACH",
        citation_resolver=_resolver(),
    )
    assert _EXPECTED_CITATION in out.response_text
    assert "the '' book" not in out.response_text  # the blank slot, named


# ======================================================================
# The nn4 regression guard — a citation must never truncate the pick-list
# ======================================================================


def test_offered_skills_survives_an_image39_shaped_cited_outline() -> None:
    """THE REGRESSION GUARD. Brady's image39 is a lead paragraph plus points,
    cited per claim — the exact shape this plan exists to produce.

    Why it is dangerous: ``_build_text_outcome`` records ``offered_skills`` from
    the SAME formatted text a citation has just entered, and
    ``picklist._scan_list_lines`` ends the list at the first non-list line
    ("Prose after the list does end it"). So a citation on its OWN line mid-list
    truncates the pick-list -> "number 4" falls out of range ->
    ``resolve_ordinal_pick`` returns None -> the model's guess stands -> the
    teacher asks for 4 and SILENTLY GETS 3. That defect (`nn4`) was fixed one day
    before this plan started; per-claim citations are the one change that could
    revive it.

    Task 4's prompt says "Never put a marker on a line of its own" — but a prompt
    is not a guarantee, which is the whole reason for the resolver. The guarantee
    is ``_resolve_one_line``'s per-line contract, and this is what proves it holds
    end-to-end rather than in isolation.

    Kills: any resolver that emits its citation on a line of its own
    (``return body + "\\n" + citation``) — that truncates this list to 1 item.
    Also kills a resolver that prepends its citation to the claim, which would
    bake our sentence into the skill NAME the teacher's ordinal resolves to.
    """
    outline = (
        "Second graders who can't write sentences usually need one of these "
        "skills, not all of them:\n\n"
        f"- **Say it, then write it**: rehearse the sentence aloud first. [[src:{_CITED_ID}]]\n"
        f"- **Stretch the sounds**: hear each sound before spelling it. [[src:{_ATTRACTOR_ID}]]\n"
        f"- **Capitals and periods**: mark where a sentence starts and stops. [[src:{_CITED_ID}]]\n"
        f"- **Add a detail**: grow a bare sentence by one detail. [[src:{_ATTRACTOR_ID}]]\n"
        f"- **Reread to check**: reread the sentence to hear what is missing. [[src:{_CITED_ID}]]\n\n"
        f"{_HTT_CLOSER}"
    )
    out = _build_text_outcome(
        response_text=outline,
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
        retrieved_context=_CTX,
        log_label="t",
        query_type="HOW_TO_TEACH",
        citation_resolver=_resolver(),
    )

    # The citations really landed (otherwise the guard below is vacuous — it
    # would be guarding text that has nothing in it to truncate the list).
    assert _EXPECTED_CITATION in out.response_text
    assert "[[src:" not in out.response_text

    # THE GUARD: all five skills are still offered, in order.
    assert len(out.offered_skills) == 5, out.offered_skills
    assert out.offered_skills[0].startswith("Say it, then write it")
    assert out.offered_skills[3].startswith("Add a detail")  # the "number 4" case
    assert out.offered_skills[4].startswith("Reread to check")

    # And no skill NAME carries our citation sentence: an ordinal pick feeds the
    # next lesson's skill_focus, and "Add a detail. If you have the '...' book,
    # you'll find this lesson on p.64" is the `"Number 4"`-titled-lesson defect
    # wearing a new coat.
    for skill in out.offered_skills:
        assert "If you have the" not in skill, skill
        assert "p.64" not in skill, skill


# ======================================================================
# The negative half — the loop cites only for handlers that ASK
# ======================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler, request_type, body",
    [
        (
            handle_management,
            RequestType.MANAGEMENT,
            "Set up a predictable writing block: gather materials, then write.\n\n"
            "This was an overview. Which ONE area or SINGLE routine would you "
            "like to start with?",
        ),
        (
            handle_plan_unit,
            RequestType.PLAN_UNIT,
            "Day 1: rehearse the sentence aloud.\n\nDay 2: stretch the sounds.\n\n"
            "Which of these skills do you want to start with? You can't teach "
            "them all in a single lesson.",
        ),
        (
            handle_think_aloud,
            RequestType.THINK_ALOUD,
            "Watch me think this through: I want my reader to picture the room, "
            "so I'll name one detail I can see.\n\nDoes this make sense? Is this "
            "helpful?",
        ),
    ],
)
async def test_a_handler_that_asks_for_no_citation_gets_none(
    handler, request_type, body
) -> None:
    """The citation is OPT-IN per handler, not an accident of retrieval.

    All five markdown handlers share ONE loop. These three pass NO resolver, so
    even when retrieval hands them the SAME citeable Launch chunk the cited
    handlers cite (``test_fm5_citation_wiring.test_fixture_chunk_is_citeable``
    proves it is citeable, so this absence is not vacuous), they must stay
    silent — a classroom-procedure answer or a think-aloud script is not "this
    lesson", so a "you'll find this lesson on p.N" pointer would be a lie about
    what the teacher is reading.

    Kills: wiring a resolver into any of these three (the live risk while Task 6
    edits handlers), or giving ``citation_resolver`` a non-None default in the
    shared loop.

    ``test_fm5_citation_wiring`` locks MANAGEMENT's ``book_citation`` half; this
    locks all three against the resolver half, which is a different mechanism
    reaching the same delivery seam.
    """
    outcome = await handler(
        intent=TurnIntent(
            request_type=request_type,
            skill=SkillSpec(canonical="transitions", as_stated="transitions"),
        ),
        conversation=Conversation(session_id="s"),
        handshakes=SessionHandshakes(),
        new_user_message="how do I run my writing block?",
        client=_FakeTextClient([body] * 3),  # the loop may retry
        model="GEN",
        canonicalizer=None,
        retrieval_fn=_retrieval_fn,
        library=None,
    )

    text = outcome.response_text
    assert _EXPECTED_CITATION not in text
    assert "If you have the" not in text
    assert "you'll find this lesson on p." not in text
