"""Unit tests for the META handler and dispatcher."""

from __future__ import annotations

import re

import pytest

from api.models import ModelSet
from handlers import dispatch
from handlers.meta import handle_meta
from schemas import (
    Conversation,
    Quality,
    RequestType,
    SessionHandshakes,
    TurnIntent,
)


# Brady's E8 redline, reconstructed from bradys-7-july-feedback/feedback.docx
# para 122 by deleting the two struck runs. Verified directly against the
# document XML: exactly 2 strikethrough runs exist in the whole file (of 468),
# and BOTH are in this one sentence.
#   "...directly here, but [STRUCK: I can format the mini-lesson into a clean,
#    copy-ready layout] you can copy & paste this text into Google Docs or Word
#    and save as a PDF. [STRUCK: Just say the word and I'll prepare it so it's
#    ready to export.]"
# Note Brady's own text has NO em-dash — the "—" in the shipped constant was an
# implementation artifact joining the struck clause, so it goes with it.
_BRADY_E8_REDLINE = (
    "I can't generate or attach a PDF directly here, but you can copy & "
    "paste this text into Google Docs or Word and save as a PDF."
)

# CLASS assertion for E8: the reply must make NO affirmative first-person
# promise of further action. Brady struck the ONLY such clause ("I can format
# the mini-lesson into a clean, copy-ready layout") and said on the video:
# "So Copilot doesn't have to do anything else." The one permitted first-person
# statement is the NEGATED limitation ("I can't generate or attach a PDF").
# This is deliberately not `"I can format" not in text` — that would only ban
# the one struck phrasing; any re-worded offer ("I'll prepare it", "I could
# format that", "I am able to...") is the same defect.
_PROMISE_OF_ACTION_RE = re.compile(
    r"\bI\s*(?:['’]ll|\s*will|\s*can(?!['’]t)|\s*could|\s*am\s+able)\b",
    re.IGNORECASE,
)


class _DummyClient:
    """Stand-in AsyncOpenAI client — META handler doesn't call it."""


@pytest.mark.asyncio
async def test_handle_meta_off_topic_weather() -> None:
    intent = TurnIntent(request_type=RequestType.META)
    outcome = await handle_meta(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        handshakes=SessionHandshakes(),
        new_user_message="What's the weather today?",
        client=_DummyClient(),  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert outcome.quality is Quality.VALID
    assert "writing" in outcome.response_text.lower()
    assert outcome.structured is None


@pytest.mark.asyncio
async def test_handle_meta_pdf_capability_is_self_contained() -> None:
    intent = TurnIntent(request_type=RequestType.META)
    outcome = await handle_meta(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        handshakes=SessionHandshakes(),
        new_user_message="Can you put this in a PDF?",
        client=_DummyClient(),  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert outcome.quality is Quality.VALID
    text = outcome.response_text
    # Brady E8: the FIRST reply is self-contained (copy-paste instruction),
    # with NO dead-end "just say the word" second-step promise and NO generic
    # closer (the handshake write-path that promise relied on is inert).
    assert "copy & paste this text into" in text
    assert "just say the word" not in text.lower()
    assert "i'll prepare" not in text.lower()
    assert "Does this make sense?" not in text


@pytest.mark.asyncio
async def test_e8_pdf_reply_is_bradys_redlined_text_verbatim() -> None:
    """E8/X2: the delivered PDF reply is Brady's redline, i.e. the sentence he
    typed MINUS the clause he struck out. He struck only two runs in the entire
    feedback.docx and both are in this sentence — this one is the survivor."""
    intent = TurnIntent(request_type=RequestType.META)
    outcome = await handle_meta(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        handshakes=SessionHandshakes(),
        new_user_message="Can you put this in a PDF?",
        client=_DummyClient(),  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert outcome.response_text == _BRADY_E8_REDLINE


@pytest.mark.asyncio
async def test_e8_pdf_reply_promises_no_further_action() -> None:
    """CLASS lock: the E8 reply makes no affirmative first-person promise of
    further action — "So Copilot doesn't have to do anything else." Only the
    negated limitation ("I can't ...") may speak in the first person.

    This fails for the struck "I can format the mini-lesson ..." clause AND for
    any re-worded offer, so it cannot be satisfied by deleting one phrase.
    """
    intent = TurnIntent(request_type=RequestType.META)
    outcome = await handle_meta(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        handshakes=SessionHandshakes(),
        new_user_message="Can you put this in a PDF?",
        client=_DummyClient(),  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    offer = _PROMISE_OF_ACTION_RE.search(outcome.response_text)
    assert offer is None, (
        "E8 reply offers to do something Brady struck out: "
        f"{offer.group(0)!r} in {outcome.response_text!r}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ask",
    [
        # Brady's OWN vocabulary for this ask. "copy ready" / "copy-ready" is
        # the phrasing he used in both the doc ("I thought I asked it to give
        # me 'copy ready'") and the video ("I thought I just asked you to give
        # me copy-ready") — and it is in the E8 requirement itself, which reads
        # "A PDF / copy-ready request gets a self-contained FIRST reply".
        "copy ready",
        "copy-ready",
        "can you make it copy-ready?",
        "Can you give me that copy ready?",
        # The PDF half of the same family (already worked).
        "Can you put the above in a PDF?",
        "export it",
        "download it",
    ],
)
async def test_output_packaging_ask_gets_capability_reply_not_refusal(ask) -> None:
    """E8 root defect (Brady's ACTUAL complaint): asking for the lesson
    "copy ready" came back with "That question is outside my scope" — "a
    response that would be frustrating for the user".

    The E8 requirement covers the "PDF / copy-ready" family, but the router
    only recognised the PDF half, so the co-pilot refused a capability its own
    reply advertises ("you can copy & paste this text ..."). Every phrasing of
    that one family must reach the capability answer, never the refusal.
    """
    intent = TurnIntent(request_type=RequestType.META)
    outcome = await handle_meta(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        handshakes=SessionHandshakes(),
        new_user_message=ask,
        client=_DummyClient(),  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert "outside my scope" not in outcome.response_text.lower(), (
        f"Refused an output-packaging ask it advertises: {ask!r}"
    )
    assert outcome.response_text == _BRADY_E8_REDLINE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ask",
    [
        # "copy" is ordinary writing-instruction vocabulary — students copy
        # sentences, teachers copy handouts. Widening the output-packaging
        # family must NOT hijack these into the PDF reply.
        "Should students copy the sentence from the board?",
        "Do my writers copy the model paragraph into their notebooks?",
    ],
)
async def test_writing_use_of_copy_is_not_treated_as_output_packaging(ask) -> None:
    """Anti-overfit guard: the fix widens the family by Brady's phrasing, not
    by the bare word "copy" — a writing-instruction use of "copy" must still
    get the warm writing redirect, not the PDF capability answer."""
    intent = TurnIntent(request_type=RequestType.META)
    outcome = await handle_meta(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        handshakes=SessionHandshakes(),
        new_user_message=ask,
        client=_DummyClient(),  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert "PDF" not in outcome.response_text, (
        f"Writing use of 'copy' hijacked into the PDF reply: {ask!r}"
    )
    assert "outside my scope" not in outcome.response_text.lower()


@pytest.mark.asyncio
async def test_handle_meta_general_capability_is_not_pdf_only() -> None:
    # "What can you do?" is a general capability question, not a PDF ask —
    # it must NOT return the PDF-only reply (Brady E8 review note).
    intent = TurnIntent(request_type=RequestType.META)
    outcome = await handle_meta(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        handshakes=SessionHandshakes(),
        new_user_message="What can you do?",
        client=_DummyClient(),  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert outcome.quality is Quality.VALID
    assert "PDF" not in outcome.response_text
    assert "writing" in outcome.response_text.lower()


@pytest.mark.asyncio
async def test_handle_meta_greeting() -> None:
    intent = TurnIntent(request_type=RequestType.META)
    outcome = await handle_meta(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        handshakes=SessionHandshakes(),
        new_user_message="Hi!",
        client=_DummyClient(),  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert outcome.quality is Quality.VALID
    assert "writing co-pilot" in outcome.response_text.lower()
    # NB: "writing co-pilot" alone canNOT tell the greeting reply apart from
    # the off-topic refusal — both contain it. Pin the greeting specifically.
    assert "outside my scope" not in outcome.response_text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "greeting",
    ["Hi!", "Hi", "Hi.", "Hello!", "Hello.", "Hey!", "Thanks!", "Thank you!", "OK.", "Okay!"],
)
async def test_greeting_is_never_refused_over_punctuation(greeting) -> None:
    """Same class as the E8 'copy ready' defect: a marker miss falls through to
    the off-topic refusal, so ordinary punctuation decided whether the co-pilot
    greeted the teacher or told them they were out of scope. "Hi" greeted;
    "Hi!" answered "That question is outside my scope."

    Marker matching must be robust to trailing punctuation.
    """
    intent = TurnIntent(request_type=RequestType.META)
    outcome = await handle_meta(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        handshakes=SessionHandshakes(),
        new_user_message=greeting,
        client=_DummyClient(),  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert "outside my scope" not in outcome.response_text.lower(), (
        f"Refused a greeting: {greeting!r}"
    )
    assert "what are you preparing to teach" in outcome.response_text.lower()


@pytest.mark.asyncio
async def test_handle_meta_never_has_grounding() -> None:
    """META responses are canned — no retrieval, no grounding."""
    intent = TurnIntent(request_type=RequestType.META)
    outcome = await handle_meta(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        handshakes=SessionHandshakes(),
        new_user_message="What's the weather?",
        client=_DummyClient(),  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert outcome.grounding == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "opener",
    [
        # U2 "How can I help?" buttons (verbatim, copilot-v2-frontend/
        # ui_content.py). Writing-related openers QU classifies as META —
        # the app must NEVER refuse its own suggested prompts.
        "Do you need a scripted mini-lesson for a grade-level writing skill?",
        "What writing unit are you planning for?",
        "Are your students writing in pictures and letters?",
        "Do you want a suggested prop or trigger to teach a writing skill?",
        "Are you looking for different ideas to teach the same writing skill?",
    ],
)
async def test_handle_meta_writing_opener_is_not_off_topic_refused(opener) -> None:
    """A writing-related META query (the U2 opener buttons) must get the
    warm capability redirect that asks for specifics — NOT the off-topic
    'outside my scope' refusal."""
    intent = TurnIntent(request_type=RequestType.META)
    outcome = await handle_meta(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        handshakes=SessionHandshakes(),
        new_user_message=opener,
        client=_DummyClient(),  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert outcome.quality is Quality.VALID
    assert "outside my scope" not in outcome.response_text.lower(), (
        f"Refused its own suggested opener: {opener!r}"
    )
    # Warm redirect asks for the specifics needed to proceed.
    assert "what writing skill, grade, or unit" in outcome.response_text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "off_topic",
    ["What's the weather today?", "Tell me a joke", "Who won the super bowl?"],
)
async def test_handle_meta_genuinely_off_topic_still_refused(off_topic) -> None:
    """Regression guard: genuinely off-topic queries (no writing-instruction
    vocabulary) still get the 'outside my scope' redirect — the fix must not
    make the co-pilot try to answer everything."""
    intent = TurnIntent(request_type=RequestType.META)
    outcome = await handle_meta(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        handshakes=SessionHandshakes(),
        new_user_message=off_topic,
        client=_DummyClient(),  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert "outside my scope" in outcome.response_text.lower(), (
        f"Off-topic query should still be refused: {off_topic!r}"
    )


@pytest.mark.asyncio
async def test_dispatch_routes_to_meta() -> None:
    """The dispatcher must route META → handle_meta without requiring
    retrieval or library kwargs."""
    intent = TurnIntent(request_type=RequestType.META)
    outcome = await dispatch(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        handshakes=SessionHandshakes(),
        new_user_message="Hi!",
        client=_DummyClient(),  # type: ignore[arg-type]
        models=ModelSet("gpt-4o", "gpt-4o-mini", "gpt-4o-mini"),
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert outcome.quality is Quality.VALID
    assert outcome.response_text


@pytest.mark.asyncio
async def test_dispatch_has_handler_for_every_request_type() -> None:
    """After Stage 4, every RequestType must have a handler registered.
    Missing one would silently drop turns — fail loudly instead."""
    from handlers import _HANDLERS

    for rt in RequestType:
        assert rt in _HANDLERS, f"No handler registered for {rt.value}"
        assert callable(_HANDLERS[rt])


# ----------------------------------------------------------------------
# Clarification gate — missing_required intercept
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_asks_grade_question_when_missing_for_how_to_teach() -> None:
    """HOW_TO_TEACH with no grade + missing_required=['grade'] must
    return a clarifying question, not attempt generation."""
    intent = TurnIntent(
        request_type=RequestType.HOW_TO_TEACH,
        missing_required=["grade"],
    )
    outcome = await dispatch(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        handshakes=SessionHandshakes(),
        new_user_message="how do I teach transitions?",
        client=_DummyClient(),  # type: ignore[arg-type]
        models=ModelSet("gpt-4o", "gpt-4o-mini", "gpt-4o-mini"),
        canonicalizer=None,  # type: ignore[arg-type]
    )
    from schemas import Quality
    assert outcome.quality is Quality.VALID
    assert "grade" in outcome.response_text.lower()
    assert outcome.structured is None


@pytest.mark.asyncio
async def test_dispatch_asks_grade_for_plan_unit_and_scripted_ml() -> None:
    for rt in (RequestType.PLAN_UNIT, RequestType.SCRIPTED_ML, RequestType.THINK_ALOUD):
        intent = TurnIntent(request_type=rt, missing_required=["grade"])
        outcome = await dispatch(
            intent=intent,
            conversation=Conversation(session_id="s1"),
            handshakes=SessionHandshakes(),
            new_user_message="q",
            client=_DummyClient(),  # type: ignore[arg-type]
            models=ModelSet("gpt-4o", "gpt-4o-mini", "gpt-4o-mini"),
            canonicalizer=None,  # type: ignore[arg-type]
        )
        assert "grade" in outcome.response_text.lower(), f"Missing grade question for {rt.value}"


@pytest.mark.asyncio
async def test_dispatch_does_not_gate_coaching_on_missing_grade() -> None:
    """COACHING is grade-optional — missing_required=['grade'] should
    NOT intercept; the handler must run normally (or as far as a
    DummyClient allows). _DummyClient has no `chat` attribute, so if the
    dispatcher routes past the gate into handle_coaching, generation
    reaches `client.chat.completions.create(...)` and raises
    AttributeError. Asserting that SPECIFIC error — instead of a bare
    `except Exception: pass` — proves the gate did NOT intercept while
    still failing this test loudly on anything else raised during the
    call, e.g. a signature-level TypeError from dispatch() itself."""
    intent = TurnIntent(
        request_type=RequestType.COACHING,
        missing_required=["grade"],
    )
    with pytest.raises(AttributeError, match="chat"):
        await dispatch(
            intent=intent,
            conversation=Conversation(session_id="s1"),
            handshakes=SessionHandshakes(),
            new_user_message="q",
            client=_DummyClient(),  # type: ignore[arg-type]
            models=ModelSet("gpt-4o", "gpt-4o-mini", "gpt-4o-mini"),
            canonicalizer=None,  # type: ignore[arg-type]
        )
