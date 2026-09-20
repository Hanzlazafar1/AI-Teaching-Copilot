"""Unit tests for multi-lesson sequence tracking in plan_unit."""

try:
    import pytest
except ImportError:
    pytest = None
from handlers.plan_unit import _extract_lesson_count
from schemas import Conversation, Role, Turn


def test_extract_lesson_count():
    assert _extract_lesson_count("give me the 10 days lesson plan") == 10
    assert _extract_lesson_count("5 day unit plan") == 5
    assert _extract_lesson_count("give me the one week lesson plan") == 5
    assert _extract_lesson_count("giv eme the one week plan") == 5
    assert _extract_lesson_count("7 days plan") == 7
    assert _extract_lesson_count("one month plan") == 20
    assert _extract_lesson_count("five-day unit plan") == 5
    assert _extract_lesson_count("2-week plan") == 10
    assert _extract_lesson_count("persuasive") is None
    assert _extract_lesson_count("150-day plan") is None  # > 30 caps out


def test_trim_plan_to_lesson_count():
    from handlers.plan_unit import _trim_plan_to_lesson_count

    raw_text = (
        "Grade 5 | Persuasive\n\n"
        "For 5 persuasive writing, here are the priority skills in order:\n\n"
        "1. Skill 1\n"
        "2. Skill 2\n"
        "3. Skill 3\n"
        "4. Skill 4\n"
        "5. Skill 5\n"
        "6. Skill 6\n"
        "7. Skill 7\n"
        "8. Skill 8\n"
        "9. Skill 9\n"
        "10. Skill 10\n\n"
        "These are taught in mini-units of 1-2 weeks each...\n\n"
        "Is this helpful? Would you like a general outline of this unit?"
    )

    trimmed = _trim_plan_to_lesson_count(raw_text, 5)
    assert "1. Skill 1" in trimmed
    assert "5. Skill 5" in trimmed
    assert "6. Skill 6" not in trimmed
    assert "10. Skill 10" not in trimmed
    assert "These are taught in mini-units" in trimmed


def test_plan_unit_build_prompt_includes_lesson_count_from_new_user_message():
    from handlers.plan_unit import _build_prompt
    from schemas import RequestType, TurnIntent

    intent = TurnIntent(request_type=RequestType.PLAN_UNIT)
    conv = Conversation(session_id="test-123", turns=[])
    
    prompt = _build_prompt(intent, "", conv, None, new_user_message="giv eme the one week plan")
    assert "=== LESSON COUNT / PLAN DURATION ===" in prompt
    assert "5-lesson / 5-day plan" in prompt
    assert "EXACTLY 5 priority skills/lessons" in prompt



def test_extract_lesson_count_from_conversation():
    conv = Conversation(
        session_id="test-123",
        turns=[
            Turn(
                index=0,
                role=Role.USER,
                text="give me the 10 days lesson plan for 1st grade students",
            ),
            Turn(
                index=1,
                role=Role.ASSISTANT,
                text="Are you preparing for a persuasive, informative, or narrative unit?",
            ),
        ],
    )
    new_msg = "persuasive"

    count = _extract_lesson_count(new_msg)
    if count is None and conv and conv.turns:
        for turn in reversed(conv.turns):
            if turn.role.value == "user" and turn.text:
                c = _extract_lesson_count(turn.text)
                if c is not None:
                    count = c
                    break

    assert count == 10


def test_apply_lesson_sequence_continuation_respects_intervening_turn():
    from canonicalizer import get_canonicalizer
    from query.qu_v4 import apply_lesson_sequence_continuation
    from schemas import PendingLessonSequence, RequestType, SessionHandshakes, TurnIntent

    seq = PendingLessonSequence(
        skills=["Skill A", "Skill B"],
        total=2,
        current_index=0,
        grade="4",
        started_at_turn=0,
    )
    handshakes = SessionHandshakes(lesson_sequence=seq)
    canon = get_canonicalizer()
    base_intent = TurnIntent(request_type=RequestType.COACHING)

    # 1. When last assistant turn WAS sequence prompt -> yes triggers continuation
    conv_seq = Conversation(
        session_id="s1",
        turns=[
            Turn(
                index=0,
                role=Role.ASSISTANT,
                text="That's Lesson 1 of 2. Ready for Lesson 2 — Skill B?",
            )
        ],
    )
    res1 = apply_lesson_sequence_continuation(base_intent, "yes", handshakes, canon, conv_seq)
    assert res1.request_type == RequestType.SCRIPTED_ML
    assert res1.skill is not None and res1.skill.as_stated == "Skill B"

    # 2. When last assistant turn WAS A COACHING QUESTION -> yes does NOT trigger sequence continuation
    conv_coaching = Conversation(
        session_id="s1",
        turns=[
            Turn(
                index=0,
                role=Role.ASSISTANT,
                text="Would you like me to map out a 3-day mini-lesson sequence for teaching one persuasive paragraph?",
            )
        ],
    )
    res2 = apply_lesson_sequence_continuation(base_intent, "yes", handshakes, canon, conv_coaching)
    assert res2.request_type == RequestType.COACHING


def test_plan_unit_build_prompt_includes_lesson_count():
    from handlers.plan_unit import _build_prompt
    from schemas import RequestType, TurnIntent

    intent = TurnIntent(request_type=RequestType.PLAN_UNIT)
    conv = Conversation(
        session_id="test-123",
        turns=[
            Turn(
                index=0,
                role=Role.USER,
                text="give me the ten days plan for teaching",
            ),
            Turn(
                index=1,
                role=Role.ASSISTANT,
                text="Are you preparing for a persuasive, informative, or narrative unit?",
            ),
        ],
    )
    prompt = _build_prompt(intent, "", conv, None)
    assert "EXACTLY 10 priority skills/lessons" in prompt


def test_new_skill_request_clears_stale_lesson_sequence():
    from canonicalizer import get_canonicalizer
    from query.qu_v4 import apply_lesson_sequence_continuation
    from schemas import PendingLessonSequence, RequestType, SessionHandshakes, SkillSpec, TurnIntent

    seq = PendingLessonSequence(
        skills=["Paragraphing - Main Idea", "Paragraphing - Supporting Details"],
        total=2,
        current_index=0,
        grade="4",
        started_at_turn=0,
    )
    handshakes = SessionHandshakes(lesson_sequence=seq)
    canon = get_canonicalizer()

    # When user explicitly asks for a NEW skill (e.g. "transitions"), sequence continuation must NOT override it
    new_intent = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        skill=SkillSpec(canonical="transitions", as_stated="transition words"),
    )
    res = apply_lesson_sequence_continuation(new_intent, "can you give me a lesson on transition words?", handshakes, canon)
    assert res.skill.as_stated == "transition words"
    assert res.skill.canonical == "transitions"


def test_sequence_continuation_on_phrased_request_with_intervening_turn():
    from canonicalizer import get_canonicalizer
    from query.qu_v4 import apply_lesson_sequence_continuation
    from schemas import PendingLessonSequence, RequestType, SessionHandshakes, TurnIntent

    seq = PendingLessonSequence(
        skills=["Topic Sentences", "Supporting Details", "Transitions"],
        total=3,
        current_index=0,
        grade="4",
        started_at_turn=0,
    )
    handshakes = SessionHandshakes(lesson_sequence=seq)
    canon = get_canonicalizer()
    base_intent = TurnIntent(request_type=RequestType.SCRIPTED_ML)

    # Intervening turn where assistant answered a coaching question (not a sequence prompt)
    conv = Conversation(
        session_id="s1",
        turns=[
            Turn(
                index=0,
                role=Role.ASSISTANT,
                text="Here is some coaching guidance on teaching paragraphs with mentor texts.",
            )
        ],
    )

    # Teacher explicitly asks for the next lesson plan
    res = apply_lesson_sequence_continuation(
        base_intent,
        "generate the next lesson plan for the next skill",
        handshakes,
        canon,
        conv,
    )
    assert res.request_type == RequestType.SCRIPTED_ML
    assert res.skill is not None
    assert res.skill.as_stated == "Supporting Details"
    assert res.skill.canonical == canon.canonicalize_skill("Supporting Details")


def test_current_lesson_revision_preserves_sequence_in_scripted_ml():
    from handlers.scripted_ml import _finalize_ml_delivery
    from schemas import PendingLessonSequence, Quality, RequestType, SessionHandshakes, SkillSpec, TurnIntent, TurnOutcome

    seq = PendingLessonSequence(
        skills=["Main Idea", "Supporting Details"],
        total=2,
        current_index=0,
        grade="4",
        started_at_turn=0,
    )
    handshakes = SessionHandshakes(lesson_sequence=seq)
    intent = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        skill=SkillSpec(canonical="main idea", as_stated="Main Idea"),
    )
    outcome = TurnOutcome(
        response_text="Script text",
        structured={"skill_focus": "Main Idea"},
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
    )

    # Delivering a revised version of Lesson 1 (Main Idea)
    finalized = _finalize_ml_delivery(outcome, intent, handshakes)
    assert finalized.handshake_updates is not None
    # Sequence should STILL be active at current_index=0!
    assert finalized.handshake_updates.lesson_sequence is not None
    assert finalized.handshake_updates.lesson_sequence.current_index == 0
    assert "revised Lesson 1 of 2" in finalized.structured["followup"]
    assert "Supporting Details" in finalized.structured["followup"]


def test_deictic_pointer_recognizes_skills_provided_above():
    from canonicalizer import get_canonicalizer
    from query.qu_v4 import _is_deictic_pointer, resolve_deictic_skill
    from schemas import RequestType, SkillSpec, TurnIntent

    canon = get_canonicalizer()
    assert _is_deictic_pointer("the skills you provide above", canon) is True
    assert _is_deictic_pointer("the skills above", canon) is True
    assert _is_deictic_pointer("the mentioned skills", canon) is True
    assert _is_deictic_pointer("topic sentences", canon) is False

    # Conversation with an assistant turn offering a list of skills
    conv = Conversation(
        session_id="s1",
        turns=[
            Turn(
                index=0,
                role=Role.ASSISTANT,
                text="Here are sub-skills:\n1. Topic sentences\n2. Supporting details",
                offered_skills=["Teach students to write topic sentences", "Teach students supporting details"],
            )
        ],
    )
    intent = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        skill=SkillSpec(canonical="the skills you provide above", as_stated="the skills you provide above"),
    )
    resolved = resolve_deictic_skill(intent, conv, canon)
    assert resolved.skill is not None
    # Should resolve to the primary skill offered in the previous turn
    assert resolved.skill.as_stated == "write topic sentences"

