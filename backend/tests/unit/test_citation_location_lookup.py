"""Fail-safe SILENCE on a deictic page-lookup follow-up (bug C2, fix 8 part 1).

The bug: a teacher asks a scripted lesson, then follows up "what page is this
lesson on?". That follow-up is referent-less, so retrieval re-runs on it and
returns GENERIC chunks (a paraphrase, the TOC) — never the lesson actually
asked about. The model marks a framing claim ``[[src:<id>]]``; the resolver
resolves that generic chunk to a CONFIDENT WRONG page, printed right after the
model hedged "I can't confirm the exact page." A lie AND a self-contradiction.

The fix (part 1): on a ``refers_to_prior`` location-lookup turn, resolve the
markers against EMPTY chunks. ``resolve_markers`` still SWEEPS every marker (so
nothing raw leaks) but has nothing to cite, so it stays silent — matching the
model's own hedge. Brady: "better to stay silent than lie."

WHY DRIVE THE REAL HANDLERS. The gate lives in ``handle_coaching`` /
``handle_how_to_teach`` — the two ``resolve_markers`` producers. Testing
``is_location_lookup`` alone would prove the predicate but NOT the wiring; a
future edit dropping the gate (or, worse, passing ``citation_resolver=None``,
which SKIPS the sweep and LEAKS raw markers) would keep a predicate-only test
green while shipping the exact defect. So the wiring tests below run the real
handlers end-to-end, mirroring test_fm5_citation_wiring's (b)/(c) present-path
locks and reusing their page-verified fixture — ``test_fixture_chunk_is_citeable``
there proves the chunk really cites p.64, so every "citation absent" assertion
here is non-vacuous (the same body + chunk DOES cite on the non-lookup turn).
"""
from __future__ import annotations

import pytest

from handlers.citation import is_location_lookup
from handlers.coaching import handle_coaching
from handlers.how_to_teach import handle_how_to_teach
from schemas import (
    Conversation,
    RequestType,
    SessionHandshakes,
    SkillSpec,
    TurnIntent,
)
from tests.unit.test_fm5_citation_wiring import (
    _EXPECTED_CITATION,
    _HTT_CLOSER,
    _MARKER,
    _FakeTextClient,
    _retrieval_fn,
)


# ---------------------------------------------------------------------------
# The bounded predicate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "msg",
    [
        "what page is that lesson on?",
        "which page is it on?",
        "where can I find that in the book?",
        "what page?",
        "where is it in the book?",
        "on what page is this lesson?",
        "what's the page number?",
        "Where in the book is this?",
        "what pages are these on?",  # plural
    ],
)
def test_is_location_lookup_true(msg: str) -> None:
    """A page / "where in the book" question is a location lookup."""
    assert is_location_lookup(msg) is True


@pytest.mark.parametrize(
    "msg",
    [
        "go deeper on that",
        "give me a lesson on that",
        "can you make it more rigorous",
        "tell me more about the pizza table",
        "",  # empty — never a lookup
    ],
)
def test_is_location_lookup_false(msg: str) -> None:
    """A CONTENT follow-up is not a location lookup — the predicate must not
    fire on go-deeper / more-rigorous, or it would silence citations Brady
    wants (bounded toward silence is safe; over-broad is not)."""
    assert is_location_lookup(msg) is False


# ---------------------------------------------------------------------------
# The gate, driven through the real handlers
# ---------------------------------------------------------------------------
#
# Same body + same citeable chunk for every case, so the ONLY thing that moves
# the citation in or out is the gate condition under test.

_COACHING_BODY = (
    "Transitions between paragraphs help readers follow your thinking. "
    f"Model one or two connectors and show writers where they belong. {_MARKER}\n\n"
    "Does this make sense? Is this helpful?"
)

_HTT_BODY = (
    "Here are a few focus skills for teaching transitions between paragraphs:\n\n"
    "- Signal words: teach connectors like 'however' and 'in addition'.\n"
    f"- Placement: show writers where a transition belongs between ideas. {_MARKER}\n\n"
    f"{_HTT_CLOSER}"
)

_CITED_HANDLERS = [
    pytest.param(handle_coaching, RequestType.COACHING, _COACHING_BODY, id="coaching"),
    pytest.param(
        handle_how_to_teach, RequestType.HOW_TO_TEACH, _HTT_BODY, id="how_to_teach"
    ),
]


async def _run(handler, request_type, body, *, message: str, refers_to_prior: bool):
    """Drive a cited text handler end-to-end. ``[body] * 3`` covers up to three
    retries so a canned body that fails validation still delivers (LOW) rather
    than exhausting the fake client — the resolver runs at every exit, so the
    citation assertions hold regardless of quality."""
    return await handler(
        intent=TurnIntent(
            request_type=request_type,
            skill=SkillSpec(
                canonical="transitions between paragraphs",
                as_stated="transitions between paragraphs",
            ),
            refers_to_prior=refers_to_prior,
        ),
        conversation=Conversation(session_id="s"),
        handshakes=SessionHandshakes(),
        new_user_message=message,
        client=_FakeTextClient([body] * 3),
        model="GEN",
        canonicalizer=None,
        retrieval_fn=_retrieval_fn,
        library=None,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("handler, request_type, body", _CITED_HANDLERS)
async def test_page_lookup_followup_stays_silent(handler, request_type, body) -> None:
    """THE FIX. A ``refers_to_prior`` location-lookup turn emits NO citation and
    leaks NO raw marker — the citation off this turn's generic chunks would be a
    confident wrong page (C2).

    Kills: (1) the gate not being wired (the citation appears — proven possible
    by the non-lookup sibling on the SAME body+chunk); (2) ``citation_resolver=
    None`` for the silence case, which would SKIP the sweep and ship a raw
    ``[[src:...]]`` marker (caught by the marker assertion)."""
    outcome = await _run(
        handler, request_type, body,
        message="What page is that lesson on?", refers_to_prior=True,
    )
    text = outcome.response_text
    assert "[[src:" not in text, f"raw marker leaked on the silence path: {text!r}"
    assert _EXPECTED_CITATION not in text
    assert "If you have the" not in text
    assert "you'll find this lesson on p." not in text
    # SILENCE, not emptiness: the model's own answer/hedge survives untouched —
    # only the fabricated page is withheld.
    assert "transitions between paragraphs" in text.lower(), (
        f"the answer body was lost, not just the citation: {text!r}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("handler, request_type, body", _CITED_HANDLERS)
async def test_non_lookup_followup_still_cites(handler, request_type, body) -> None:
    """A CONTENT follow-up ("go deeper") is not a location lookup, so the gate
    does not fire and the per-claim citation is delivered exactly as before.

    Kills: an over-broad gate that silences whenever ``refers_to_prior`` is set,
    which would strip citations Brady's approved outlines carry."""
    outcome = await _run(
        handler, request_type, body,
        message="go deeper on transitions between paragraphs", refers_to_prior=True,
    )
    text = outcome.response_text
    assert _EXPECTED_CITATION in text, f"the citation was wrongly silenced: {text!r}"
    assert "[[src:" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("handler, request_type, body", _CITED_HANDLERS)
async def test_fresh_page_lookup_is_not_over_silenced(handler, request_type, body) -> None:
    """The gate is ``refers_to_prior AND is_location_lookup`` — BOTH. A page
    lookup that is NOT a follow-up (``refers_to_prior=False``) retrieved its own
    lesson and can cite the RIGHT page, so it must NOT be silenced.

    Kills: gating on ``is_location_lookup`` alone, which would over-silence a
    fresh, correctly-citeable page lookup."""
    outcome = await _run(
        handler, request_type, body,
        message="What page is that lesson on?", refers_to_prior=False,
    )
    text = outcome.response_text
    assert _EXPECTED_CITATION in text, (
        f"a non-follow-up page lookup was over-silenced: {text!r}"
    )
    assert "[[src:" not in text
