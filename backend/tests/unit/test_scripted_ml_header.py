"""Unit tests for Brady Fm4 — the SCRIPTED_ML "Grade X | <Mode>" header,
computed from INTENT (never the LLM-authored ``lesson.writing_mode``) and
delivered on BOTH the generated path and the library-verbatim early-return.

The reliability crux (see task-4 brief): when the teacher stated no mode
(``intent.mode is None``), ``lesson.writing_mode`` is an LLM-invented value —
surfacing it would fabricate a mode the teacher never asked for. So the header
must be grade-only ("Grade 4") in that case, EVEN when the lesson object carries
a concrete ``writing_mode``. The mode-disagreement test below proves the source
is intent, not the lesson.

Interface produced (Tasks 6/7 depend): every SCRIPTED_ML
``TurnOutcome.structured`` carries a ``"header"`` key (string) and
``response_text`` starts with that header (when non-empty), on both delivery
paths.
"""
from __future__ import annotations

import re
from typing import Optional

import pytest

import handlers.scripted_ml as scripted_ml_mod
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
from validation.judge_v4 import DimensionScore, JudgeVerdict


# ----------------------------------------------------------------------
# Minimal fake generation client (mirrors test_scripted_ml_outcome.py):
# chat.completions.parse(...) returns a fixed, policy-clean MiniLesson so
# the handler runs end-to-end with no network.
# ----------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, parsed) -> None:
        self.parsed = parsed


class _FakeChoice:
    def __init__(self, parsed) -> None:
        self.message = _FakeMessage(parsed)


class _FakeCompletion:
    def __init__(self, parsed) -> None:
        self.choices = [_FakeChoice(parsed)]


class _FakeCompletions:
    def __init__(self, lesson) -> None:
        self._lesson = lesson
        self.calls: list[dict] = []

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeCompletion(self._lesson)


class _FakeChat:
    def __init__(self, lesson) -> None:
        self.completions = _FakeCompletions(lesson)


class _FakeGenerationClient:
    def __init__(self, lesson) -> None:
        self.chat = _FakeChat(lesson)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _intent(*, grade: Optional[str], mode: Optional[str]) -> TurnIntent:
    """SCRIPTED_ML intent whose skill matches _good_lesson()'s skill_focus so
    validate_lesson_policy passes. grade/mode become the header's ONLY source."""
    return TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        skill=SkillSpec(
            canonical="transitions between paragraphs",
            as_stated="transitions between paragraphs",
        ),
        grade=GradeSpec(value=grade, stated_explicit=True) if grade else None,
        mode=ModeSpec(value=mode, stated_explicit=True) if mode else None,
    )


@pytest.fixture
def pass_judge(monkeypatch):
    """Make the accept-gate deterministic + network-free: the judge always
    passes, so a policy-clean lesson ships VALID on the first attempt."""

    async def _fake_judge(*, lesson, client, model):
        good = DimensionScore(score=9, violations=[])
        return JudgeVerdict(
            narrative_coherence=good,
            strategy_gist_present=good,
            step1_structure=good,
        )

    monkeypatch.setattr(scripted_ml_mod, "judge_scripted_ml", _fake_judge)


async def _run_generated(intent: TurnIntent, lesson) -> TurnOutcome:
    client = _FakeGenerationClient(lesson)
    return await scripted_ml_mod.handle_scripted_ml(
        intent=intent,
        conversation=Conversation(session_id="s"),
        handshakes=SessionHandshakes(),
        new_user_message="lesson on transitions between paragraphs",
        client=client,
        model="GEN",
        judge_model="JDG",
        canonicalizer=object(),
        retrieval_fn=None,
        library=None,
    )


# ----------------------------------------------------------------------
# Generated path
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generated_header_from_stated_grade_and_mode(pass_judge):
    """Teacher stated grade=4 + mode=Inform → 'Grade 4 | Informative' on the
    structured payload AND as the response_text prefix."""
    outcome = await _run_generated(_intent(grade="4", mode="Inform"), _good_lesson())
    assert outcome.structured["header"] == "Grade 4 | Informative"
    assert outcome.response_text.startswith("Grade 4 | Informative")


@pytest.mark.asyncio
async def test_generated_header_grade_only_when_intent_mode_none_despite_lesson_writing_mode(
    pass_judge,
):
    """THE reliability crux: intent.mode is None (teacher named no mode), but the
    LLM invented ``writing_mode="Persuade"`` on the lesson. The header MUST be
    grade-only 'Grade 4' — the LLM's invented mode must NOT surface. Proves the
    header source is intent, never lesson.writing_mode."""
    lesson = _good_lesson(writing_mode="Persuade")
    outcome = await _run_generated(_intent(grade="4", mode=None), lesson)

    assert outcome.structured["header"] == "Grade 4"
    assert outcome.response_text.startswith("Grade 4\n")
    # The invented mode never leaks into the header...
    assert "Persuasive" not in outcome.structured["header"]
    assert not outcome.response_text.startswith("Grade 4 | ")
    # ...even though the lesson's own field (in the structured payload) is
    # untouched — which is exactly why reading it for the header would be a bug.
    assert outcome.structured["writing_mode"] == "Persuade"


# ----------------------------------------------------------------------
# Library-verbatim early-return path
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verbatim_path_gets_header_from_intent(monkeypatch):
    """The library-verbatim early return must also get the intent-computed
    header. We force the verbatim hit with a canned outcome (the real
    embed+precheck internals are covered by test_library_precheck) and assert
    handle_scripted_ml wraps it with the header while preserving its payload."""
    verbatim = TurnOutcome(
        response_text="Transitions within paragraphs\nStep 1 — Introduce the skill.",
        structured={
            "skill_focus": "Transitions within paragraphs",
            "grade_level": "4",
            "source_document": "Launching the Writers Workshop 3-12.pdf",
            "library_ml_id": "lib-transitions",
        },
        grounding=[],
        quality=Quality.VALID,
        library_match_id="lib-transitions",
    )

    async def _fake_verbatim(intent, library, user_message):
        return verbatim

    monkeypatch.setattr(scripted_ml_mod, "_try_library_verbatim", _fake_verbatim)

    outcome = await scripted_ml_mod.handle_scripted_ml(
        intent=_intent(grade="4", mode="Inform"),
        conversation=Conversation(session_id="s"),
        handshakes=SessionHandshakes(),
        new_user_message="give me the transitions lesson",
        client=object(),  # never used — verbatim short-circuits before generation
        model="GEN",
        judge_model="JDG",
        canonicalizer=object(),
        retrieval_fn=None,
        library=object(),  # non-None so the verbatim precheck path is entered
    )

    assert outcome.structured["header"] == "Grade 4 | Informative"
    assert outcome.response_text.startswith("Grade 4 | Informative")
    # The original verbatim payload survives alongside the new header.
    assert outcome.structured["library_ml_id"] == "lib-transitions"
    assert outcome.library_match_id == "lib-transitions"


@pytest.mark.asyncio
async def test_verbatim_path_header_grade_only_when_intent_mode_none(monkeypatch):
    """Verbatim path honours the same grade-only rule when intent.mode is None."""
    verbatim = TurnOutcome(
        response_text="Transitions within paragraphs\nStep 1 — Introduce the skill.",
        structured={"library_ml_id": "lib-transitions"},
        quality=Quality.VALID,
        library_match_id="lib-transitions",
    )

    async def _fake_verbatim(intent, library, user_message):
        return verbatim

    monkeypatch.setattr(scripted_ml_mod, "_try_library_verbatim", _fake_verbatim)

    outcome = await scripted_ml_mod.handle_scripted_ml(
        intent=_intent(grade="4", mode=None),
        conversation=Conversation(session_id="s"),
        handshakes=SessionHandshakes(),
        new_user_message="give me the transitions lesson",
        client=object(),
        model="GEN",
        judge_model="JDG",
        canonicalizer=object(),
        retrieval_fn=None,
        library=object(),
    )

    assert outcome.structured["header"] == "Grade 4"
    assert outcome.response_text.startswith("Grade 4\n")
    assert not outcome.response_text.startswith("Grade 4 | ")


# ----------------------------------------------------------------------
# _finalize_ml_delivery boundary helper — direct, fast contract tests
#
# The seam applies EVERY deterministic transform (Fm3 title-case + E2 follow-up
# + this Fm4 header) to the delivered structured payload; these tests cover its
# Fm4 half. The full delivered-payload contract — and the class lock that fails
# a response_text-only transform — lives in test_ml_delivery_contract.py.
# ----------------------------------------------------------------------


def test_finalize_applies_full_header_when_mode_stated():
    from handlers.scripted_ml import _finalize_ml_delivery

    out = _finalize_ml_delivery(
        TurnOutcome(response_text="body", structured={"x": 1}),
        _intent(grade="3", mode="Inform"),
    )
    assert out.structured["header"] == "Grade 3 | Informative"
    assert out.response_text == "Grade 3 | Informative\nbody"
    assert out.structured["x"] == 1  # existing structured keys preserved


def test_finalize_header_grade_only_when_mode_none_ignores_structured_writing_mode():
    from handlers.scripted_ml import _finalize_ml_delivery

    # Even with a concrete writing_mode already in the payload, mode=None → the
    # header is grade-only and the payload's writing_mode is left untouched.
    out = _finalize_ml_delivery(
        TurnOutcome(response_text="body", structured={"writing_mode": "Persuade"}),
        _intent(grade="4", mode=None),
    )
    assert out.structured["header"] == "Grade 4"
    assert out.response_text == "Grade 4\nbody"
    assert out.structured["writing_mode"] == "Persuade"


def test_finalize_omits_header_when_grade_unknown():
    from handlers.scripted_ml import _finalize_ml_delivery

    # No grade → format_lesson_header returns "" → no header key, response_text
    # un-prefixed. The gate is header-ONLY: the seam's other transforms are
    # unconditional, so an unknown grade must not swallow them (see
    # test_transforms_survive_when_grade_unknown in the delivery-contract file).
    out = _finalize_ml_delivery(
        TurnOutcome(response_text="body", structured={"x": 1}),
        _intent(grade=None, mode="Inform"),
    )
    assert "header" not in (out.structured or {})
    assert out.response_text == "body"
    assert out.structured["x"] == 1


def test_finalize_handles_none_structured():
    from handlers.scripted_ml import _finalize_ml_delivery
    from handlers.scripted_ml import _E2_FOLLOWUP

    # Verbatim/early outcomes may carry structured=None; the seam must still
    # attach the header without raising. (Defensive only — both real SCRIPTED_ML
    # producers always build a structured payload.)
    out = _finalize_ml_delivery(
        TurnOutcome(response_text="body", structured=None),
        _intent(grade="4", mode="Persuade"),
    )
    assert out.structured == {
        "header": "Grade 4 | Persuasive",
        "followup": _E2_FOLLOWUP,
    }
    assert out.response_text == "Grade 4 | Persuasive\nbody"


# ----------------------------------------------------------------------
# F39 — delivered-payload header SHAPE lock (deterministic, always-on)
#
# Distinct from the exact-value assertions above (Task 4) and the
# format_lesson_header unit tests (Task 2): this locks the general SHAPE
# invariant — the ``header`` on EVERY *actual delivered* SCRIPTED_ML payload
# (driven end-to-end through handle_scripted_ml, across BOTH the generated and
# the library-verbatim paths) always matches one of the three valid forms:
#     Grade X · Grade X | <Informative|Persuasive|Narrative> · Grade X | Management
# On purpose it is NOT wired into the per-attempt ``validators`` list: the
# header is applied post-retry by _finalize_ml_delivery and is never LLM-authored, so a
# runtime validator would be inert. Precedent: TestTierBoostConsistency — a
# deterministic, network-free lock that bites on every gate run (Task 7's
# live ``header_correct`` only bites at the re-baseline).
# ----------------------------------------------------------------------

_HEADER_SHAPE = re.compile(
    r"^Grade \S+( \| (Informative|Persuasive|Narrative|Management))?$"
)


async def _deliver_verbatim(
    monkeypatch, *, grade: Optional[str], mode: Optional[str]
) -> TurnOutcome:
    """Drive handle_scripted_ml down the library-verbatim early return (same
    stubbing pattern as the verbatim tests above) and return the ACTUAL
    delivered outcome — header attached by _finalize_ml_delivery from the intent."""
    verbatim = TurnOutcome(
        response_text="Transitions within paragraphs\nStep 1 — Introduce the skill.",
        structured={"library_ml_id": "lib-transitions"},
        quality=Quality.VALID,
        library_match_id="lib-transitions",
    )

    async def _fake_verbatim(intent, library, user_message):
        # Mirror the real guard (no library → no verbatim hit) so this stub is
        # inert on the generated deliveries, which pass library=None.
        return verbatim if library is not None else None

    monkeypatch.setattr(scripted_ml_mod, "_try_library_verbatim", _fake_verbatim)
    return await scripted_ml_mod.handle_scripted_ml(
        intent=_intent(grade=grade, mode=mode),
        conversation=Conversation(session_id="s"),
        handshakes=SessionHandshakes(),
        new_user_message="give me the transitions lesson",
        client=object(),  # never used — verbatim short-circuits before generation
        model="GEN",
        judge_model="JDG",
        canonicalizer=object(),
        retrieval_fn=None,
        library=object(),  # non-None so the verbatim precheck path is entered
    )


async def _deliver_headers(monkeypatch, *, generated, verbatim) -> list[TurnOutcome]:
    """Collect the ACTUAL delivered TurnOutcomes across both real code paths.

    ``generated`` (grade, mode) cases run the full generate→validate→judge path
    (needs the ``pass_judge`` fixture); ``verbatim`` cases run the library early
    return. Both paths funnel through _finalize_ml_delivery, so every returned outcome
    carries the header exactly as a teacher would receive it. Generated cases
    run first (library=None) so the real _try_library_verbatim stays a no-op
    before the verbatim monkeypatch is installed."""
    outcomes: list[TurnOutcome] = []
    for grade, mode in generated:
        outcomes.append(
            await _run_generated(_intent(grade=grade, mode=mode), _good_lesson())
        )
    for grade, mode in verbatim:
        outcomes.append(await _deliver_verbatim(monkeypatch, grade=grade, mode=mode))
    return outcomes


@pytest.mark.asyncio
async def test_delivered_scripted_ml_header_shape(pass_judge, monkeypatch):
    """F39: EVERY header on an ACTUAL delivered SCRIPTED_ML payload matches one
    of the three valid shapes. Drives handle_scripted_ml end-to-end for the
    generated mode-stated (→ 'Grade 4 | Informative') and mode-None (→ grade-only
    'Grade 4') cases AND the library-verbatim path (→ 'Grade 2 | Narrative') —
    covering the adjective, grade-only, and second-adjective shapes across BOTH
    delivery paths. Deterministic + network-free: it locks the invariant on
    every gate run, independent of the live re-baseline."""
    outcomes = await _deliver_headers(
        monkeypatch,
        generated=[("4", "Inform"), ("4", None)],
        verbatim=[("2", "Entertain")],
    )
    # Guard against a vacuous pass: assert all three real deliveries happened.
    assert len(outcomes) == 3
    for outcome in outcomes:
        header = (outcome.structured or {}).get("header", "")
        assert _HEADER_SHAPE.match(header), header
