"""Brady SG2 / §F — a stated WRITING LEVEL supplants the grade requirement.

Brady (§F): "Not always a grade level. … Also need to follow with more than
GRADE LEVEL, but current writing level."

For a subgroup / early-writer ask, the operative signal is the student's
current developmental WRITING LEVEL (picture · label · word · sentence), not
the grade. Asking "What grade level do you teach?" when the teacher has
ALREADY supplied the stage is the exact frustration Brady flagged (task #64).

The RULE locked here (not the one probe string): a known ``writing_level``
answers the "how do I pitch this?" question that grade otherwise answers, so
grade stops being an INDEPENDENT hard requirement. It is keyed on QU's
structured ``writing_level`` signal — never on the literal words "SPED" or
"picture-drawing" — so ANY teacher phrasing QU resolves to a stage satisfies
it.

The gate has THREE places where a missing grade turns into a question to the
teacher, all consuming ``missing_required``. They therefore all consume
``effective_missing_required``, the single definition of the rule:

  1. dispatch's missing-required gate  — WHETHER to clarify
  2. clarify_question (U3 wording)     — WHAT to ask (SCRIPTED_ML composition)
  3. _clarify_missing's fallback loop  — the generic per-field ask

The ANTI-REGRESSION half is equally locked: with NO grade and NO stage, the
app must STILL ask for grade (the `grade-first-clarify` claim), and a subgroup
with NO stage must still ask the stage (SG2 itself).
"""

from __future__ import annotations

import pytest

from api.models import ModelSet
from handlers import dispatch
from handlers.clarify import (
    GRADE_Q,
    SCRIPTED_ML_SKILL_Q,
    WRITING_LEVEL_Q,
    clarify_question,
    effective_missing_required,
)
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


# Brady's four developmental stages, plus teacher-phrasings QU resolves to a
# stage. Parametrising over these locks the RULE rather than the one probe.
STAGES = ["picture", "label", "word", "sentence", "still drawing pictures"]

# The recognized subgroup families. The rule must not be keyed on any of them.
SUBGROUPS = ["SPED", "MLL", "EL", "RTI"]

# The request types that gate on grade (handlers/__init__.py _GRADE_REQUIRED).
GRADE_REQUIRED_TYPES = [
    RequestType.SCRIPTED_ML,
    RequestType.HOW_TO_TEACH,
    RequestType.PLAN_UNIT,
    RequestType.THINK_ALOUD,
]


def _intent(rt: RequestType, **kw) -> TurnIntent:
    kw.setdefault("skill", SkillSpec(canonical="leads", as_stated="strong leads"))
    # Default a mode for the same reason skill is defaulted: these tests isolate
    # the GRADE rule, and mode is PLAN_UNIT's other structural prerequisite
    # (u3 — handlers/clarify.py::_STRUCTURAL_PREREQS). Without it a PLAN_UNIT
    # case would clarify on the missing mode and mask what the test asserts
    # about grade. SG2 is a grade rule; it says nothing about mode.
    kw.setdefault("mode", ModeSpec(value="Persuade", stated_explicit=True))
    return TurnIntent(request_type=rt, **kw)


def _models() -> ModelSet:
    return ModelSet("GEN", "QRY", "JDG")


async def _dispatch(intent: TurnIntent, monkeypatch) -> tuple[TurnOutcome, bool]:
    """Run REAL dispatch with every handler stubbed. Returns (outcome,
    reached_handler) so a test can tell "clarified" from "generated" without
    an LLM call."""
    import handlers as handlers_pkg

    reached: dict[str, bool] = {"hit": False}

    async def _fake(**kwargs):
        reached["hit"] = True
        return TurnOutcome(
            response_text="LESSON", structured=None, grounding=[], quality=Quality.VALID
        )

    for rt in RequestType:
        monkeypatch.setitem(handlers_pkg._HANDLERS, rt, _fake)

    outcome = await dispatch(
        intent,
        Conversation(session_id="s"),
        SessionHandshakes(),
        "give me a lesson on strong leads",
        client=object(),
        models=_models(),
        canonicalizer=object(),
        retrieval_fn=None,
        library=None,
    )
    return outcome, reached["hit"]


# ---------------------------------------------------------------------------
# The rule, as a pure predicate — one definition, three consumers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stage", STAGES)
def test_effective_missing_drops_grade_when_subgroup_and_stage_known(stage: str) -> None:
    """A SUBGROUP context + known writing level removes 'grade' from what we ASK
    (Brady: for a subgroup, grade level doesn't matter — capture the stage)."""
    intent = _intent(
        RequestType.SCRIPTED_ML, missing_required=["grade"],
        subgroup="SPED", writing_level=stage,
    )
    assert effective_missing_required(intent) == set()


@pytest.mark.parametrize("stage", STAGES)
def test_effective_missing_keeps_grade_when_stage_but_no_subgroup(stage: str) -> None:
    """THE BUG (2026-07-19): a stage word with NO subgroup must NOT drop grade.
    QU pulls writing_level='label' out of the skill "LABELing ... picture" with no
    subgroup; the old rule spuriously dropped grade -> a gradeless SCRIPTED_ML shipped
    a model-inferred K-2 lesson with a defaulted 3-12 close. Brady's stage-supplants-
    grade rule is SUBGROUP-scoped."""
    intent = _intent(
        RequestType.SCRIPTED_ML, missing_required=["grade"], writing_level=stage
    )
    assert effective_missing_required(intent) == {"grade"}


def test_effective_missing_keeps_grade_when_no_stage() -> None:
    """ANTI-REGRESSION (grade-first-clarify): no stage -> grade still required."""
    intent = _intent(RequestType.SCRIPTED_ML, missing_required=["grade"])
    assert effective_missing_required(intent) == {"grade"}


@pytest.mark.parametrize("band", ["K-2", "3-5", "6-8", "9-12"])
def test_band_grade_present_is_never_missing(band: str) -> None:
    """THE BUG (2026-07-19): the teacher answered "What grade level do you teach?"
    with the BAND "K-2" and got the SAME question again. QU is told to flag a band
    as still needing a specific grade and seeds 'grade' into missing_required; the
    derive only ever ADDS, so that flag reached the dispatch gate and re-asked.
    A canonical band IS a first-class grade here (the GradeValue Literal, the
    "Grade K-2" header, the K-2 non-negotiable close) and no Brady primary asks a
    band to be disambiguated. Grade PRESENT is never missing.

    Kills: a gate that re-asks whenever QU flags grade, ignoring a stated band."""
    intent = _intent(
        RequestType.SCRIPTED_ML,
        missing_required=["grade"],
        grade=GradeSpec(value=band, stated_explicit=True),
    )
    assert effective_missing_required(intent) == set()


def test_specific_grade_present_is_never_missing() -> None:
    """Same rule for a specific grade — a stated grade is never 'missing' even if
    QU flagged it. Kills a fix that special-cased only bands."""
    intent = _intent(
        RequestType.SCRIPTED_ML,
        missing_required=["grade"],
        grade=GradeSpec(value="2", stated_explicit=True),
    )
    assert effective_missing_required(intent) == set()


def test_effective_missing_never_drops_other_fields() -> None:
    """The rule is scoped to GRADE. A known stage says nothing about which
    skill or mode the teacher wants — those asks must survive. (Subgroup context
    present so the grade-drop actually fires under the corrected rule.)"""
    intent = _intent(
        RequestType.SCRIPTED_ML,
        missing_required=["grade", "skill", "mode"],
        subgroup="SPED",
        writing_level="picture",
    )
    assert effective_missing_required(intent) == {"skill", "mode"}


def test_effective_missing_does_not_mutate_intent() -> None:
    """The gate owns the POLICY; QU's observation ('grade was not stated')
    stays honest for logging / correction-merge downstream."""
    intent = _intent(
        RequestType.SCRIPTED_ML, missing_required=["grade"], writing_level="picture"
    )
    effective_missing_required(intent)
    assert intent.missing_required == ["grade"]


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_stage_is_not_a_stage(blank: str) -> None:
    """A blank/whitespace writing_level is NOT a stage — grade stays required.
    Guards against an empty-string signal silently disabling the grade ask."""
    intent = _intent(
        RequestType.SCRIPTED_ML, missing_required=["grade"], writing_level=blank
    )
    assert effective_missing_required(intent) == {"grade"}


# ---------------------------------------------------------------------------
# Seam 1 — dispatch's missing-required gate (WHETHER to clarify)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", STAGES)
@pytest.mark.parametrize("subgroup", SUBGROUPS)
async def test_subgroup_plus_stage_does_not_ask_grade(stage, subgroup, monkeypatch):
    """THE DEFECT: subgroup + stage stated together, grade unstated. The app
    must build the lesson, NOT reply "What grade level do you teach?".

    Parametrised over every stage x subgroup so the fix can never be a
    special-case for "SPED" / "picture-drawing".
    """
    outcome, reached = await _dispatch(
        _intent(
            RequestType.SCRIPTED_ML,
            missing_required=["grade"],
            subgroup=subgroup,
            writing_level=stage,
        ),
        monkeypatch,
    )
    assert reached, "must reach the handler, not the clarify path"
    assert "grade level" not in (outcome.response_text or "").lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", STAGES)
async def test_early_writer_stage_without_subgroup_DOES_ask_grade(
    stage, monkeypatch
):
    """CORRECTED (2026-07-19): the stage-supplants-grade rule is SUBGROUP-scoped.
    A stage with NO subgroup — e.g. QU echoing 'label' out of the skill name
    "labeling multiple details in one picture" — must STILL ask the grade. Grade
    is Brady's SCRIPTED_ML prerequisite; inferring the band from a bare stage word
    shipped a wrong-band lesson (K-2 content, 3-12 close). This is the live bug the
    teacher hit; the dispatch must now reach the CLARIFY path, not the handler.
    """
    outcome, reached = await _dispatch(
        _intent(
            RequestType.SCRIPTED_ML, missing_required=["grade"], writing_level=stage
        ),
        monkeypatch,
    )
    assert not reached, "must ask grade (clarify), not reach the handler"
    assert "grade level" in (outcome.response_text or "").lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("rt", GRADE_REQUIRED_TYPES)
async def test_stage_supplants_grade_for_every_grade_required_type(rt, monkeypatch):
    """The gate is one rule across every grade-gated request type — not a
    SCRIPTED_ML special case."""
    outcome, reached = await _dispatch(
        _intent(rt, missing_required=["grade"], subgroup="SPED",
                writing_level="picture"),
        monkeypatch,
    )
    assert reached, f"{rt} must reach its handler when the stage is known"


# ---------------------------------------------------------------------------
# ANTI-REGRESSION — `grade-first-clarify` (adjudicated ALIGNED @0.93)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("rt", GRADE_REQUIRED_TYPES)
async def test_no_grade_no_stage_still_asks_grade(rt, monkeypatch):
    """THE OTHER DIRECTION: a plain lesson ask with NO grade and NO stage must
    STILL ask for grade. This is the half the fix must not trade away."""
    outcome, reached = await _dispatch(
        _intent(rt, missing_required=["grade"]), monkeypatch
    )
    assert not reached, "must clarify, not generate"
    assert "grade" in (outcome.response_text or "").lower()
    assert outcome.structured is None


@pytest.mark.asyncio
async def test_how_to_teach_no_grade_clarifies_even_when_qu_omits_grade(monkeypatch):
    """THE HOW_TO_TEACH DEFECT (live-confirmed): the app produced a full OUTLINE
    without asking the grade first.

    Distinct from test_no_grade_no_stage_still_asks_grade above: THERE QU flags
    the gap (missing_required=['grade']); HERE QU OMITS it (missing_required=[])
    — the common live case, since QU only flags HOW_TO_TEACH's grade via an
    unreliable 'grade-sensitive skill' judgment. The armed HOW_TO_TEACH gate
    then never fires and a grade-less outline ships. Grade must be DERIVED from
    the fact (intent.grade is None), like the other grade-gated categories, so
    the gate fires and the teacher is asked instead.
    """
    outcome, reached = await _dispatch(
        _intent(RequestType.HOW_TO_TEACH, missing_required=[]), monkeypatch
    )
    assert not reached, "must clarify (ask grade), not generate a grade-less outline"
    assert "grade" in (outcome.response_text or "").lower()
    assert outcome.structured is None


@pytest.mark.asyncio
@pytest.mark.parametrize("subgroup", SUBGROUPS)
async def test_subgroup_without_stage_asks_writing_level_not_grade(
    subgroup, monkeypatch
):
    """SG2 itself must survive: a subgroup with NO stage stated still asks the
    WRITING LEVEL (and must not fall back to the grade question)."""
    outcome, reached = await _dispatch(
        _intent(RequestType.SCRIPTED_ML, missing_required=["grade"],
                subgroup=subgroup),
        monkeypatch,
    )
    assert not reached
    assert outcome.response_text == WRITING_LEVEL_Q


# ---------------------------------------------------------------------------
# Seam 1b — U3 wording composition (WHAT to ask)
# ---------------------------------------------------------------------------


def test_u3_wording_omits_grade_question_when_stage_known() -> None:
    """A SCRIPTED_ML turn missing grade AND skill, with the stage known, still
    reaches the clarify path (skill is genuinely missing) — but the composed
    question must ask ONLY the skill. Without this, Brady's banned grade
    question leaks through the skill door.
    """
    q = clarify_question(
        _intent(
            RequestType.SCRIPTED_ML,
            missing_required=["grade", "skill"],
            subgroup="SPED",
            writing_level="picture",
        )
    )
    assert q == SCRIPTED_ML_SKILL_Q
    assert "grade level" not in (q or "").lower()


def test_u3_wording_still_asks_both_when_no_stage() -> None:
    """ANTI-REGRESSION: no stage -> Brady's full B-S01 example is unchanged."""
    q = clarify_question(
        _intent(RequestType.SCRIPTED_ML, missing_required=["grade", "skill"])
    )
    assert q == f"{GRADE_Q} {SCRIPTED_ML_SKILL_Q}"


def test_u3_wording_returns_none_when_subgroup_stage_clears_the_only_gap() -> None:
    """SUBGROUP + stage known and grade the ONLY missing field -> nothing left to
    ask, so the pure lookup reports 'no question'. (SG2: for a subgroup the stage
    supplants grade.)"""
    q = clarify_question(
        _intent(
            RequestType.SCRIPTED_ML, missing_required=["grade"],
            subgroup="SPED", writing_level="picture"
        )
    )
    assert q is None


def test_u3_wording_asks_grade_when_stage_but_no_subgroup() -> None:
    """CORRECTED (2026-07-19): a stage with NO subgroup does NOT clear grade, so
    the wording seam still asks Brady's grade question (the live bug's wording side)."""
    q = clarify_question(
        _intent(
            RequestType.SCRIPTED_ML, missing_required=["grade"],
            writing_level="picture"
        )
    )
    assert q == GRADE_Q


# ---------------------------------------------------------------------------
# Seam 1c — the generic per-field fallback loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generic_fallback_does_not_ask_grade_when_stage_known(monkeypatch):
    """THINK_ALOUD has no Brady per-category wording, so it falls to the generic
    per-field loop. That loop reads missing_required directly — it must honour
    the same rule or the banned grade ask leaks out of a third door.
    """
    outcome, reached = await _dispatch(
        _intent(
            RequestType.THINK_ALOUD,
            missing_required=["grade", "skill"],
            subgroup="SPED",
            writing_level="picture",
        ),
        monkeypatch,
    )
    assert not reached, "skill is genuinely missing -> still clarifies"
    text = (outcome.response_text or "").lower()
    assert "grade" not in text, "the stage is known -> never ask the grade"
    assert "writing skill" in text
