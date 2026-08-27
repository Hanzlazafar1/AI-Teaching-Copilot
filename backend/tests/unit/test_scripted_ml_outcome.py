"""Unit tests for handlers/scripted_ml.py::_build_outcome — deterministic
outcome assembly (Wave 1a Task 5 / Brady E2: post-lesson customization
follow-up).

_build_outcome is a pure function over an already-generated _Attempt (no
LLM call happens inside it), so these tests construct a minimal _Attempt
directly and assert on the returned TurnOutcome. Fully deterministic, no
network.
"""
from __future__ import annotations

import types

import pytest

import handlers.scripted_ml as scripted_ml_mod
from handlers.scripted_ml import (
    _Attempt,
    _build_outcome,
    _E2_FOLLOWUP,
    _lesson_to_free_text,
)
from schemas import (
    Conversation,
    Quality,
    RequestType,
    SessionHandshakes,
    SkillSpec,
    TurnIntent,
)
from tests.unit._policy_fixtures import _good_lesson
from validation.judge_v4 import DimensionScore, JudgeVerdict
from validation.policy import LessonPolicyResult


def _passing_attempt() -> _Attempt:
    """A minimal attempt that already passed policy + judge — the shape
    _build_outcome sees on the success path. response_text is a throwaway;
    _build_outcome always recomputes it from attempt.lesson."""
    return _Attempt(
        lesson=_good_lesson(),
        response_text="unused — _build_outcome recomputes response_text from the lesson",
        policy=LessonPolicyResult(errors=[]),
        judge=None,
        passed=True,
    )


def test_scripted_ml_response_ends_with_e2_followup():
    """Brady E2: every rendered scripted-ML response ends with a short
    customization follow-up asking whether the script fits the teacher's
    student-writers. _good_lesson() carries no book-page citations, so the
    citation scrubber inside _build_outcome is a no-op with
    retrieved_context="" — the E2 paragraph is guaranteed to be the literal
    tail of response_text (stable assertion, no accidental trailing text)."""
    outcome = _build_outcome(
        attempt=_passing_attempt(),
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
    )
    # Pin exactly ONE blank line between the lesson close and the E2
    # paragraph (Brady formatting non-negotiable: the follow-up is its own
    # clean paragraph, matching every other section boundary rendered by
    # _lesson_to_free_text). endswith(_E2_FOLLOWUP) alone is suffix-only and
    # would silently accept any amount of leading whitespace (a triple
    # newline = two blank lines), so assert the exact "\n\n" separator AND
    # reject the "\n\n\n" (two-blank-line) form.
    assert outcome.response_text.endswith(f"\n\n{_E2_FOLLOWUP}")
    assert not outcome.response_text.endswith(f"\n\n\n{_E2_FOLLOWUP}")


def test_e2_followup_text_matches_brady_wording():
    # test_scripted_ml_response_ends_with_e2_followup compares response_text
    # against _E2_FOLLOWUP dynamically, so it would still pass even if the
    # wording drifted from what Brady actually asked for. Pin the literal
    # text independently so a wording change is caught here.
    assert _E2_FOLLOWUP == (
        "Does this script seem appropriate for your student-writers? "
        "Do I need to make anything more rigorous or simpler?"
    )


# ----------------------------------------------------------------------
# Forbidden-word scrub backstop (Wave 1a Task 8 — F31/F32, Brady April #5)
# ----------------------------------------------------------------------
#
# Brady's non-negotiable #5: NEVER emit "discuss"/"activity"/"I'll listen
# in"/PD-plug language. _build_outcome already runs a deterministic
# citation scrub per step before shipping; it must chain a forbidden-word
# scrub on the same per-field loop so a word that survives the validator's
# generation-time retries still never reaches the teacher.


def test_scripted_ml_scrubs_forbidden_words_from_steps():
    # Keep the 4 required Smekens Step-3 phrases present so this fixture
    # stays realistic, even though _build_outcome bypasses
    # validate_lesson_policy (the attempt is constructed pre-validated).
    lesson = _good_lesson(
        step_3_interact=(
            "Let's discuss the activity together. Help me with the next. "
            "Turn and talk. Back to me. This is some of what I heard."
        )
    )
    attempt = _Attempt(
        lesson=lesson,
        response_text="unused — _build_outcome recomputes response_text from the lesson",
        policy=LessonPolicyResult(errors=[]),
        judge=None,
        passed=True,
    )
    outcome = _build_outcome(
        attempt=attempt,
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
    )
    lowered = outcome.response_text.lower()
    assert "discuss" not in lowered
    assert "activity" not in lowered
    assert "turn-and-talk" in outcome.response_text
    assert "mini-lesson" in outcome.response_text
    # The E2 follow-up is appended AFTER the per-field scrub and must
    # survive byte-for-byte (it carries no forbidden words to begin with,
    # but pin the exact boundary so nothing upstream leaks into it).
    assert outcome.response_text.endswith(f"\n\n{_E2_FOLLOWUP}")


def test_scripted_ml_forbidden_word_scrub_is_noop_on_clean_lesson():
    # Behavior-preserving: _good_lesson() carries no forbidden words, so
    # wiring the scrub in must not change a single character of the
    # already-passing E2 test's output.
    outcome = _build_outcome(
        attempt=_passing_attempt(),
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
    )
    assert outcome.response_text == (
        f"{_lesson_to_free_text(_good_lesson()).rstrip()}\n\n{_E2_FOLLOWUP}"
    )


# ----------------------------------------------------------------------
# Title-case the rendered lesson title (Wave 1a Task 10 — Brady Fm3)
# ----------------------------------------------------------------------
#
# Brady Fm3: the scripted mini-lesson's displayed TITLE (the first line of
# _lesson_to_free_text, rendered from skill_focus) must start with a
# capital letter — "Use the room for spelling support", not "use the
# room…". This is a render-site-only change: validate_skill_focus_vocab
# (validation/vocabulary.py) lowercases both sides of its comparison
# before checking substring containment, so it is unaffected either way;
# and the stored MiniLesson.skill_focus field — which the final
# structured/model_dump() payload exposes verbatim — must NOT be mutated.


def test_lesson_to_free_text_capitalizes_title_first_letter():
    lesson = _good_lesson(skill_focus="use the room for spelling support")
    text = _lesson_to_free_text(lesson)
    assert text.startswith("Use the room for spelling support")


def test_lesson_to_free_text_title_case_does_not_mutate_stored_field():
    # Guard: rendering must not leak the capitalized title back onto the
    # MiniLesson itself. validate_skill_focus_vocab and the delivered
    # structured/model_dump() payload both read lesson.skill_focus
    # directly, not this rendered free text.
    lesson = _good_lesson(skill_focus="use the room for spelling support")
    _lesson_to_free_text(lesson)
    assert lesson.skill_focus == "use the room for spelling support"


def test_lesson_to_free_text_title_case_is_noop_when_already_capitalized():
    lesson = _good_lesson(skill_focus="Use the room for spelling support")
    text = _lesson_to_free_text(lesson)
    assert text.startswith("Use the room for spelling support")


def test_lesson_to_free_text_title_case_handles_empty_skill_focus():
    lesson = _good_lesson(skill_focus="")
    text = _lesson_to_free_text(lesson)  # must not raise
    assert text.splitlines()[0] == ""


def test_titlecase_first_preserves_interior_caps() -> None:
    from handlers.scripted_ml import _titlecase_first

    # Brady Fm3: capitalize ONLY the first character; interior caps (acronyms,
    # proper nouns) are preserved — unlike str.title()/str.capitalize().
    assert _titlecase_first("use the RACE strategy for responses") == "Use the RACE strategy for responses"
    assert _titlecase_first("iPad rotations during writing time") == "IPad rotations during writing time"


# ----------------------------------------------------------------------
# F27 — scripted_ml runs the accept-gate on judge_model, not generation
# ----------------------------------------------------------------------
#
# handle_scripted_ml receives distinct `model` (generation) and `judge_model`
# and must invoke judge_scripted_ml on judge_model (F27 judge split). Only the
# dispatch boundary currently guards this split at the call site; this test
# locks scripted_ml's INTERNAL threading (handler -> _single_attempt -> judge)
# so a future refactor can't silently regress the judge back onto the flagship
# generation model. Fully deterministic: a fake generation client returns a
# policy-clean lesson so the accept-gate fires, and judge_scripted_ml is
# monkeypatched to record the model it was handed.


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
    """Minimal stand-in for AsyncOpenAI: chat.completions.parse(...) returns a
    completion whose parsed payload is a fixed, policy-clean MiniLesson."""

    def __init__(self, lesson) -> None:
        self.chat = _FakeChat(lesson)


@pytest.mark.asyncio
async def test_scripted_ml_runs_judge_on_judge_model_not_generation(monkeypatch):
    captured: dict = {}

    async def _fake_judge(*, lesson, client, model):
        captured["model"] = model
        good = DimensionScore(score=9, violations=[])
        return JudgeVerdict(
            narrative_coherence=good,
            strategy_gist_present=good,
            step1_structure=good,
        )

    monkeypatch.setattr(scripted_ml_mod, "judge_scripted_ml", _fake_judge)

    # skill phrase matches the lesson's skill_focus so validate_lesson_policy
    # passes (mirrors test_policy.test_good_lesson_passes_all_rules) — the
    # judge only runs when policy has no errors.
    intent = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        skill=SkillSpec(
            canonical="transitions between paragraphs",
            as_stated="transitions between paragraphs",
        ),
    )
    client = _FakeGenerationClient(_good_lesson())

    outcome = await scripted_ml_mod.handle_scripted_ml(
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

    # Generation ran on GEN; the accept-gate ran on JDG — the F27 split.
    assert outcome.quality is Quality.VALID
    assert client.chat.completions.calls[0]["model"] == "GEN"
    assert captured["model"] == "JDG", (
        "judge_scripted_ml must run on judge_model, not the generation model"
    )


# ----------------------------------------------------------------------
# Fm5 — deterministic soft-citation FOOTER placement (Brady Fm5 redesign)
# ----------------------------------------------------------------------
#
# _build_outcome accepts a precomputed `book_citation` (built by
# handlers.citation.build_soft_citation from the top Launch chunk's typed
# metadata — never LLM-authored). It must land as its OWN paragraph AFTER the
# lesson body and BEFORE the E2 follow-up, and be surfaced on
# structured["book_citation"] (mirroring how _finalize_ml_delivery surfaces the Fm4
# header). When no citation is known it must be silent — no footer text, no
# structured key — while the E2 follow-up still renders. The citation is
# appended AFTER the per-step citation scrubber runs, so it is never itself
# re-scrubbed (a full book title with no Teal/K-2 marker in context would be
# stripped otherwise).
#
# _attempt() uses a SimpleNamespace because _build_outcome only reads
# attempt.lesson / attempt.judge / attempt.policy.errors.

_CITE = "If you have the 'Launching the Writers Workshop 3-12' book, you'll find this lesson on p.64."


def _attempt():
    # _build_outcome only reads attempt.lesson / attempt.judge / attempt.policy.errors.
    return types.SimpleNamespace(
        lesson=_good_lesson(), judge=None,
        policy=types.SimpleNamespace(errors=[]), response_text="", passed=True,
    )


def test_build_outcome_appends_citation_footer_before_e2():
    out = _build_outcome(
        attempt=_attempt(), grounding=[], quality=Quality.VALID,
        retry_count=0, retrieved_context="", book_citation=_CITE,
    )
    assert _CITE in out.response_text
    # Footer: citation sits AFTER the lesson body and BEFORE the E2 follow-up.
    assert out.response_text.index(_CITE) < out.response_text.index(_E2_FOLLOWUP)
    assert out.response_text.index("Step 4") < out.response_text.index(_CITE)
    assert out.structured["book_citation"] == _CITE


def test_build_outcome_silent_when_no_citation():
    out = _build_outcome(
        attempt=_attempt(), grounding=[], quality=Quality.VALID,
        retry_count=0, retrieved_context="", book_citation="",
    )
    assert "If you have the" not in out.response_text
    assert "book_citation" not in out.structured
    assert _E2_FOLLOWUP in out.response_text  # follow-up still present
