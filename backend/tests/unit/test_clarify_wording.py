"""U3 — per-category open-question clarify phrasing (Brady 38:50).

Brady's rule: the first Copilot response to a category click / under-specified
request must be an OPEN QUESTION worded PER CATEGORY, never an assumed-specifics
answer:

  - SCRIPTED_ML (missing specifics) -> "What grade level do you teach? What
    writing skill are you working on?"
  - PLAN_UNIT                       -> "Are you preparing for a persuasive,
    informative, or narrative unit?" (+ the grade clause when also unstated)
  - MANAGEMENT                      -> "What area of management are you
    struggling with?"

A category Brady did NOT name keeps the existing generic per-field ask, and a
fully-specified request never reaches the clarify path at all. The wording is a
pure, deterministic function of (request_type + which required fields are still
missing) — so a field the teacher already stated is never re-asked (Brady's
B-S01 'don't re-ask' rule).
"""

import pytest

from api.models import ModelSet
from handlers import dispatch
from handlers.clarify import (
    GRADE_Q,
    MANAGEMENT_AREA_Q,
    PLAN_UNIT_MODE_Q,
    SCRIPTED_ML_SKILL_Q,
    UNKNOWN_SUBGROUP_ACRONYM_Q,
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


def _intent(rt: RequestType, **kw) -> TurnIntent:
    return TurnIntent(request_type=rt, **kw)


def _grade(value: str = "5") -> GradeSpec:
    return GradeSpec(value=value, stated_explicit=True)


def _mode(value: str = "Persuade") -> ModeSpec:
    return ModeSpec(value=value, stated_explicit=True)


def _models() -> ModelSet:
    return ModelSet("GEN", "QRY", "JDG")


# ---------------------------------------------------------------------------
# Pure function: request_type (+ still-missing fields) -> Brady wording
# ---------------------------------------------------------------------------


def test_scripted_ml_both_missing_asks_grade_and_skill() -> None:
    q = clarify_question(_intent(RequestType.SCRIPTED_ML,
                                 missing_required=["grade", "skill"]))
    assert q is not None
    assert GRADE_Q in q
    assert SCRIPTED_ML_SKILL_Q in q
    assert q == f"{GRADE_Q} {SCRIPTED_ML_SKILL_Q}"


def test_scripted_ml_grade_only_does_not_reask_skill() -> None:
    q = clarify_question(_intent(RequestType.SCRIPTED_ML,
                                 missing_required=["grade"]))
    assert q == GRADE_Q
    # 'don't re-ask a known field': skill was stated -> not asked.
    assert "writing skill" not in q.lower()


def test_scripted_ml_skill_only_asks_skill_only() -> None:
    # Grade is STATED here — that is what makes skill the ONLY gap, and what
    # Brady's 'don't re-ask a known field' rule is about. (The fixture used to
    # omit grade while asserting grade is not asked, which only held because QU
    # was trusted to report the gap; see test_scripted_ml_grade_is_derived...)
    q = clarify_question(_intent(RequestType.SCRIPTED_ML,
                                 grade=_grade("4"),
                                 missing_required=["skill"]))
    assert q == SCRIPTED_ML_SKILL_Q
    assert "grade level" not in q.lower()


def test_scripted_ml_grade_is_derived_when_qu_omits_it() -> None:
    # Brady's ML row asks for BOTH: "What grade level do you teach? What writing
    # skill are you working on?" — and it is his most-used category.
    #
    # Measured on production gpt-5.4-mini (campaign/recert/probe_u3_qu_mode.py
    # + the u3 re-drive): "Can you give me a scripted mini-lesson?" leaves
    # intent.grade None 5/5 while QU flags "grade" only 2/5 — so 3/5 of the time
    # the app asks the skill alone and drops half of Brady's question. Grade then
    # reaches scripted_ml_grade_band(None), which silently defaults to the 3-12
    # close for a grade nobody stated. Same root as the PLAN_UNIT half: a FACT
    # left to an LLM's discretion.
    #
    # NOTE "skill" is deliberately NOT derived — whether a skill can be
    # extracted or INHERITED from context is a genuine judgment (QU owns the
    # offered-skill pickup), so it stays with the LLM.
    intent = _intent(RequestType.SCRIPTED_ML, missing_required=["skill"])
    assert effective_missing_required(intent) == {"grade", "skill"}
    q = clarify_question(intent)
    assert q == f"{GRADE_Q} {SCRIPTED_ML_SKILL_Q}"


def test_scripted_ml_skill_is_never_derived() -> None:
    # A stated grade + a skill QU resolved (or inherited) must NOT be clarified:
    # deriving "skill" would re-ask a field the LLM legitimately resolved.
    intent = _intent(
        RequestType.SCRIPTED_ML,
        grade=_grade("4"),
        skill=SkillSpec(canonical="leads", as_stated="strong leads"),
        missing_required=[],
    )
    assert effective_missing_required(intent) == set()
    assert clarify_question(intent) is None


def test_how_to_teach_grade_is_derived_when_qu_omits_it() -> None:
    # THE BUG (live-confirmed): on the HOW_TO_TEACH path the app produced a full
    # OUTLINE without asking the grade first, while SCRIPTED_ML / PLAN_UNIT DO
    # ask. HOW_TO_TEACH is armed on grade (handlers/__init__.py _GRADE_REQUIRED),
    # but grade only entered `missing` via QU's unreliable "grade-sensitive
    # skill" judgment — the same coin flip the SCRIPTED_ML / PLAN_UNIT rows were
    # pulled off of (a FACT, intent.grade, must not ride an LLM's discretion).
    # So HOW_TO_TEACH belongs in _STRUCTURAL_PREREQS with ("grade",), exactly
    # like the other two grade-gated content categories.
    #
    # QU OMITTED grade (missing_required empty) and none was stated -> the fact
    # (grade is None) must put it in what we ask about.
    intent = _intent(RequestType.HOW_TO_TEACH, missing_required=[])
    assert "grade" in effective_missing_required(intent)

    # Control: a stated grade is NOT re-asked (the derive only adds when absent,
    # so Brady's 'don't re-ask a known field' rule still holds).
    stated = _intent(RequestType.HOW_TO_TEACH, grade=_grade("3"), missing_required=[])
    assert "grade" not in effective_missing_required(stated)


def test_plan_unit_missing_mode_asks_mode() -> None:
    # Grade is STATED here so mode is the only gap; a grade-less unit ask asks
    # for both (test_plan_unit_both_unstated_asks_grade_and_mode).
    q = clarify_question(_intent(RequestType.PLAN_UNIT,
                                 grade=_grade("5"),
                                 missing_required=["mode"]))
    assert q == PLAN_UNIT_MODE_Q
    assert "persuasive, informative, or narrative" in q


def test_management_asks_area() -> None:
    q = clarify_question(_intent(RequestType.MANAGEMENT,
                                 missing_required=["skill"]))
    assert q == MANAGEMENT_AREA_Q
    assert "What area of management" in q


def test_unnamed_category_returns_none() -> None:
    # HOW_TO_TEACH is a real category that gates on grade, but Brady named NO
    # per-category wording for it -> pure fn returns None so the caller keeps
    # its existing generic ask (do NOT invent wording).
    #
    # NB: this test USED to also assert that a PLAN_UNIT missing only grade is
    # "likewise un-worded by Brady" -> None. That assertion encoded the u3
    # defect: it is exactly the state QU reports 5/5 for a bare unit ask, and
    # returning None is what sent it to the generic grade-only ask Brady never
    # gets his mode question from. A PLAN_UNIT can no longer be missing "only"
    # grade — an unstated mode is now derived from the fact (see below).
    assert clarify_question(_intent(RequestType.HOW_TO_TEACH,
                                    missing_required=["grade"])) is None


# ---------------------------------------------------------------------------
# u3 — Brady's unit-planning category MUST get his writing-mode question.
#
# Brady's written table (feedback.docx p166-172, his BLUE = new-ask hand) gives
# one open question per category button, and row 2 is the unit row:
#   "What writing unit are you planning for?"
#     -> "Are you preparing for a persuasive, informative, or narrative unit?"
# and p166 scopes it to EACH category click, unconditionally. His video adds
# grade for this row (@12943: "Do you want a unit plan? Yes. Then I want it to
# ask me what grade level and persuasive, informative, or narrative. I want
# that."), so a unit ask stating neither must ask for both.
#
# WHY DERIVED, NOT TRUSTED FROM QU: whether the teacher stated a mode is a
# FACT (intent.mode), not a judgment. Measured on production gpt-5.4-mini
# (campaign/recert/probe_u3_qu_mode.py): for "plan a writing unit for my 5th
# graders" intent.mode was None 10/10 while QU's missing_required flagged
# "mode" only 5/10 — and the rate swung 4/5 -> 1/5 between two identical runs.
# handlers/plan_unit.py mandates the opening "For {grade} {mode} writing, ..."
# while feeding "Writing mode: (not specified)", so every unflagged turn ORDERS
# the model to name a mode nobody gave it. That invented "5th-grade persuasive"
# unit IS Brady's original complaint ("a question as opposed to an assumption
# of a very narrow group") — so the gate must not depend on a coin flip.
# ---------------------------------------------------------------------------


def test_plan_unit_mode_is_derived_when_qu_omits_it() -> None:
    # QU's dominant real output for "plan a writing unit for my 5th graders":
    # grade resolved, mode None, and missing_required EMPTY (4/5 measured).
    # The fact (mode is None) must win over QU's silence.
    intent = _intent(RequestType.PLAN_UNIT, grade=_grade("5"), missing_required=[])
    assert "mode" in effective_missing_required(intent)
    q = clarify_question(intent)
    assert q == PLAN_UNIT_MODE_Q
    # grade WAS stated -> Brady's 'don't re-ask a known field' rule holds.
    assert "grade level" not in q.lower()


def test_plan_unit_both_unstated_asks_grade_and_mode() -> None:
    # QU's real output for a bare "I want to plan a writing unit": grade-only,
    # 5/5. Brady wants both asked, so mode is derived and the two clauses are
    # composed exactly as the SCRIPTED_ML row already composes grade+skill.
    intent = _intent(RequestType.PLAN_UNIT, missing_required=["grade"])
    assert effective_missing_required(intent) == {"grade", "mode"}
    q = clarify_question(intent)
    assert q is not None
    assert GRADE_Q in q
    assert PLAN_UNIT_MODE_Q in q
    assert q == f"{GRADE_Q} {PLAN_UNIT_MODE_Q}"


def test_plan_unit_mode_all_is_not_a_concrete_mode() -> None:
    # ModeSpec allows "all" (mode-agnostic). A unit cannot be sequenced from it
    # and the mandated opening would render "For 5th all writing" — so "all" is
    # NOT an answer to Brady's persuasive/informative/narrative question.
    intent = _intent(RequestType.PLAN_UNIT, grade=_grade("5"), mode=_mode("all"))
    assert "mode" in effective_missing_required(intent)
    assert clarify_question(intent) == PLAN_UNIT_MODE_Q


def test_plan_unit_concrete_mode_and_grade_never_clarifies() -> None:
    # CONTROL: fully specified -> no gap, no question, straight to the handler.
    intent = _intent(RequestType.PLAN_UNIT, grade=_grade("5"), mode=_mode("Persuade"))
    assert effective_missing_required(intent) == set()
    assert clarify_question(intent) is None


def test_plan_unit_writing_level_still_supplants_grade() -> None:
    # SG2 REGRESSION LOCK (de2ef1e): a stated writing level removes the GRADE
    # requirement. Deriving PLAN_UNIT's prerequisites must not resurrect it —
    # the derive runs BEFORE the SG2 discard, so SG2 keeps the final say on
    # grade while mode (which a stage says nothing about) is still asked.
    intent = _intent(
        RequestType.PLAN_UNIT,
        subgroup="SPED",
        writing_level="picture",
        missing_required=["grade"],
    )
    assert effective_missing_required(intent) == {"mode"}


@pytest.mark.asyncio
async def test_dispatch_plan_unit_never_reaches_handler_without_a_mode() -> None:
    # THE STRUCTURAL LOCK — the one that actually protects Brady's rule.
    # client=None means any path reaching handle_plan_unit would blow up on the
    # LLM call, so a clean clarify PROVES the handler cannot run mode-less and
    # therefore cannot be ordered to invent one.
    outcome = await dispatch(
        _intent(RequestType.PLAN_UNIT, grade=_grade("5"), missing_required=[]),
        Conversation(session_id="s"),
        SessionHandshakes(),
        "5th grade",
        client=None,
        models=_models(),
        canonicalizer=None,
        retrieval_fn=None,
        library=None,
    )
    assert outcome.response_text == PLAN_UNIT_MODE_Q
    assert outcome.structured is None


# ---------------------------------------------------------------------------
# Wiring: real dispatch (NO LLM) delivers the per-category question
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_scripted_ml_missing_specifics_uses_brady_wording() -> None:
    outcome = await dispatch(
        _intent(RequestType.SCRIPTED_ML, missing_required=["grade", "skill"]),
        Conversation(session_id="s"),
        SessionHandshakes(),
        "give me a lesson",
        client=None,          # clarify path makes no LLM call
        models=_models(),
        canonicalizer=None,
        retrieval_fn=None,
        library=None,
    )
    assert GRADE_Q in outcome.response_text
    assert SCRIPTED_ML_SKILL_Q in outcome.response_text
    assert outcome.structured is None


@pytest.mark.asyncio
async def test_dispatch_plan_unit_missing_mode_clarifies() -> None:
    # A mode-less PLAN_UNIT reaches the clarify path and asks Brady's mode
    # question. (This test's comment used to claim "QU already emits
    # missing_required=['mode'] for it" — measured false: QU emits it on only
    # ~half of mode-less unit asks, and never when grade is also absent. The
    # gate no longer depends on QU volunteering it; grade is stated here so
    # mode is the only gap.)
    outcome = await dispatch(
        _intent(RequestType.PLAN_UNIT, grade=_grade("5"), missing_required=["mode"]),
        Conversation(session_id="s"),
        SessionHandshakes(),
        "what writing unit am I planning for?",
        client=None,
        models=_models(),
        canonicalizer=None,
        retrieval_fn=None,
        library=None,
    )
    assert outcome.response_text == PLAN_UNIT_MODE_Q
    assert outcome.structured is None


@pytest.mark.asyncio
async def test_dispatch_management_missing_required_uses_area_wording() -> None:
    # NEW gate: a MANAGEMENT turn QU flagged as under-specified asks Brady's
    # 'what area of management' question rather than guessing.
    outcome = await dispatch(
        _intent(RequestType.MANAGEMENT, missing_required=["skill"]),
        Conversation(session_id="s"),
        SessionHandshakes(),
        "help me with classroom management",
        client=None,
        models=_models(),
        canonicalizer=None,
        retrieval_fn=None,
        library=None,
    )
    assert outcome.response_text == MANAGEMENT_AREA_Q
    assert outcome.structured is None


@pytest.mark.asyncio
async def test_dispatch_unnamed_category_keeps_generic() -> None:
    # HOW_TO_TEACH missing grade still clarifies, but with the GENERIC per-field
    # ask (Brady named no HOW_TO_TEACH wording -> don't invent).
    outcome = await dispatch(
        _intent(RequestType.HOW_TO_TEACH, missing_required=["grade"]),
        Conversation(session_id="s"),
        SessionHandshakes(),
        "how do I teach leads?",
        client=None,
        models=_models(),
        canonicalizer=None,
        retrieval_fn=None,
        library=None,
    )
    text = outcome.response_text.lower()
    assert "grade" in text                       # it does ask for grade
    assert GRADE_Q not in outcome.response_text   # but NOT Brady's SCRIPTED_ML phrasing
    assert "what writing skill are you working on" not in text
    assert outcome.structured is None


@pytest.mark.asyncio
async def test_dispatch_fully_specified_scripted_ml_does_not_clarify(monkeypatch) -> None:
    # A request with everything stated must skip the clarify path entirely and
    # reach the real handler (stubbed here so no LLM is called).
    import handlers as handlers_pkg

    async def _fake(**kwargs):
        return TurnOutcome(
            response_text="LESSON",
            structured={"skill_focus": "topic sentences"},
            grounding=[],
            quality=Quality.VALID,
        )

    monkeypatch.setitem(handlers_pkg._HANDLERS, RequestType.SCRIPTED_ML, _fake)
    outcome = await dispatch(
        _intent(
            RequestType.SCRIPTED_ML,
            grade=GradeSpec(value="3", stated_explicit=True),
            skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
            missing_required=[],
        ),
        Conversation(session_id="s"),
        SessionHandshakes(),
        "grade 3 lesson on topic sentences",
        client=object(),
        models=_models(),
        canonicalizer=object(),
        retrieval_fn=None,
        library=None,
    )
    assert outcome.response_text == "LESSON"      # reached the handler, not clarify
    assert outcome.structured == {"skill_focus": "topic sentences"}


# ---------------------------------------------------------------------------
# SG1 — unrecognized subgroup acronym -> Brady's "what does it stand for?" Q
# ---------------------------------------------------------------------------


def test_unknown_subgroup_acronym_asks_brady_question() -> None:
    # Pure fn: when QU flags a subgroup-like acronym it does NOT recognize,
    # the clarify seam returns Brady's exact acronym question (not a generic
    # per-field ask), regardless of request_type.
    q = clarify_question(_intent(RequestType.COACHING,
                                 unknown_subgroup_acronym="TAG"))
    assert q == UNKNOWN_SUBGROUP_ACRONYM_Q
    assert "What does that acronym stand for" in q
    assert "different names/acronyms" in q


def test_unknown_acronym_takes_precedence_over_missing_grade_skill() -> None:
    # Even on a SCRIPTED_ML turn missing grade AND skill (which normally asks
    # Brady's grade+skill wording), an unrecognized subgroup acronym is the
    # higher-priority clarify — ask what the acronym means first.
    q = clarify_question(_intent(RequestType.SCRIPTED_ML,
                                 missing_required=["grade", "skill"],
                                 unknown_subgroup_acronym="XYZ"))
    assert q == UNKNOWN_SUBGROUP_ACRONYM_Q
    assert GRADE_Q not in q
    assert SCRIPTED_ML_SKILL_Q not in q


def test_no_acronym_leaves_clarify_wording_unchanged() -> None:
    # Back-compat: with no acronym flagged, the U3 wording is exactly as before
    # (the acronym check must not perturb the existing per-category path).
    q = clarify_question(_intent(RequestType.SCRIPTED_ML,
                                 missing_required=["grade", "skill"]))
    assert q == f"{GRADE_Q} {SCRIPTED_ML_SKILL_Q}"


@pytest.mark.asyncio
async def test_dispatch_unknown_subgroup_acronym_clarifies() -> None:
    # Wiring: a COACHING turn (normally NOT gated on grade/skill/mode, so it
    # would reach its handler) is diverted to the clarify path purely because
    # QU flagged an unrecognized subgroup acronym — and asks Brady's question.
    outcome = await dispatch(
        _intent(RequestType.COACHING, unknown_subgroup_acronym="TAG"),
        Conversation(session_id="s"),
        SessionHandshakes(),
        "how do I support my TAG students with leads?",
        client=None,          # clarify path makes no LLM call
        models=_models(),
        canonicalizer=None,
        retrieval_fn=None,
        library=None,
    )
    assert outcome.response_text == UNKNOWN_SUBGROUP_ACRONYM_Q
    assert outcome.structured is None


@pytest.mark.asyncio
async def test_dispatch_no_acronym_reaches_handler(monkeypatch) -> None:
    # Negative: a normal COACHING turn (no acronym, nothing missing) must NOT
    # be diverted to the acronym clarify — it reaches its real handler.
    import handlers as handlers_pkg

    async def _fake(**kwargs):
        return TurnOutcome(
            response_text="COACHING_ANSWER",
            structured=None,
            grounding=[],
            quality=Quality.VALID,
        )

    monkeypatch.setitem(handlers_pkg._HANDLERS, RequestType.COACHING, _fake)
    outcome = await dispatch(
        _intent(RequestType.COACHING),
        Conversation(session_id="s"),
        SessionHandshakes(),
        "how do I teach strong leads?",
        client=object(),
        models=_models(),
        canonicalizer=object(),
        retrieval_fn=None,
        library=None,
    )
    assert outcome.response_text == "COACHING_ANSWER"


# ---------------------------------------------------------------------------
# SG2 — recognized subgroup context, no writing level -> ask the WRITING LEVEL
# ---------------------------------------------------------------------------


def test_subgroup_without_writing_level_asks_writing_level() -> None:
    # Pure fn: a RECOGNIZED subgroup (SPED/MLL/EL/RTI) with NO writing level
    # stated returns Brady's writing-level question (for a subgroup, grade
    # doesn't matter — ask the developmental stage), regardless of request_type.
    q = clarify_question(_intent(RequestType.HOW_TO_TEACH, subgroup="SPED"))
    assert q == WRITING_LEVEL_Q
    assert "picture, label, word, or sentence" in q


def test_subgroup_with_writing_level_does_not_ask() -> None:
    # Level already stated -> no writing-level clarify (nothing to ask). A
    # HOW_TO_TEACH turn with the stage present falls through to no per-category Q.
    q = clarify_question(_intent(
        RequestType.HOW_TO_TEACH, subgroup="SPED", writing_level="word",
    ))
    assert q != WRITING_LEVEL_Q


def test_unknown_acronym_takes_precedence_over_writing_level() -> None:
    # SG1 acronym ask is higher priority than SG2: if BOTH an unrecognized
    # acronym and a subgroup are set with no level, ask what the acronym stands
    # for FIRST (you can't ask the writing level of a subgroup you can't name).
    q = clarify_question(_intent(
        RequestType.COACHING,
        unknown_subgroup_acronym="TAG",
        subgroup="SPED",
    ))
    assert q == UNKNOWN_SUBGROUP_ACRONYM_Q


def test_no_subgroup_no_writing_level_ask() -> None:
    # Back-compat: with no subgroup context the writing-level ask never fires.
    q = clarify_question(_intent(RequestType.COACHING))
    assert q != WRITING_LEVEL_Q


@pytest.mark.asyncio
async def test_dispatch_subgroup_without_level_asks_writing_level() -> None:
    # Wiring: a HOW_TO_TEACH turn is diverted to the clarify path purely because
    # a recognized subgroup is present with no writing level — and asks Brady's
    # writing-level question (ahead of any grade ask; grade doesn't matter here).
    outcome = await dispatch(
        _intent(RequestType.HOW_TO_TEACH, subgroup="SPED"),
        Conversation(session_id="s"),
        SessionHandshakes(),
        "how do I teach leads to my SPED students?",
        client=None,          # clarify path makes no LLM call
        models=_models(),
        canonicalizer=None,
        retrieval_fn=None,
        library=None,
    )
    assert outcome.response_text == WRITING_LEVEL_Q
    assert outcome.structured is None


@pytest.mark.asyncio
async def test_dispatch_subgroup_with_level_reaches_handler(monkeypatch) -> None:
    # Negative: subgroup + writing_level stated -> NOT diverted; reaches handler.
    import handlers as handlers_pkg

    async def _fake(**kwargs):
        return TurnOutcome(
            response_text="OUTLINE",
            structured=None,
            grounding=[],
            quality=Quality.VALID,
        )

    monkeypatch.setitem(handlers_pkg._HANDLERS, RequestType.HOW_TO_TEACH, _fake)
    outcome = await dispatch(
        _intent(
            RequestType.HOW_TO_TEACH,
            subgroup="SPED",
            writing_level="word",
            grade=GradeSpec(value="3", stated_explicit=True),
        ),
        Conversation(session_id="s"),
        SessionHandshakes(),
        "how do I teach leads to my SPED students at the word stage?",
        client=object(),
        models=_models(),
        canonicalizer=object(),
        retrieval_fn=None,
        library=None,
    )
    assert outcome.response_text == "OUTLINE"


@pytest.mark.asyncio
async def test_dispatch_coaching_subgroup_without_level_reaches_handler(monkeypatch) -> None:
    # SG2 is SCOPED to lesson/outline request_types: a plain COACHING turn with a
    # recognized subgroup but NO writing level must NOT be diverted to the
    # writing-level clarify — asking "what's their writing level?" in response to
    # an open coaching question ("what strategies work for my SPED students?") is
    # a non-sequitur. The turn reaches the coaching handler and gets answered.
    # Contrast test_dispatch_subgroup_without_level_asks_writing_level, where the
    # SAME subgroup/no-level on a HOW_TO_TEACH (lesson-shaped) turn DOES fire the
    # writing-level clarify — because there we're producing a lesson/outline for
    # the subgroup, and the developmental stage genuinely drives the content.
    import handlers as handlers_pkg

    async def _fake(**kwargs):
        return TurnOutcome(
            response_text="COACHING_ANSWER",
            structured=None,
            grounding=[],
            quality=Quality.VALID,
        )

    monkeypatch.setitem(handlers_pkg._HANDLERS, RequestType.COACHING, _fake)
    outcome = await dispatch(
        _intent(RequestType.COACHING, subgroup="SPED"),
        Conversation(session_id="s"),
        SessionHandshakes(),
        "what strategies work for my SPED students?",
        client=object(),
        models=_models(),
        canonicalizer=object(),
        retrieval_fn=None,
        library=None,
    )
    assert outcome.response_text == "COACHING_ANSWER"
