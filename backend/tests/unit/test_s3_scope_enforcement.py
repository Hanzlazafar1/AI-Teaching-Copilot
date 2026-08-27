"""Brady S3 — the guard and the lesson can never contradict (END-TO-END).

The shipped S3 defect: the one-skill guard was a post-hoc DECORATION. dispatch
rendered it AFTER `await handler(...)`, read `intent.additional_skills` ONLY to
build the guard string, and NOTHING ever told the generator a skill had been
deferred. The LLM — handed a Launch source that covers both skills together —
taught the deferred skill in full, so the app shipped a payload that promised to
defer a skill while teaching it.

The unit-seam invariant lives in test_scripted_ml_prompt.py
(`test_guard_fires_iff_generator_is_constrained`). THIS file locks the same
invariant across the REAL seam — real `dispatch` -> real `handle_scripted_ml` ->
the actual system prompt handed to the model — because that is where S3 was bitten
before: the guard was correct in isolation and got dropped at the API boundary.
A unit test on the renderer alone would not have caught that, and would not catch
a future refactor that stops threading the intent into the prompt builder.

No network: the OpenAI client is a fake that records each system prompt, and the
judge is stubbed out.
"""

from __future__ import annotations

import types

import pytest

import handlers.scripted_ml as scripted_ml_mod
from api.models import ModelSet
from handlers import dispatch
from handlers.formatting import format_one_skill_guard
from handlers.scripted_ml_prompt import _ONE_SKILL_SCOPE_MARKER
from schemas import (
    Conversation,
    GradeSpec,
    ModeSpec,
    Quality,
    RequestType,
    Role,
    SessionHandshakes,
    SkillSpec,
    Turn,
    TurnIntent,
)
from tests.unit._policy_fixtures import _good_lesson


class _RecordingClient:
    """Stands in for AsyncOpenAI: records every system prompt and returns a
    lesson that passes policy, so the handler takes its first-attempt success
    path (one prompt, no retries)."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.chat = types.SimpleNamespace(
            completions=types.SimpleNamespace(parse=self._parse)
        )

    async def _parse(self, *, model, messages, response_format, **kwargs):
        self.prompts.append(messages[0]["content"])
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(
                    message=types.SimpleNamespace(parsed=_good_lesson())
                )
            ]
        )


@pytest.fixture
def no_judge(monkeypatch):
    """The LLM judge is orthogonal to scope enforcement — stub it to abstain."""
    async def _abstain(**kwargs):
        return None

    monkeypatch.setattr(scripted_ml_mod, "judge_scripted_ml", _abstain)


def _intent(extras: list[str]) -> TurnIntent:
    """A real scope-creep intent. The PRIMARY skill matches `_good_lesson`'s
    skill_focus (and grade 4 matches its 3-12 close phrase) so the fixture
    lesson passes policy on attempt 1 — this test is about the PROMPT, not the
    retry loop."""
    return TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        grade=GradeSpec(value="4", stated_explicit=True, stated_turn=0),
        mode=ModeSpec(value="Inform", stated_explicit=True),
        skill=SkillSpec(
            canonical="transitions", as_stated="transitions between paragraphs"
        ),
        additional_skills=extras,
    )


async def _run(client, intent: TurnIntent):
    return await dispatch(
        intent,
        Conversation(session_id="s"),
        SessionHandshakes(),
        "one 4th grade lesson on transitions between paragraphs and conclusions",
        client=client,
        models=ModelSet("GEN", "QRY", "JDG"),
        canonicalizer=object(),
        retrieval_fn=None,
        library=None,
    )


@pytest.mark.asyncio
async def test_guard_and_generation_constraint_ship_together(no_judge):
    """The defect, locked: if the teacher is told a skill is deferred, the
    generator MUST have been told to leave it out — in the same turn, on the
    delivered payload. Fails on the pre-fix code (guard present, prompt silent)."""
    client = _RecordingClient()
    outcome = await _run(client, _intent(["conclusions"]))

    # (1) the teacher-facing guard is delivered on the structured payload
    guard = format_one_skill_guard(["conclusions"])
    assert outcome.structured["one_skill_guard"] == guard

    # (2) ... and the model was actually told to defer that skill.
    assert client.prompts, "the generator must have been prompted"
    for prompt in client.prompts:
        assert _ONE_SKILL_SCOPE_MARKER in prompt, (
            "guard shipped without constraining generation — the lesson would "
            "promise to defer 'conclusions' and then teach it"
        )
        assert "conclusions" in prompt[prompt.index(_ONE_SKILL_SCOPE_MARKER):]


@pytest.mark.asyncio
async def test_no_guard_and_no_constraint_for_a_single_skill(no_judge):
    """The mirror, and the false-positive gate: a normal single-skill lesson
    (empty additional_skills — the overwhelming default, and Brady's B03 shape)
    gets NEITHER the guard NOR any exclusion. Catches a regression that starts
    constraining the generator on ordinary lessons."""
    client = _RecordingClient()
    outcome = await _run(client, _intent([]))

    assert "one_skill_guard" not in outcome.structured
    assert client.prompts
    for prompt in client.prompts:
        assert _ONE_SKILL_SCOPE_MARKER not in prompt
        assert "deferred" not in prompt.lower()


@pytest.mark.asyncio
async def test_deepen_prior_carries_scope_creep_into_generation(no_judge):
    """DEEPEN_PRIOR is the OTHER lesson-shaped type the guard fires on, and it
    reaches generation by delegating to handle_scripted_ml through
    `_merge_intent`. Locks that additional_skills survives that hop — otherwise
    the guard fires on a deepen turn while the prompt stays silent (the exact
    shipped defect, on the second path)."""
    client = _RecordingClient()
    intent = _intent(["conclusions"]).model_copy(
        update={"request_type": RequestType.DEEPEN_PRIOR}
    )
    outcome = await _run(client, intent)

    assert outcome.structured["one_skill_guard"] == format_one_skill_guard(
        ["conclusions"]
    )
    assert client.prompts
    for prompt in client.prompts:
        assert _ONE_SKILL_SCOPE_MARKER in prompt


# --- The CORRECTION path — open task #63, locked CONSISTENT, not fixed -------
# A teacher who adds the 2nd skill in a FOLLOW-UP ("...also add transitions to
# it") produces request_type=CORRECTION, and S3 is inert there — by TWO
# independent gaps that must be closed together or not at all:
#
#   (a) `correction._merge_correction` never copies the current turn's
#       `additional_skills` (it merges only grade/mode/trait/skill/triggers), so
#       the delegate intent reaches generation with the signal dropped; and
#   (b) dispatch's guard gate keys on `intent.request_type`, which is CORRECTION
#       — not in `_LESSON_SHAPED` — so the guard cannot fire regardless of (a).
#
# Closing (a) ALONE would be strictly worse than today: generation would silently
# omit the skill the teacher just asked for, with no guard explaining why — the
# mirror of the defect this file exists to prevent. Closing (b) puts the guard on
# a user-visible path that never went through S3's live 0/30 false-positive gate
# (and `_merge_correction` carries the PRIOR turn's extras forward, so a naive
# fix re-fires the guard on every later correction). That needs its own
# live-gated slice + a Brady call on whether the guard repeats.
#
# So this test asserts the INVARIANT, not the bug: on the CORRECTION path the
# guard and the generation constraint are both OFF, hence consistent. Whoever
# closes #63 will see it fail the moment they close only one half.


@pytest.mark.asyncio
async def test_correction_path_guard_and_constraint_stay_consistent(no_judge):
    client = _RecordingClient()
    prior_user = Turn(
        index=0,
        role=Role.USER,
        text="give me a 4th grade lesson on transitions between paragraphs",
        intent=_intent([]),
    )
    prior_assistant = Turn(
        index=1, role=Role.ASSISTANT, text="<lesson>", quality=Quality.VALID
    )
    conversation = Conversation(session_id="s", turns=[prior_user, prior_assistant])

    outcome = await dispatch(
        TurnIntent(
            request_type=RequestType.CORRECTION, additional_skills=["conclusions"]
        ),
        conversation,
        SessionHandshakes(),
        "also add conclusions to that lesson",
        client=client,
        models=ModelSet("GEN", "QRY", "JDG"),
        canonicalizer=object(),
        retrieval_fn=None,
        library=None,
    )

    guard_shown = "one_skill_guard" in (outcome.structured or {})
    constrained = any(_ONE_SKILL_SCOPE_MARKER in p for p in client.prompts)
    assert client.prompts, "the correction must have reached generation"
    assert guard_shown == constrained, (
        "S3 half-wired on the CORRECTION path: guard_shown="
        f"{guard_shown} but generator_constrained={constrained}. Task #63 must "
        "close BOTH _merge_correction (carry additional_skills) AND the "
        "_LESSON_SHAPED gate (which keys on the pre-delegation request_type) — "
        "never one without the other."
    )
