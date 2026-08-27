"""TurnIntent — the Layer 2 output that drives everything downstream.

QU reads the full conversation and produces a TurnIntent that completely
specifies what THIS turn needs. No separate session ledger, no rules
layer. Handlers consume TurnIntent directly to derive retrieval params
and prompt content.

Every field has provenance (stated_turn, stated_explicit, confidence)
so handlers and prompts can tell the model what the teacher already
said and when.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class RequestType(str, Enum):
    """The nine pedagogical intents a turn can have.

    Each value dispatches to its own handler. See Section 4 of
    QU-DRIVEN-DESIGN.md for the decision rules QU uses.
    """

    HOW_TO_TEACH = "HOW_TO_TEACH"
    SCRIPTED_ML = "SCRIPTED_ML"
    PLAN_UNIT = "PLAN_UNIT"
    THINK_ALOUD = "THINK_ALOUD"
    DEEPEN_PRIOR = "DEEPEN_PRIOR"
    COACHING = "COACHING"
    MANAGEMENT = "MANAGEMENT"
    META = "META"
    CORRECTION = "CORRECTION"


# Canonical grade values — closed enum. OpenAI structured output honors
# this as a JSON schema enum, making it structurally impossible for QU
# to emit invalid grades like "3rd grade band". Brady's entire vocabulary
# for grades is either a specific K..12 or one of the four canonical
# bands, so this enum exactly matches his usage.
GradeValue = Literal[
    "K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
    "K-2", "3-5", "6-8", "9-12", "K-12", "all",
]


class GradeSpec(BaseModel):
    """Grade level with provenance.

    ``value`` is constrained to the GradeValue Literal — the LLM cannot
    emit anything outside this enum when using structured output. This
    closes the Turn 6 failure mode where QU hallucinated "3rd grade
    band" as a value. When teacher phrasing doesn't map cleanly, QU
    sets value=None and populates TurnIntent.missing_required.

    ``stated_explicit`` is True if the teacher said it literally this
    turn or in a prior turn; False if QU inferred from context.

    Provenance lets the prompt tell the model things like "teacher
    stated grade=3 in Turn 1 — do not re-ask" which directly addresses
    Brady's B-S01 complaint.
    """

    model_config = ConfigDict(frozen=True)

    value: GradeValue
    stated_explicit: bool
    stated_turn: Optional[int] = Field(default=None, ge=0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ModeSpec(BaseModel):
    """Writing mode with provenance.

    ``all`` is used when the query is mode-agnostic (e.g., a general
    coaching question about the writing workshop).
    """

    model_config = ConfigDict(frozen=True)

    value: Literal["Inform", "Persuade", "Entertain", "all"]
    stated_explicit: bool
    stated_turn: Optional[int] = Field(default=None, ge=0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class TraitSpec(BaseModel):
    """6+1 Writing Trait with provenance.

    ``all`` is used when the query spans multiple traits or is
    trait-agnostic.
    """

    model_config = ConfigDict(frozen=True)

    value: Literal[
        "Ideas",
        "Organization",
        "Voice",
        "Word Choice",
        "Sentence Fluency",
        "Conventions",
        "all",
    ]
    stated_explicit: bool
    stated_turn: Optional[int] = Field(default=None, ge=0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class SkillSpec(BaseModel):
    """The writing skill under discussion, with dual representation.

    ``canonical`` is the normalized skill name used for retrieval and
    cross-turn consistency. Comes from canonicalizer.canonicalize_skill.

    ``as_stated`` is the teacher's literal vocabulary (e.g., "topic
    sentence and supporting details"). This is what goes into the
    response's ``skill_focus`` so the teacher sees their own words back.

    This dual representation directly addresses Brady's complaint:
    teacher said "topic sentence and supporting details" but got back
    "distinguish between details and development" — a skill rename.
    """

    model_config = ConfigDict(frozen=True)

    canonical: str
    as_stated: str
    stated_turn: Optional[int] = Field(default=None, ge=0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class TurnIntent(BaseModel):
    """Complete specification of what a single turn needs.

    Produced by QU, consumed by dispatcher + handlers. This is the
    single atomic unit of "what the teacher is asking for right now,
    given everything said so far."

    Design principle: ZERO ambiguity. Every field has a clear role.
    If a handler can't decide what to do from TurnIntent alone, the
    schema is missing a field — add it here, don't patch around it.
    """

    model_config = ConfigDict(validate_assignment=True)

    # Primary intent
    request_type: RequestType

    # Pedagogical "who" — carried from convo when stated earlier
    grade: Optional[GradeSpec] = None
    mode: Optional[ModeSpec] = None
    trait: Optional[TraitSpec] = None

    # Pedagogical "what"
    skill: Optional[SkillSpec] = None

    # Continuity signals — drive DEEPEN_PRIOR + CORRECTION handlers
    refers_to_prior: bool = False
    reuse_example_from_prior: bool = False
    prior_turn_ref: Optional[int] = Field(default=None, ge=0)

    # Explicit user constraints — drive trigger-adherence validator
    required_triggers: list[str] = Field(default_factory=list)

    # Confirmation handshake — QU decides when to ask the teacher to
    # confirm before the system commits to an expensive action (usually
    # SCRIPTED_ML generation). Set True ONLY when QU sees real
    # ambiguity — conflicting skill candidates, first SCRIPTED_ML in
    # a session with implicit context, corrected/pivoted skill where
    # the new skill is close but not identical to a prior turn's skill.
    # The handler reads this flag and, if True, emits
    # PendingMLConfirmation instead of generating immediately.
    needs_confirmation: bool = False
    confirmation_reason: Optional[str] = None

    # Clarification needs — drive the clarifying-question path
    missing_required: list[Literal["grade", "skill", "mode"]] = Field(
        default_factory=list
    )
    ambiguities: list[str] = Field(default_factory=list)

    # Brady S3 scope-creep signal. NON-EMPTY only when the teacher asks to
    # cram a SECOND (or more) distinct, independently-teachable skill into
    # ONE mini-lesson ("a lesson on A and B" or a follow-up "also add B to
    # this lesson"). Each entry is the EXTRA skill in the teacher's words
    # (it slots the deterministic one-skill guard). The PRIMARY skill stays
    # in ``skill``. list[str] (not SkillSpec) — we never retrieve on it,
    # only name it. Emptiness IS the boolean: empty (the overwhelming
    # default) leaves the guard inert, preserving back-compat.
    additional_skills: list[str] = Field(default_factory=list)

    # Brady SG1 subgroup-acronym signal (video 56:00). NON-NULL only when the
    # teacher describes their students with a subgroup-like acronym that QU does
    # NOT recognize -- i.e. NOT one of the four named families SPED / MLL(MLs) /
    # EL(ELL) / RTI, and not a known skill/trigger. Holds the acronym in the
    # teacher's words; the dispatch clarify gate reads it to ask Brady's "What
    # does that acronym stand for?" question instead of a generic re-ask.
    # Optional[str] mirrors additional_skills' "the value IS the boolean":
    # None (the overwhelming default -- no acronym, or one QU recognizes as
    # subgroup context) leaves the acronym-clarify path inert (back-compat).
    unknown_subgroup_acronym: Optional[str] = None

    # Brady SG2 recognized-subgroup signal (video 57:30). NON-NULL when the
    # teacher names one of the four RECOGNIZED subgroup families (SPED / MLL /
    # EL(ELL) / RTI) as WHO the lesson is for -- held in the teacher's words. It
    # is the "recognized-subgroup context" that (with no writing_level stated)
    # drives Brady's writing-level clarify: for a subgroup, grade level matters
    # less than the current WRITING LEVEL. Distinct from
    # unknown_subgroup_acronym (which is for UNrecognized labels -> SG1 asks what
    # it stands for FIRST). None is the overwhelming default (not a subgroup
    # turn) and leaves the writing-level ask inert (back-compat).
    subgroup: Optional[str] = None

    # Brady SG2 developmental-writing-level signal (video 57:30, doc 286). The
    # current WRITING LEVEL as the teacher stated it -- the developmental stage
    # (e.g. "picture", "label", "word", "sentence"), NOT a grade. QU extracts it
    # when stated; it threads into generation so the outline frames each skill
    # AT that stage (drawing/labeling/word-era vs sentence-era). When a subgroup
    # context is present and this is None, the clarify seam ASKS for it. None is
    # the default (no stage stated) and leaves the stage-threaded generation
    # inert (back-compat). Free string (not an enum) -- Brady's four stages are
    # the common case but the field must not overfit to a closed list.
    writing_level: Optional[str] = None

    # Brady C10 emotional-validation signal (dogfood C10; coaching C1 @52:50).
    # True when the teacher VOICES frustration / being stuck / discouraged /
    # overwhelmed ("I'm so frustrated", "they STILL can't do it", "this isn't
    # working"). It is the teacher's EMOTIONAL state and is ORTHOGONAL to
    # request_type -- a frustrated "how do I teach X?" sets this True AND keeps
    # request_type=HOW_TO_TEACH. It is NOT topic difficulty: a neutral/descriptive
    # "my students struggle with X" or a calm "how do I teach X" is False. Brady's
    # "validate the emotion FIRST, then the practical guidance" rule lived ONLY in
    # COACHING, so it fired only when a frustrated opener happened to route there
    # (~1/4 -- a routing lottery); this deterministic signal lets one shared
    # validation rule splice into EVERY text handler gated on the flag (mirrors
    # additional_skills / subgroup / writing_level). False is the overwhelming
    # default and a no-op -- a calm turn's prompt is byte-identical (back-compat).
    expressed_frustration: bool = False
