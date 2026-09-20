"""Tests for the shared GLOBAL_VOCAB_RULES prompt fragment (Brady N1/N2).

There is no shared prompt scaffolding elsewhere in handlers/ — every
builder hand-duplicates its own rules constant. GLOBAL_VOCAB_RULES is
the first cross-builder fragment: the two vocabulary non-negotiables
(N1 "details not reasons", N2 "story only for narrative") that apply
to every request_type regardless of output shape. These tests confirm
the constant carries the required nuance and that it is spliced into
all six prompt builders, so the rule can't silently drift out of one
handler while staying in the others.
"""

from __future__ import annotations

from handlers import (
    _prompt_rules,
    coaching,
    how_to_teach,
    management,
    plan_unit,
    scripted_ml_prompt,
    think_aloud,
)
from handlers._prompt_rules import (
    FRUSTRATION_VALIDATION_RULE,
    GLOBAL_VOCAB_RULES,
    LIST_FORMAT_RULE,
    MANAGEMENT_CLOSING_QUESTION_RULE,
    SINGLE_CLOSING_QUESTION_RULE,
)
from schemas import (
    Conversation,
    GradeSpec,
    ModeSpec,
    RequestType,
    SkillSpec,
    TraitSpec,
    TurnIntent,
)

_BUILDER_MODULES = (
    scripted_ml_prompt,
    coaching,
    how_to_teach,
    management,
    plan_unit,
    think_aloud,
)


def _basic_intent(rt: RequestType) -> TurnIntent:
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


def _all_six_prompts() -> list[str]:
    """Build one real prompt from each of the 6 builders with a minimal
    stub TurnIntent, mirroring the construction pattern in
    test_scripted_ml_prompt.py and test_handlers_stage4_prompts.py."""
    conv = Conversation(session_id="s1")
    return [
        scripted_ml_prompt.build_scripted_ml_prompt(
            intent=_basic_intent(RequestType.SCRIPTED_ML),
            retrieved_context="",
            conversation=conv,
        ),
        coaching._build_prompt(
            _basic_intent(RequestType.COACHING), "", conv, None
        ),
        how_to_teach._build_prompt(
            _basic_intent(RequestType.HOW_TO_TEACH), "", conv, None
        ),
        management._build_prompt(
            _basic_intent(RequestType.MANAGEMENT), "", conv, None
        ),
        plan_unit._build_prompt(
            _basic_intent(RequestType.PLAN_UNIT), "", conv, None
        ),
        think_aloud._build_prompt(
            _basic_intent(RequestType.THINK_ALOUD), "", conv, None
        ),
    ]


def test_rules_mention_details_and_story() -> None:
    assert "details" in GLOBAL_VOCAB_RULES.lower()
    assert "reasons" in GLOBAL_VOCAB_RULES.lower()
    assert "story" in GLOBAL_VOCAB_RULES.lower()
    assert "narrative" in GLOBAL_VOCAB_RULES.lower()


def test_rules_mention_pronoun_agreement() -> None:
    assert "singular/plural pronoun" in GLOBAL_VOCAB_RULES.lower()
    assert "demonstrative" in GLOBAL_VOCAB_RULES.lower()
    assert "these" in GLOBAL_VOCAB_RULES.lower()
    assert "this" in GLOBAL_VOCAB_RULES.lower()


def test_global_rules_spliced_into_every_builder() -> None:
    for prompt in _all_six_prompts():
        assert GLOBAL_VOCAB_RULES.strip() in prompt


def test_each_builder_module_imports_the_shared_constant() -> None:
    """Fallback-style guard (per task brief): every builder module must
    import the *same* GLOBAL_VOCAB_RULES object, not a re-declared copy,
    so a future edit to the constant can't silently fork per-handler."""
    for mod in _BUILDER_MODULES:
        assert mod.GLOBAL_VOCAB_RULES is GLOBAL_VOCAB_RULES


# ---------------------------------------------------------------------------
# Brady E4: SINGLE_CLOSING_QUESTION_RULE — the "end with ONE closing
# question" instruction. Originally shared by the coaching + management
# builders. Brady E3 (28:30, doc 128) splits MANAGEMENT off onto its own
# overview closer (MANAGEMENT_CLOSING_QUESTION_RULE, "This was an overview.
# Which ONE area or SINGLE routine would you like to start with?"), so the
# shared generic rule is now spliced into COACHING only. Both are extracted
# to _prompt_rules so the wording can't fork; mirrors GLOBAL_VOCAB_RULES.
# ---------------------------------------------------------------------------


def test_closing_question_rule_carries_offer_and_generic_fallback() -> None:
    r = SINGLE_CLOSING_QUESTION_RULE
    assert "never two" in r.lower()          # the anti-double-question nut
    assert "Want me to" in r                 # the offer exemplar
    assert "Does this make sense? Is this helpful?" in r  # the generic fallback


def test_single_closing_question_rule_spliced_into_coaching_only() -> None:
    # Brady E3: MANAGEMENT no longer uses the shared generic closer, so the
    # SINGLE_CLOSING_QUESTION_RULE is spliced into COACHING and NOT MANAGEMENT.
    conv = Conversation(session_id="s1")
    coaching_prompt = coaching._build_prompt(
        _basic_intent(RequestType.COACHING), "", conv, None
    )
    management_prompt = management._build_prompt(
        _basic_intent(RequestType.MANAGEMENT), "", conv, None
    )
    assert SINGLE_CLOSING_QUESTION_RULE.strip() in coaching_prompt
    assert SINGLE_CLOSING_QUESTION_RULE.strip() not in management_prompt


def test_management_closing_question_rule_carries_e3_overview_closer() -> None:
    r = MANAGEMENT_CLOSING_QUESTION_RULE
    assert (
        "Which ONE area or SINGLE routine would you like to start with?" in r
    )  # the verbatim E3 closer
    # It replaces (does NOT re-instruct) the generic coaching closer.
    assert "Does this make sense? Is this helpful?" not in r


def test_management_prompt_uses_e3_overview_closer() -> None:
    # Brady E3 (28:30, doc 128): the MANAGEMENT prompt instructs the overview
    # closer verbatim and NO LONGER the generic "Does this make sense? Is this
    # helpful?" closer.
    conv = Conversation(session_id="s1")
    management_prompt = management._build_prompt(
        _basic_intent(RequestType.MANAGEMENT), "", conv, None
    )
    assert MANAGEMENT_CLOSING_QUESTION_RULE.strip() in management_prompt
    assert (
        "Which ONE area or SINGLE routine would you like to start with?"
        in management_prompt
    )
    assert "Does this make sense? Is this helpful?" not in management_prompt


def test_closing_question_rules_are_the_shared_objects() -> None:
    """Each builder must reference the *same* rule object, not a re-declared
    copy — otherwise the wording could silently fork. Coaching uses the shared
    generic closer; management uses the shared E3 overview closer (Brady E3)."""
    assert coaching.SINGLE_CLOSING_QUESTION_RULE is SINGLE_CLOSING_QUESTION_RULE
    assert (
        management.MANAGEMENT_CLOSING_QUESTION_RULE
        is MANAGEMENT_CLOSING_QUESTION_RULE
    )


# ---------------------------------------------------------------------------
# Brady Fm1: LIST_FORMAT_RULE — the "numbers only for sequences, bullets
# for options" instruction, shared by the how_to_teach/coaching/management
# builders only (not all six). Extracted from inline copies so the
# wording can't fork between handlers; mirrors the GLOBAL_VOCAB_RULES pattern.
# ---------------------------------------------------------------------------


def test_list_format_rule_mentions_numbers_bullets_and_sequence() -> None:
    r = LIST_FORMAT_RULE.lower()
    assert "number" in r
    assert "bullet" in r
    assert "sequence" in r


def test_list_format_rule_spliced_into_list_bearing_builders() -> None:
    conv = Conversation(session_id="s1")
    prompts = [
        how_to_teach._build_prompt(_basic_intent(RequestType.HOW_TO_TEACH), "", conv, None),
        coaching._build_prompt(_basic_intent(RequestType.COACHING), "", conv, None),
        management._build_prompt(_basic_intent(RequestType.MANAGEMENT), "", conv, None),
    ]
    for prompt in prompts:
        assert LIST_FORMAT_RULE.strip() in prompt


def test_how_to_teach_prompt_uses_bulleted_not_numbered() -> None:
    conv = Conversation(session_id="s1")
    p = how_to_teach._build_prompt(_basic_intent(RequestType.HOW_TO_TEACH), "", conv, None)
    assert "BULLETED LIST of 3-5" in p
    assert "NUMBERED LIST of 3-5" not in p


# ---------------------------------------------------------------------------
# Brady S5: SKILL_ORDER_AFFIRM_RULE — "recognize that the skill order is
# correct". When a teacher presents their own scope-and-sequence / ordered
# skill list, affirm the order rather than reshuffling it. An explicit unit-
# plan request routes to PLAN_UNIT, but the "does my order work?" message
# routes to COACHING (dogfood C5), so the rule is shared by BOTH builders.
# Extracted to _prompt_rules so the wording can't fork between them; mirrors
# the GLOBAL_VOCAB_RULES / SINGLE_CLOSING_QUESTION_RULE pattern.
# ---------------------------------------------------------------------------


def test_skill_order_affirm_rule_carries_affirm_and_no_reshuffle() -> None:
    r = _prompt_rules.SKILL_ORDER_AFFIRM_RULE
    assert "the skill order is correct" in r    # the affirm nut
    assert "reshuffle" in r.lower()             # the anti-reshuffle prohibition


def test_skill_order_affirm_rule_spliced_into_coaching_and_plan_unit() -> None:
    # (a) COACHING is the FIX: the "does my order work?" message routes here and
    #     its rules previously lacked S5, so the app reshuffled the teacher's
    #     order (dogfood C5). (b) PLAN_UNIT is BEHAVIOUR-PRESERVING: the rule
    #     moved OUT of _PLAN_UNIT_RULES into the shared constant and the prompt
    #     must still carry the identical instruction.
    conv = Conversation(session_id="s1")
    coaching_prompt = coaching._build_prompt(
        _basic_intent(RequestType.COACHING), "", conv, None
    )
    plan_unit_prompt = plan_unit._build_prompt(
        _basic_intent(RequestType.PLAN_UNIT), "", conv, None
    )
    for prompt in (coaching_prompt, plan_unit_prompt):
        # behavioural assertions first, so a RED failure names the real gap
        assert "the skill order is correct" in prompt
        assert "reshuffle" in prompt.lower()
        assert _prompt_rules.SKILL_ORDER_AFFIRM_RULE.strip() in prompt


def test_skill_order_affirm_rule_is_the_shared_object() -> None:
    # Defined once, imported by both — not duplicated as a literal, so a future
    # edit to the wording can't silently fork per-handler (mirrors
    # test_closing_question_rules_are_the_shared_objects).
    assert (
        coaching.SKILL_ORDER_AFFIRM_RULE
        is _prompt_rules.SKILL_ORDER_AFFIRM_RULE
    )
    assert (
        plan_unit.SKILL_ORDER_AFFIRM_RULE
        is _prompt_rules.SKILL_ORDER_AFFIRM_RULE
    )


def test_skill_order_affirm_rule_scoped_to_coaching_and_plan_unit() -> None:
    # The rule is spliced into COACHING + PLAN_UNIT only. The other _build_prompt
    # builders must NOT carry it (mirrors the SINGLE_CLOSING_QUESTION scoping
    # test) — a bound against a future accidental over-splice.
    conv = Conversation(session_id="s1")
    for mod, rt in (
        (how_to_teach, RequestType.HOW_TO_TEACH),
        (management, RequestType.MANAGEMENT),
        (think_aloud, RequestType.THINK_ALOUD),
    ):
        prompt = mod._build_prompt(_basic_intent(rt), "", conv, None)
        assert "## The teacher's skill order is correct" not in prompt


# ---------------------------------------------------------------------------
# Brady C10: FRUSTRATION_VALIDATION_RULE — "validate the emotion FIRST, THEN
# the practical guidance". This instruction lived ONLY in COACHING's bespoke
# rules, so it fired only when a frustrated opener happened to route to COACHING
# — a frustrated "how do I teach X?" routes to HOW_TO_TEACH and got no
# validation (dogfood C10: validation fired ~1/4, a routing lottery). Promoted
# to a shared rule spliced into ALL FIVE text handlers, gated on the
# deterministic expressed_frustration QU signal (orthogonal to request_type) so
# the emotion is validated no matter which handler the turn lands in. Mirrors
# the EARLY_WRITER_STAGE_RULE gated splice; the validating sentence itself stays
# LLM-authored.
# ---------------------------------------------------------------------------

_FRUSTRATION_TEXT_MODULES = (coaching, how_to_teach, management, plan_unit, think_aloud)


def _five_text_prompts(*, frustrated: bool) -> list[str]:
    """One prompt from each of the 5 TEXT handlers. SCRIPTED_ML is a structured
    4-step lesson (JSON fields), not a prose handler, so it is excluded — the
    same scope as the validation splice. When frustrated=True, the intent
    carries expressed_frustration=True; otherwise it is the default (False)."""
    conv = Conversation(session_id="s1")

    def mk(rt: RequestType) -> TurnIntent:
        it = _basic_intent(rt)
        return it.model_copy(update={"expressed_frustration": True}) if frustrated else it

    return [
        coaching._build_prompt(mk(RequestType.COACHING), "", conv, None),
        how_to_teach._build_prompt(mk(RequestType.HOW_TO_TEACH), "", conv, None),
        management._build_prompt(mk(RequestType.MANAGEMENT), "", conv, None),
        plan_unit._build_prompt(mk(RequestType.PLAN_UNIT), "", conv, None),
        think_aloud._build_prompt(mk(RequestType.THINK_ALOUD), "", conv, None),
    ]


def test_frustration_validation_rule_carries_validate_first_and_bradys_example() -> None:
    r = FRUSTRATION_VALIDATION_RULE
    assert "This is not unusual" in r        # Brady's verbatim exemplar, kept
    assert "normal and hard" in r            # the validate-the-emotion nut
    assert "validate" in r.lower()
    assert "practical guidance" in r.lower()  # THEN the guidance, not instead of


def test_frustration_validation_rule_spliced_into_all_five_when_flag_set() -> None:
    # C10 fix: the validate-first rule must be present in EVERY text handler when
    # the teacher voiced frustration — no longer a COACHING-only rule that fired
    # only when a frustrated opener happened to route there.
    for prompt in _five_text_prompts(frustrated=True):
        assert FRUSTRATION_VALIDATION_RULE.strip() in prompt


def test_frustration_validation_rule_absent_when_flag_unset() -> None:
    # Back-compat / no-op: a calm turn (expressed_frustration False, the default)
    # carries NO validation instruction in ANY handler — byte-for-byte the prior
    # behavior on the overwhelming common case. Gated exactly like
    # EARLY_WRITER_STAGE_RULE.
    for prompt in _five_text_prompts(frustrated=False):
        assert FRUSTRATION_VALIDATION_RULE.strip() not in prompt
        assert "This is not unusual" not in prompt


def test_frustration_validation_rule_is_the_shared_object() -> None:
    # Defined once, imported by all five text handlers — not duplicated as a
    # literal, so a future edit to the wording can't silently fork per-handler
    # (mirrors test_skill_order_affirm_rule_is_the_shared_object).
    for mod in _FRUSTRATION_TEXT_MODULES:
        assert mod.FRUSTRATION_VALIDATION_RULE is FRUSTRATION_VALIDATION_RULE


def test_frustration_validation_rule_not_in_scripted_ml() -> None:
    # SCRIPTED_ML is a structured 4-step lesson, not prose — a "validate first,
    # then guidance" prose rule has no shape to live in, exactly like
    # EARLY_WRITER_STAGE_PER_BULLET_RULE is outline-only. Locks the scope to the
    # 5 text handlers even when the frustration flag is set.
    conv = Conversation(session_id="s1")
    frustrated = _basic_intent(RequestType.SCRIPTED_ML).model_copy(
        update={"expressed_frustration": True}
    )
    prompt = scripted_ml_prompt.build_scripted_ml_prompt(
        intent=frustrated, retrieved_context="", conversation=conv
    )
    assert FRUSTRATION_VALIDATION_RULE.strip() not in prompt


def test_coaching_bespoke_frustration_block_removed_superseded_by_shared_rule() -> None:
    # Brady C10 fix step 5: coaching's bespoke "## Responding to frustration"
    # block is DELETED — superseded by the shared FRUSTRATION_VALIDATION_RULE it
    # now receives via the gated splice. Removing it prevents a double
    # instruction and future drift; the OTHER _COACHING_RULES sections survive.
    assert "## Responding to frustration" not in coaching._COACHING_RULES
    assert "This is not unusual" not in coaching._COACHING_RULES
    # An unrelated coaching section survives the surgical deletion.
    assert "## Grounding" in coaching._COACHING_RULES
    # The instruction still reaches a frustrated coaching turn — via the splice.
    frustrated = _basic_intent(RequestType.COACHING).model_copy(
        update={"expressed_frustration": True}
    )
    prompt = coaching._build_prompt(
        frustrated, "", Conversation(session_id="s1"), None
    )
    assert FRUSTRATION_VALIDATION_RULE.strip() in prompt
    assert "This is not unusual" in prompt


# ---------------------------------------------------------------------------
# FULFILL_OFFERED_DELIVERABLES_RULE — deliver promised deliverables when
# accepted by teacher (chart of new-writing vs revisit days, unit tables, etc.)
# ---------------------------------------------------------------------------


def test_fulfill_offered_deliverables_rule_carries_key_instructions() -> None:
    r = _prompt_rules.FULFILL_OFFERED_DELIVERABLES_RULE
    assert "new-writing days vs. revisit days" in r
    assert "PRODUCE AND DELIVER THE PROMISED DELIVERABLE IMMEDIATELY" in r
    assert "NEVER ask the teacher to supply the details" in r
    assert "1 skill takes 2-4 days" in r


def test_fulfill_offered_deliverables_rule_spliced_into_text_handlers() -> None:
    conv = Conversation(session_id="s1")
    prompts = [
        how_to_teach._build_prompt(_basic_intent(RequestType.HOW_TO_TEACH), "", conv, None),
        plan_unit._build_prompt(_basic_intent(RequestType.PLAN_UNIT), "", conv, None),
        coaching._build_prompt(_basic_intent(RequestType.COACHING), "", conv, None),
    ]
    for prompt in prompts:
        assert _prompt_rules.FULFILL_OFFERED_DELIVERABLES_RULE.strip() in prompt
        assert "PRODUCE AND DELIVER THE PROMISED DELIVERABLE IMMEDIATELY" in prompt

