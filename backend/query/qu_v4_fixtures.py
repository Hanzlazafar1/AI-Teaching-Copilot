"""QU fixture data — conversation + expected TurnIntent pairs.

Each fixture is a (Conversation, new_user_message, expected_intent)
triple used by both unit tests (checking post-processing logic with
mocked LLM responses) and live acceptance tests (running against the
real QU model).

Fixtures are grouped:
  - BRADY_SAMPLE_CHAT: replays Brady's SAMPLE CHAT docx turn-by-turn.
    Every turn Brady annotated in red gets its own fixture.
  - EDGE_CASES: additional scenarios not in the sample chat (grade-
    band terms, offered-skill pickup, CORRECTION, META boundaries).

Matching semantics (see LivenessMatcher for full rules):
  - request_type: MUST match exactly
  - grade.value / mode.value / trait.value: MUST match if expected set
  - skill.canonical: MUST match if expected set; as_stated checked
    with contains (teacher vocab preservation)
  - refers_to_prior / reuse_example_from_prior / needs_confirmation:
    MUST match if expected set
  - prior_turn_ref: MUST equal if expected set
  - required_triggers: as-set comparison (order-insensitive)
  - missing_required: as-set comparison
  - Extra fields beyond what's expected: allowed (don't fail)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from schemas import (
    ChunkRef,
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
)


@dataclass
class QUFixture:
    """A single QU fixture — inputs + expected output."""

    name: str
    description: str
    conversation: Conversation
    new_user_message: str
    handshakes: SessionHandshakes = field(default_factory=SessionHandshakes)
    expected: TurnIntent = field(default_factory=lambda: TurnIntent(request_type=RequestType.META))


# ----------------------------------------------------------------------
# Helpers for fixture construction
# ----------------------------------------------------------------------


def _assistant_turn(
    index: int,
    text: str,
    *,
    structured: Optional[dict] = None,
    grounding: Optional[list[ChunkRef]] = None,
    quality: Quality = Quality.VALID,
) -> Turn:
    return Turn(
        index=index,
        role=Role.ASSISTANT,
        text=text,
        structured=structured,
        grounding=grounding or [],
        quality=quality,
    )


def _user_turn(index: int, text: str) -> Turn:
    return Turn(index=index, role=Role.USER, text=text)


def _conversation(turns: list[Turn], session_id: str = "fixture-session") -> Conversation:
    conv = Conversation(session_id=session_id)
    for turn in turns:
        conv.append(turn)
    return conv


# ----------------------------------------------------------------------
# Brady Sample Chat fixtures — one per turn Brady annotated
# ----------------------------------------------------------------------

BRADY_SAMPLE_CHAT: list[QUFixture] = [
    QUFixture(
        name="B01_paragraph_writing_opener",
        description=(
            "Brady's Turn 1. Fresh conversation — user asks 'how do I teach X'. "
            "Classic HOW_TO_TEACH with explicit grade."
        ),
        conversation=_conversation([]),
        new_user_message="How do I teach paragraph writing to 3rd graders?",
        expected=TurnIntent(
            request_type=RequestType.HOW_TO_TEACH,
            grade=GradeSpec(value="3", stated_explicit=True, stated_turn=0),
            skill=SkillSpec(
                canonical="paragraph writing",
                as_stated="paragraph writing",
                stated_turn=0,
            ),
            refers_to_prior=False,
            needs_confirmation=False,
        ),
    ),
    QUFixture(
        name="B02_put_in_lesson_followup",
        description=(
            "Brady Turn 2: 'Can you put this in a lesson?' — refers to prior "
            "turn's outline, wants SCRIPTED_ML. Requires DEEPEN_PRIOR routing."
        ),
        conversation=_conversation([
            _user_turn(0, "How do I teach paragraph writing to 3rd graders?"),
            _assistant_turn(
                1,
                "Pizza-table strategy for paragraph writing...",
                structured={"skill_focus": "paragraph writing"},
            ),
        ]),
        new_user_message="Can you put this in a lesson for me to deliver to my students?",
        expected=TurnIntent(
            request_type=RequestType.DEEPEN_PRIOR,
            grade=GradeSpec(value="3", stated_explicit=True, stated_turn=0),
            skill=SkillSpec(
                canonical="paragraph writing",
                as_stated="paragraph writing",
            ),
            refers_to_prior=True,
            prior_turn_ref=1,
            needs_confirmation=False,
        ),
    ),
    QUFixture(
        name="B03_skill_narrowing_reply",
        description=(
            "Brady Turn 3: user narrows skill. System had asked 'what specific "
            "aspect?'; user replies with 'topic sentence and supporting details'. "
            "Should produce SkillSpec with as_stated='topic sentence and "
            "supporting details' (teacher vocab) and canonical='topic sentences'."
        ),
        conversation=_conversation([
            _user_turn(0, "How do I teach paragraph writing to 3rd graders?"),
            _assistant_turn(1, "...pizza-table outline...",
                            structured={"skill_focus": "paragraph writing"}),
            _user_turn(2, "Can you put this in a lesson for me to deliver?"),
            _assistant_turn(3, "What specific aspect of paragraph writing would you like to focus on?"),
        ]),
        new_user_message="Topic sentence and supporting details",
        expected=TurnIntent(
            request_type=RequestType.SCRIPTED_ML,
            grade=GradeSpec(value="3", stated_explicit=True, stated_turn=0),
            skill=SkillSpec(
                canonical="topic sentences",
                as_stated="topic sentence and supporting details",
            ),
            refers_to_prior=True,
            needs_confirmation=False,
        ),
    ),
    QUFixture(
        name="B04_grade_already_given_dont_reask",
        description=(
            "Grade was stated in Turn 0 ('3rd graders'). When user sends a new "
            "SCRIPTED_ML query, QU must NOT add 'grade' to missing_required — "
            "grade persists."
        ),
        conversation=_conversation([
            _user_turn(0, "I teach 5th grade and want a lesson on transitions"),
            _assistant_turn(1, "Transitions lesson...", structured={"skill_focus": "transitions"}),
            _user_turn(2, "Can you make it informative mode?"),
            _assistant_turn(3, "Sure. Here's the transitions lesson for 5th grade, informative mode...",
                            structured={"skill_focus": "transitions", "grade": "5", "mode": "Inform"}),
        ]),
        new_user_message="Now one on topic sentences",
        expected=TurnIntent(
            request_type=RequestType.SCRIPTED_ML,
            grade=GradeSpec(value="5", stated_explicit=True, stated_turn=0),
            skill=SkillSpec(
                canonical="topic sentences",
                as_stated="topic sentences",
            ),
            missing_required=[],  # grade NOT missing — it's stated
        ),
    ),
    QUFixture(
        name="B05_pdf_export_is_META",
        description=(
            "Brady Turn 5: 'Can you put this in a PDF?'. Brady marked this "
            "response GOOD — co-pilot politely refused, explained workaround. "
            "QU must route to META (capability question, not pedagogical)."
        ),
        conversation=_conversation([
            _user_turn(0, "Lesson on topic sentences for 3rd grade"),
            _assistant_turn(1, "Scripted ML...",
                            structured={"skill_focus": "topic sentences"}),
        ]),
        new_user_message="Can you put this in a PDF?",
        expected=TurnIntent(
            request_type=RequestType.META,
        ),
    ),
    QUFixture(
        name="B06_deepen_think_aloud_SKILL_inherits_not_think_aloud",
        description=(
            "THE CRITICAL TEST — Brady Turn 6. User asks to 'provide all of "
            "the teacher's internal thinking'. The prior lesson was topic "
            "sentences. QU must NOT extract 'think-aloud' as skill — "
            "think-aloud is a meta-technique, not a skill. Inherit the "
            "topic-sentences skill from the prior turn."
        ),
        conversation=_conversation([
            _user_turn(0, "How do I teach paragraph writing to 3rd graders?"),
            _assistant_turn(1, "Outline...", structured={"skill_focus": "paragraph writing"}),
            _user_turn(2, "Can you put this in a lesson?"),
            _assistant_turn(3, "What aspect?"),
            _user_turn(4, "Topic sentence and supporting details"),
            _assistant_turn(5, "Scripted ML on topic sentences with Step 2B example...",
                            structured={"skill_focus": "topic sentences",
                                        "step_2b_show": "example about exercise"}),
        ]),
        new_user_message=(
            "Using the example & think aloud you wrote in step 2B, please "
            "provide all of the teacher's internal thinking to consume the "
            "full five minutes."
        ),
        expected=TurnIntent(
            request_type=RequestType.DEEPEN_PRIOR,
            grade=GradeSpec(value="3", stated_explicit=True, stated_turn=0),
            skill=SkillSpec(
                canonical="topic sentences",  # INHERITED, NOT "think-aloud"
                as_stated="topic sentence and supporting details",
            ),
            refers_to_prior=True,
            prior_turn_ref=5,
            reuse_example_from_prior=True,
        ),
    ),
    QUFixture(
        name="B07_rewrite_lesson_with_think_aloud_still_DEEPEN",
        description=(
            "Brady Turn 7: 'Take this guidance and then rewrite the lesson with "
            "a scripted think-aloud included'. User wants to extend the prior "
            "discussion into a full lesson. DEEPEN_PRIOR."
        ),
        conversation=_conversation([
            _user_turn(0, "How do I teach paragraph writing to 3rd graders?"),
            _assistant_turn(1, "outline", structured={"skill_focus": "paragraph writing"}),
            _user_turn(2, "Topic sentence and supporting details"),
            _assistant_turn(3, "Scripted ML on topic sentences...",
                            structured={"skill_focus": "topic sentences"}),
            _user_turn(4, "Provide all the teacher's internal thinking"),
            _assistant_turn(5, "Deeper think-aloud on topic sentences...",
                            structured={"skill_focus": "topic sentences"}),
        ]),
        new_user_message=(
            "Take this guidance and then rewrite the lesson with a scripted "
            "think-aloud included"
        ),
        expected=TurnIntent(
            request_type=RequestType.DEEPEN_PRIOR,
            grade=GradeSpec(value="3", stated_explicit=True, stated_turn=0),
            skill=SkillSpec(
                canonical="topic sentences",
                as_stated="topic sentence and supporting details",
            ),
            refers_to_prior=True,
            reuse_example_from_prior=True,
        ),
    ),
    QUFixture(
        name="B08_is_there_a_lesson_with_pizza_table",
        description=(
            "Brady Turn 8: 'Is there a lesson with a pizza table?'. Direct "
            "lookup question. User names the trigger — required_triggers "
            "must include 'pizza-table'. Request_type is COACHING (meta "
            "lookup about whether a lesson exists)."
        ),
        conversation=_conversation([
            _user_turn(0, "How do I teach paragraph writing?"),
            _assistant_turn(1, "Pizza-table strategy...",
                            structured={"skill_focus": "paragraph writing"}),
        ]),
        new_user_message="Is there a lesson with a pizza table?",
        expected=TurnIntent(
            request_type=RequestType.COACHING,
            required_triggers=["pizza-table"],
            skill=SkillSpec(
                canonical="pizza-table",
                as_stated="pizza table",
            ),
        ),
    ),
    QUFixture(
        name="B09_organizer_recall",
        description=(
            "Brady Turn 9: 'Where can I get that graphic organizer?'. 'That' "
            "refers to an organizer the assistant mentioned in the prior turn. "
            "COACHING-shape with refers_to_prior=True. Load-bearing: "
            "required_triggers includes pizza-table (what organizer they're "
            "asking about) and refers_to_prior is True. skill.canonical can "
            "be either 'pizza-table' (the organizer itself) or 'paragraph "
            "writing' (the broader skill being taught) — both defensible."
        ),
        conversation=_conversation([
            _user_turn(0, "How do I teach paragraphs?"),
            _assistant_turn(1, "pizza-table, see page 64 for the organizer",
                            structured={"skill_focus": "paragraph writing",
                                        "trigger": "pizza-table",
                                        "cited_page": 64}),
        ]),
        new_user_message="Where can I get that graphic organizer?",
        expected=TurnIntent(
            request_type=RequestType.COACHING,
            required_triggers=["pizza-table"],
            refers_to_prior=True,
            prior_turn_ref=1,
        ),
    ),
    QUFixture(
        name="B10_what_page_followup",
        description=(
            "Brady Turn 13: 'What page?'. Terse follow-up, meaningful only in "
            "context. DEEPEN_PRIOR, COACHING-shape."
        ),
        conversation=_conversation([
            _user_turn(0, "Is the pizza-table lesson in the Launch book?"),
            _assistant_turn(
                1,
                "Yes, the pizza-table (tables-and-legs) lesson is in "
                "Launching the Writers Workshop 3-12.",
                structured={"skill_focus": "pizza-table"},
            ),
        ]),
        new_user_message="What page?",
        expected=TurnIntent(
            request_type=RequestType.COACHING,
            refers_to_prior=True,
            prior_turn_ref=1,
        ),
    ),
    QUFixture(
        name="B11_think_aloud_surgery_example",
        description=(
            "Brady Turn 14: 'Provide another scripted think-aloud to determine "
            "the transition between these two sentences: My mom is having "
            "surgery. She is very anxious.' Brady's gold-standard request — "
            "THINK_ALOUD with a specific example the model should preserve."
        ),
        conversation=_conversation([]),
        new_user_message=(
            "Provide another scripted think-aloud to determine the transition "
            "between these two sentences: My mom is having surgery. She is "
            "very anxious."
        ),
        expected=TurnIntent(
            request_type=RequestType.THINK_ALOUD,
            skill=SkillSpec(
                canonical="transitions",
                as_stated="transition",
            ),
        ),
    ),
    QUFixture(
        name="B12_reuse_example_into_full_lesson",
        description=(
            "Brady Turn 15: 'Insert this entire think-aloud with the example "
            "into a new mini-lesson script for step 2B. Add Steps 1, 2A, 3, 4... "
            "Grade 4.' DEEPEN_PRIOR with reuse_example_from_prior=True. "
            "Grade is stated in THIS message."
        ),
        conversation=_conversation([
            _user_turn(
                0,
                "Provide a think-aloud for the transition between: My mom is "
                "having surgery. She is very anxious."
            ),
            _assistant_turn(
                1,
                "...therefore... [perfect think-aloud modeling]",
                structured={"skill_focus": "transitions",
                            "step_2b_show": "mom surgery therefore example"},
            ),
        ]),
        new_user_message=(
            "Insert this entire think-aloud with the example into a new mini-"
            "lesson script for step 2B. Add Steps 1, 2A, 3 and 4 to provide me "
            "a full mini-lesson script on how to choose transitions. Grade 4."
        ),
        expected=TurnIntent(
            request_type=RequestType.DEEPEN_PRIOR,
            grade=GradeSpec(value="4", stated_explicit=True),
            skill=SkillSpec(
                canonical="transitions",
                as_stated="transitions",
            ),
            refers_to_prior=True,
            prior_turn_ref=1,
            reuse_example_from_prior=True,
        ),
    ),
    QUFixture(
        name="B13_plan_unit_persuasive",
        description="Brady Turn 16: 'Give me a persuasive writing unit plan, please'",
        conversation=_conversation([]),
        new_user_message="Give me a persuasive writing unit plan, please",
        expected=TurnIntent(
            request_type=RequestType.PLAN_UNIT,
            mode=ModeSpec(value="Persuade", stated_explicit=True),
        ),
    ),
    QUFixture(
        name="B14_report_writing_skill_list_query",
        description=(
            "Brady Turn 18: 'Do you have any lessons on skills for teaching "
            "report writing?'. HOW_TO_TEACH-shape — asking what's available. "
            "Skill canonical can reasonably be either 'report writing' or "
            "'collect facts and details' (the Smekens foundation skill for "
            "reports). We don't strict-match skill here; request_type + mode "
            "are the load-bearing expectations."
        ),
        conversation=_conversation([]),
        new_user_message="Do you have any lessons on skills for teaching report writing?",
        expected=TurnIntent(
            request_type=RequestType.HOW_TO_TEACH,
            # mode=Inform is STRONGLY implied by "report writing"
            mode=ModeSpec(value="Inform", stated_explicit=False, confidence=0.9),
            # No skill.canonical expectation — either form acceptable
        ),
    ),
    QUFixture(
        name="B15_offered_skill_pickup_off_list",
        description=(
            "Brady Turn 19: user picks 'Snapple details' but Co-Pilot's prior "
            "list didn't include it. needs_confirmation must fire."
        ),
        conversation=_conversation([
            _user_turn(0, "Do you have lessons on report writing skills?"),
            _assistant_turn(
                1,
                "Here are the four essential report-writing skills: ...",
                structured={
                    "offered_skills": [
                        "collect facts and details",
                        "jot fact phrases",
                        "organize into categories",
                        "write the introduction",
                        "write the conclusion",
                    ],
                    "skill_focus": "report writing",
                },
            ),
            _user_turn(2, "Please provide me a lesson to teach on this"),
            _assistant_turn(3, "What grade level?"),
        ]),
        new_user_message="6",
        handshakes=SessionHandshakes(
            clarification=None,  # not setting a handshake — this is from QU ambiguity
        ),
        expected=TurnIntent(
            request_type=RequestType.SCRIPTED_ML,
            grade=GradeSpec(value="6", stated_explicit=True),
            # skill can reasonably be 'report writing' OR 'collect facts and
            # details' — don't strict-match
            refers_to_prior=True,
        ),
    ),
    QUFixture(
        name="B16_picture_details_early_writer",
        description=(
            "Brady Turn 20 (new chat): 'How do I get my students to add "
            "details to the pictures'. HOW_TO_TEACH for K-2 EARLY_WRITER "
            "territory. No grade stated — QU may or may not add missing_required. "
            "Skill canonical may be 'add details to pictures', 'adding "
            "details', or 'magnify-close-up' (Smekens canonical trigger) — "
            "all defensible; don't strict-match."
        ),
        conversation=_conversation([]),
        new_user_message="How do I get my students to add details to the pictures",
        expected=TurnIntent(
            request_type=RequestType.HOW_TO_TEACH,
            # Skill canonical not strict — multiple reasonable forms
        ),
    ),
    QUFixture(
        name="B17_no_book_coaching",
        description=(
            "Brady Turn 21: 'I don't have that book. But can you tell me "
            "more about the magnify close up details lesson?'. User is "
            "asking for an explainer + references the prior turn. "
            "DEEPEN_PRIOR is also defensible since they're following up on "
            "the prior turn's mention of the lesson. Load-bearing: "
            "required_triggers must include magnify-close-up (user named "
            "it) and refers_to_prior=True."
        ),
        conversation=_conversation([
            _user_turn(0, "How do I get my students to add details to pictures?"),
            _assistant_turn(
                1,
                "Several strategies from Launching K-2 including Magnify "
                "Close-Up Details (ML #9)...",
                structured={"skill_focus": "add details to pictures",
                            "trigger": "magnify-close-up"},
            ),
        ]),
        new_user_message=(
            "I don't have that book. But can you tell me more about the "
            "\"magnify close up details\" lesson?"
        ),
        # request_type intentionally unspecified — COACHING or DEEPEN_PRIOR
        # both acceptable. Lock down the trigger + refers_to_prior.
        expected=TurnIntent(
            request_type=RequestType.COACHING,
            required_triggers=["magnify-close-up"],
            refers_to_prior=True,
        ),
    ),
    QUFixture(
        name="B18_scripted_lesson_for_magnify_K",
        description=(
            "Brady Turn 22: 'Can you give me a scripted lesson for this'. "
            "'This' = magnify-close-up, Kindergarten context. DEEPEN_PRIOR "
            "with skill inherited. Grade must be extractable from conversation "
            "('pictures' + prior context implies K-2)."
        ),
        conversation=_conversation([
            _user_turn(0, "How do I teach kindergarten students to add details to pictures?"),
            _assistant_turn(1, "Magnify close-up details lesson...",
                            structured={"skill_focus": "magnify-close-up",
                                        "trigger": "magnify-close-up"}),
            _user_turn(2, "Tell me more about it"),
            _assistant_turn(3, "It's a Smekens strategy where...",
                            structured={"skill_focus": "magnify-close-up"}),
        ]),
        new_user_message="Can you give me a scripted lesson for this",
        expected=TurnIntent(
            request_type=RequestType.DEEPEN_PRIOR,
            grade=GradeSpec(value="K", stated_explicit=True, stated_turn=0),
            skill=SkillSpec(
                canonical="magnify-close-up",
                as_stated="magnify close-up details",
            ),
            refers_to_prior=True,
        ),
    ),
]


# ----------------------------------------------------------------------
# Edge-case fixtures — hard cases not covered by the sample chat replay
# ----------------------------------------------------------------------

EDGE_CASES: list[QUFixture] = [
    QUFixture(
        name="E01_correction_grade",
        description=(
            "User explicitly corrects grade. CORRECTION request_type. "
            "The corrected grade must appear in the intent."
        ),
        conversation=_conversation([
            _user_turn(0, "Give me a transitions lesson for 3rd grade"),
            _assistant_turn(1, "Scripted ML for 3rd grade transitions...",
                            structured={"skill_focus": "transitions", "grade": "3"}),
        ]),
        new_user_message="Actually wait, make it 4th grade.",
        expected=TurnIntent(
            request_type=RequestType.CORRECTION,
            grade=GradeSpec(value="4", stated_explicit=True),
            skill=SkillSpec(
                canonical="transitions",
                as_stated="transitions",
            ),
            refers_to_prior=True,
            prior_turn_ref=1,
        ),
    ),
    QUFixture(
        name="E02_grade_band_triggers_missing_required",
        description=(
            "User uses band term 'upper elementary'. QU should output the "
            "band value AND add 'grade' to missing_required (need specific "
            "grade within band)."
        ),
        conversation=_conversation([]),
        new_user_message="Give me a scripted lesson on topic sentences for upper elementary",
        expected=TurnIntent(
            request_type=RequestType.SCRIPTED_ML,
            grade=GradeSpec(value="3-5", stated_explicit=True),
            skill=SkillSpec(
                canonical="topic sentences",
                as_stated="topic sentences",
            ),
            missing_required=["grade"],
        ),
    ),
    QUFixture(
        name="E03_greeting_is_META",
        description="Simple greeting — META, no extraction needed.",
        conversation=_conversation([]),
        new_user_message="Hi!",
        expected=TurnIntent(request_type=RequestType.META),
    ),
    QUFixture(
        name="E04_named_trigger_extraction",
        description=(
            "User names 'slinky test' — required_triggers should include "
            "'slinky-test' (canonical form). 'Tell me about X lesson' can "
            "route to either COACHING (explainer) or HOW_TO_TEACH (guide to "
            "teaching) — both acceptable. Load-bearing: required_triggers "
            "must contain slinky-test."
        ),
        conversation=_conversation([]),
        new_user_message="Tell me about the slinky test lesson",
        expected=TurnIntent(
            request_type=RequestType.COACHING,
            required_triggers=["slinky-test"],
            skill=SkillSpec(
                canonical="slinky-test",
                as_stated="slinky test",
            ),
        ),
    ),
    QUFixture(
        name="E05_management_routines",
        description=(
            "Classroom management question — MANAGEMENT request_type, not "
            "HOW_TO_TEACH (no specific writing skill)."
        ),
        conversation=_conversation([]),
        new_user_message=(
            "How do I set up writing workshop routines at the start of the year?"
        ),
        expected=TurnIntent(request_type=RequestType.MANAGEMENT),
    ),
    QUFixture(
        name="E06_banned_word_activity_still_parses_normally",
        description=(
            "User uses 'activity' in their query. QU doesn't care (banned "
            "words are a RESPONSE rule, not an input rule). Extract normally. "
            "Load-bearing: request_type + grade; skill canonical can be "
            "'supporting details' or similar — don't strict-match."
        ),
        conversation=_conversation([]),
        new_user_message="What activities can I do with my 3rd graders for detail?",
        expected=TurnIntent(
            request_type=RequestType.HOW_TO_TEACH,
            grade=GradeSpec(value="3", stated_explicit=True),
            # skill canonical flexible
        ),
    ),
    QUFixture(
        name="E07_off_topic_is_META",
        description="Non-writing query → META.",
        conversation=_conversation([]),
        new_user_message="What's the weather today?",
        expected=TurnIntent(request_type=RequestType.META),
    ),
    QUFixture(
        name="E08_scope_creep_two_skills_one_lesson",
        description=(
            "S3 one-skill guard: teacher crams a SECOND distinct skill into "
            "ONE mini-lesson ('topic sentences AND transitions'). These are "
            "two co-equal, each-a-full-lesson skills, so QU flags scope creep "
            "— PRIMARY skill = topic sentences (named first), the EXTRA skill "
            "named in additional_skills. Contrast B03 ('topic sentence and "
            "supporting details') which is ONE skill → additional_skills "
            "empty. Downstream the dispatch gate prepends Brady's guard and "
            "generates on the primary skill only."
        ),
        conversation=_conversation([]),
        new_user_message="Give me one 3rd-grade lesson on topic sentences and transitions",
        expected=TurnIntent(
            request_type=RequestType.SCRIPTED_ML,
            grade=GradeSpec(value="3", stated_explicit=True),
            skill=SkillSpec(
                canonical="topic sentences",
                as_stated="topic sentences",
            ),
            additional_skills=["transitions"],
        ),
    ),
]


ALL_FIXTURES: list[QUFixture] = BRADY_SAMPLE_CHAT + EDGE_CASES
