"""Deterministic ordinal resolution against the list we actually offered.

WHY THIS EXISTS (recert 2026-07-16): the teacher asked for "number 4" and
silently got item 3 — a confident, correctly-titled lesson on the WRONG skill.
Root: nothing persisted the offered list, so resolving an ordinal was left to
LLM arithmetic over rendered markdown. Proven in the drive cache: session
16a8e8a5 taught item 3 ("state an opinion to a particular audience") when the
teacher asked for item 4 ("generate reasons to support an opinion"); a7ed9561,
identical input, taught item 4.

The seam: an ORDINAL is arithmetic, not judgment. Code owns it. A name or a
fuzzy title stays the LLM's call (it is genuine semantic judgment) — so this
function returns None for anything that is not an unambiguous ordinal, and the
caller leaves QU's answer alone.
"""
from handlers.picklist import (
    extract_offered_skills,
    resolve_ordinal_pick,
    skill_name_from_offer,
)


SKILLS = [
    "Recognize opinionated/debatable topics",
    "Determine the strongest side",
    "State an opinion to a particular audience",
    "Generate reasons to support an opinion about the topic",
    "Support reasons with facts and details about a topic",
    "Organize reasons for impact",
    "Provide an introductory paragraph and a concluding paragraph",
]


class TestOrdinalPick:
    def test_bradys_exact_case_number_4_resolves_to_the_fourth_item(self):
        """The regression that shipped item 3. 'number 4' is the 4th item."""
        assert (
            resolve_ordinal_pick("Give me a lesson on number 4", SKILLS)
            == "Generate reasons to support an opinion about the topic"
        )

    def test_word_ordinal_the_third_one(self):
        assert (
            resolve_ordinal_pick("Give me a lesson on the third one", SKILLS)
            == "State an opinion to a particular audience"
        )

    def test_digit_ordinal_the_3rd_one(self):
        assert (
            resolve_ordinal_pick("give me the 3rd one", SKILLS)
            == "State an opinion to a particular audience"
        )

    def test_hash_form(self):
        assert (
            resolve_ordinal_pick("let's do #2", SKILLS)
            == "Determine the strongest side"
        )

    def test_first_and_last_boundaries(self):
        assert resolve_ordinal_pick("number 1", SKILLS) == SKILLS[0]
        assert resolve_ordinal_pick("number 7", SKILLS) == SKILLS[6]


class TestReturnsNoneRatherThanGuess:
    """Silence is cheap; a wrong lesson is a lie. Every ambiguous or
    undefined case must defer to the LLM rather than resolve."""

    def test_no_ordinal_is_not_a_pick(self):
        assert resolve_ordinal_pick("Give me a lesson on transitions", SKILLS) is None

    def test_fuzzy_title_stays_the_llms_job(self):
        """Brady's Snapple case — a NAME, not an ordinal. Not ours to resolve."""
        assert resolve_ordinal_pick("Give me a lesson on Snapple details", SKILLS) is None

    def test_out_of_range_ordinal_does_not_wrap_or_clamp(self):
        assert resolve_ordinal_pick("number 9", SKILLS) is None
        assert resolve_ordinal_pick("number 0", SKILLS) is None

    def test_two_distinct_ordinals_are_ambiguous(self):
        assert resolve_ordinal_pick("can I get number 3 and number 4?", SKILLS) is None

    def test_empty_offered_list_resolves_nothing(self):
        assert resolve_ordinal_pick("number 4", []) is None


# The real thing PLAN_UNIT rendered live on 2026-07-16 (backend :8050),
# reduced to its list. Verbatim so the test breaks if the real shape drifts.
_PLAN_UNIT_LIVE = """Grade 4 | Persuasive

For 4th grade persuasive writing, here are the priority skills in order:

1. Recognize opinionated/debatable topics.

2. Determine the strongest side.

3. State an opinion to a particular audience.

4. Generate reasons to support an opinion about the topic.

These are taught in mini-units of 1-2 weeks each.

Is this helpful? Would you like a general outline of this unit?"""

# HOW_TO_TEACH renders BULLETS, not numbers (Brady Fm1) — so "the third one"
# refers to a list with no numerals in it at all. VERBATIM from :8050 on
# 2026-07-16: bullets are separated by BLANK LINES (Brady Fm2 paragraph
# blocks) and each bullet is a whole paragraph — a bolded sub-skill sentence
# followed by explanation. Both properties broke the old extractor, which
# returned ONE item containing an entire paragraph.
_HOW_TO_TEACH_LIVE = """Grade 3

To teach paragraph writing in 3rd grade, use the **tables and legs** strategy.

- Teach the difference between a **listy piece** and a real paragraph. Students need to see that a paragraph is not just several ideas in a row; it is one main idea developed with multiple supporting sentences.

- Teach students to build a paragraph with a **table-top sentence and leg sentences**. In this strategy, the "table top" is the main sentence, and the "legs" are the supporting detail sentences.

- Teach students to generate **details that match the main idea**. A strong paragraph stays focused, so each added sentence should explain, prove, describe, or give an example.

Are you ready for a scripted mini-lesson on this skill?"""


class TestExtractOfferedSkills:
    def test_plan_unit_numbered_list_is_captured_in_order(self):
        assert extract_offered_skills(_PLAN_UNIT_LIVE) == [
            "Recognize opinionated/debatable topics",
            "Determine the strongest side",
            "State an opinion to a particular audience",
            "Generate reasons to support an opinion about the topic",
        ]

    def test_how_to_teach_blank_line_separated_bullets_are_all_captured(self):
        """The old extractor stopped at the first blank line and returned ONE
        item holding a whole paragraph. Each bullet is a sub-skill; the item
        is its leading sentence, not the explanation trailing it."""
        assert extract_offered_skills(_HOW_TO_TEACH_LIVE) == [
            "Teach the difference between a listy piece and a real paragraph",
            "Teach students to build a paragraph with a table-top sentence and leg sentences",
            "Teach students to generate details that match the main idea",
        ]

    def test_how_to_teach_third_one_resolves_to_the_third_sub_skill(self):
        offered = extract_offered_skills(_HOW_TO_TEACH_LIVE)
        assert (
            resolve_ordinal_pick("Give me a lesson on the third one", offered)
            == "Teach students to generate details that match the main idea"
        )

    def test_end_to_end_number_4_against_the_real_plan_unit_render(self):
        """The whole point, on real output: 'number 4' is item 4, not item 3."""
        offered = extract_offered_skills(_PLAN_UNIT_LIVE)
        assert (
            resolve_ordinal_pick("Give me a lesson on number 4", offered)
            == "Generate reasons to support an opinion about the topic"
        )

    def test_prose_without_a_list_offers_nothing(self):
        assert extract_offered_skills(
            "Focus on topic sentences first, then add details."
        ) == []


class TestGradeIsNotAPick:
    """The trap: a grade is written as an ordinal. '4th grade' must never
    resolve to item 4. canonicalizer._GRADE_ORDINAL_RE owns grades; this
    function must not compete with it."""

    def test_grade_ordinal_alone_is_not_a_pick(self):
        assert resolve_ordinal_pick("I teach 4th grade", SKILLS) is None

    def test_grade_ordinal_does_not_contaminate_a_real_pick(self):
        assert (
            resolve_ordinal_pick("I teach 4th grade — give me number 2", SKILLS)
            == "Determine the strongest side"
        )

    def test_spelled_grade_is_not_a_pick(self):
        assert resolve_ordinal_pick("my second graders need help", SKILLS) is None


class TestSkillNameFromOffer:
    """HOW_TO_TEACH bullets are phrased at the TEACHER ("Teach students to
    build a paragraph"). Used as the lesson's skill they render as "today
    we're going to Teach students to build a paragraph" — inside a script
    read to children. Measured live: 5/10.

    Provably bounded, in the E4 mould: strip ONLY an imperative prefix whose
    remainder is already a verb phrase. Anything else is returned untouched,
    so this can never turn a skill name into a non-verb-based fragment —
    which is exactly what a general strip does to "Teach the difference
    between X and Y" ("difference between X and Y").
    """

    def test_strips_teach_students_to(self):
        assert skill_name_from_offer(
            "Teach students to build a paragraph with the tables-and-legs strategy"
        ) == "build a paragraph with the tables-and-legs strategy"

    def test_strips_teach_students_how_to(self):
        assert skill_name_from_offer(
            "Teach students how to generate details that match one main idea"
        ) == "generate details that match one main idea"

    def test_strips_bare_teach_how_to(self):
        assert skill_name_from_offer(
            "Teach how to build a strong paragraph"
        ) == "build a strong paragraph"

    def test_leaves_a_noun_phrase_alone_rather_than_mangle_it(self):
        """A general strip yields "difference between adding words and
        adding development" — not a verb-based statement, and worse than
        leaving it. Brady's rule wants a verb."""
        s = "Teach students the difference between adding words and adding development"
        assert skill_name_from_offer(s) == s

    def test_leaves_a_that_clause_alone(self):
        s = "Teach students that each table becomes its own paragraph"
        assert skill_name_from_offer(s) == s

    def test_leaves_a_when_clause_alone(self):
        s = "Teach when to start a new paragraph with a new indent"
        assert skill_name_from_offer(s) == s

    def test_plan_unit_skill_names_pass_through_untouched(self):
        """PLAN_UNIT items are already verb-based skill names — 0/10 leak
        live. Nothing here may touch them."""
        for s in SKILLS:
            assert skill_name_from_offer(s) == s


# The real thing a COACHING answer renders when it lists moves. Item 4 is a
# teacher-directive bullet, exactly the shape Brady C14 hit: the teacher picked
# "number 4" off THIS list and got "Teach students to think small..." as the
# lesson title, because the list was recorded only for PLAN_UNIT/HOW_TO_TEACH.
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


class TestAnyRenderedListIsCaptured:
    """Brady C14: the offered list is recorded off ANY response that renders a
    countable list — not just PLAN_UNIT/HOW_TO_TEACH. A COACHING turn offers a
    pointable list just as a PLAN_UNIT unit outline does; the old request_type
    gate dropped it, so the ordinal resolver (which also strips the imperative)
    never ran and the LLM copied the raw bullet as the title.

    The safety is downstream, not in a type gate: resolve_ordinal_pick fires
    only on an explicit in-range ordinal, and only against the most recent
    assistant turn — a list the teacher does not point at stays inert.
    """

    def test_a_coaching_style_numbered_list_is_captured(self):
        assert extract_offered_skills(_COACHING_WITH_LIST) == _COACHING_OFFERED

    def test_the_directive_bullet_strips_to_a_clean_skill_name(self):
        """The C14 title garble in full: item 4 is a teacher-directive bullet;
        the ordinal path names the skill by stripping the imperative, so the
        lesson is titled "think small ..." not "Teach students to think ..."."""
        offered = extract_offered_skills(_COACHING_WITH_LIST)
        picked = resolve_ordinal_pick("give me number 4", offered)
        assert picked == "Teach students to think small by zooming in on one tiny moment"
        assert (
            skill_name_from_offer(picked)
            == "think small by zooming in on one tiny moment"
        )

    def test_empty_text_offers_nothing(self):
        assert extract_offered_skills("") == []

    def test_a_multi_skill_outline_counts_more_than_one(self):
        """Task 2's HOW_TO_TEACH multi-skill closer swap keys on this count
        through the updated (type-free) call."""
        assert len(extract_offered_skills(_HOW_TO_TEACH_LIVE)) == 3
