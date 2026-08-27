"""Delivery-contract lock for SCRIPTED_ML — the DELIVERED payload, not the text.

Why this file exists (the bug class it locks):
``api.routes_v4._build_response`` delivers ``outcome.structured`` as the API's
``response`` whenever structured is non-None — which is ALWAYS true for a
mini-lesson — and DISCARDS ``outcome.response_text``. So every deterministic
Brady transform written only to ``response_text`` is invisible to the teacher.

That class has bitten repeatedly, and each time it was patched field-by-field
(``header`` Fm4, ``one_skill_guard`` S3, ``book_citation`` Fm5) while the
transforms nobody thought to plumb died silently:
  * Fm3 (title-case the lesson title) shipped 2026-07-09 and NEVER worked — the
    structured-takes-priority branch predates it by ~2.5 months.
  * E2 (the post-lesson customization follow-up) never reached the payload.
Both had passing unit tests, because those tests scored ``response_text`` or the
transform helper in isolation — never the artifact the teacher receives.

So these tests assert at the DELIVERY BOUNDARY: they drive the real handler
end-to-end across BOTH SCRIPTED_ML producers (LLM-generated + library-verbatim),
push the outcome through the real ``_build_response``, and inspect the dict the
API actually returns. A transform added to ``response_text`` alone fails here.
"""
from __future__ import annotations

import re
from typing import Any, Optional

import pytest

import handlers.scripted_ml as scripted_ml_mod
from api.routes_v4 import _build_response
from handlers.scripted_ml import _E2_FOLLOWUP
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
# Network-free generation client (same shape as test_scripted_ml_header.py)
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

    async def parse(self, **kwargs):
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

_SKILL = "transitions between paragraphs"


def _intent(*, grade: Optional[str] = "4", mode: Optional[str] = "Inform") -> TurnIntent:
    return TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        skill=SkillSpec(canonical=_SKILL, as_stated=_SKILL),
        grade=GradeSpec(value=grade, stated_explicit=True) if grade else None,
        mode=ModeSpec(value=mode, stated_explicit=True) if mode else None,
    )


@pytest.fixture
def pass_judge(monkeypatch):
    async def _fake_judge(*, lesson, client, model):
        good = DimensionScore(score=9, violations=[])
        return JudgeVerdict(
            narrative_coherence=good,
            strategy_gist_present=good,
            step1_structure=good,
        )

    monkeypatch.setattr(scripted_ml_mod, "judge_scripted_ml", _fake_judge)


async def _run_generated(intent: TurnIntent, lesson) -> TurnOutcome:
    """Drive the LLM-generated producer end-to-end (no network)."""
    return await scripted_ml_mod.handle_scripted_ml(
        intent=intent,
        conversation=Conversation(session_id="s"),
        handshakes=SessionHandshakes(),
        new_user_message=f"lesson on {_SKILL}",
        client=_FakeGenerationClient(lesson),
        model="GEN",
        judge_model="JDG",
        canonicalizer=object(),
        retrieval_fn=None,
        library=None,
    )


async def _run_verbatim(monkeypatch, intent: TurnIntent) -> TurnOutcome:
    """Drive the library-verbatim producer end-to-end. The canned outcome
    mirrors the real ``_try_library_verbatim`` return shape (metadata-only
    structured + the fully-rendered verbatim text)."""
    verbatim = TurnOutcome(
        response_text=(
            f"Here's the Smekens scripted ML on {_SKILL}:\n\n"
            "Step 1 — Introduce the skill.\n\n"
            f"{_E2_FOLLOWUP}"
        ),
        structured={
            "skill_focus": _SKILL,
            "grade_level": "4",
            "source_document": "Launching the Writers Workshop 3-12.pdf",
            "library_ml_id": "lib-transitions",
        },
        grounding=[],
        quality=Quality.VALID,
        library_match_id="lib-transitions",
    )

    async def _fake_verbatim(intent, library, user_message):
        return verbatim if library is not None else None

    monkeypatch.setattr(scripted_ml_mod, "_try_library_verbatim", _fake_verbatim)
    return await scripted_ml_mod.handle_scripted_ml(
        intent=intent,
        conversation=Conversation(session_id="s"),
        handshakes=SessionHandshakes(),
        new_user_message=f"give me the {_SKILL} lesson",
        client=object(),  # verbatim short-circuits before generation
        model="GEN",
        judge_model="JDG",
        canonicalizer=object(),
        retrieval_fn=None,
        library=object(),
    )


def _deliver(outcome: TurnOutcome, intent: TurnIntent) -> Any:
    """Push an outcome through the REAL delivery boundary and return exactly
    what the API hands the frontend (``ChatResponse.response``)."""
    conversation = Conversation(session_id="s")
    return _build_response(
        outcome=outcome,
        intent=intent,
        conversation=conversation,
        handshakes=SessionHandshakes(),
        session_id="s",
    ).response


def _flatten(delivered: Any) -> str:
    """All teacher-visible text reachable from the delivered payload."""
    if isinstance(delivered, str):
        return delivered
    if isinstance(delivered, dict):
        return "\n\n".join(str(v) for v in delivered.values() if isinstance(v, str))
    return str(delivered)


# ----------------------------------------------------------------------
# Fm3 — title-case reaches the DELIVERED payload (was dead on arrival)
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivered_payload_titlecases_skill_focus_generated(pass_judge):
    """Brady Fm3: the lesson title the teacher receives starts capitalized.
    The generator authors skill_focus in the teacher's (lowercase) words, so
    the transform must land on the DELIVERED payload — asserting it on
    response_text is what let this ship broken for months."""
    intent = _intent()
    outcome = await _run_generated(intent, _good_lesson(skill_focus=_SKILL))
    delivered = _deliver(outcome, intent)

    assert delivered["skill_focus"] == "Transitions between paragraphs"


@pytest.mark.asyncio
async def test_delivered_payload_titlecases_skill_focus_verbatim(monkeypatch):
    """Same Fm3 guarantee on the library-verbatim producer — one seam, both
    paths, so a transform can't be right on one and dead on the other."""
    intent = _intent()
    outcome = await _run_verbatim(monkeypatch, intent)
    delivered = _deliver(outcome, intent)

    assert delivered["skill_focus"] == "Transitions between paragraphs"


def test_titlecase_capitalizes_first_char_only():
    """Fm3 is a first-CHARACTER capitalization — not str.title() (which would
    mangle 'transitions between paragraphs' into Title Case) and not upper()."""
    assert scripted_ml_mod._titlecase_first("use the room") == "Use the room"
    assert scripted_ml_mod._titlecase_first("") == ""
    # idempotent — safe to apply at both the render site and the seam
    once = scripted_ml_mod._titlecase_first("use the room")
    assert scripted_ml_mod._titlecase_first(once) == once


# ----------------------------------------------------------------------
# E2 — the post-lesson follow-up reaches the DELIVERED payload
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivered_payload_carries_e2_followup_generated(pass_judge):
    """Brady E2: the teacher-facing customization follow-up must be part of
    what the API delivers, not just the discarded response_text."""
    intent = _intent()
    outcome = await _run_generated(intent, _good_lesson(skill_focus=_SKILL))
    delivered = _deliver(outcome, intent)

    assert delivered["followup"] == _E2_FOLLOWUP


@pytest.mark.asyncio
async def test_delivered_payload_carries_e2_followup_verbatim(monkeypatch):
    intent = _intent()
    outcome = await _run_verbatim(monkeypatch, intent)
    delivered = _deliver(outcome, intent)

    assert delivered["followup"] == _E2_FOLLOWUP


def test_e2_wording_is_brady_verbatim():
    """The exact wording is a Brady contract — locked so a reword can't drift
    through a refactor (the anti-Fm5 pattern)."""
    assert _E2_FOLLOWUP == (
        "Does this script seem appropriate for your student-writers? "
        "Do I need to make anything more rigorous or simpler?"
    )


# ----------------------------------------------------------------------
# C1 — the model-authored verb-led lesson_title reaches the DELIVERED
# payload (title-cased), and skill_focus stays the teacher-vocab anchor.
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivered_payload_carries_lesson_title_generated(pass_judge):
    """Brady C1: the DISPLAYED title is a model-authored verb-led statement
    ('Determine the strongest side'), title-cased on the DELIVERED payload —
    the same delivery-boundary guarantee Fm3 needs (assert it on response_text
    and it would ship broken)."""
    intent = _intent()
    outcome = await _run_generated(
        intent,
        _good_lesson(skill_focus=_SKILL, lesson_title="determine the strongest side"),
    )
    delivered = _deliver(outcome, intent)

    assert delivered["lesson_title"] == "Determine the strongest side"


@pytest.mark.asyncio
async def test_lesson_title_does_not_disturb_the_skill_focus_anchor(pass_judge):
    """C1 decouples the DISPLAY title from the vocab anchor: lesson_title is the
    rephrasing, skill_focus stays the teacher's exact wording (still title-cased
    per Fm3) for the step bodies + validate_skill_focus_vocab. Both coexist."""
    intent = _intent()
    outcome = await _run_generated(
        intent,
        _good_lesson(skill_focus=_SKILL, lesson_title="determine the strongest side"),
    )
    delivered = _deliver(outcome, intent)

    assert delivered["lesson_title"] == "Determine the strongest side"
    assert delivered["skill_focus"] == "Transitions between paragraphs"


@pytest.mark.asyncio
async def test_verbatim_path_has_no_lesson_title_so_frontend_falls_back(monkeypatch):
    """The library-verbatim producer builds a metadata-only structured dict with
    no lesson_title. The seam must not fabricate one — it stays absent so the
    frontend's `lesson_title or skill_focus` fallback renders skill_focus."""
    intent = _intent()
    outcome = await _run_verbatim(monkeypatch, intent)
    delivered = _deliver(outcome, intent)

    assert not delivered.get("lesson_title")
    assert delivered["skill_focus"] == "Transitions between paragraphs"


# ----------------------------------------------------------------------
# C1 forbidden-word safety net — the title is deliberately NOT in
# response_text (validate_no_forbidden_words never scans it; the
# response_text title comes from skill_focus), so without an explicit scrub a
# banned word in the model-authored title would reach the teacher. The
# delivery-time scrub in _build_outcome is the only thing that can catch it
# (Brady non-negotiable #5).
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forbidden_word_in_lesson_title_is_scrubbed_before_delivery(pass_judge):
    intent = _intent()
    # "activity" is banned. It sits ONLY in the title — never in a step nor the
    # response_text the validator scans — so the lesson passes policy, and the
    # delivery scrub is the sole line of defense.
    outcome = await _run_generated(
        intent,
        _good_lesson(skill_focus=_SKILL, lesson_title="lead a fun activity"),
    )
    delivered = _deliver(outcome, intent)

    assert "activity" not in delivered["lesson_title"].lower()


# ----------------------------------------------------------------------
# Fm4 header + S3 guard — the already-plumbed transforms stay plumbed
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delivered_payload_carries_header(pass_judge):
    intent = _intent(grade="4", mode="Inform")
    outcome = await _run_generated(intent, _good_lesson(skill_focus=_SKILL))
    delivered = _deliver(outcome, intent)

    assert delivered["header"] == "Grade 4 | Informative"


@pytest.mark.asyncio
async def test_transforms_survive_when_grade_unknown(pass_judge):
    """The header is grade-gated (no grade → no header). That gate must NOT
    swallow the ungated transforms: Fm3 + E2 still have to be delivered."""
    intent = _intent(grade=None, mode=None)
    outcome = await _run_generated(intent, _good_lesson(skill_focus=_SKILL))
    delivered = _deliver(outcome, intent)

    assert "header" not in delivered
    assert delivered["skill_focus"] == "Transitions between paragraphs"
    assert delivered["followup"] == _E2_FOLLOWUP


# ----------------------------------------------------------------------
# THE CLASS LOCK — self-extending
#
# The three explicit checks above lock the transforms we know about today. This
# one locks the RULE, and discovers new transforms on its own: any module-level
# deterministic output string in handlers.scripted_ml that reaches the teacher's
# response_text must ALSO be reachable from the delivered payload.
#
# Add a `_E5_FOLLOWUP = "..."` and append it to response_text only, and this
# test fails without anyone remembering to update it — which is precisely what
# nobody did for Fm3 and E2.
# ----------------------------------------------------------------------


def _deterministic_output_constants() -> dict[str, str]:
    """Module-level CONST-cased long string literals in handlers.scripted_ml —
    i.e. the deterministic, Brady-verbatim strings the handler emits."""
    return {
        name: val
        for name, val in vars(scripted_ml_mod).items()
        if isinstance(val, str)
        and re.fullmatch(r"_?[A-Z][A-Z0-9_]*", name)
        and len(val) >= 20
    }


@pytest.mark.asyncio
async def test_no_deterministic_constant_is_response_text_only(pass_judge):
    """CLASS LOCK — see the block comment above."""
    constants = _deterministic_output_constants()
    assert constants, (
        "discovery found no deterministic output constants — the lock would be "
        "vacuous; fix the discovery predicate rather than deleting this test"
    )

    intent = _intent()
    outcome = await _run_generated(intent, _good_lesson(skill_focus=_SKILL))
    delivered = _flatten(_deliver(outcome, intent))

    for name, const in constants.items():
        if const in outcome.response_text:
            assert const in delivered, (
                f"{name} reaches response_text but NOT the delivered payload. "
                f"api.routes_v4._build_response delivers `structured` and "
                f"DISCARDS response_text for a mini-lesson, so this transform "
                f"never reaches the teacher. Apply it in the ONE delivery seam "
                f"(handlers.scripted_ml._finalize_ml_delivery) so it lands on "
                f"the structured payload too."
            )
