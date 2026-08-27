"""A clarify is a QUESTION, and the next message is its ANSWER.

THE BUG: after the app asks "What grade level do you teach? What writing skill
are you working on?", the teacher types "8th grade" — and QU re-classifies that
bare answer FROM SCRATCH. It lands in COACHING (prompt rule 9 makes COACHING the
catch-all for "ANY terse follow-up referencing a prior writing-related turn"),
which is in NEITHER ``_GRADE_REQUIRED`` nor ``_SKILL_REQUIRED``, so the clarify
gate never re-runs and the teacher gets coaching prose that INVENTS skills
instead of the lesson they were being asked to specify.

Nothing pinned the answer to the question. ``PendingClarification`` exists in
``schemas/handshakes.py`` but is DEAD CODE — its only constructors are in
``tests/unit/test_schemas.py``, so QU's ``=== PENDING HANDSHAKES ===`` block is
always empty and QU literally cannot know a clarify is outstanding. And the
classification is a knife's edge: the same input routes SCRIPTED_ML via the live
endpoint but COACHING 63/63 through a direct ``understand()`` call — so a prompt
tweak cannot fix it.

THE SEAM (mirrors ``offered_skills`` / ``apply_ordinal_pick`` exactly): "the
last assistant turn was a clarify, and this message supplies a field it asked
for" is a FACT, so code decides it. The clarify constructor RECORDS which
request_type it was clarifying FOR (``TurnOutcome.clarifying_for`` ->
``Turn.clarifying_for``), and ``apply_clarify_resume`` restores that type when —
and only when — the reply is a bare field answer. The gate then re-runs and asks
for whatever is STILL missing, or proceeds.

⚠️ The pending type is deliberately NOT carried in ``TurnOutcome.structured``:
routes_v4.py:211 treats a non-None ``structured`` as "this response IS a
mini_lesson" and DISCARDS response_text, so smuggling it through ``structured``
would ship a JSON blob to the teacher instead of the question.

These tests are ordered as the fact travels: recorded -> persisted -> read.
A green test that fabricates the field would be the "pipe with no water" bug
this codebase has now hit three times (Fm3, S3, offered_skills), so the first
group drives REAL ``dispatch`` and asserts PRODUCTION populates it.
"""

from __future__ import annotations

import pytest

from api.models import ModelSet
from canonicalizer import get_canonicalizer
from handlers import dispatch
from query.qu_v4 import _is_bare_field_answer, apply_clarify_resume, understand
from schemas import (
    Conversation,
    GradeSpec,
    Quality,
    RequestType,
    Role,
    SessionHandshakes,
    SkillSpec,
    Turn,
    TurnIntent,
    TurnOutcome,
)

CANON = get_canonicalizer()

_MODELS = ModelSet("gpt-4o", "gpt-4o-mini", "gpt-4o-mini")


async def _dispatch(intent: TurnIntent, conversation: Conversation | None = None):
    """Drive the REAL dispatcher. The clarify path short-circuits before any
    handler, so client/canonicalizer/retrieval are never touched (the
    test_dispatch_real.py precedent)."""
    return await dispatch(
        intent,
        conversation if conversation is not None else Conversation(session_id="s"),
        SessionHandshakes(),
        "give me a lesson",
        client=None,
        models=_MODELS,
        canonicalizer=None,
        retrieval_fn=None,
        library=None,
    )


# ----------------------------------------------------------------------
# 1. The clarify constructor records what it was clarifying FOR
# ----------------------------------------------------------------------


class TestClarifyRecordsThePendingRequestType:
    @pytest.mark.asyncio
    async def test_a_scripted_ml_clarify_records_scripted_ml(self):
        """Brady's most-used category. Grade is a STRUCTURAL prerequisite
        (handlers/clarify.py::_STRUCTURAL_PREREQS) so this turn clarifies."""
        out = await _dispatch(
            TurnIntent(
                request_type=RequestType.SCRIPTED_ML,
                missing_required=["grade", "skill"],
            )
        )
        assert out.clarifying_for is RequestType.SCRIPTED_ML

    @pytest.mark.asyncio
    async def test_a_how_to_teach_clarify_records_how_to_teach(self):
        """Generic, not a SCRIPTED_ML special case — this is the documented
        C8 'clarify -> resume' residual (a bare "7th grade" answering a
        HOW_TO_TEACH clarify landed in COACHING)."""
        out = await _dispatch(
            TurnIntent(
                request_type=RequestType.HOW_TO_TEACH,
                missing_required=["grade"],
            )
        )
        assert out.clarifying_for is RequestType.HOW_TO_TEACH

    @pytest.mark.asyncio
    async def test_a_plan_unit_clarify_records_plan_unit(self):
        out = await _dispatch(TurnIntent(request_type=RequestType.PLAN_UNIT))
        assert out.clarifying_for is RequestType.PLAN_UNIT

    @pytest.mark.asyncio
    async def test_the_clarify_is_still_delivered_as_text_not_a_blob(self):
        """The delivery contract: recording the pending type must not flip the
        response into the structured/mini_lesson lane."""
        out = await _dispatch(
            TurnIntent(request_type=RequestType.SCRIPTED_ML,
                       missing_required=["grade", "skill"])
        )
        assert out.structured is None
        assert out.response_text.strip()

    def test_a_normal_outcome_records_nothing(self):
        """None is the default and the overwhelming case — a generated lesson
        is not a pending question."""
        assert TurnOutcome(response_text="a lesson").clarifying_for is None


# ----------------------------------------------------------------------
# 2. It survives onto the Turn (the Fm3 / S3 / offered_skills failure class:
#    a rule wired to something that never reaches the next turn)
# ----------------------------------------------------------------------


class TestPendingTypeSurvivesOntoTheTurn:
    def test_turn_carries_the_pending_type(self):
        t = Turn(index=0, role=Role.ASSISTANT, text="What grade level do you teach?",
                 clarifying_for=RequestType.SCRIPTED_ML)
        assert t.clarifying_for is RequestType.SCRIPTED_ML

    def test_turn_defaults_to_none(self):
        assert Turn(index=0, role=Role.ASSISTANT, text="x").clarifying_for is None


# ----------------------------------------------------------------------
# 3. The override — a bare answer resumes the pending request
# ----------------------------------------------------------------------


def _clarify_convo(pending: RequestType, question: str = "What grade level do you teach?"):
    """A conversation whose most recent assistant turn is a pending clarify."""
    return Conversation(session_id="s", turns=[
        Turn(index=0, role=Role.USER, text="give me a lesson"),
        Turn(index=1, role=Role.ASSISTANT, text=question, clarifying_for=pending),
    ])


def _coaching_intent():
    """What QU actually returns for a bare answer: re-classified from scratch
    into the catch-all (63/63 through a direct understand() call)."""
    return TurnIntent(request_type=RequestType.COACHING)


class TestBareAnswerResumesThePendingRequest:
    def test_a_bare_grade_answer_resumes_scripted_ml(self):
        """THE BUG. QU says COACHING; the teacher answered our question."""
        out = apply_clarify_resume(
            _coaching_intent(), "8th grade",
            _clarify_convo(RequestType.SCRIPTED_ML), CANON,
        )
        assert out.request_type is RequestType.SCRIPTED_ML

    def test_a_bare_grade_answer_resumes_how_to_teach(self):
        """Proves it is GENERIC — the rule is 'resume what was pending', not a
        SCRIPTED_ML special case. Closes the C8 residual."""
        out = apply_clarify_resume(
            _coaching_intent(), "3rd grade",
            _clarify_convo(RequestType.HOW_TO_TEACH), CANON,
        )
        assert out.request_type is RequestType.HOW_TO_TEACH

    def test_a_bare_skill_answer_resumes_too(self):
        """The other half of Brady's ML question ("What writing skill are you
        working on?") — the answer is a skill, not a grade."""
        out = apply_clarify_resume(
            _coaching_intent(), "topic sentences",
            _clarify_convo(
                RequestType.SCRIPTED_ML,
                "What grade level do you teach? What writing skill are you working on?",
            ),
            CANON,
        )
        assert out.request_type is RequestType.SCRIPTED_ML

    def test_a_bare_mode_answer_resumes_plan_unit(self):
        """Brady's PLAN_UNIT row asks persuasive / informative / narrative."""
        out = apply_clarify_resume(
            _coaching_intent(), "persuasive",
            _clarify_convo(
                RequestType.PLAN_UNIT,
                "Are you preparing for a persuasive, informative, or narrative unit?",
            ),
            CANON,
        )
        assert out.request_type is RequestType.PLAN_UNIT

    def test_an_answer_echoing_the_questions_own_verb_still_resumes(self):
        """"What grade level do you TEACH?" -> "I teach 8th grade". The guard
        must not read the question's own verb back as a new request."""
        out = apply_clarify_resume(
            _coaching_intent(), "I teach 8th grade",
            _clarify_convo(RequestType.SCRIPTED_ML), CANON,
        )
        assert out.request_type is RequestType.SCRIPTED_ML

    def test_only_request_type_is_touched(self):
        """The override is about ROUTING. Extraction stays QU's job — nothing
        else on the intent is rewritten."""
        intent = TurnIntent(
            request_type=RequestType.COACHING,
            grade=GradeSpec(value="8", stated_explicit=True),
            skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
        )
        out = apply_clarify_resume(
            intent, "8th grade", _clarify_convo(RequestType.SCRIPTED_ML), CANON,
        )
        assert out.request_type is RequestType.SCRIPTED_ML
        assert out.grade == intent.grade
        assert out.skill == intent.skill


# ----------------------------------------------------------------------
# 4. It stays in its lane (anti-overfit)
# ----------------------------------------------------------------------


class TestResumeStaysInItsLane:
    def test_a_genuine_topic_switch_is_not_overridden(self):
        """The teacher abandoned the question. A new request is not an answer,
        and hijacking it back to the pending type would be worse than the bug."""
        out = apply_clarify_resume(
            _coaching_intent(), "actually, how do I set up writing centers?",
            _clarify_convo(RequestType.SCRIPTED_ML), CANON,
        )
        assert out.request_type is RequestType.COACHING

    def test_no_pending_clarify_leaves_a_terse_followup_alone(self):
        """A normal lesson turn is not a question, so a terse follow-up after it
        is genuinely QU's call (that is what DEEPEN_PRIOR is for)."""
        convo = Conversation(session_id="s", turns=[
            Turn(index=0, role=Role.USER, text="lesson on transitions for 8th grade"),
            Turn(index=1, role=Role.ASSISTANT, text="a full 4-step lesson body",
                 structured={"skill_focus": "transitions"}),
        ])
        out = apply_clarify_resume(_coaching_intent(), "8th grade", convo, CANON)
        assert out.request_type is RequestType.COACHING

    def test_an_empty_conversation_is_a_no_op(self):
        out = apply_clarify_resume(
            _coaching_intent(), "8th grade", Conversation(session_id="s"), CANON,
        )
        assert out.request_type is RequestType.COACHING

    def test_a_message_supplying_no_field_is_not_an_answer(self):
        """"I'm not sure" is not a grade, a skill, or a mode. Brady's asymmetry:
        when in doubt, do nothing — silence is cheap, a wrong route is a lie."""
        out = apply_clarify_resume(
            _coaching_intent(), "I'm not sure",
            _clarify_convo(RequestType.SCRIPTED_ML), CANON,
        )
        assert out.request_type is RequestType.COACHING

    def test_a_full_request_that_happens_to_name_a_grade_is_not_overridden(self):
        """canonicalize_grade SEARCHES, so any message containing "5th" supplies
        a grade. Length + the new-request markers are what keep a real request
        from being read as a bare answer."""
        out = apply_clarify_resume(
            _coaching_intent(),
            "can you show me how to run writing conferences with 5th graders",
            _clarify_convo(RequestType.SCRIPTED_ML), CANON,
        )
        assert out.request_type is RequestType.COACHING

    def test_a_clarify_answered_by_the_pending_type_is_untouched(self):
        """QU got it right on its own — the override must be a no-op, not a
        second opinion."""
        intent = TurnIntent(request_type=RequestType.SCRIPTED_ML)
        out = apply_clarify_resume(
            intent, "8th grade", _clarify_convo(RequestType.SCRIPTED_ML), CANON,
        )
        assert out.request_type is RequestType.SCRIPTED_ML


# ----------------------------------------------------------------------
# 4b. The guard's calibration, pinned
# ----------------------------------------------------------------------
#
# The rule is only as good as the line between "an answer" and "a new request",
# so that line is tested directly rather than inferred from the six routing
# tests above. Note the near-misses in the second list: each one NAMES a grade
# or a skill and would sail through a field check alone — length and the
# new-request markers are what stop them.


@pytest.mark.parametrize("message", [
    "8th grade", "3rd grade", "K", "kindergarten", "grade 4", "2nd",
    "middle school", "high school", "my 5th graders", "I teach 8th grade",
    "topic sentences",
    "persuasive", "informative", "narrative",
])
def test_these_are_bare_field_answers(message):
    assert _is_bare_field_answer(message, CANON) is True


@pytest.mark.parametrize("message", [
    # New requests that DO name a grade or skill — the hard cases.
    "give me a lesson on topic sentences",
    "plan a unit for 3rd grade",
    "I need help with 4th grade",
    "how do I teach 2nd graders paragraphs",
    "what about narrative writing?",
    "can you show me how to run writing conferences with 5th graders",
    "actually, how do I set up writing centers?",
    "never mind, show me management tips",
    "forget the lesson",
    # Replies that answer nothing at all.
    "", "yes", "no", "thanks", "ok", "I am not sure", "can you repeat that?",
])
def test_these_are_not_bare_field_answers(message):
    assert _is_bare_field_answer(message, CANON) is False


# ----------------------------------------------------------------------
# 5. End-to-end through understand() — the wiring, not just the helper
# ----------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, parsed):
        self.parsed = parsed
        self.refusal = None


class _FakeChoice:
    def __init__(self, parsed):
        self.message = _FakeMessage(parsed)


class _FakeCompletion:
    def __init__(self, parsed):
        self.choices = [_FakeChoice(parsed)]


class _FakeCompletions:
    def __init__(self, parsed):
        self._parsed = parsed

    async def parse(self, **kwargs):
        return _FakeCompletion(self._parsed)


class _FakeChat:
    def __init__(self, parsed):
        self.completions = _FakeCompletions(parsed)


class _FakeQUClient:
    """Stand-in for AsyncOpenAI whose parse() returns a fixed TurnIntent."""

    def __init__(self, parsed):
        self.chat = _FakeChat(parsed)


class TestUnderstandAppliesTheResumeEndToEnd:
    @pytest.mark.asyncio
    async def test_understand_resumes_the_pending_type(self):
        """The live shape: QU emits COACHING for "8th grade". The sibling call
        must restore SCRIPTED_ML before the intent leaves QU — proving the
        wiring, not just the isolated helper."""
        out = await understand(
            _clarify_convo(RequestType.SCRIPTED_ML), "8th grade",
            client=_FakeQUClient(_coaching_intent()), model="fake",
            canonicalizer=CANON,
        )
        assert out.request_type is RequestType.SCRIPTED_ML

    @pytest.mark.asyncio
    async def test_understand_leaves_a_real_new_request_alone(self):
        out = await understand(
            _clarify_convo(RequestType.SCRIPTED_ML),
            "actually, how do I set up writing centers?",
            client=_FakeQUClient(_coaching_intent()), model="fake",
            canonicalizer=CANON,
        )
        assert out.request_type is RequestType.COACHING


# ----------------------------------------------------------------------
# 6. The round trip — the gate re-runs and asks for what is STILL missing
# ----------------------------------------------------------------------


class TestResumedTurnReachesTheClarifyGateAgain:
    @pytest.mark.asyncio
    async def test_the_resumed_turn_asks_for_the_still_missing_skill(self):
        """The point of restoring the type: SCRIPTED_ML is in _SKILL_REQUIRED,
        so a turn that now HAS a grade and still lacks a skill asks Brady's
        skill question — instead of COACHING silently inventing one."""
        resumed = TurnIntent(
            request_type=RequestType.SCRIPTED_ML,
            grade=GradeSpec(value="8", stated_explicit=True),
            missing_required=["skill"],
        )
        out = await _dispatch(resumed, _clarify_convo(RequestType.SCRIPTED_ML))
        assert out.structured is None
        assert "skill" in out.response_text.lower()
        # Grade was answered — Brady's B-S01 "never re-ask a known field".
        assert "what grade level do you teach" not in out.response_text.lower()
        assert out.clarifying_for is RequestType.SCRIPTED_ML

    @pytest.mark.asyncio
    async def test_a_fully_specified_resumed_turn_stops_clarifying(self):
        """When the answer completes the picture the gate stops asking — the
        loop terminates rather than re-asking forever."""
        resumed = TurnIntent(
            request_type=RequestType.SCRIPTED_ML,
            grade=GradeSpec(value="8", stated_explicit=True),
            skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
        )
        import handlers as handlers_pkg

        async def _fake(**kwargs):
            return TurnOutcome(response_text="a real lesson", quality=Quality.VALID)

        original = handlers_pkg._HANDLERS[RequestType.SCRIPTED_ML]
        handlers_pkg._HANDLERS[RequestType.SCRIPTED_ML] = _fake
        try:
            out = await _dispatch(resumed, _clarify_convo(RequestType.SCRIPTED_ML))
        finally:
            handlers_pkg._HANDLERS[RequestType.SCRIPTED_ML] = original
        assert out.response_text == "a real lesson"
        assert out.clarifying_for is None
