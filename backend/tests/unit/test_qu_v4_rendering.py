"""Unit tests for QU v4 prompt + message rendering.

These tests verify the PROMPT CONSTRUCTION logic — no LLM call. The
LLM's actual behavior is tested separately in acceptance tests that
hit the real API.
"""

from __future__ import annotations

import pytest

from query.qu_v4 import _build_messages, _render_conversation, _render_handshakes
from query.qu_v4_prompt import SYSTEM_PROMPT, get_system_prompt
from schemas import (
    ChunkRef,
    Conversation,
    PendingMLConfirmation,
    Quality,
    Role,
    SessionHandshakes,
    Turn,
)


# ----------------------------------------------------------------------
# System prompt — structural expectations
# ----------------------------------------------------------------------


def test_system_prompt_nonempty_and_cached() -> None:
    """System prompt returns non-empty string; get_system_prompt is
    idempotent (same instance returned each call — cache-friendly)."""
    first = get_system_prompt()
    second = get_system_prompt()
    assert first
    assert first is second  # same string reference
    assert first is SYSTEM_PROMPT


def test_system_prompt_contains_all_nine_request_types() -> None:
    """The 9 request_types must all appear in the prompt's decision
    tree. If one's removed the prompt drifts silently from schema."""
    expected_types = {
        "CORRECTION", "DEEPEN_PRIOR", "META", "SCRIPTED_ML",
        "HOW_TO_TEACH", "PLAN_UNIT", "THINK_ALOUD", "MANAGEMENT",
        "COACHING",
    }
    for rt in expected_types:
        assert rt in SYSTEM_PROMPT, f"request_type {rt!r} missing from prompt"


def test_system_prompt_warns_against_meta_technique_as_skill() -> None:
    """The Turn 5 bug fix — the prompt MUST explicitly block
    meta-techniques from being emitted as skill."""
    # Each of the core meta-techniques must appear with a prohibition
    for term in ("think-aloud", "mini-lesson", "turn-and-talk"):
        assert term in SYSTEM_PROMPT, (
            f"Prompt must mention {term!r} as a meta-technique "
            f"(never a skill)"
        )


def test_system_prompt_includes_grade_enum_values() -> None:
    """Prompt must tell the LLM the valid grade enum values. If the
    schema Literal changes without the prompt being updated, this
    catches it."""
    # Spot-check a sampling of grade values
    for g in ("K", "3", "K-2", "3-5", "6-8", "9-12"):
        assert g in SYSTEM_PROMPT, f"grade value {g!r} missing from prompt"


def test_system_prompt_references_canonical_triggers() -> None:
    """The trigger list must include Brady's priority triggers."""
    for trigger in ("pizza-table", "road-sign", "slinky-test",
                    "magnify-close-up", "dissected-web"):
        assert trigger in SYSTEM_PROMPT, (
            f"trigger {trigger!r} missing from prompt canonical list"
        )


def test_system_prompt_has_examples_section() -> None:
    """Few-shot examples are load-bearing for QU reliability. Must exist."""
    assert "EXAMPLES" in SYSTEM_PROMPT
    assert "Example 1" in SYSTEM_PROMPT or "### Example" in SYSTEM_PROMPT


def test_system_prompt_defines_additional_skills_scope_creep_rule() -> None:
    """S3 one-skill guard: QU is the only layer that can see 'two skills
    were requested' (a handler receives a single primary skill). The
    prompt MUST define the additional_skills signal, or the field goes
    dark and the guard never fires. The rule is genuine semantic
    judgment — it must NOT be reducible to keyword matching, so it must
    also warn against firing on 'and'/'also'/'add' wording (the B03
    false-positive killer: 'topic sentences and supporting details' is
    ONE skill)."""
    assert "additional_skills" in SYSTEM_PROMPT, (
        "prompt must define the additional_skills scope-creep signal"
    )
    # The one-skill-per-mini-lesson principle must be stated.
    assert "one skill" in SYSTEM_PROMPT.lower(), (
        "prompt must state the one-skill-per-mini-lesson principle"
    )
    # Must inoculate against the token-keying overfit (judge by meaning).
    lowered = SYSTEM_PROMPT.lower()
    assert "and" in lowered and "meaning" in lowered, (
        "rule must tell QU to judge by meaning, not by 'and'/'also' wording"
    )


def test_system_prompt_additional_skills_has_two_calibrating_examples() -> None:
    """The rule ships with EXACTLY the two few-shot it needs to hold the
    boundary: one true scope-creep (populate) and one tricky negative
    (empty). The negative is the load-bearing one — it holds Brady's B03
    happy-path golden ('supporting details' is part of the topic-sentence
    lesson, not a second lesson)."""
    # Scope-creep positive: a genuine second skill appears alongside the
    # primary and is named in additional_skills.
    assert 'additional_skills=["' in SYSTEM_PROMPT, (
        "prompt must show a populated additional_skills example (scope creep)"
    )
    # Negative: a compound single-skill phrase resolves to empty.
    assert "additional_skills=[]" in SYSTEM_PROMPT, (
        "prompt must show an empty additional_skills example (single skill)"
    )
    assert "supporting details" in SYSTEM_PROMPT, (
        "negative few-shot must anchor on the topic-sentences/supporting-"
        "details boundary (Brady's B03 golden must never fire the guard)"
    )


def test_system_prompt_defines_subgroup_acronym_glossary() -> None:
    """SG1 (Brady 56:00): QU must recognize the four named subgroup acronyms
    as WHO-the-learners-are context (not a grade, not the writing skill, not
    an unknown to clarify), so it stops mis-handling 'my SPED students'. The
    glossary must name all four families and the `unknown_subgroup_acronym`
    signal it populates for an UNRECOGNIZED subgroup acronym."""
    # All four named acronym families must appear so QU treats them as known.
    for ac in ("SPED", "MLL", "EL", "RTI"):
        assert ac in SYSTEM_PROMPT, (
            f"subgroup acronym {ac!r} missing from QU glossary"
        )
    # Framing: these are subgroups (who the learners are), not grades/skills.
    assert "subgroup" in SYSTEM_PROMPT.lower(), (
        "prompt must frame the acronyms as subgroup context"
    )
    # The QU-extracted signal for an unrecognized acronym must be defined,
    # or the field goes dark and the clarify path never fires.
    assert "unknown_subgroup_acronym" in SYSTEM_PROMPT, (
        "prompt must define the unknown_subgroup_acronym signal"
    )


def test_system_prompt_defines_writing_level_and_subgroup() -> None:
    """SG2 (Brady 57:30): for a subgroup / early writer, grade matters less than
    the current WRITING LEVEL. QU must (a) extract writing_level as the stated
    developmental stage and (b) set subgroup for a RECOGNIZED family — the two
    signals that drive the stage-threaded generation and the writing-level ask.
    The prompt must define both signals and name the four developmental stages."""
    lowered = SYSTEM_PROMPT.lower()
    # Both QU-extracted signals must be named, or the fields go dark.
    assert "writing_level" in SYSTEM_PROMPT, (
        "QU prompt must define the writing_level signal"
    )
    assert "subgroup" in lowered
    # The four developmental stages Brady named — QU maps phrasing to one.
    for stage in ("picture", "label", "word", "sentence"):
        assert stage in lowered, f"writing stage {stage!r} missing from QU prompt"
    # Brady's rationale: for a subgroup, grade level matters less than the stage.
    assert "writing level" in lowered


def test_system_prompt_has_unknown_acronym_generic_rule() -> None:
    """The generic (non-overfit) rule: for a subgroup-like acronym NOT in the
    named glossary, set unknown_subgroup_acronym so the app asks what it stands
    for — because each state uses different names/acronyms for the same
    subgroups (Brady's exact rationale)."""
    lowered = SYSTEM_PROMPT.lower()
    # Must reference recognizing vs. NOT recognizing the acronym.
    assert "acronym" in lowered
    # Must carry Brady's rationale that acronyms vary by state, so QU knows
    # WHY an unrecognized one is asked about rather than guessed.
    assert "state" in lowered and "different" in lowered, (
        "prompt must state each state uses different subgroup acronyms"
    )


def test_system_prompt_recognizes_unit_outline_drilldown_e6() -> None:
    """E6 (Brady 05:15, doc 34-35): Brady's flow is "Plan a unit" -> priority
    skills -> "Would you like a general outline of this unit?" -> a HOW_TO_TEACH
    outline -> scripted ML. This locks the DRILL-DOWN recognition: after the
    priority-skill list, a teacher who asks for a "general outline of this unit"
    (or "outline the whole unit") wants the UNIT-LEVEL instructional outline ->
    route to HOW_TO_TEACH (reuse the outline handler). It must NOT re-run
    PLAN_UNIT (re-list the skills) and must NOT be swallowed by OFFERED-SKILL
    PICKUP as an ambiguous 'pick' (-> ASK). Routing is purely by the
    request_type QU emits, so the recognition MUST live in this prompt.

    NOTE: additive recognition only — the PLAN_UNIT closer (E5b) lives in
    handlers/plan_unit.py and is deliberately NOT changed here; its dedicated
    ending tests (test_endings / test_protected_deterministic /
    test_handlers_stage4_prompts) stay green as proof."""
    lowered = SYSTEM_PROMPT.lower()
    # Brady's drill-down phrase must be recognized. Absent before E6 -> real RED.
    assert "general outline" in lowered, (
        "QU prompt must recognize the 'general outline of this unit' request"
    )
    # Framed as a UNIT-LEVEL outline (the whole unit just planned), not a fresh
    # single-skill HOW_TO_TEACH — so the intent generalizes past Brady's words.
    assert "unit-level outline" in lowered, (
        "recognition must frame the drill-down as a unit-level outline"
    )
    # The E6 decision: route the drill-down to HOW_TO_TEACH. Assert it appears
    # NEAR the recognition, not merely somewhere else in the prompt.
    idx = lowered.index("general outline")
    window = SYSTEM_PROMPT[max(0, idx - 240): idx + 480]
    assert "HOW_TO_TEACH" in window, (
        "the 'general outline' recognition must route to HOW_TO_TEACH"
    )
    # Inoculate against the two failure modes it replaces: re-listing the
    # priority skills (re-running PLAN_UNIT), and the ambiguous offered-skill
    # pick that would ASK. Both concepts must be named in the note.
    assert "re-list" in lowered, (
        "recognition must tell QU NOT to re-list the priority skills"
    )


# ----------------------------------------------------------------------
# _render_conversation — flatten conversation to LLM-readable text
# ----------------------------------------------------------------------


def _user(index: int, text: str) -> Turn:
    return Turn(index=index, role=Role.USER, text=text)


def _asst(index: int, text: str, structured: dict | None = None,
          quality: Quality = Quality.VALID,
          offered_skills: list[str] | None = None) -> Turn:
    return Turn(index=index, role=Role.ASSISTANT, text=text,
                structured=structured or None, quality=quality,
                offered_skills=list(offered_skills or []))


def test_render_conversation_empty() -> None:
    conv = Conversation(session_id="s1")
    rendered = _render_conversation(conv)
    assert rendered == ""


def test_render_conversation_basic_turns() -> None:
    conv = Conversation(session_id="s1")
    conv.append(_user(0, "How do I teach paragraphs?"))
    conv.append(_asst(1, "Pizza-table outline..."))
    rendered = _render_conversation(conv)

    assert "Turn 0" in rendered
    assert "USER" in rendered
    assert "How do I teach paragraphs?" in rendered
    assert "Turn 1" in rendered
    assert "ASSISTANT" in rendered
    assert "Pizza-table outline" in rendered


def test_render_conversation_includes_structured_fields() -> None:
    """For assistant turns with structured bodies, QU needs to see
    skill_focus for DEEPEN_PRIOR inheritance. Rendering must surface it.

    HISTORY: this test used to hand-write an "offered_skills" key into
    `structured` and assert the renderer forwarded it. NO production code has
    ever written that key — the test fabricated the field and then proved the
    pipe carried it, which is how an inert field stayed green for months while
    "number 4" silently resolved to item 3. The real list now lives on
    Turn.offered_skills; see the test below.
    """
    conv = Conversation(session_id="s1")
    conv.append(_user(0, "How do I teach report writing?"))
    conv.append(_asst(
        1,
        "Four essential skills for reports...",
        structured={
            "skill_focus": "report writing",
            "trigger": "read-find-say-jot",
        },
    ))
    rendered = _render_conversation(conv)

    assert "skill_focus" in rendered
    assert "report writing" in rendered
    assert "read-find-say-jot" in rendered


def test_render_conversation_shows_the_offered_pick_list() -> None:
    """The list QU resolves a pick against comes from the real field that
    production actually populates — not from a key inside `structured`."""
    conv = Conversation(session_id="s1")
    conv.append(_user(0, "How do I teach report writing?"))
    conv.append(_asst(
        1,
        "Four essential skills for reports...",
        offered_skills=["collect facts", "jot notes", "organize"],
    ))
    rendered = _render_conversation(conv)

    assert "offered_skills" in rendered
    assert "collect facts" in rendered


def test_render_ignores_a_fabricated_offered_skills_key_in_structured() -> None:
    """One home for the pick-list. Honouring a `structured` key nothing
    writes would re-open the two-sources-of-truth gap this replaced."""
    conv = Conversation(session_id="s1")
    conv.append(_asst(0, "outline...",
                      structured={"offered_skills": ["ghost item"]}))
    assert "ghost item" not in _render_conversation(conv)


def test_render_conversation_shows_low_quality() -> None:
    """A LOW-quality turn should be labeled so QU knows not to treat
    the prior response's structured fields as canonical."""
    conv = Conversation(session_id="s1")
    conv.append(_user(0, "Lesson on X"))
    conv.append(_asst(1, "Shallow lesson", structured={"skill_focus": "X"},
                      quality=Quality.LOW))
    rendered = _render_conversation(conv)
    assert "quality=low" in rendered.lower()


# ----------------------------------------------------------------------
# _render_handshakes
# ----------------------------------------------------------------------


def test_render_handshakes_empty() -> None:
    h = SessionHandshakes()
    assert _render_handshakes(h) == ""


def test_render_handshakes_ml_confirmation() -> None:
    h = SessionHandshakes(
        ml_confirmation=PendingMLConfirmation(
            skill="topic sentences", grade="3", mode="Inform", asked_at_turn=4
        )
    )
    rendered = _render_handshakes(h)
    assert "ML confirmation pending" in rendered
    assert "topic sentences" in rendered
    assert "3" in rendered


# ----------------------------------------------------------------------
# _build_messages — end-to-end message construction
# ----------------------------------------------------------------------


def test_build_messages_order_system_first_user_second() -> None:
    """Caching requires system first, user with history+message second."""
    conv = Conversation(session_id="s1")
    conv.append(_user(0, "prior turn"))
    conv.append(_asst(1, "prior response"))

    msgs = _build_messages(
        conversation=conv,
        new_user_message="new message",
        handshakes=SessionHandshakes(),
    )

    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert msgs[0]["content"] == SYSTEM_PROMPT


def test_build_messages_user_content_includes_history_and_new_message() -> None:
    conv = Conversation(session_id="s1")
    conv.append(_user(0, "prior message from user"))

    msgs = _build_messages(
        conversation=conv,
        new_user_message="the NEW user message",
        handshakes=SessionHandshakes(),
    )
    user_content = msgs[1]["content"]

    assert "CONVERSATION HISTORY" in user_content
    assert "prior message from user" in user_content
    assert "NEW USER MESSAGE" in user_content
    assert "the NEW user message" in user_content


def test_build_messages_empty_history_skips_history_section() -> None:
    """First turn in a session: no history to render. User content
    jumps straight to NEW USER MESSAGE. No stale 'CONVERSATION HISTORY'
    header that would confuse the model."""
    conv = Conversation(session_id="s1")

    msgs = _build_messages(
        conversation=conv,
        new_user_message="first message",
        handshakes=SessionHandshakes(),
    )
    user_content = msgs[1]["content"]

    assert "CONVERSATION HISTORY" not in user_content
    assert "NEW USER MESSAGE" in user_content
    assert "first message" in user_content


def test_build_messages_includes_handshakes_when_set() -> None:
    conv = Conversation(session_id="s1")
    handshakes = SessionHandshakes(
        ml_confirmation=PendingMLConfirmation(
            skill="transitions", grade="3", asked_at_turn=0
        )
    )
    msgs = _build_messages(
        conversation=conv,
        new_user_message="yes please",
        handshakes=handshakes,
    )
    user_content = msgs[1]["content"]
    assert "PENDING HANDSHAKES" in user_content
    assert "ML confirmation pending" in user_content
    assert "transitions" in user_content


def test_build_messages_instruction_mentions_current_turn_index() -> None:
    """The instruction tells the LLM what turn index to use for
    stated_turn provenance. Exact turn index matters for DEEPEN_PRIOR
    prior_turn_ref semantics."""
    conv = Conversation(session_id="s1")
    for i in range(4):
        turn = _user(i, f"turn {i}") if i % 2 == 0 else _asst(i, f"response {i}")
        conv.append(turn)

    msgs = _build_messages(
        conversation=conv,
        new_user_message="new",
        handshakes=SessionHandshakes(),
    )
    user_content = msgs[1]["content"]
    assert "turn index would be 4" in user_content.lower()
