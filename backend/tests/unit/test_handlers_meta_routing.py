"""Tests for DEEPEN_PRIOR + CORRECTION — the meta-handlers that
delegate to content handlers with mutated intent.

Strategy: monkeypatch the target handlers to capture the intent passed
in, so we can assert the mutation logic without running any LLM calls.
"""

from __future__ import annotations

from typing import Any

import pytest

import handlers.coaching as coaching_mod
import handlers.correction as correction_mod
import handlers.deepen_prior as deepen_mod
import handlers.how_to_teach as how_to_teach_mod
import handlers.management as management_mod
import handlers.plan_unit as plan_unit_mod
import handlers.scripted_ml as scripted_ml_mod
import handlers.think_aloud as think_aloud_mod
from api.models import ModelSet
from handlers import dispatch
from handlers.correction import _find_prior_content_intent, handle_correction
from handlers.deepen_prior import (
    _find_prior_context,
    _merge_intent,
    _pick_target_request_type,
    handle_deepen_prior,
)
from schemas import (
    Conversation,
    GradeSpec,
    ModeSpec,
    Quality,
    RequestType,
    Role,
    SessionHandshakes,
    SkillSpec,
    TraitSpec,
    Turn,
    TurnIntent,
    TurnOutcome,
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _prior_intent(
    request_type: RequestType = RequestType.HOW_TO_TEACH,
    grade: str = "3",
    mode: str = "Inform",
    skill_stated: str = "topic sentences",
) -> TurnIntent:
    return TurnIntent(
        request_type=request_type,
        grade=GradeSpec(value=grade, stated_explicit=True),
        mode=ModeSpec(value=mode, stated_explicit=True),  # type: ignore[arg-type]
        trait=TraitSpec(value="Ideas", stated_explicit=False, confidence=0.8),
        skill=SkillSpec(canonical=skill_stated, as_stated=skill_stated),
    )


def _build_convo(prior_intent: TurnIntent, assistant_text: str = "reply") -> Conversation:
    conv = Conversation(session_id="s1")
    conv.append(Turn(index=0, role=Role.USER, text="earlier question", intent=prior_intent))
    conv.append(Turn(index=1, role=Role.ASSISTANT, text=assistant_text, quality=Quality.VALID))
    return conv


class _RouteCapture:
    """Records which handler was called + with what intent."""

    def __init__(self) -> None:
        self.called_with: dict[str, Any] = {}

    async def __call__(self, **kwargs: Any) -> TurnOutcome:
        self.called_with = kwargs
        return TurnOutcome(
            response_text="stub",
            structured=None,
            grounding=[],
            quality=Quality.VALID,
            retry_count=0,
            validation_errors=[],
        )


# ----------------------------------------------------------------------
# DEEPEN_PRIOR — target selection
# ----------------------------------------------------------------------


def test_deepen_picks_scripted_ml_when_user_asks_for_lesson() -> None:
    assert _pick_target_request_type("put this in a lesson", None) is RequestType.SCRIPTED_ML
    assert _pick_target_request_type("wrap it into a full mini-lesson", None) is RequestType.SCRIPTED_ML


def test_deepen_picks_think_aloud_on_explicit_ask() -> None:
    assert (
        _pick_target_request_type("show me just the think-aloud", None)
        is RequestType.THINK_ALOUD
    )
    assert (
        _pick_target_request_type("model your thinking for this", None)
        is RequestType.THINK_ALOUD
    )


def test_pick_target_lesson_shaped_beats_think_aloud() -> None:
    # Brady Fm2 / TS03: "put the think-aloud into a 4-step ML" must route to
    # the STRUCTURED generator, not THINK_ALOUD (which yields prose). The
    # think-aloud bucket used to win because it was checked with these words
    # present but no lesson word.
    assert _pick_target_request_type("put the think-aloud into a 4-step ML", None) is RequestType.SCRIPTED_ML
    assert _pick_target_request_type("turn this think aloud into a lesson", None) is RequestType.SCRIPTED_ML


def test_pick_target_pure_think_aloud_unaffected() -> None:
    # Guard: a pure think-aloud ask (no lesson token) still routes to THINK_ALOUD.
    assert _pick_target_request_type("show me just the think-aloud", None) is RequestType.THINK_ALOUD
    assert _pick_target_request_type("model your thinking for this", None) is RequestType.THINK_ALOUD


def test_deepen_picks_how_to_teach_on_outline_ask() -> None:
    assert (
        _pick_target_request_type("what are strategies for this", None)
        is RequestType.HOW_TO_TEACH
    )
    assert (
        _pick_target_request_type("how to teach this", None)
        is RequestType.HOW_TO_TEACH
    )


def test_deepen_picks_plan_unit_on_unit_ask() -> None:
    assert (
        _pick_target_request_type("plan a unit around this", None)
        is RequestType.PLAN_UNIT
    )


def test_deepen_default_after_how_to_teach_is_scripted_ml() -> None:
    prior = deepen_mod._PriorContext(
        intent=None,
        request_type=RequestType.HOW_TO_TEACH,
        structured=None,
        quality=Quality.VALID,
    )
    assert (
        _pick_target_request_type("that sounds great, the first one", prior)
        is RequestType.SCRIPTED_ML
    )


# ----------------------------------------------------------------------
# DEEPEN_PRIOR — intent merge
# ----------------------------------------------------------------------


def test_merge_inherits_missing_fields_from_prior() -> None:
    prior = _prior_intent()
    current = TurnIntent(request_type=RequestType.DEEPEN_PRIOR, refers_to_prior=True)
    merged = _merge_intent(current, prior, RequestType.SCRIPTED_ML)

    assert merged.request_type is RequestType.SCRIPTED_ML
    assert merged.grade is not None and merged.grade.value == "3"
    assert merged.mode is not None and merged.mode.value == "Inform"
    assert merged.skill is not None and merged.skill.canonical == "topic sentences"
    assert merged.refers_to_prior is True


def test_merge_does_not_overwrite_current_fields() -> None:
    prior = _prior_intent(grade="3")
    current = TurnIntent(
        request_type=RequestType.DEEPEN_PRIOR,
        grade=GradeSpec(value="5", stated_explicit=True),
    )
    merged = _merge_intent(current, prior, RequestType.SCRIPTED_ML)
    assert merged.grade is not None and merged.grade.value == "5"


def test_merge_carries_required_triggers_when_current_has_none() -> None:
    prior = TurnIntent(
        request_type=RequestType.HOW_TO_TEACH,
        required_triggers=["pizza-table"],
    )
    current = TurnIntent(request_type=RequestType.DEEPEN_PRIOR)
    merged = _merge_intent(current, prior, RequestType.SCRIPTED_ML)
    assert merged.required_triggers == ["pizza-table"]


# ----------------------------------------------------------------------
# DEEPEN_PRIOR — prior-context discovery
# ----------------------------------------------------------------------


def test_find_prior_context_skips_low_quality_turns() -> None:
    conv = Conversation(session_id="s1")
    conv.append(Turn(index=0, role=Role.USER, text="q1", intent=_prior_intent()))
    conv.append(Turn(index=1, role=Role.ASSISTANT, text="bad", quality=Quality.LOW))
    conv.append(Turn(index=2, role=Role.USER, text="q2", intent=_prior_intent(grade="4")))
    conv.append(Turn(index=3, role=Role.ASSISTANT, text="good", quality=Quality.VALID))

    prior = _find_prior_context(conv)
    assert prior is not None
    assert prior.intent is not None and prior.intent.grade is not None
    assert prior.intent.grade.value == "4"  # the VALID one's prior user turn


def test_find_prior_context_returns_none_on_empty_convo() -> None:
    assert _find_prior_context(Conversation(session_id="s1")) is None


# ----------------------------------------------------------------------
# DEEPEN_PRIOR — dispatch wiring
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deepen_delegates_to_scripted_ml_with_inherited_skill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = _RouteCapture()
    monkeypatch.setattr(scripted_ml_mod, "handle_scripted_ml", cap)
    # Also patch any re-exports so the late import picks it up
    monkeypatch.setattr("handlers.scripted_ml.handle_scripted_ml", cap)

    conv = _build_convo(_prior_intent(skill_stated="topic sentences"))
    current = TurnIntent(request_type=RequestType.DEEPEN_PRIOR, refers_to_prior=True)

    out = await handle_deepen_prior(
        intent=current,
        conversation=conv,
        handshakes=SessionHandshakes(),
        new_user_message="put this in a lesson",
        client=None,  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert out.response_text == "stub"
    delegated: TurnIntent = cap.called_with["intent"]
    assert delegated.request_type is RequestType.SCRIPTED_ML
    assert delegated.skill is not None
    assert delegated.skill.canonical == "topic sentences"


@pytest.mark.asyncio
async def test_deepen_delegates_to_think_aloud_on_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = _RouteCapture()
    monkeypatch.setattr("handlers.think_aloud.handle_think_aloud", cap)

    conv = _build_convo(_prior_intent())
    current = TurnIntent(request_type=RequestType.DEEPEN_PRIOR, refers_to_prior=True)

    await handle_deepen_prior(
        intent=current,
        conversation=conv,
        handshakes=SessionHandshakes(),
        new_user_message="show me just the think-aloud",
        client=None,  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    delegated: TurnIntent = cap.called_with["intent"]
    assert delegated.request_type is RequestType.THINK_ALOUD


# ----------------------------------------------------------------------
# DEEPEN_PRIOR — carried organizer / prior approach (Brady C3)
# ----------------------------------------------------------------------
#
# Brady C3: the app gave a great description of a specific organizer /
# anchor-chart (e.g. "PIE flaps"), the teacher said "give me a mini-lesson
# for that", and the generated ML did NOT incorporate the organizer it had
# just described. Fix: when DEEPEN_PRIOR turns a prior *description* into a
# lesson, thread that description into the generation context as an explicit
# must-incorporate block — rather than letting it survive only as generic
# conversation history the model may ignore.


@pytest.mark.asyncio
async def test_deepen_carries_prior_organizer_into_scripted_ml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = _RouteCapture()
    monkeypatch.setattr("handlers.scripted_ml.handle_scripted_ml", cap)

    organizer = (
        "Use PIE flaps: a three-flap foldable where each flap holds a Point, "
        "the Information that backs it up, and the Explanation that ties it back."
    )
    conv = _build_convo(
        _prior_intent(skill_stated="topic sentences"), assistant_text=organizer
    )
    current = TurnIntent(request_type=RequestType.DEEPEN_PRIOR, refers_to_prior=True)

    await handle_deepen_prior(
        intent=current,
        conversation=conv,
        handshakes=SessionHandshakes(),
        new_user_message="give me a mini-lesson for that",
        client=None,  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    carried = cap.called_with.get("carried_context")
    assert carried is not None, "the prior organizer description must be threaded"
    assert "PIE flaps" in carried


@pytest.mark.asyncio
async def test_deepen_omits_carry_when_prior_was_a_full_lesson(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No-op guard: if the prior VALID turn was ITSELF a scripted mini-lesson
    (structured carries skill_focus) there is no separate organizer to fold in
    — continuity already flows through the inherited skill/grade fields — so no
    carried_context is threaded."""
    cap = _RouteCapture()
    monkeypatch.setattr("handlers.scripted_ml.handle_scripted_ml", cap)

    conv = Conversation(session_id="s1")
    conv.append(
        Turn(
            index=0, role=Role.USER, text="lesson on topic sentences",
            intent=_prior_intent(request_type=RequestType.SCRIPTED_ML),
        )
    )
    conv.append(
        Turn(
            index=1, role=Role.ASSISTANT, text="a full lesson body",
            quality=Quality.VALID, structured={"skill_focus": "topic sentences"},
        )
    )
    current = TurnIntent(request_type=RequestType.DEEPEN_PRIOR, refers_to_prior=True)

    await handle_deepen_prior(
        intent=current,
        conversation=conv,
        handshakes=SessionHandshakes(),
        new_user_message="put this in a lesson",
        client=None,  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert "carried_context" not in cap.called_with


@pytest.mark.asyncio
async def test_deepen_omits_carry_when_no_prior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No-op guard: with no prior VALID assistant turn there is nothing to
    carry, so no carried_context reaches the delegate."""
    cap = _RouteCapture()
    monkeypatch.setattr("handlers.scripted_ml.handle_scripted_ml", cap)

    conv = Conversation(session_id="s1")
    conv.append(
        Turn(
            index=0, role=Role.USER, text="give me a lesson",
            intent=TurnIntent(request_type=RequestType.DEEPEN_PRIOR),
        )
    )
    current = TurnIntent(request_type=RequestType.DEEPEN_PRIOR, refers_to_prior=True)

    await handle_deepen_prior(
        intent=current,
        conversation=conv,
        handshakes=SessionHandshakes(),
        new_user_message="put this in a lesson",
        client=None,  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert "carried_context" not in cap.called_with


# ----------------------------------------------------------------------
# CORRECTION — routing
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correction_reruns_prior_handler_with_new_grade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = _RouteCapture()
    # CORRECTION does late imports of each target handler; patch at source
    monkeypatch.setattr("handlers.scripted_ml.handle_scripted_ml", cap)

    prior = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        grade=GradeSpec(value="3", stated_explicit=True),
        skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
    )
    conv = _build_convo(prior)

    correction = TurnIntent(
        request_type=RequestType.CORRECTION,
        grade=GradeSpec(value="4", stated_explicit=True),
    )

    await handle_correction(
        intent=correction,
        conversation=conv,
        handshakes=SessionHandshakes(),
        new_user_message="actually, make it 4th grade",
        client=None,  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    delegated: TurnIntent = cap.called_with["intent"]
    assert delegated.request_type is RequestType.SCRIPTED_ML  # prior preserved
    assert delegated.grade is not None and delegated.grade.value == "4"
    # Fields not mentioned in the correction stay from prior
    assert delegated.skill is not None
    assert delegated.skill.canonical == "topic sentences"


@pytest.mark.asyncio
async def test_correction_falls_back_to_coaching_when_no_prior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cap = _RouteCapture()
    monkeypatch.setattr("handlers.coaching.handle_coaching", cap)

    correction = TurnIntent(request_type=RequestType.CORRECTION)

    await handle_correction(
        intent=correction,
        conversation=Conversation(session_id="s1"),
        handshakes=SessionHandshakes(),
        new_user_message="no, 4th grade",
        client=None,  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    delegated: TurnIntent = cap.called_with["intent"]
    assert delegated.request_type is RequestType.COACHING


@pytest.mark.asyncio
async def test_correction_ignores_non_content_prior_and_walks_further_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prior user turn that was a META greeting shouldn't count as the
    handler to re-run. The correction walks further back to find content."""
    cap = _RouteCapture()
    monkeypatch.setattr("handlers.how_to_teach.handle_how_to_teach", cap)

    conv = Conversation(session_id="s1")
    # Turn 0: HOW_TO_TEACH content
    conv.append(
        Turn(
            index=0, role=Role.USER, text="how do I teach?",
            intent=_prior_intent(request_type=RequestType.HOW_TO_TEACH),
        )
    )
    conv.append(Turn(index=1, role=Role.ASSISTANT, text="outline", quality=Quality.VALID))
    # Turn 2: META greeting  (not correctable)
    conv.append(
        Turn(
            index=2, role=Role.USER, text="thanks",
            intent=TurnIntent(request_type=RequestType.META),
        )
    )
    conv.append(Turn(index=3, role=Role.ASSISTANT, text="np", quality=Quality.VALID))

    correction = TurnIntent(
        request_type=RequestType.CORRECTION,
        grade=GradeSpec(value="5", stated_explicit=True),
    )
    await handle_correction(
        intent=correction,
        conversation=conv,
        handshakes=SessionHandshakes(),
        new_user_message="actually 5th grade",
        client=None,  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    delegated: TurnIntent = cap.called_with["intent"]
    assert delegated.request_type is RequestType.HOW_TO_TEACH
    assert delegated.grade is not None and delegated.grade.value == "5"


# ----------------------------------------------------------------------
# CORRECTION — chained corrections (finding F7)
# ----------------------------------------------------------------------
#
# A 2nd CORRECTION used to silently revert the 1st: the backward walk
# skipped intervening CORRECTION turns (not in _CORRECTABLE) and re-anchored
# on the ORIGINAL content intent, dropping the 1st correction's delta. The
# anchor for a NEW correction must be the EFFECTIVE intent — the base content
# intent with every intervening CORRECTION folded on, in turn order.


@pytest.mark.asyncio
async def test_chained_correction_preserves_earlier_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F7 repro: "3rd-grade lesson on X" -> "make it 4th grade" -> "make it
    narrative" must yield a 4TH-grade NARRATIVE lesson. Pre-fix, the 2nd
    correction re-anchored to the original SCRIPTED_ML turn and the grade
    silently reverted to 3."""
    cap = _RouteCapture()
    monkeypatch.setattr("handlers.scripted_ml.handle_scripted_ml", cap)

    conv = Conversation(session_id="s1")
    # Turn 0: base content — 3rd-grade lesson on skill X
    conv.append(
        Turn(
            index=0, role=Role.USER, text="3rd grade lesson on topic sentences",
            intent=TurnIntent(
                request_type=RequestType.SCRIPTED_ML,
                grade=GradeSpec(value="3", stated_explicit=True),
                skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
            ),
        )
    )
    conv.append(Turn(index=1, role=Role.ASSISTANT, text="lesson v1", quality=Quality.VALID))
    # Turn 2: FIRST correction — bump to 4th grade
    conv.append(
        Turn(
            index=2, role=Role.USER, text="actually make it 4th grade",
            intent=TurnIntent(
                request_type=RequestType.CORRECTION,
                grade=GradeSpec(value="4", stated_explicit=True),
            ),
        )
    )
    conv.append(Turn(index=3, role=Role.ASSISTANT, text="lesson v2", quality=Quality.VALID))

    # SECOND correction (current turn — NOT yet in convo, per the dispatch
    # contract). Deliberately carries NO grade, mirroring a field QU need
    # not re-emit, so the fold — not QU field-carry — is what preserves it.
    second = TurnIntent(
        request_type=RequestType.CORRECTION,
        mode=ModeSpec(value="Entertain", stated_explicit=True),
    )

    await handle_correction(
        intent=second,
        conversation=conv,
        handshakes=SessionHandshakes(),
        new_user_message="make it narrative",
        client=None,  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    delegated: TurnIntent = cap.called_with["intent"]
    assert delegated.request_type is RequestType.SCRIPTED_ML
    # BOTH corrections survive:
    assert delegated.grade is not None and delegated.grade.value == "4"  # 1st preserved
    assert delegated.mode is not None and delegated.mode.value == "Entertain"  # 2nd applied
    # untouched base field carried through
    assert delegated.skill is not None and delegated.skill.canonical == "topic sentences"


def test_find_prior_content_intent_folds_multiple_corrections() -> None:
    """The anchor returned to a NEW correction is the EFFECTIVE intent: base
    content intent with every intervening CORRECTION folded on in turn order.
    Proven at the helper level so it holds regardless of QU field-carry."""
    conv = Conversation(session_id="s1")
    conv.append(
        Turn(
            index=0, role=Role.USER, text="q",
            intent=TurnIntent(
                request_type=RequestType.SCRIPTED_ML,
                grade=GradeSpec(value="3", stated_explicit=True),
                skill=SkillSpec(canonical="X", as_stated="X"),
            ),
        )
    )
    conv.append(Turn(index=1, role=Role.ASSISTANT, text="a", quality=Quality.VALID))
    conv.append(
        Turn(
            index=2, role=Role.USER, text="4th grade",
            intent=TurnIntent(
                request_type=RequestType.CORRECTION,
                grade=GradeSpec(value="4", stated_explicit=True),
            ),
        )
    )
    conv.append(Turn(index=3, role=Role.ASSISTANT, text="a", quality=Quality.VALID))
    conv.append(
        Turn(
            index=4, role=Role.USER, text="narrative",
            intent=TurnIntent(
                request_type=RequestType.CORRECTION,
                mode=ModeSpec(value="Entertain", stated_explicit=True),
            ),
        )
    )
    conv.append(Turn(index=5, role=Role.ASSISTANT, text="a", quality=Quality.VALID))

    effective = _find_prior_content_intent(conv)
    assert effective is not None
    assert effective.request_type is RequestType.SCRIPTED_ML  # base type preserved
    assert effective.grade is not None and effective.grade.value == "4"
    assert effective.mode is not None and effective.mode.value == "Entertain"
    assert effective.skill is not None and effective.skill.canonical == "X"


def test_find_prior_content_intent_single_correction_returns_base_unchanged() -> None:
    """No-regression: with no intervening corrections the effective intent IS
    the base content intent, field-for-field — the fold is a no-op on the
    single-correction path."""
    base = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        grade=GradeSpec(value="3", stated_explicit=True),
        skill=SkillSpec(canonical="X", as_stated="X"),
    )
    conv = Conversation(session_id="s1")
    conv.append(Turn(index=0, role=Role.USER, text="q", intent=base))
    conv.append(Turn(index=1, role=Role.ASSISTANT, text="a", quality=Quality.VALID))

    effective = _find_prior_content_intent(conv)
    assert effective is not None
    assert effective.model_dump() == base.model_dump()


# ----------------------------------------------------------------------
# F27 residual — judge_model threading through the meta-handlers
# ----------------------------------------------------------------------
#
# F27 runs the LLM accept-gate on the cheaper judge model, not the generation
# flagship. The DIRECT SCRIPTED_ML dispatch path already threads judge_model.
# DEEPEN_PRIOR and CORRECTION can DELEGATE to handle_scripted_ml (and thus
# reach the judge), so dispatch must give them judge_model AND the meta-handler
# must forward it — but ONLY when the delegated target IS handle_scripted_ml.
# Every other target (think_aloud, how_to_teach, plan_unit, coaching,
# management) has no judge and does not accept the kwarg; forwarding it there
# would raise TypeError live. These tests exercise the FULL chain through the
# real dispatch so a regression in EITHER the dispatch guard or the handler
# forwarding is caught.


@pytest.mark.asyncio
async def test_dispatch_deepen_to_scripted_ml_threads_judge_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dispatch -> handle_deepen_prior -> handle_scripted_ml threads
    judge_model=models.judge (JDG), NOT the generation model (GEN)."""
    cap = _RouteCapture()
    # Late import inside the handler resolves to the module attribute.
    monkeypatch.setattr("handlers.scripted_ml.handle_scripted_ml", cap)

    conv = _build_convo(_prior_intent(skill_stated="topic sentences"))
    current = TurnIntent(request_type=RequestType.DEEPEN_PRIOR, refers_to_prior=True)

    await dispatch(
        current,
        conv,
        SessionHandshakes(),
        "put this in a lesson",
        client=object(),
        models=ModelSet("GEN", "QRY", "JDG"),
        canonicalizer=object(),
        retrieval_fn=None,
        library=None,
    )
    assert cap.called_with["model"] == "GEN"
    assert cap.called_with["judge_model"] == "JDG"


@pytest.mark.asyncio
async def test_dispatch_deepen_to_think_aloud_omits_judge_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When DEEPEN_PRIOR delegates to a NON-scripted target, judge_model is
    withheld — handle_think_aloud has no judge and doesn't accept the kwarg."""
    cap = _RouteCapture()
    monkeypatch.setattr("handlers.think_aloud.handle_think_aloud", cap)

    conv = _build_convo(_prior_intent())
    current = TurnIntent(request_type=RequestType.DEEPEN_PRIOR, refers_to_prior=True)

    await dispatch(
        current,
        conv,
        SessionHandshakes(),
        "show me just the think-aloud",
        client=object(),
        models=ModelSet("GEN", "QRY", "JDG"),
        canonicalizer=object(),
        retrieval_fn=None,
        library=None,
    )
    assert cap.called_with["model"] == "GEN"
    assert "judge_model" not in cap.called_with


@pytest.mark.asyncio
async def test_dispatch_correction_to_scripted_ml_threads_judge_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dispatch -> handle_correction -> handle_scripted_ml threads
    judge_model=models.judge (JDG), NOT the generation model (GEN)."""
    cap = _RouteCapture()
    monkeypatch.setattr("handlers.scripted_ml.handle_scripted_ml", cap)

    prior = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        grade=GradeSpec(value="3", stated_explicit=True),
        skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
    )
    conv = _build_convo(prior)
    correction = TurnIntent(
        request_type=RequestType.CORRECTION,
        grade=GradeSpec(value="4", stated_explicit=True),
    )

    await dispatch(
        correction,
        conv,
        SessionHandshakes(),
        "actually, make it 4th grade",
        client=object(),
        models=ModelSet("GEN", "QRY", "JDG"),
        canonicalizer=object(),
        retrieval_fn=None,
        library=None,
    )
    assert cap.called_with["model"] == "GEN"
    assert cap.called_with["judge_model"] == "JDG"


@pytest.mark.asyncio
async def test_dispatch_correction_to_non_scripted_target_omits_judge_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CORRECTION picks its target from a per-request-type map. When that
    target is NOT handle_scripted_ml (here HOW_TO_TEACH), judge_model must be
    withheld — handle_how_to_teach doesn't accept it (would TypeError live)."""
    cap = _RouteCapture()
    monkeypatch.setattr("handlers.how_to_teach.handle_how_to_teach", cap)

    prior = _prior_intent(request_type=RequestType.HOW_TO_TEACH)
    conv = _build_convo(prior)
    correction = TurnIntent(
        request_type=RequestType.CORRECTION,
        grade=GradeSpec(value="5", stated_explicit=True),
    )

    await dispatch(
        correction,
        conv,
        SessionHandshakes(),
        "actually 5th grade",
        client=object(),
        models=ModelSet("GEN", "QRY", "JDG"),
        canonicalizer=object(),
        retrieval_fn=None,
        library=None,
    )
    assert cap.called_with["model"] == "GEN"
    assert "judge_model" not in cap.called_with


# Silence unused-import for monkeypatch target modules — they must be
# importable at test discovery time so monkeypatch paths resolve.
_ = (
    coaching_mod,
    correction_mod,
    how_to_teach_mod,
    management_mod,
    plan_unit_mod,
    think_aloud_mod,
)


# ----------------------------------------------------------------------
# Brady's e9 complaint — deepening a MANAGEMENT overview (docx:136)
# ----------------------------------------------------------------------
# "This is frustrating for the user for several reasons: Response listed skills
#  that were not even mentioned in the overview!"
# "Ok, we have a big disconnect here. When 'routines, management, start up,
#  writer's workshop, writer habits, expectations, procedures' are the focus,
#  then Co-Pilot must pull from Sections 1-5 in the Launch books."
#
# He asked for a ROUTINES overview, praised it ("Good overview"), then asked a
# follow-up — and got writing SKILLS. Two links caused it, both here:
#   1. _pick_target_request_type has no MANAGEMENT branch and defaults to
#      SCRIPTED_ML ("the 'deepen' intent presumes teaching content"), so a bare
#      follow-up to a routines overview became a writing-skill mini-lesson.
#   2. the delegation else-branch falls through to handle_coaching, whose
#      retrieval is labelled COACHING_GENERAL — so the reranker's management
#      scoping (DEPRIO_WRONG_MGMT on ch 8-13) silently stopped applying.
# Measured live: the follow-up retrieved s6-ml1-define-trait /
# s8-ml04-details-vs-development / s8-ml05-table-top-leg-sentences — Sections 6
# and 8, precisely what he said must not happen.


def test_deepen_of_a_management_overview_stays_management() -> None:
    prior = _prior_intent(request_type=RequestType.MANAGEMENT)
    convo = _build_convo(prior, assistant_text="Here are your workshop routines...")
    ctx = _find_prior_context(convo)
    assert _pick_target_request_type("Can you expand on those?", ctx) is RequestType.MANAGEMENT


def test_deepen_of_a_skill_turn_is_unaffected() -> None:
    """Scoped to management — the existing default must not move."""
    prior = _prior_intent(request_type=RequestType.HOW_TO_TEACH)
    convo = _build_convo(prior)
    ctx = _find_prior_context(convo)
    assert _pick_target_request_type("Can you expand on those?", ctx) is RequestType.SCRIPTED_ML


def test_an_explicit_lesson_ask_after_management_is_left_alone() -> None:
    """Brady wants management routines taught AS 4-step MLs (Wave 3 #14).
    That build does not exist, so an explicit lesson ask still routes to
    SCRIPTED_ML — the gap stays VISIBLE rather than being half-closed here."""
    prior = _prior_intent(request_type=RequestType.MANAGEMENT)
    convo = _build_convo(prior)
    ctx = _find_prior_context(convo)
    assert _pick_target_request_type("give me a lesson on that", ctx) is RequestType.SCRIPTED_ML


@pytest.mark.asyncio
async def test_deepen_delegates_management_to_the_management_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MANAGEMENT was the ONE request type this delegation could not reach."""
    cap = _RouteCapture()
    monkeypatch.setattr("handlers.management.handle_management", cap)
    coach = _RouteCapture()
    monkeypatch.setattr("handlers.coaching.handle_coaching", coach)

    convo = _build_convo(_prior_intent(request_type=RequestType.MANAGEMENT),
                         assistant_text="Here are your workshop routines...")
    current = TurnIntent(request_type=RequestType.DEEPEN_PRIOR, refers_to_prior=True)
    await handle_deepen_prior(
        intent=current,
        conversation=convo,
        handshakes=SessionHandshakes(),
        new_user_message="Can you expand on those?",
        client=None,  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert cap.called_with, "a MANAGEMENT deepen must reach handle_management"
    assert not coach.called_with, "it must NOT fall through to coaching"
    assert cap.called_with["intent"].request_type is RequestType.MANAGEMENT
