"""Unit tests for the campaign judge (``campaign/judge.py``).

The judge turns one Brady-alignment *claim* + a driven *Envelope* into a
:class:`Verdict` (ALIGNED / MISALIGNED / UNCERTAIN). Four dispatch methods:

  * **deterministic** — run the named ``validation/`` validator on the
    flattened response text; a violation → MISALIGNED, clean → ALIGNED.
  * **llm-judge** — gpt-4o @ temp 0 with the claim's rubric → structured verdict.
  * **hybrid** — validator AND llm must both pass; disagreement → UNCERTAIN.
  * **launch-first** — per-query_type tier-vs-provenance check on ``sources``.

Every LLM call is STUBBED — no network, no real OpenAI key. These tests pin
the contract with fixed inputs so they belong in the always-run gate.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from campaign import drive
from campaign import judge
from tests.unit._policy_fixtures import _good_lesson

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Stubs — an OpenAI-client stand-in whose .chat.completions.parse is fully
# controlled. No real network / key is ever touched.
# ---------------------------------------------------------------------------


class _StubOpenAI:
    """Returns a preset ``_LLMJudgment`` from .chat.completions.parse and
    records the kwargs it was called with (so tests can assert temp=0 etc.)."""

    def __init__(self, judgment: "judge._LLMJudgment") -> None:
        self._judgment = judgment
        self.calls: list[dict] = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(parse=self._parse)
        )

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(parsed=self._judgment)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _BoomOpenAI:
    """Any use of the LLM raises — proves the deterministic / launch-first
    paths never reach for the model."""

    def __init__(self) -> None:
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(parse=self._boom)
        )

    def _boom(self, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("LLM must not be called on this path")


def _aligned_llm(conf=0.9):
    return judge._LLMJudgment(status="ALIGNED", confidence=conf, rationale="ok")


def _misaligned_llm(conf=0.9):
    return judge._LLMJudgment(
        status="MISALIGNED", confidence=conf, rationale="no modeled answer follows"
    )


# ---------------------------------------------------------------------------
# Envelope builders
# ---------------------------------------------------------------------------


def _env(response, *, parsed_query=None, sources=None, session_state=None,
         prior_turns=None, status="OK"):
    raw = {"response": response}
    if parsed_query is not None:
        raw["parsed_query"] = parsed_query
    if sources is not None:
        raw["sources"] = sources
    if session_state is not None:
        raw["session_state"] = session_state
    if prior_turns is not None:
        raw["prior_turns"] = prior_turns
    return drive.Envelope(raw=raw, status=status)


def _lesson_dict(**overrides) -> dict:
    """A clean SCRIPTED_ML lesson dict that passes every validator."""
    return _good_lesson(**overrides).model_dump()


# ---------------------------------------------------------------------------
# Verdict shape
# ---------------------------------------------------------------------------


def test_verdict_has_the_documented_fields():
    v = judge.Verdict(
        status="ALIGNED", confidence=1.0, rationale="r", method="deterministic",
        evidence="e",
    )
    assert v.status == "ALIGNED"
    assert v.confidence == 1.0
    assert v.rationale == "r"
    assert v.method == "deterministic"
    assert v.evidence == "e"


# ---------------------------------------------------------------------------
# deterministic — banned words (#5) on flattened text
# ---------------------------------------------------------------------------


_BANNED_CLAIM = {"judge_method": "deterministic", "observable": "validate_no_forbidden_words"}


def test_deterministic_banned_word_discuss_is_misaligned():
    env = _env("Have the students discuss their topic with a partner.")
    v = judge.judge_claim(_BANNED_CLAIM, env, openai_client=_BoomOpenAI())
    assert v.status == "MISALIGNED"
    assert v.method == "deterministic"
    assert "discuss" in v.rationale.lower()


def test_deterministic_clean_text_is_aligned():
    env = _env("Have students turn and talk with a partner about their topic.")
    v = judge.judge_claim(_BANNED_CLAIM, env, openai_client=_BoomOpenAI())
    assert v.status == "ALIGNED"
    assert v.method == "deterministic"


def test_deterministic_flattens_a_scripted_ml_lesson_dict():
    # A banned word buried in Step 2B of a structured lesson must still trip
    # the text validator — the judge flattens the lesson dict to text first.
    env = _env(_lesson_dict(step_2b_show="Let me discuss this with myself."))
    v = judge.judge_claim(_BANNED_CLAIM, env, openai_client=_BoomOpenAI())
    assert v.status == "MISALIGNED"
    assert "discuss" in v.rationale.lower()


# ---------------------------------------------------------------------------
# deterministic — E1 grade-band close (needs the MiniLesson shape + grade)
# ---------------------------------------------------------------------------


_E1_CLAIM = {"judge_method": "deterministic", "observable": "validate_grade_band_close"}


def test_deterministic_e1_wrong_grade_band_close_is_misaligned():
    # Grade K lesson that closes with the 3-12 phrase → E1 violation.
    env = _env(_lesson_dict(
        grade_level="K",
        step_4_close="Great work today. Now it's your turn! Go write.",
    ))
    v = judge.judge_claim(_E1_CLAIM, env, openai_client=_BoomOpenAI())
    assert v.status == "MISALIGNED"


def test_deterministic_e1_correct_grade_band_close_is_aligned():
    env = _env(_lesson_dict(
        grade_level="K",
        step_4_close="Great work today. Let's go be writers!",
    ))
    v = judge.judge_claim(_E1_CLAIM, env, openai_client=_BoomOpenAI())
    assert v.status == "ALIGNED"


def test_deterministic_e1_normalizes_spelled_out_kindergarten():
    # The app sometimes renders grade_level as "Kindergarten" (display) rather
    # than canonical "K". A correct K lesson closing "Let's go be writers!" must
    # stay ALIGNED — not mis-band to 3-12 and demand "Now it's your turn!"
    # (a false MISALIGNED on E1, a non-negotiable, seen live during the run).
    env = _env(_lesson_dict(
        grade_level="Kindergarten",
        step_4_close="Wonderful work today. Let's go be writers!",
    ))
    v = judge.judge_claim(_E1_CLAIM, env, openai_client=_BoomOpenAI())
    assert v.status == "ALIGNED", v.rationale


def test_normalize_grade_maps_display_forms():
    n = judge._normalize_grade
    assert n("Kindergarten") == "K"
    assert n("kindergarten class") == "K"
    assert n("K") == "K"
    assert n("7") == "7"
    assert n("Grade 5") == "5"
    assert n("3-5") == "3-5"          # a band must not be mangled to "3"
    assert n("prekindergarten") == "PK"
    assert n(None) is None
    assert n("") is None


# ---------------------------------------------------------------------------
# deterministic — N1 details-not-reasons (needs grade + mode from parsed_query)
# ---------------------------------------------------------------------------


_N1_CLAIM = {"judge_method": "deterministic", "observable": "validate_details_not_reasons"}


def test_deterministic_n1_reasons_in_k1_persuasive_is_misaligned():
    env = _env(
        "Ask your writers to give three reasons why recess should be longer.",
        parsed_query={"query_type": "HOW_TO_TEACH", "grade_level": "1",
                      "writing_mode": "Persuade"},
    )
    v = judge.judge_claim(_N1_CLAIM, env, openai_client=_BoomOpenAI())
    assert v.status == "MISALIGNED"


def test_deterministic_n1_details_in_k1_persuasive_is_aligned():
    env = _env(
        "Ask your writers to give three details why recess should be longer.",
        parsed_query={"query_type": "HOW_TO_TEACH", "grade_level": "1",
                      "writing_mode": "Persuade"},
    )
    v = judge.judge_claim(_N1_CLAIM, env, openai_client=_BoomOpenAI())
    assert v.status == "ALIGNED"


def test_deterministic_inapplicable_validator_is_uncertain():
    # validate_step_3_phrases needs a lesson; a free-text response can't supply
    # one → the judge reports UNCERTAIN rather than a false ALIGNED.
    env = _env("Just some coaching prose, no lesson structure here.")
    claim = {"judge_method": "deterministic", "observable": "validate_step_3_phrases"}
    v = judge.judge_claim(claim, env, openai_client=_BoomOpenAI())
    assert v.status == "UNCERTAIN"


# ---------------------------------------------------------------------------
# hybrid — validator AND llm both pass; disagreement → UNCERTAIN
# ---------------------------------------------------------------------------


_STEP3_HYBRID = {"judge_method": "hybrid", "observable": "validate_step_3_phrases",
                 "rubric": "Step 3 must contain the four Smekens phrases AND a "
                           "real modeled teacher answer."}


def test_hybrid_validator_passes_but_llm_fails_is_uncertain():
    # _good_lesson() has all four Step-3 phrases (validator passes), but the
    # stubbed llm says the modeled answer is missing → disagreement → UNCERTAIN.
    env = _env(_lesson_dict())
    stub = _StubOpenAI(_misaligned_llm())
    v = judge.judge_claim(_STEP3_HYBRID, env, openai_client=stub)
    assert v.status == "UNCERTAIN"
    assert v.method == "hybrid"
    assert stub.calls, "llm leg should have been consulted"


def test_hybrid_validator_fails_is_misaligned_without_llm():
    # Validator fails outright → MISALIGNED; the llm must NOT be consulted.
    env = _env(_lesson_dict(step_3_interact="Students just practice quietly."))
    v = judge.judge_claim(_STEP3_HYBRID, env, openai_client=_BoomOpenAI())
    assert v.status == "MISALIGNED"
    assert v.method == "hybrid"


def test_hybrid_both_pass_is_aligned():
    env = _env(_lesson_dict())
    stub = _StubOpenAI(_aligned_llm())
    v = judge.judge_claim(_STEP3_HYBRID, env, openai_client=stub)
    assert v.status == "ALIGNED"
    assert v.method == "hybrid"


# ---------------------------------------------------------------------------
# llm-judge — gpt-4o @ temp 0, structured verdict passed through
# ---------------------------------------------------------------------------


_LLM_CLAIM = {"judge_method": "llm-judge", "rubric": "No listy Step 4.",
              "observable": "judge_v4.narrative_coherence"}


def test_llm_judge_passes_through_stubbed_verdict_and_uses_temp0_gpt4o():
    env = _env(_lesson_dict())
    stub = _StubOpenAI(_aligned_llm(conf=0.77))
    v = judge.judge_claim(_LLM_CLAIM, env, openai_client=stub)
    assert v.status == "ALIGNED"
    assert v.method == "llm-judge"
    assert v.confidence == 0.77
    # temperature 0 + gpt-4o + our structured schema
    assert stub.calls[0]["temperature"] == 0
    assert stub.calls[0]["model"] == "gpt-4o"
    assert stub.calls[0]["response_format"] is judge._LLMJudgment


# ---------------------------------------------------------------------------
# #56/#67 — a multi-turn probe's judgeable unit is the EXCHANGE, not the last
# message. Judging the final turn alone made a correct clarify-then-deliver
# flow read as an assumption: the u3 re-drive scored "Turn 1 asks the mode
# question / Turn 2 supplies it / app delivers the unit" MISALIGNED @0.95
# ("assumes a specific grade and writing mode and provides content") purely
# because the judge could not see that Turn 1 had asked. Re-judged with Turn 1
# visible: ALIGNED @0.9. Any rubric describing a FLOW is unjudgeable from the
# last turn alone, in BOTH directions.
# ---------------------------------------------------------------------------


def test_llm_judge_shows_prior_turns_to_the_model():
    env = _env(
        "Grade 3 | Persuasive\n\nFor 3rd grade persuasive writing, here are the priority skills:",
        prior_turns=[
            {"message": "I want to plan a writing unit for my class.",
             "response": "What grade level do you teach? Are you preparing for a "
                         "persuasive, informative, or narrative unit?"},
        ],
    )
    stub = _StubOpenAI(_aligned_llm())
    judge.judge_claim(_LLM_CLAIM, env, openai_client=stub)
    sent = stub.calls[0]["messages"][-1]["content"]
    # The earlier exchange must reach the model...
    assert "I want to plan a writing unit for my class." in sent
    assert "Are you preparing for a persuasive, informative, or narrative unit?" in sent
    # ...and the final turn must still be the thing under judgment.
    assert "For 3rd grade persuasive writing" in sent
    assert sent.index("I want to plan a writing unit") < sent.index("For 3rd grade persuasive")


def test_llm_judge_without_prior_turns_is_byte_identical():
    # BACK-COMPAT LOCK: single-turn probes are the overwhelming majority and
    # their prompt must not drift (the whole gold set is single-turn).
    env = _env("some response text")
    stub = _StubOpenAI(_aligned_llm())
    judge.judge_claim(_LLM_CLAIM, env, openai_client=stub)
    sent = stub.calls[0]["messages"][-1]["content"]
    assert sent == f"RUBRIC:\n{_LLM_CLAIM['rubric']}\n\nRESPONSE:\nsome response text"


# ---------------------------------------------------------------------------
# #31 — the judge CONFABULATES structure because the lesson is flattened with
# no field labels. A SCRIPTED_ML lesson reaches the LLM judge as bare adjacent
# blocks:
#     'Grade 5\n\n\n\nSnapple details\n\n5\n\nInform\n\n...'
# header, skill_focus, grade_level and writing_mode are indistinguishable, so
# the model reads "Grade 5" + "Inform" as a header "Grade 5 | Inform" — a string
# that exists nowhere. Real f7 rationales quote exactly that, at high confidence.
#
# It is worse than a cosmetic misquote: `writing_mode` is the LLM-invented field
# Brady's Fm4 decision deliberately KEEPS OUT of the teacher-facing header
# (grade-only when the teacher stated no mode). So the judge grades a header the
# teacher never sees, and papers over the rubric/Fm4 conflict by inventing one.
#
# The fix is a SEPARATE renderer: the deterministic validators need the
# teacher-visible PROSE (they check banned words / vocabulary IN it), while the
# judge needs a LABELLED view. One function cannot serve both — labelling the
# validators' text would feed field names into a banned-word scan.
# ---------------------------------------------------------------------------


def test_llm_judge_sees_the_teachers_view_not_stitchable_blocks():
    lesson = _lesson_dict()
    lesson.update(header="Grade 5", skill_focus="Snapple details",
                  grade_level="5", writing_mode="Inform")
    env = _env(lesson)
    stub = _StubOpenAI(_aligned_llm())
    judge.judge_claim(_LLM_CLAIM, env, openai_client=stub)
    sent = stub.calls[0]["messages"][-1]["content"]

    # Brady's OWN display labels reach the judge — the same ones the frontend
    # shows. fm2's rubric checks for exactly these and a value-join emitted 0/5,
    # making that rubric unpassable however correct the app was.
    assert "Step 1 — Introduce" in sent
    assert "Step 2A — Tell" in sent
    assert "Step 2B — Show" in sent

    # The stitchable blob is gone: f7's judge read 'Grade 5' + 'Inform' as one
    # header "Grade 5 | Inform" and quoted it as evidence. It never existed.
    assert "Grade 5\n\n\n\nSnapple details\n\n5\n\nInform" not in sent

    # And `writing_mode` no longer reaches the judge AT ALL — Fm4's decision is
    # that the LLM-authored mode is NOT teacher-facing (the header is grade-only
    # when the teacher stated no mode). A judge grading Brady-alignment must
    # grade what the teacher sees, so it cannot convict on a field they never do.
    assert "\nInform\n" not in sent
    assert "Grade 5" in sent          # the real, delivered header still arrives


def test_validators_still_see_unlabelled_teacher_prose():
    # THE LOCK THAT MAKES THE SPLIT SAFE. The deterministic legs scan the
    # teacher-visible text for banned words / vocabulary. Field labels must
    # NEVER leak into it — a label is not something the teacher can read, and
    # feeding "step_1_introduce:" into a banned-word scan is a new false-positive
    # class. _flatten_response stays exactly what it was.
    lesson = _lesson_dict()
    lesson.update(header="Grade 5", writing_mode="Inform")
    flat = judge._flatten_response(_env(lesson))
    for label in ("header:", "writing_mode:", "skill_focus:", "step_1_introduce:"):
        assert label not in flat, f"validator text must not contain the {label!r} label"
    assert "Grade 5" in flat  # the content itself still arrives


def test_free_text_response_prompt_is_byte_identical():
    # BACK-COMPAT: every non-SCRIPTED_ML handler returns a plain string, and the
    # whole gold set is free text. Those prompts must not drift at all, or the
    # calibration stops measuring what it measured.
    env = _env("some free-text coaching answer")
    stub = _StubOpenAI(_aligned_llm())
    judge.judge_claim(_LLM_CLAIM, env, openai_client=stub)
    sent = stub.calls[0]["messages"][-1]["content"]
    assert sent == f"RUBRIC:\n{_LLM_CLAIM['rubric']}\n\nRESPONSE:\nsome free-text coaching answer"


def test_prior_turns_never_enter_the_validated_text():
    # THE SAFETY TEST. Deterministic legs validate the TARGET turn's response.
    # If prior turns leaked into the flattened text, a banned word the teacher
    # or an earlier turn used would fail the turn actually under test — a whole
    # new false-MISALIGNED class. prior_turns is envelope metadata, never response.
    env = _env("clean final response",
               prior_turns=[{"message": "m", "response": "discuss discuss discuss"}])
    assert judge._flatten_response(env) == "clean final response"


def test_llm_judge_misaligned_passes_through():
    env = _env(_lesson_dict())
    stub = _StubOpenAI(_misaligned_llm())
    v = judge.judge_claim(_LLM_CLAIM, env, openai_client=stub)
    assert v.status == "MISALIGNED"


# ---------------------------------------------------------------------------
# launch-first — per query_type tier-vs-provenance
# ---------------------------------------------------------------------------


_LAUNCH_CLAIM = {"judge_method": "launch-first",
                 "observable": "source_tier+source_document"}


def _src(chunk_id, doc, tier):
    return {"chunk_id": chunk_id, "source_document": doc, "content_type": "lesson",
            "relevance_score": 0.5, "source_tier": tier}


def test_launch_first_plan_unit_pie_top_is_aligned_not_flagged():
    # PLAN_UNIT: the PIE doc is the CORRECT top source (Launch sits below).
    # A naive "top must be Launch" check would wrongly flag this.
    env = _env(
        _lesson_dict(),
        parsed_query={"query_type": "PLAN_UNIT"},
        sources=[
            _src("c1", "Essential Skills PIE.pdf", 0),
            _src("c2", "Launching the Writers Workshop 3-12.pdf", 1),
        ],
    )
    v = judge.judge_claim(_LAUNCH_CLAIM, env, openai_client=_BoomOpenAI())
    assert v.status == "ALIGNED"
    assert v.method == "launch-first"


def test_launch_first_skill_seeking_non_launch_top_is_misaligned():
    # HOW_TO_TEACH (skill-seeking): a non-Launch episode script sits at the top
    # tier while a Launch chunk is sunk below → Launch-first inversion.
    env = _env(
        _lesson_dict(),
        parsed_query={"query_type": "HOW_TO_TEACH"},
        sources=[
            _src("c1", "Ep 3 SEC Script.pdf", 0),
            _src("c2", "Launching the Writers Workshop 3-12.pdf", 1),
        ],
    )
    v = judge.judge_claim(_LAUNCH_CLAIM, env, openai_client=_BoomOpenAI())
    assert v.status == "MISALIGNED"


def test_launch_first_skill_seeking_launch_top_is_aligned():
    env = _env(
        _lesson_dict(),
        parsed_query={"query_type": "HOW_TO_TEACH"},
        sources=[
            _src("c1", "Launching the Writers Workshop 3-12.pdf", 0),
            _src("c2", "Ep 3 SEC Script.pdf", 3),
        ],
    )
    v = judge.judge_claim(_LAUNCH_CLAIM, env, openai_client=_BoomOpenAI())
    assert v.status == "ALIGNED"


def test_launch_first_management_launch_top_is_aligned():
    env = _env(
        "Here is how to run your writing workshop routine.",
        parsed_query={"query_type": "MANAGEMENT"},
        sources=[
            _src("c1", "Launching the Writers Workshop 3-12.pdf", 0),
            _src("c2", "Ep 11 K-12 Script.pdf", 1),
        ],
    )
    v = judge.judge_claim(_LAUNCH_CLAIM, env, openai_client=_BoomOpenAI())
    assert v.status == "ALIGNED"


def test_launch_first_no_source_tier_is_uncertain():
    # Without the /api/chat source_tier debug field, Launch-first is unobservable.
    env = _env(
        _lesson_dict(),
        parsed_query={"query_type": "HOW_TO_TEACH"},
        sources=[{"chunk_id": "c1", "source_document": "Ep 3 SEC Script.pdf"}],
    )
    v = judge.judge_claim(_LAUNCH_CLAIM, env, openai_client=_BoomOpenAI())
    assert v.status == "UNCERTAIN"


# ---------------------------------------------------------------------------
# Guards — non-verdict never scored; unknown method → UNCERTAIN; plain dict OK
# ---------------------------------------------------------------------------


def test_non_verdict_envelope_is_never_scored():
    env = drive.Envelope(raw={}, status="NON_VERDICT", http_status=503)
    v = judge.judge_claim(_BANNED_CLAIM, env, openai_client=_BoomOpenAI())
    assert v.status == "UNCERTAIN"


def test_unknown_judge_method_is_uncertain():
    env = _env("anything")
    v = judge.judge_claim({"judge_method": "bogus"}, env)
    assert v.status == "UNCERTAIN"


def test_judge_accepts_a_plain_dict_envelope():
    # The judge reads via .get(), so a plain dict works as well as an Envelope.
    v = judge.judge_claim(_BANNED_CLAIM, {"response": "please discuss this"},
                          openai_client=_BoomOpenAI())
    assert v.status == "MISALIGNED"
