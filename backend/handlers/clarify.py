"""U3 — deterministic, per-category clarify wording (Brady 38:50).

When the backend decides a request is under-specified and must ask the teacher
an OPEN QUESTION before producing content, the WORDING of that question is
chosen per ``request_type``, in Brady's own phrasing — not a generic one-size
ask, and never an assumed-specifics answer.

This module is a pure lookup: ``(request_type + which required fields are still
missing) -> the open question``, or ``None`` when Brady named no wording for
that category (the caller then keeps its existing generic per-field ask — we do
NOT invent wording Brady didn't give). It has NO conversation/LLM dependency so
it stays trivially testable and import-cycle-free. The list-re-surfacing logic
in ``handlers/__init__.py`` (which DOES need the conversation) layers on top of
this for the one narrow SCRIPTED_ML skill-only case.

It also owns ``effective_missing_required`` — WHICH gaps are worth asking about
at all (as opposed to QU's raw observation of which fields went unstated). That
policy lives here, next to the wording, because the dispatcher's gate (WHETHER
to clarify) and the wording composer (WHAT to ask) must never disagree: a rule
applied in only one of them re-opens the exact leak Brady flagged (task #64).

Brady's per-category questions (doc 38:50; his written table, feedback.docx
p166-172, is the authority — p166: "We need it to follow EACH 'query category'
click with an open-ended question to the user"):
  SCRIPTED_ML (missing specifics) -> ask the still-missing subset of grade/skill
  PLAN_UNIT                       -> ask persuasive / informative / narrative
                                     (+ grade if also unstated, per video @12943)
  MANAGEMENT                      -> ask which area of management
"""

from __future__ import annotations

from typing import Callable, Optional

from schemas import RequestType, TurnIntent


# Brady-verbatim clauses. Named constants so tests assert the exact key phrase
# and a future wording tweak is a one-line change (never scattered string dup).
# GRADE_Q / SKILL_Q are NOT SCRIPTED_ML-specific: Brady's table reuses the same
# wording across category rows (grade on the ML + unit rows; skill on the ML,
# prop-or-trigger, and different-ideas rows).
GRADE_Q = "What grade level do you teach?"
SCRIPTED_ML_SKILL_Q = "What writing skill are you working on?"
# Brady's written table, feedback.docx p168 / feedback.pdf:251 (both renderings
# agree), his BLUE new-ask hand. NOT "Is this for persuasive, informative, or
# narrative writing?" — that was ours, and note he says "unit", matching the
# category the question follows.
PLAN_UNIT_MODE_Q = "Are you preparing for a persuasive, informative, or narrative unit?"
MANAGEMENT_AREA_Q = "What area of management are you struggling with?"


# --- Structural prerequisites (u3) -----------------------------------------
# Fields a handler CANNOT RENDER WITHOUT — categorically different from the
# fields QU *judges* worth asking about. handlers/plan_unit.py mandates the
# opening "For {grade} {mode} writing, here are the priority skills in order:"
# while being fed "Writing mode: (not specified)" when mode is absent: the gap
# doesn't degrade the answer, it ORDERS the model to invent a mode. An invented
# "5th-grade persuasive" unit is precisely the assumption Brady objected to
# ("the first Copilot response to a category being clicked is a question as
# opposed to an assumption of a very narrow group"), and his rule for this
# category is unconditional.
#
# Whether the teacher STATED a mode is a FACT, not a judgment, so it is derived
# here instead of trusted from QU. Measured on production gpt-5.4-mini
# (campaign/recert/probe_u3_qu_mode.py): mode was genuinely None 10/10 while
# QU's missing_required flagged it only 5/10, swinging 4/5 -> 1/5 between two
# identical runs. A rule Brady states unconditionally must not ride a coin flip.
#
# Deliberately NOT a blanket "derive every required field": whether a
# HOW_TO_TEACH skill is grade-sensitive, or whether a skill can be inherited
# from context, ARE judgments and stay with the LLM (the project's
# deterministic-layer-is-a-bounded-backstop convention).
# SCRIPTED_ML carries the same shape on Brady's most-used category: his ML row
# asks for BOTH ("What grade level do you teach? What writing skill are you
# working on?"), grade feeds the Fm4 header, and an unstated grade reaches
# scripted_ml_grade_band(None) — which silently defaults to the 3-12 close for a
# grade nobody gave. Measured: "Can you give me a scripted mini-lesson?" leaves
# intent.grade None 5/5 while QU flags it only 2/5, so 3/5 of the time half of
# Brady's question is dropped.
#
# "skill" is NOT listed: whether a skill can be extracted or INHERITED from the
# conversation is a genuine judgment (QU owns the offered-skill pickup), so it
# stays with the LLM. Only facts belong in this table.
_STRUCTURAL_PREREQS: dict[RequestType, tuple[str, ...]] = {
    RequestType.PLAN_UNIT: ("grade", "mode"),
    RequestType.SCRIPTED_ML: ("grade",),
    # HOW_TO_TEACH gates on grade (handlers/__init__.py _GRADE_REQUIRED) and
    # renders a grade-sensitive outline, but grade only reached the gate via
    # QU's unreliable "grade-sensitive skill" judgment — so a grade-less
    # HOW_TO_TEACH produced a full outline WITHOUT asking, while SCRIPTED_ML /
    # PLAN_UNIT correctly asked. Whether the teacher STATED a grade is a FACT,
    # so it is derived here like the other two grade-gated content categories
    # (SG2's stated-writing-level discard still supplants it downstream).
    RequestType.HOW_TO_TEACH: ("grade",),
}

# Is the field actually stated? Per-field because "stated" differs by field:
# ModeSpec's "all" is its mode-AGNOSTIC marker — it is not an answer to Brady's
# persuasive/informative/narrative question and would render his mandated
# opening as "For 5th all writing". A GradeSpec band ("K-2", "3-5") IS a real
# answer, so grade only checks presence.
_PREREQ_STATED: dict[str, Callable[[TurnIntent], bool]] = {
    "grade": lambda i: i.grade is not None,
    "mode": lambda i: i.mode is not None and i.mode.value != "all",
}
# SG1 (Brady 56:00) — the follow-up for a subgroup-like acronym QU does NOT
# recognize. Brady-verbatim: don't guess or re-ask generically; ask what it
# stands for, because acronyms for the same subgroup vary state to state.
UNKNOWN_SUBGROUP_ACRONYM_Q = (
    "What does that acronym stand for? Each state has different "
    "names/acronyms for the same subgroups."
)
# SG2 (Brady 57:30) — the writing-level ask for a subgroup / early-writer
# context. Brady: for a subgroup, grade level doesn't matter; ask the current
# WRITING LEVEL and teach grade-level skills at that developmental stage.
WRITING_LEVEL_Q = (
    "What's their current writing level — are they at the picture, "
    "label, word, or sentence stage?"
)


def effective_missing_required(intent: TurnIntent) -> set[str]:
    """The fields we will actually ASK the teacher about.

    QU's ``intent.missing_required`` is an honest OBSERVATION ("grade was not
    stated"). Whether that gap is worth a question is POLICY, and this function
    is where that policy lives — so every ask-site agrees.

    Brady SG2 / §F (57:30): "Not always a grade level. … Also need to follow
    with more than GRADE LEVEL, but current writing level." For a subgroup /
    early writer the operative signal is the current developmental WRITING
    LEVEL (picture · label · word · sentence). A known stage already answers
    the "how do I pitch this?" question that grade otherwise answers, so grade
    stops being an INDEPENDENT hard requirement — asking for it anyway is the
    frustration Brady flagged (task #64).

    The rule keys on QU's STRUCTURED ``writing_level`` signal, never on the
    words "SPED" / "picture-drawing": any phrasing QU resolves to a stage
    ("they're still drawing pictures") satisfies it, and a phrasing it doesn't
    resolve leaves the grade ask intact. It is deliberately scoped to GRADE —
    a stage says nothing about WHICH skill or mode the teacher wants, so those
    asks survive untouched.

    u3 — a request_type's STRUCTURAL prerequisites (``_STRUCTURAL_PREREQS``)
    are derived from the intent itself and UNIONed in, whether or not QU
    volunteered them. Union, never replace: QU still contributes the fields
    only it can judge (e.g. "skill").

    Returns a NEW set; ``intent.missing_required`` is never mutated (QU's
    observation stays intact for logging and the CORRECTION merge).
    """
    missing = set(intent.missing_required or [])
    for field in _STRUCTURAL_PREREQS.get(intent.request_type, ()):
        if not _PREREQ_STATED[field](intent):
            missing.add(field)
    # A STATED grade is a real answer whether it is a specific grade ("2") or one
    # of the canonical BANDS ("K-2", "3-5") — the Grade enum, the "Grade K-2"
    # header, and the K-2 non-negotiable close all treat a band as first-class.
    # QU is told to flag a band as still needing a specific grade and seeds
    # "grade" into missing_required, which contradicts THIS module's own rule
    # (_PREREQ_STATED: "grade only checks presence"); because the derive above only
    # ever ADDS, that flag leaked to the dispatch gate and re-asked "What grade
    # level do you teach?" at a teacher who had just answered "K-2". Grade PRESENT
    # is never missing. No Brady primary asks for a band to be disambiguated.
    if _PREREQ_STATED["grade"](intent):
        missing.discard("grade")
    # SG2 runs AFTER the derive, so a stated writing level still supplants the
    # grade requirement (Brady: FOR A SUBGROUP, grade level doesn't matter).
    # Order is load-bearing: deriving afterwards would resurrect the grade ask
    # this rule exists to remove.
    #
    # MUST be gated on subgroup context, matching every other SG2 site (dispatch's
    # needs_writing_level, clarify_question's SG2 branch). Without the subgroup
    # guard, a stage word ECHOED from the skill name — QU pulls writing_level='label'
    # out of "LABELing multiple details in one picture" with NO subgroup — spuriously
    # dropped the grade ask, so a gradeless SCRIPTED_ML produced a model-inferred
    # K-2 lesson with a defaulted 3-12 close ("Now it's your turn!"). Brady's rule
    # is subgroup-scoped; a plain gradeless lesson must still ask the grade.
    if (intent.subgroup or "").strip() and (intent.writing_level or "").strip():
        missing.discard("grade")
    return missing


def clarify_question(intent: TurnIntent) -> Optional[str]:
    """Return Brady's per-category open question for an under-specified turn.

    Returns ``None`` when this ``request_type`` has no Brady-specified wording —
    the caller then keeps the existing generic per-field clarify (do NOT invent
    wording). For SCRIPTED_ML the question is COMPOSED from the fields still
    missing, so a field the teacher already stated is never re-asked (Brady's
    B-S01 'don't re-ask a known field' rule); his full example asks both because
    both are missing.
    """
    # SG1 (Brady 56:00): an unrecognized subgroup acronym is the highest-
    # priority clarify — its question is returned FIRST, ahead of any
    # grade/skill/mode wording and regardless of request_type. Presence of
    # QU's unknown_subgroup_acronym signal IS the trigger.
    if (intent.unknown_subgroup_acronym or "").strip():
        return UNKNOWN_SUBGROUP_ACRONYM_Q

    # SG2 (Brady 57:30): a RECOGNIZED subgroup context with NO writing level
    # stated asks the developmental WRITING LEVEL next — ahead of any
    # grade/skill/mode wording (for a subgroup, grade level doesn't matter).
    # The acronym check above already returned for the UNrecognized case, so a
    # subgroup we can't name never reaches here.
    if (intent.subgroup or "").strip() and not (intent.writing_level or "").strip():
        return WRITING_LEVEL_Q

    rt = intent.request_type
    # SG2 / §F — ask about the fields that still MATTER: a stated writing level
    # supplants the grade requirement, so the composed question below never
    # re-asks Brady's banned grade question on a subgroup+stage turn (it would
    # otherwise leak in via a co-missing field, e.g. missing={grade, skill}).
    missing = effective_missing_required(intent)

    if rt is RequestType.MANAGEMENT:
        # Management doesn't decompose into grade/skill/mode; the whole open
        # question is fixed regardless of which field QU happened to flag.
        return MANAGEMENT_AREA_Q

    if rt is RequestType.PLAN_UNIT:
        # Brady's written table names the MODE question for this row; his video
        # (@12943) adds grade — "Then I want it to ask me what grade level and
        # persuasive, informative, or narrative. I want that." Composed from the
        # still-missing subset, exactly like the SCRIPTED_ML row below, so a
        # field the teacher already stated is never re-asked. Both are derived
        # when unstated (_STRUCTURAL_PREREQS), so the mode clause no longer
        # depends on QU volunteering "mode".
        clauses: list[str] = []
        if "grade" in missing:
            clauses.append(GRADE_Q)
        if "mode" in missing:
            clauses.append(PLAN_UNIT_MODE_Q)
        return " ".join(clauses) if clauses else None

    if rt is RequestType.SCRIPTED_ML:
        clauses = []
        if "grade" in missing:
            clauses.append(GRADE_Q)
        if "skill" in missing:
            clauses.append(SCRIPTED_ML_SKILL_Q)
        return " ".join(clauses) if clauses else None

    # Any other category: Brady specified no wording -> keep generic behavior.
    return None
