"""Prompt-shape tests for Stage 4 markdown handlers.

No LLM calls — verify each handler's prompt builder emits the rules
Brady requires and threads TurnIntent fields through correctly.
"""

from __future__ import annotations

from handlers._prompt_rules import (
    EARLY_WRITER_STAGE_PER_BULLET_RULE,
    EARLY_WRITER_STAGE_RULE,
)
from handlers.coaching import _build_prompt as build_coaching_prompt
from handlers.how_to_teach import _build_prompt as build_how_to_teach_prompt
from handlers.management import _build_prompt as build_management_prompt
from handlers.plan_unit import _build_prompt as build_plan_unit_prompt
from handlers.think_aloud import _build_prompt as build_think_aloud_prompt
from schemas import (
    Conversation,
    GradeSpec,
    ModeSpec,
    RequestType,
    Role,
    SkillSpec,
    TraitSpec,
    Turn,
    TurnIntent,
)


def _basic_intent(rt: RequestType = RequestType.HOW_TO_TEACH) -> TurnIntent:
    return TurnIntent(
        request_type=rt,
        grade=GradeSpec(value="3", stated_explicit=True),
        mode=ModeSpec(value="Inform", stated_explicit=True),
        trait=TraitSpec(value="Ideas", stated_explicit=False, confidence=0.8),
        skill=SkillSpec(
            canonical="topic sentences",
            as_stated="topic sentence and supporting details",
        ),
        required_triggers=["pizza-table"],
    )


# ----------------------------------------------------------------------
# HOW_TO_TEACH prompt
# ----------------------------------------------------------------------


def test_how_to_teach_prompt_requires_closing_phrase() -> None:
    prompt = build_how_to_teach_prompt(
        _basic_intent(RequestType.HOW_TO_TEACH),
        "", Conversation(session_id="s1"), None,
    )
    assert "Are you ready for a scripted mini-lesson on this skill?" in prompt


def test_how_to_teach_prompt_bans_scripted_4step_output() -> None:
    prompt = build_how_to_teach_prompt(
        _basic_intent(RequestType.HOW_TO_TEACH),
        "", Conversation(session_id="s1"), None,
    )
    assert "step_1_introduce" in prompt  # explicitly listed as NOT to produce


def test_how_to_teach_prompt_threads_skill_as_stated() -> None:
    prompt = build_how_to_teach_prompt(
        _basic_intent(RequestType.HOW_TO_TEACH),
        "", Conversation(session_id="s1"), None,
    )
    assert "topic sentence and supporting details" in prompt


def test_how_to_teach_prompt_orders_cache_prefix() -> None:
    conv = Conversation(session_id="s1")
    conv.append(Turn(index=0, role=Role.USER, text="earlier"))
    conv.append(Turn(index=1, role=Role.ASSISTANT, text="response"))
    prompt = build_how_to_teach_prompt(
        _basic_intent(RequestType.HOW_TO_TEACH),
        "chunk content", conv, "repair feedback",
    )
    assert (
        prompt.index("SESSION CONTEXT")
        < prompt.index("CONVERSATION")
        < prompt.index("RETRIEVED CONTEXT")
        < prompt.index("PREVIOUS ATTEMPT FAILED")
    )


# ----------------------------------------------------------------------
# COACHING prompt
# ----------------------------------------------------------------------


def test_coaching_prompt_requires_closing_phrase() -> None:
    prompt = build_coaching_prompt(
        _basic_intent(RequestType.COACHING),
        "", Conversation(session_id="s1"), None,
    )
    assert "Does this make sense? Is this helpful?" in prompt


def test_coaching_prompt_bans_forbidden_vocabulary() -> None:
    prompt = build_coaching_prompt(
        _basic_intent(RequestType.COACHING),
        "", Conversation(session_id="s1"), None,
    )
    for banned in ("discuss", "activity", "professional development"):
        assert banned in prompt


def test_coaching_prompt_refers_to_prior_flag_emits_note() -> None:
    intent = TurnIntent(
        request_type=RequestType.COACHING,
        skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
        refers_to_prior=True,
    )
    prompt = build_coaching_prompt(intent, "", Conversation(session_id="s1"), None)
    assert "following up on the prior" in prompt


def test_coaching_prompt_validates_frustration_before_guidance() -> None:
    # C1/C10 (Brady 52:50): when the teacher voices frustration, OPEN with a brief
    # validating sentence ("it's normal and hard") BEFORE the practical guidance.
    # This is now a SHARED rule (FRUSTRATION_VALIDATION_RULE) gated on the
    # deterministic expressed_frustration QU signal and spliced into every text
    # handler — so it fires wherever a frustrated turn routes, not only COACHING
    # (dogfood C10: it used to fire ~1/4, a routing lottery). Present only when
    # the flag is set; a calm coaching turn is untouched. Cross-handler coverage
    # lives in test_prompt_rules.py.
    frustrated = _basic_intent(RequestType.COACHING).model_copy(
        update={"expressed_frustration": True}
    )
    prompt = build_coaching_prompt(
        frustrated, "", Conversation(session_id="s1"), None,
    )
    assert "This is not unusual" in prompt
    assert "normal and hard" in prompt

    # Calm coaching turn (flag False, the default) — no validation instruction.
    calm = build_coaching_prompt(
        _basic_intent(RequestType.COACHING),
        "", Conversation(session_id="s1"), None,
    )
    assert "This is not unusual" not in calm


def test_coaching_prompt_asks_which_facets_before_narrowing() -> None:
    # C2 (Brady 1:02:00): on a "we taught it but they still can't" follow-up,
    # FIRST ask which facets students struggled with, THEN narrow the guidance.
    prompt = build_coaching_prompt(
        _basic_intent(RequestType.COACHING),
        "", Conversation(session_id="s1"), None,
    )
    assert "which facets they struggled with" in prompt
    assert "Skim the original lesson" in prompt


def test_coaching_prompt_steers_one_lesson_per_skill() -> None:
    # S4 (Brady 47:00): on a multi-skill question, steer back to the idea that
    # each priority skill is its own individual lesson (softer sibling of the
    # deterministic S3 one-skill guard).
    prompt = build_coaching_prompt(
        _basic_intent(RequestType.COACHING),
        "", Conversation(session_id="s1"), None,
    )
    assert "each priority skill is its own individual lesson" in prompt


def test_coaching_prompt_threads_writing_level_and_stage_rules() -> None:
    # C7 / Brady SG3 (58:40, doc 290): a leveled follow-up ("picture/label
    # stage") routes to COACHING, so COACHING must carry the SAME early-writer
    # rules as HOW_TO_TEACH — BOTH the shared SG2 stage core and the SG3
    # restate-per-bullet clause — AND surface the developmental stage in
    # SESSION CONTEXT. Mirror of how_to_teach, gated on writing_level.
    intent = TurnIntent(
        request_type=RequestType.COACHING,
        skill=SkillSpec(canonical="leads", as_stated="strong leads"),
        writing_level="label",
    )
    prompt = build_coaching_prompt(intent, "", Conversation(session_id="s1"), None)
    assert EARLY_WRITER_STAGE_RULE in prompt
    assert EARLY_WRITER_STAGE_PER_BULLET_RULE in prompt
    assert "Current writing level (developmental stage): label" in prompt


def test_coaching_prompt_no_writing_level_is_noop() -> None:
    # Back-compat: normal on-grade coaching (writing_level None) must be
    # UNCHANGED — neither early-writer rule nor the stage-context line. The
    # splice is gated on writing_level, so this stays a no-op off the leveled
    # path (mirror of test_no_writing_level_is_noop_in_how_to_teach_prompt).
    intent = TurnIntent(
        request_type=RequestType.COACHING,
        skill=SkillSpec(canonical="leads", as_stated="strong leads"),
    )
    prompt = build_coaching_prompt(intent, "", Conversation(session_id="s1"), None)
    assert EARLY_WRITER_STAGE_RULE not in prompt
    assert EARLY_WRITER_STAGE_PER_BULLET_RULE not in prompt
    assert "Current writing level" not in prompt


def test_coaching_prompt_threads_subgroup_context() -> None:
    # The subgroup line is gated on its OWN field (mirror of how_to_teach:148-149,
    # each SESSION CONTEXT line gated independently): when the teacher named a
    # recognized subgroup, surface it so the guidance is framed for that group.
    intent = TurnIntent(
        request_type=RequestType.COACHING,
        skill=SkillSpec(canonical="leads", as_stated="strong leads"),
        subgroup="SPED",
    )
    prompt = build_coaching_prompt(intent, "", Conversation(session_id="s1"), None)
    assert "Subgroup: SPED" in prompt


# ----------------------------------------------------------------------
# MANAGEMENT prompt
# ----------------------------------------------------------------------


def test_management_prompt_requires_closing_phrase() -> None:
    # Brady E3 (28:30, doc 128): the MANAGEMENT prompt instructs the overview
    # closer, NOT the generic "Does this make sense? Is this helpful?" closer.
    prompt = build_management_prompt(
        _basic_intent(RequestType.MANAGEMENT),
        "", Conversation(session_id="s1"), None,
    )
    assert (
        "This was an overview. Which ONE area or SINGLE routine would you like to start with?"
        in prompt
    )
    assert "Does this make sense? Is this helpful?" not in prompt


def test_management_prompt_says_chapters_1_to_7() -> None:
    prompt = build_management_prompt(
        _basic_intent(RequestType.MANAGEMENT),
        "", Conversation(session_id="s1"), None,
    )
    assert "chapters 1-7" in prompt


def test_management_prompt_forbids_ml_output() -> None:
    prompt = build_management_prompt(
        _basic_intent(RequestType.MANAGEMENT),
        "", Conversation(session_id="s1"), None,
    )
    # Must explicitly mark scripted/outline output as out of scope
    assert "SCRIPTED_ML" in prompt
    assert "HOW_TO_TEACH" in prompt


# ----------------------------------------------------------------------
# PLAN_UNIT prompt
# ----------------------------------------------------------------------


def test_plan_unit_prompt_requires_closing_phrase() -> None:
    prompt = build_plan_unit_prompt(
        _basic_intent(RequestType.PLAN_UNIT),
        "", Conversation(session_id="s1"), None,
    )
    # Brady x1 — his response-shapes table (docx para 33, RED "Good"; video
    # @5682): "'Plan a unit' gets list of priority skills. To be followed by
    # 'Is this helpful? Would you like a general outline of this unit?'".
    # The "which of these skills" wording Wave 2c put here is his HOW_TO_TEACH
    # refinement for multi-skill outlines (docx para 332 / image52.png).
    assert "Is this helpful? Would you like a general outline of this unit?" in prompt


def test_plan_unit_prompt_forbids_daily_calendar() -> None:
    prompt = build_plan_unit_prompt(
        _basic_intent(RequestType.PLAN_UNIT),
        "", Conversation(session_id="s1"), None,
    )
    # Must explicitly mark calendar output as out of scope
    assert "daily calendar" in prompt.lower()
    assert "day 1" in prompt.lower()


def test_plan_unit_prompt_threads_grade_and_mode() -> None:
    prompt = build_plan_unit_prompt(
        _basic_intent(RequestType.PLAN_UNIT),
        "", Conversation(session_id="s1"), None,
    )
    assert "Grade: 3" in prompt
    assert "Inform" in prompt


def test_plan_unit_prompt_handles_missing_grade_mode() -> None:
    intent = TurnIntent(request_type=RequestType.PLAN_UNIT)
    prompt = build_plan_unit_prompt(intent, "", Conversation(session_id="s1"), None)
    assert "(not specified)" in prompt


def test_plan_unit_prompt_steers_each_skill_is_its_own_lesson() -> None:
    # S4 (Brady 47:00, doc 191), verbatim: "Our response needs to always come
    # back to the idea that each priority skill is its own individual lesson."
    #
    # This test used to ALSO assert `"one lesson per skill" in prompt` — i.e. it
    # enforced the CONVERSE of Brady's rule, which contradicts his mini-lesson
    # series ("1 skill requires 2-4 days"). The direction is now locked by
    # test_prompts_never_invert_bradys_one_skill_rule.
    prompt = build_plan_unit_prompt(
        _basic_intent(RequestType.PLAN_UNIT),
        "", Conversation(session_id="s1"), None,
    )
    assert "each priority skill is its own individual lesson" in prompt


def test_plan_unit_prompt_affirms_presented_skill_order() -> None:
    # S5 (Brady D0143/T0449): when the teacher presents an ordered skill list,
    # recognize the skill ORDER IS correct — do NOT reshuffle it.
    prompt = build_plan_unit_prompt(
        _basic_intent(RequestType.PLAN_UNIT),
        "", Conversation(session_id="s1"), None,
    )
    assert "the skill order is correct" in prompt
    assert "reshuffle" in prompt.lower()


def test_plan_unit_prompt_stays_consistent_no_unit_drift() -> None:
    # E9 (Brady T0291/D0101): a follow-up stays consistent with the overview's
    # named skills and must NOT silently drift from skills to units.
    prompt = build_plan_unit_prompt(
        _basic_intent(RequestType.PLAN_UNIT),
        "", Conversation(session_id="s1"), None,
    )
    assert "consistent with the overview" in prompt
    assert "drift to units" in prompt.lower()


# ----------------------------------------------------------------------
# THINK_ALOUD prompt
# ----------------------------------------------------------------------


def test_think_aloud_prompt_requires_closing_phrase() -> None:
    prompt = build_think_aloud_prompt(
        _basic_intent(RequestType.THINK_ALOUD),
        "", Conversation(session_id="s1"), None,
    )
    assert "Want me to wrap this in a scripted mini-lesson?" in prompt


def test_think_aloud_prompt_demands_first_person_monologue() -> None:
    prompt = build_think_aloud_prompt(
        _basic_intent(RequestType.THINK_ALOUD),
        "", Conversation(session_id="s1"), None,
    )
    assert "first-person" in prompt.lower()
    assert "monologue" in prompt.lower()


def test_think_aloud_prompt_forbids_4step_structure() -> None:
    prompt = build_think_aloud_prompt(
        _basic_intent(RequestType.THINK_ALOUD),
        "", Conversation(session_id="s1"), None,
    )
    assert "SCRIPTED_ML" in prompt  # flagged as wrong target
    assert "HOW_TO_TEACH" in prompt


def test_think_aloud_prompt_bans_forbidden_vocabulary() -> None:
    prompt = build_think_aloud_prompt(
        _basic_intent(RequestType.THINK_ALOUD),
        "", Conversation(session_id="s1"), None,
    )
    for banned in ("discuss", "activity", "professional development"):
        assert banned in prompt


def test_prompts_never_invert_bradys_one_skill_rule() -> None:
    """S4 is EXCLUSIVITY (one SKILL per LESSON), never CARDINALITY (one LESSON
    per SKILL). We shipped the converse, and it contradicts Brady's #1 new ask.

    Brady, S4 (47:00, doc 191), verbatim: "Our response needs to always come
    back to the idea that each priority skill is its own individual lesson."
    And on what a lesson covers (transcript @29143): "mini-lessons are focused
    on one skill, one aspect, one ingredient of the writing... adding in the why
    would come in a second or future mini-lesson."

    Both say: a LESSON covers ONE SKILL. Neither says a SKILL gets ONE LESSON.

    The converse is not merely unsupported — it contradicts his mini-lesson
    SERIES ask (his #1 new build), transcript @32152: "we have this skill on
    determine the strongest side, and then on another day, determine the
    strongest side, and on another day... So I have three days for that same
    skill." And his definition (doc 434): "1 skill requires 2-4 days (most
    commonly 3)."

    plan_unit.py shipped "## One lesson per skill (always) ... one lesson per
    skill, taught one at a time" — telling teachers the opposite of the feature
    we are being asked to build. "one skill at a time" (the S3 guard) is the
    CORRECT direction and must keep working.
    """
    inverted = ("one lesson per skill", "taught one at a time")
    for build, rt in (
        (build_plan_unit_prompt, RequestType.PLAN_UNIT),
        (build_coaching_prompt, RequestType.COACHING),
    ):
        prompt = build(_basic_intent(rt), "", Conversation(session_id="s1"), None)
        lowered = prompt.lower()
        for phrase in inverted:
            assert phrase not in lowered, (
                f"{rt.value} prompt claims {phrase!r} — that is the CONVERSE of "
                f"Brady's rule and contradicts his 2-4-day mini-lesson series"
            )
        # The rule itself must survive, in his own words.
        assert "each priority skill is its own individual lesson" in prompt


def test_how_to_teach_prompt_steers_each_skill_is_its_own_lesson() -> None:
    """recert `s4-each-skill-own-lesson`: the rule was wired into PLAN_UNIT and
    COACHING but NOT how_to_teach — the one multi-skill-prone handler without it.

    Brady S4 (47:00, doc 191): "Our response needs to ALWAYS come back to the
    idea that each priority skill is its own individual lesson." The adjudication
    rests on a clean natural experiment: the two handlers WITH the rule passed
    15/15, and the single scenario that routes to this handler was the only
    failure ("how should I teach all three?" -> a taxonomy, never the
    lesson-boundary principle).

    _HOW_TO_TEACH_RULES:56-57 already tells the MODEL that each bullet "could
    become its own mini-lesson — NOT a step of ONE lesson", but that shapes the
    bullets; it never says the rule to the TEACHER. Brady asked for the response
    to come back to it.

    Fixing the PROMPT (not the route) is deliberate: DEEPEN_PRIOR
    (deepen_prior.py:244) and CORRECTION (correction.py:165) both delegate to
    handle_how_to_teach, so all three request types share this one prompt and
    are covered together.
    """
    prompt = build_how_to_teach_prompt(
        _basic_intent(RequestType.HOW_TO_TEACH),
        "", Conversation(session_id="s1"), None,
    )
    assert "each priority skill is its own individual lesson" in prompt
    # And it must not import the inversion we just removed from plan_unit.
    lowered = prompt.lower()
    assert "one lesson per skill" not in lowered
    assert "taught one at a time" not in lowered
