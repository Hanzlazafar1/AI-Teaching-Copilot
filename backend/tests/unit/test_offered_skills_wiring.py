"""The offered list must survive from the turn that offered it to the turn
that picks from it.

`offered_skills` was declared on the QU reader and in the QU prompt but NEVER
populated by production code — its only writers were a test and a fixture, so
a green test fabricated the field and asserted the renderer forwarded it. A
pipe with no water. These tests put water in it and fail if it ever drains.

⚠️ It is deliberately NOT carried in `TurnOutcome.structured`: routes_v4.py
:210 treats a non-None `structured` as "this response IS a mini_lesson" and
DISCARDS response_text, so smuggling the list through `structured` would ship
a bare JSON blob to the teacher instead of their unit plan.
"""
from handlers._base_text import _build_text_outcome
from query.qu_v4 import _render_conversation
from schemas import Conversation, Quality, Role, Turn

_PLAN_UNIT_RENDER = """For 4th grade persuasive writing, here are the priority skills in order:

1. Recognize opinionated/debatable topics.

2. Determine the strongest side.

3. State an opinion to a particular audience.

4. Generate reasons to support an opinion about the topic.

These are taught in mini-units of 1-2 weeks each.

Is this helpful? Would you like a general outline of this unit?"""

_EXPECTED = [
    "Recognize opinionated/debatable topics",
    "Determine the strongest side",
    "State an opinion to a particular audience",
    "Generate reasons to support an opinion about the topic",
]


def _outcome(query_type):
    return _build_text_outcome(
        response_text=_PLAN_UNIT_RENDER,
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
        retrieved_context="",
        log_label="test",
        query_type=query_type,
    )


class TestHandlerRecordsWhatItOffered:
    def test_plan_unit_outcome_carries_the_offered_list(self):
        assert _outcome("PLAN_UNIT").offered_skills == _EXPECTED

    def test_a_coaching_outcome_with_a_list_carries_it_too(self):
        """Brady C14: the list is recorded off ANY text handler that renders
        one, not just PLAN_UNIT/HOW_TO_TEACH. Was [] under the old request_type
        gate — which is why "number 4" off a COACHING list resolved against an
        empty offered list and the LLM copied the raw bullet as the title."""
        assert _outcome("COACHING_GENERAL").offered_skills == _EXPECTED

    def test_a_text_outcome_without_a_list_carries_nothing(self):
        """The remaining invariant: no list rendered -> nothing to point at.
        A later ordinal must not resolve against a pick-list never shown."""
        out = _build_text_outcome(
            response_text="Focus on topic sentences first, then add details.",
            grounding=[], quality=Quality.VALID, retry_count=0,
            validation_errors=[], retrieved_context="",
            log_label="coaching", query_type="COACHING_GENERAL",
        )
        assert out.offered_skills == []

    def test_offering_the_list_never_makes_it_a_mini_lesson(self):
        """The delivery contract: structured stays None, so routes_v4 keeps
        shipping response_text. If this flips, the teacher gets JSON."""
        out = _outcome("PLAN_UNIT")
        assert out.offered_skills == _EXPECTED
        assert out.structured is None
        assert _PLAN_UNIT_RENDER.splitlines()[0] in out.response_text


class TestListSurvivesOntoTheTurn:
    def test_turn_carries_the_offered_list(self):
        t = Turn(index=0, role=Role.ASSISTANT, text="x", offered_skills=_EXPECTED)
        assert t.offered_skills == _EXPECTED

    def test_turn_defaults_to_empty_not_none(self):
        assert Turn(index=0, role=Role.ASSISTANT, text="x").offered_skills == []


class TestQuSeesTheList:
    def test_rendered_conversation_shows_the_offered_list_to_qu(self):
        """QU is told to resolve picks against offered_skills. Until this
        rendered, QU could only count raw markdown — which is how "number 4"
        became item 3."""
        convo = Conversation(session_id="s", user_id="u", turns=[
            Turn(index=0, role=Role.USER, text="Plan a persuasive unit for 4th grade"),
            Turn(index=1, role=Role.ASSISTANT, text=_PLAN_UNIT_RENDER,
                 offered_skills=_EXPECTED),
        ])
        rendered = _render_conversation(convo)
        assert "offered_skills" in rendered
        assert "Generate reasons to support an opinion about the topic" in rendered

    def test_turn_without_an_offered_list_adds_no_noise(self):
        convo = Conversation(session_id="s", user_id="u", turns=[
            Turn(index=0, role=Role.ASSISTANT, text="Just some prose."),
        ])
        assert "offered_skills" not in _render_conversation(convo)


# ----------------------------------------------------------------------
# Deterministic override — arithmetic beats the LLM's guess
# ----------------------------------------------------------------------

from query.qu_v4 import apply_ordinal_pick  # noqa: E402
from schemas import RequestType, SkillSpec, TurnIntent  # noqa: E402


class _FakeCanon:
    """canonicalize_skill lowercases + trims the trailing qualifier, like the
    real one does for these PIE skill names."""

    def canonicalize_skill(self, raw: str) -> str:
        return raw.lower().replace(" about the topic", "")


def _offering_convo(offered=None):
    return Conversation(session_id="s", user_id="u", turns=[
        Turn(index=0, role=Role.USER, text="Plan a persuasive unit for 4th grade"),
        Turn(index=1, role=Role.ASSISTANT, text=_PLAN_UNIT_RENDER,
             offered_skills=list(_EXPECTED if offered is None else offered)),
    ])


def _picked_intent(as_stated="Number 4", canonical="number 4"):
    """What QU actually returns live for 'Give me a lesson on number 4'."""
    return TurnIntent(
        request_type=RequestType.DEEPEN_PRIOR,
        skill=SkillSpec(canonical=canonical, as_stated=as_stated),
    )


class TestOrdinalOverridesTheModel:
    def test_the_deictic_is_replaced_by_the_skill_it_points_at(self):
        """Live, 10/10 runs titled the lesson "Number 4". as_stated is meant
        to be the teacher's words for the SKILL; a deictic is a pointer, not
        vocabulary. The words they pointed at are ours, and we have them."""
        out = apply_ordinal_pick(
            _picked_intent(), "Give me a lesson on number 4",
            _offering_convo(), _FakeCanon(),
        )
        assert out.skill.as_stated == "Generate reasons to support an opinion about the topic"
        assert out.skill.canonical == "generate reasons to support an opinion"

    def test_it_overrides_the_models_WRONG_answer(self):
        """The regression itself: QU resolved 'number 4' to item 3 (drive
        session 16a8e8a5). Arithmetic wins — that is the whole point."""
        wrong = _picked_intent(
            as_stated="State an opinion to a particular audience",
            canonical="state an opinion to a particular audience",
        )
        out = apply_ordinal_pick(
            wrong, "Give me a lesson on number 4", _offering_convo(), _FakeCanon(),
        )
        assert out.skill.as_stated == "Generate reasons to support an opinion about the topic"

    def test_resolving_clears_the_skill_gap(self):
        intent = TurnIntent(request_type=RequestType.SCRIPTED_ML,
                            missing_required=["skill"])
        out = apply_ordinal_pick(
            intent, "number 4", _offering_convo(), _FakeCanon(),
        )
        assert "skill" not in out.missing_required
        assert out.skill.as_stated == "Generate reasons to support an opinion about the topic"

    def test_it_resolves_against_the_list_actually_shown(self):
        """A 9-item run and a 7-item run disagree about what "number 4" is.
        Only the list this session rendered can settle it."""
        other = ["A", "B", "C", "D-different", "E"]
        out = apply_ordinal_pick(
            _picked_intent(), "number 4", _offering_convo(other), _FakeCanon(),
        )
        assert out.skill.as_stated == "D-different"


class TestOverrideStaysInItsLane:
    def test_a_name_pick_is_left_to_the_model(self):
        """'Snapple details' is semantic matching — genuinely QU's judgment."""
        intent = _picked_intent(as_stated="Snapple details", canonical="snapple details")
        out = apply_ordinal_pick(
            intent, "Give me a lesson on Snapple details",
            _offering_convo(), _FakeCanon(),
        )
        assert out.skill.as_stated == "Snapple details"

    def test_no_offered_list_means_no_override(self):
        convo = Conversation(session_id="s", user_id="u", turns=[
            Turn(index=0, role=Role.ASSISTANT, text="just prose"),
        ])
        intent = _picked_intent()
        out = apply_ordinal_pick(intent, "number 4", convo, _FakeCanon())
        assert out.skill.as_stated == "Number 4"

    def test_out_of_range_ordinal_does_not_override(self):
        out = apply_ordinal_pick(
            _picked_intent(), "number 99", _offering_convo(), _FakeCanon(),
        )
        assert out.skill.as_stated == "Number 4"

    def test_grade_ordinal_never_triggers_a_pick(self):
        intent = TurnIntent(request_type=RequestType.PLAN_UNIT)
        out = apply_ordinal_pick(
            intent, "I teach 4th grade", _offering_convo(), _FakeCanon(),
        )
        assert out.skill is None


# ----------------------------------------------------------------------
# Re-surfacing — "the list I just shared" must not be a lie
# ----------------------------------------------------------------------

from handlers import _skill_clarification  # noqa: E402


class TestReSurfacedListIsTheOneOnScreen:
    def test_it_re_surfaces_the_prior_turns_offered_list(self):
        convo = Conversation(session_id="s", user_id="u", turns=[
            Turn(index=0, role=Role.USER, text="Plan a persuasive unit for 4th grade"),
            Turn(index=1, role=Role.ASSISTANT, text=_PLAN_UNIT_RENDER,
                 offered_skills=list(_EXPECTED)),
        ])
        q = _skill_clarification(convo)
        assert "the list I just shared" in q
        for i, skill in enumerate(_EXPECTED, 1):
            assert f"{i}. {skill}" in q

    def test_it_does_not_claim_to_have_just_shared_an_older_list(self):
        """THE BUG: the old helper walked BACK through every turn until it
        found any list, so "the list I just shared" pointed at a list from
        several turns ago that is nowhere on the teacher's screen. If the
        most recent assistant turn offered nothing, there is no list."""
        convo = Conversation(session_id="s", user_id="u", turns=[
            Turn(index=0, role=Role.USER, text="Plan a persuasive unit for 4th grade"),
            Turn(index=1, role=Role.ASSISTANT, text=_PLAN_UNIT_RENDER,
                 offered_skills=list(_EXPECTED)),
            Turn(index=2, role=Role.USER, text="thanks — what is voice?"),
            Turn(index=3, role=Role.ASSISTANT, text="Voice is the writer's personality.",
                 offered_skills=[]),
        ])
        q = _skill_clarification(convo)
        assert "just shared" not in q
        assert "Generate reasons to support an opinion about the topic" not in q

    def test_no_list_at_all_falls_back_to_the_generic_ask(self):
        convo = Conversation(session_id="s", user_id="u", turns=[
            Turn(index=0, role=Role.ASSISTANT, text="Some prose.", offered_skills=[]),
        ])
        assert "just shared" not in _skill_clarification(convo)


class TestHowToTeachPickIsNamedAsASkill:
    def test_the_teacher_directed_imperative_is_normalised_away(self):
        """Live 5/10: "today we're going to Teach students to build a
        paragraph" — in a script read aloud to children."""
        convo = Conversation(session_id="s", user_id="u", turns=[
            Turn(index=0, role=Role.ASSISTANT, text="outline",
                 offered_skills=[
                     "Teach the difference between a listy piece and a real paragraph",
                     "Teach students to build a paragraph with a table-top sentence",
                     "Teach students to generate details that match the main idea",
                 ]),
        ])
        out = apply_ordinal_pick(
            TurnIntent(request_type=RequestType.DEEPEN_PRIOR),
            "Give me a lesson on the third one", convo, _FakeCanon(),
        )
        assert out.skill.as_stated == "generate details that match the main idea"

    def test_a_noun_phrase_offer_is_left_intact_not_mangled(self):
        convo = Conversation(session_id="s", user_id="u", turns=[
            Turn(index=0, role=Role.ASSISTANT, text="outline",
                 offered_skills=[
                     "Teach students the difference between words and development",
                 ]),
        ])
        out = apply_ordinal_pick(
            TurnIntent(request_type=RequestType.DEEPEN_PRIOR),
            "number 1", convo, _FakeCanon(),
        )
        assert out.skill.as_stated == (
            "Teach students the difference between words and development"
        )


# ----------------------------------------------------------------------
# Brady C14 — a COACHING turn's pick-list is recorded and pickable too
# ----------------------------------------------------------------------
#
# The teacher was shown a numbered list of moves by a COACHING answer, said
# "number 4", and got a lesson TITLED with the raw teacher-directive bullet
# ("Teach students to think small ...") — because offered_skills was recorded
# only for PLAN_UNIT/HOW_TO_TEACH, so at the pick turn the offered list was
# empty and the ordinal resolver (which also strips the imperative) never ran.
# A countable list is a pick-list no matter which handler rendered it; the
# downstream guards (an explicit in-range ordinal, most-recent turn only) are
# what keep an un-pointed list inert.

_COACHING_WITH_LIST = """When conferring with a struggling writer, try these moves:

1. Notice one thing the writer did well and name it.

2. Ask what the writer was trying to say in this part.

3. Model the strategy aloud using your own quick example.

4. Teach students to think small by zooming in on one tiny moment.

Pick whichever fits the conference."""

_COACHING_OFFERED = [
    "Notice one thing the writer did well and name it",
    "Ask what the writer was trying to say in this part",
    "Model the strategy aloud using your own quick example",
    "Teach students to think small by zooming in on one tiny moment",
]


def _coaching_outcome():
    return _build_text_outcome(
        response_text=_COACHING_WITH_LIST,
        grounding=[], quality=Quality.VALID, retry_count=0,
        validation_errors=[], retrieved_context="",
        log_label="coaching", query_type="COACHING_GENERAL",
    )


def _coaching_convo():
    return Conversation(session_id="s", user_id="u", turns=[
        Turn(index=0, role=Role.USER,
             text="How do I confer with a struggling writer?"),
        Turn(index=1, role=Role.ASSISTANT, text=_COACHING_WITH_LIST,
             offered_skills=list(_coaching_outcome().offered_skills)),
    ])


class TestCoachingListIsRecordedAndPickable:
    def test_coaching_outcome_now_records_its_pick_list(self):
        """C14 at the outcome level: was [] because the gate excluded
        COACHING_GENERAL, so nothing downstream could resolve an ordinal."""
        out = _coaching_outcome()
        assert out.offered_skills == _COACHING_OFFERED
        assert out.structured is None  # still delivered as text, not a blob

    def test_number_4_off_a_coaching_list_gets_a_clean_titled_skill(self):
        """The whole C14 chain: pick item 4 and the teacher-directed imperative
        is stripped, so the lesson is titled "think small ..." — not "Number 4"
        and not the raw "Teach students to think small ..." bullet."""
        out = apply_ordinal_pick(
            _picked_intent(), "Give me a lesson on number 4",
            _coaching_convo(), _FakeCanon(),
        )
        assert out.skill.as_stated == "think small by zooming in on one tiny moment"
        assert not out.skill.as_stated.lower().startswith("teach")
        assert out.skill.as_stated != "Number 4"

    def test_no_ordinal_anchor_leaves_the_intent_untouched(self):
        """A coaching list is inert unless the teacher points at it: no anchor,
        no override — the model's own answer stands."""
        out = apply_ordinal_pick(
            _picked_intent(as_stated="voice", canonical="voice"),
            "actually, tell me about voice",
            _coaching_convo(), _FakeCanon(),
        )
        assert out.skill.as_stated == "voice"

    def test_out_of_range_ordinal_off_a_coaching_list_does_not_override(self):
        out = apply_ordinal_pick(
            _picked_intent(), "give me number 9",
            _coaching_convo(), _FakeCanon(),
        )
        assert out.skill.as_stated == "Number 4"
