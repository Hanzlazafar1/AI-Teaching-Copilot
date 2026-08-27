"""Smoke tests for Layer 1 + Layer 2 schemas.

These don't test behavior (there is none — schemas are pure data) but
they lock the public API so downstream code can rely on field names,
enum values, and basic invariants like index monotonicity.
"""

from __future__ import annotations

import pytest

from schemas import (
    ChunkRef,
    Conversation,
    GradeSpec,
    ModeSpec,
    PendingClarification,
    PendingLibraryOffer,
    PendingMLConfirmation,
    Quality,
    RequestType,
    Role,
    SessionHandshakes,
    SkillSpec,
    TraitSpec,
    Turn,
    TurnIntent,
)


# ----------------------------------------------------------------------
# Intent schemas
# ----------------------------------------------------------------------


def test_request_type_has_nine_values() -> None:
    """The nine request types must exist. If someone adds/removes one
    without updating the dispatcher this test fails loudly."""
    expected = {
        "HOW_TO_TEACH",
        "SCRIPTED_ML",
        "PLAN_UNIT",
        "THINK_ALOUD",
        "DEEPEN_PRIOR",
        "COACHING",
        "MANAGEMENT",
        "META",
        "CORRECTION",
    }
    assert {r.value for r in RequestType} == expected


def test_skill_spec_preserves_dual_representation() -> None:
    """SkillSpec must carry BOTH canonical (for retrieval) and
    as_stated (for teacher-facing skill_focus). This dual form directly
    fixes Brady's 'use my vocabulary' complaint."""
    skill = SkillSpec(
        canonical="topic sentences",
        as_stated="topic sentence and supporting details",
        stated_turn=3,
        confidence=0.95,
    )
    assert skill.canonical != skill.as_stated
    assert skill.canonical == "topic sentences"
    assert skill.as_stated == "topic sentence and supporting details"


def test_grade_spec_provenance_fields() -> None:
    g = GradeSpec(value="3", stated_explicit=True, stated_turn=1, confidence=1.0)
    assert g.value == "3"
    assert g.stated_explicit is True
    assert g.stated_turn == 1


@pytest.mark.parametrize(
    "valid_value",
    [
        "K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
        "K-2", "3-5", "6-8", "9-12", "K-12", "all",
    ],
)
def test_grade_spec_accepts_every_canonical_enum_value(valid_value: str) -> None:
    """Every value in the GradeValue Literal must be accepted. If this
    test fails, either the Literal drifted from the enum list in
    canonicalizer.GRADE_ENUM or a new grade value was added without
    updating both places."""
    GradeSpec(value=valid_value, stated_explicit=True)  # type: ignore


@pytest.mark.parametrize(
    "bad_value",
    [
        "3rd grade band",   # the Turn 6 hallucination phrasing
        "grade 3",          # teacher phrasing, not canonical form
        "third",            # word form, not canonical
        "elementary",       # vague
        "",                 # empty
        "13",               # out of range
        "K-5",              # not one of the four canonical bands
    ],
)
def test_grade_spec_rejects_non_canonical_values(bad_value: str) -> None:
    """GradeSpec is constrained to the Literal enum. Non-canonical
    values must fail Pydantic validation at construction time. This is
    the structural backstop for QU stochastic error."""
    with pytest.raises(Exception):
        GradeSpec(value=bad_value, stated_explicit=True)  # type: ignore


def test_mode_spec_accepts_all_canonical_modes() -> None:
    for v in ("Inform", "Persuade", "Entertain", "all"):
        ModeSpec(value=v, stated_explicit=True)


def test_trait_spec_accepts_six_traits_plus_all() -> None:
    for v in (
        "Ideas",
        "Organization",
        "Voice",
        "Word Choice",
        "Sentence Fluency",
        "Conventions",
        "all",
    ):
        TraitSpec(value=v, stated_explicit=True)


def test_turn_intent_minimal_construction() -> None:
    """TurnIntent should be constructible with only request_type —
    everything else defaults. Useful for META turns and error paths."""
    intent = TurnIntent(request_type=RequestType.META)
    assert intent.request_type is RequestType.META
    assert intent.grade is None
    assert intent.skill is None
    assert intent.refers_to_prior is False
    assert intent.required_triggers == []
    assert intent.missing_required == []
    # Confirmation handshake defaults to OFF — handlers generate
    # immediately unless QU explicitly requests confirmation.
    assert intent.needs_confirmation is False
    assert intent.confirmation_reason is None
    # S3 one-skill-guard scope-creep signal defaults EMPTY — the guard
    # is inert unless QU explicitly names a crammed-in second skill.
    assert intent.additional_skills == []


def test_turn_intent_additional_skills_defaults_empty() -> None:
    """S3 one-skill guard: additional_skills is the scope-creep signal.
    Its emptiness IS the boolean — the overwhelming default is empty,
    which keeps the guard totally inert and preserves back-compat
    (existing behavior unchanged on every turn that isn't scope creep)."""
    intent = TurnIntent(request_type=RequestType.SCRIPTED_ML)
    assert intent.additional_skills == []


def test_turn_intent_additional_skills_populated() -> None:
    """When a teacher crams a SECOND distinct skill into one lesson, QU
    names the EXTRA skill(s) here in the teacher's words; the PRIMARY
    skill still lives in `skill`. The dispatch gate reads this to prepend
    Brady's one-skill-per-mini-lesson guard before the primary lesson."""
    intent = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
        additional_skills=["transitions"],
    )
    assert intent.additional_skills == ["transitions"]
    # Primary skill is untouched — the guard fires on it, extras only name.
    assert intent.skill.canonical == "topic sentences"


def test_turn_intent_unknown_subgroup_acronym_defaults_none() -> None:
    """SG1 subgroup-acronym signal: unknown_subgroup_acronym is None by
    default (the overwhelming case — no acronym, or one QU recognizes).
    None keeps the acronym-clarify path totally inert (back-compat)."""
    intent = TurnIntent(request_type=RequestType.COACHING)
    assert intent.unknown_subgroup_acronym is None


def test_turn_intent_unknown_subgroup_acronym_populated() -> None:
    """When a teacher uses a subgroup-like acronym QU does NOT recognize
    (not SPED/MLL/EL/RTI), QU names that acronym here so the dispatch gate
    asks Brady's 'What does that acronym stand for?' question rather than a
    generic clarify. Presence IS the boolean — a non-empty string fires it."""
    intent = TurnIntent(
        request_type=RequestType.COACHING,
        unknown_subgroup_acronym="TAG",
    )
    assert intent.unknown_subgroup_acronym == "TAG"


def test_turn_intent_writing_level_defaults_none() -> None:
    """SG2 (Brady 57:30): writing_level is None by default. For a subgroup /
    early writer, QU captures the developmental WRITING LEVEL (picture / label
    / word / sentence) when the teacher states it; None keeps both the ask and
    the stage-threaded generation totally inert (back-compat)."""
    intent = TurnIntent(request_type=RequestType.HOW_TO_TEACH)
    assert intent.writing_level is None


def test_turn_intent_writing_level_populated() -> None:
    """When the teacher states the developmental stage, QU records it verbatim
    so it can thread into generation (frame each skill at that stage)."""
    intent = TurnIntent(
        request_type=RequestType.HOW_TO_TEACH,
        writing_level="label",
    )
    assert intent.writing_level == "label"


def test_turn_intent_subgroup_defaults_none() -> None:
    """SG2: subgroup is None by default — most turns are not for a named
    subgroup. None keeps the writing-level ask inert (back-compat)."""
    intent = TurnIntent(request_type=RequestType.COACHING)
    assert intent.subgroup is None


def test_turn_intent_subgroup_populated() -> None:
    """QU sets subgroup to the RECOGNIZED family (SPED/MLL/EL/RTI) the teacher
    named — the recognized-subgroup signal that (with no writing_level stated)
    drives Brady's 'what's their current writing level?' clarify."""
    intent = TurnIntent(
        request_type=RequestType.HOW_TO_TEACH,
        subgroup="SPED",
    )
    assert intent.subgroup == "SPED"


def test_turn_intent_expressed_frustration_defaults_false() -> None:
    """Brady C10 emotional-validation signal: expressed_frustration is False by
    default (the overwhelming case — the teacher is not venting). False keeps the
    shared validation splice totally inert in every handler, so a calm turn's
    prompt is byte-identical to before (back-compat)."""
    intent = TurnIntent(request_type=RequestType.HOW_TO_TEACH)
    assert intent.expressed_frustration is False


def test_turn_intent_expressed_frustration_populated() -> None:
    """When the teacher voices frustration / being stuck, QU sets this True. It
    is ORTHOGONAL to request_type: a frustrated "how do I teach X?" keeps
    request_type=HOW_TO_TEACH AND sets the flag, so the shared validation rule
    can splice in wherever the turn routes — not only COACHING."""
    intent = TurnIntent(
        request_type=RequestType.HOW_TO_TEACH,
        expressed_frustration=True,
    )
    assert intent.expressed_frustration is True
    # Orthogonal — the flag does not disturb routing.
    assert intent.request_type is RequestType.HOW_TO_TEACH


def test_turn_intent_confirmation_signal() -> None:
    """QU sets needs_confirmation when it sees real ambiguity — the
    handler reads this and emits PendingMLConfirmation instead of
    generating immediately. Brady's Turn 19 complaint: he picked
    'Snapple details' from a list and got silent generation without
    'so you want this skill, this grade, in 4-step ML format, correct?'"""
    intent = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        needs_confirmation=True,
        confirmation_reason=(
            "User picked 'Snapple details' from the offered skills list, "
            "but it wasn't on the list Co-Pilot just surfaced."
        ),
    )
    assert intent.needs_confirmation is True
    assert intent.confirmation_reason is not None
    assert "Snapple" in intent.confirmation_reason


def test_turn_intent_with_full_context() -> None:
    """Full-featured intent — the shape a well-specified SCRIPTED_ML
    turn would produce."""
    intent = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        grade=GradeSpec(value="3", stated_explicit=True, stated_turn=1),
        mode=ModeSpec(value="Inform", stated_explicit=True, stated_turn=1),
        trait=TraitSpec(value="Ideas", stated_explicit=False, confidence=0.7),
        skill=SkillSpec(
            canonical="topic sentences",
            as_stated="topic sentence and supporting details",
            stated_turn=2,
        ),
        required_triggers=["pizza-table"],
    )
    assert intent.skill.canonical == "topic sentences"
    assert "pizza-table" in intent.required_triggers


# ----------------------------------------------------------------------
# Turn / Conversation schemas
# ----------------------------------------------------------------------


def test_turn_minimal_user() -> None:
    t = Turn(index=0, role=Role.USER, text="How do I teach paragraph writing?")
    assert t.role is Role.USER
    assert t.quality is Quality.VALID  # default
    assert t.grounding == []


def test_turn_assistant_with_structured_body() -> None:
    t = Turn(
        index=1,
        role=Role.ASSISTANT,
        text="Here's a scripted mini-lesson...",
        structured={"skill_focus": "pizza table", "step_2b_show": "..."},
        grounding=[
            ChunkRef(
                chunk_id="lww312-s8-ml05",
                source_document="Launching 3-12",
                page_number=64,
            )
        ],
    )
    assert t.structured["skill_focus"] == "pizza table"
    assert len(t.grounding) == 1
    assert t.grounding[0].page_number == 64


def test_conversation_append_enforces_monotonic_index() -> None:
    """Conversation.append rejects out-of-order indices to protect
    the 'conversation history is the source of truth' invariant."""
    conv = Conversation(session_id="s1")
    conv.append(Turn(index=0, role=Role.USER, text="hi"))
    conv.append(Turn(index=1, role=Role.ASSISTANT, text="hello"))

    with pytest.raises(ValueError, match="does not match expected 2"):
        conv.append(Turn(index=5, role=Role.USER, text="skipped ahead"))


def test_conversation_last_assistant_turn_when_empty() -> None:
    conv = Conversation(session_id="s1")
    assert conv.last_assistant_turn() is None


def test_conversation_last_assistant_turn_finds_most_recent() -> None:
    conv = Conversation(session_id="s1")
    conv.append(Turn(index=0, role=Role.USER, text="q1"))
    conv.append(Turn(index=1, role=Role.ASSISTANT, text="a1"))
    conv.append(Turn(index=2, role=Role.USER, text="q2"))
    conv.append(Turn(index=3, role=Role.ASSISTANT, text="a2"))

    last = conv.last_assistant_turn()
    assert last is not None
    assert last.index == 3
    assert last.text == "a2"


def test_conversation_last_scripted_ml_turn_skips_non_ml_responses() -> None:
    """last_scripted_ml_turn must find the most recent VALID scripted
    ML (has skill_focus), skipping non-ML assistant turns in between."""
    conv = Conversation(session_id="s1")
    conv.append(Turn(index=0, role=Role.USER, text="q1"))
    conv.append(
        Turn(
            index=1,
            role=Role.ASSISTANT,
            text="outline text",
            structured={"skills": ["topic sentences"]},  # HOW_TO_TEACH shape
        )
    )
    conv.append(Turn(index=2, role=Role.USER, text="q2"))
    conv.append(
        Turn(
            index=3,
            role=Role.ASSISTANT,
            text="scripted lesson body",
            structured={
                "skill_focus": "topic sentences",
                "step_2b_show": "...",
            },  # SCRIPTED_ML shape
        )
    )
    conv.append(Turn(index=4, role=Role.USER, text="q3"))
    conv.append(Turn(index=5, role=Role.ASSISTANT, text="meta ack", structured=None))

    last_ml = conv.last_scripted_ml_turn()
    assert last_ml is not None
    assert last_ml.index == 3


def test_conversation_last_scripted_ml_turn_skips_low_quality() -> None:
    """Low-quality scripted MLs must NOT be treated as the canonical
    prior lesson. DEEPEN_PRIOR should pull from the most recent VALID
    scripted ML, never from one that failed validation."""
    conv = Conversation(session_id="s1")
    conv.append(Turn(index=0, role=Role.USER, text="q"))
    conv.append(
        Turn(
            index=1,
            role=Role.ASSISTANT,
            text="bad ml",
            structured={"skill_focus": "topic sentences", "step_2b_show": "thin"},
            quality=Quality.LOW,
        )
    )
    conv.append(Turn(index=2, role=Role.USER, text="q2"))
    conv.append(
        Turn(
            index=3,
            role=Role.ASSISTANT,
            text="good ml",
            structured={"skill_focus": "transitions", "step_2b_show": "deep"},
            quality=Quality.VALID,
        )
    )

    last_ml = conv.last_scripted_ml_turn()
    assert last_ml is not None
    assert last_ml.structured["skill_focus"] == "transitions"


# ----------------------------------------------------------------------
# SessionHandshakes
# ----------------------------------------------------------------------


def test_handshakes_default_empty() -> None:
    h = SessionHandshakes()
    assert h.is_empty()
    assert h.library_offer is None
    assert h.ml_confirmation is None
    assert h.clarification is None


def test_handshakes_not_empty_when_offer_set() -> None:
    h = SessionHandshakes(
        library_offer=PendingLibraryOffer(
            ml_id="lib-abc", skill="magnify close-up", grade="K", offered_at_turn=0
        )
    )
    assert not h.is_empty()


def test_handshakes_clarification_field_is_literal() -> None:
    """PendingClarification.waiting_for must reject invalid values."""
    # valid
    PendingClarification(waiting_for="grade", asked_at_turn=0)
    # invalid — expects pydantic validation error
    with pytest.raises(Exception):
        PendingClarification(waiting_for="nonsense", asked_at_turn=0)  # type: ignore


def test_handshakes_clear_returns_empty() -> None:
    h = SessionHandshakes(
        ml_confirmation=PendingMLConfirmation(
            skill="topic sentences", grade="3", asked_at_turn=0
        )
    )
    assert not h.is_empty()
    cleared = h.clear()
    assert cleared.is_empty()
