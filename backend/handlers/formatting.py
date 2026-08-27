"""Deterministic, LLM-free text helpers shared across handlers — the single
source of truth for output strings whose exact wording must never drift
through a model (the anti-Fm5 pattern):

- ``format_lesson_header`` — the 'Grade X | <adjective|label>' header (Brady
  Fm4) used by every handler (the 5 markdown handlers via ``_base_text`` and
  SCRIPTED_ML via ``scripted_ml``).
- ``format_one_skill_guard`` — Brady's S3 one-skill-per-mini-lesson guard: a
  fixed Brady-verbatim template whose ONLY dynamic part is the named extra
  skill(s). Emitted as a code preface at the dispatch gate — never LLM text.
- ``deferred_skills`` — the shared S3 normalizer read by BOTH the guard above
  and the SCRIPTED_ML prompt's exclusion block, so what the teacher is told is
  deferred and what the generator is told to leave out can never disagree.

Public so handlers import these rather than reaching into a private helper."""
from __future__ import annotations
from typing import Optional

MODE_ADJECTIVES = {"Inform": "Informative", "Persuade": "Persuasive", "Entertain": "Narrative"}

# Brady S3 (video 45:30 / feedback-7-july doc 188). The guard's wording is a
# CONTRACT: every character is constant except the single ``{extra}`` slot,
# which names the deferred skill(s). Do NOT reword through an LLM — that is the
# whole point (the anti-Fm5 pattern). The dispatch gate prepends the rendered
# guard to a lesson generated on the PRIMARY skill.
ONE_SKILL_GUARD_TEMPLATE = (
    "Mini-lessons are focused on one skill at a time. "
    "Adding in {extra} would come in a second or future mini-lesson."
)


def format_lesson_header(grade: Optional[str], mode: Optional[str], *, label: Optional[str] = None) -> str:
    """'Grade X | <adjective>' — or 'Grade X | <label>' when label is given
    (e.g. 'Management' for the management handler), or grade-only 'Grade X'
    when no mode adjective / label applies, or '' when grade is unknown."""
    if not grade:
        return ""
    if label:
        return f"Grade {grade} | {label}"
    adjective = MODE_ADJECTIVES.get(mode or "")
    return f"Grade {grade} | {adjective}" if adjective else f"Grade {grade}"


def format_unit_opening(grade: Optional[str], mode: Optional[str]) -> str:
    """PLAN_UNIT's opening sentence, naming ONLY what the teacher actually gave.

    Built here rather than substituted by the model. ``plan_unit.py`` used to
    hand the LLM a "verbatim shape (substitute the specific grade and mode from
    session context)" — "For {grade} {mode} writing, here are the priority
    skills in order:" — while the context could say "Grade: (not specified)" and
    carried the RAW ModeSpec enum. That does not degrade the sentence; it ORDERS
    the model to invent one. Measured live 4/4 on the grade-less path: "For K-2
    persuade writing, ..." — an invented grade band AND the internal enum
    together (grade-stated control: 0/4).

    Both halves are Brady rules already on record: he objected to "an assumption
    of a very narrow group", and his Fm4 decision rejected "Mode: Inform" for
    leaking an internal token. ``MODE_ADJECTIVES`` has been the canonical
    teacher-facing vocabulary since Fm4 — this just uses it. With nothing left to
    substitute there is no grade to invent and no enum to echo (the Fm5
    deterministic-construction precedent).

    ``mode="all"`` is ModeSpec's mode-AGNOSTIC marker, not a mode, so it is
    dropped rather than rendered as "For 5 all writing".
    """
    qualifiers = " ".join(x for x in (grade, MODE_ADJECTIVES.get(mode or "", "").lower()) if x)
    if not qualifiers:
        return "Here are the priority skills in order:"
    return f"For {qualifiers} writing, here are the priority skills in order:"


def _natural_join(items: list[str]) -> str:
    """Oxford-comma join of names: [] -> '', ['A'] -> 'A',
    ['A','B'] -> 'A and B', ['A','B','C'] -> 'A, B, and C'."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def deferred_skills(extra_skills: list[str]) -> list[str]:
    """THE single source of truth for Brady S3's "is a skill deferred, and
    which?" — the normalized form of QU's ``additional_skills``.

    Returns the extra skills the teacher tried to cram into one mini-lesson, in
    the teacher's words, stripped, with blanks dropped and order preserved.
    Empty (the overwhelming default) means nothing is deferred: emptiness IS the
    boolean.

    Why this is a shared helper and not two copies of ``[s.strip() for s ...]``:
    S3 has TWO consumers that must never disagree — the teacher-facing guard
    (``format_one_skill_guard``, below) which SAYS a skill is deferred, and the
    SCRIPTED_ML prompt block (``scripted_ml_prompt._render_one_skill_scope_block``)
    which tells the generator not to teach it. If those two ever computed
    "deferred" differently, the app could promise to defer a skill and then
    teach it in full — the exact self-contradiction S3 shipped with, when the
    prompt side did not exist at all. Deriving BOTH from this one function makes
    "guard fires <=> generator is constrained" true by construction; the
    invariant is locked in tests/unit/test_scripted_ml_prompt.py
    (``test_guard_fires_iff_generator_is_constrained``) and end-to-end in
    tests/unit/test_s3_scope_enforcement.py."""
    return [s.strip() for s in extra_skills if s and s.strip()]


def format_one_skill_guard(extra_skills: list[str]) -> str:
    """Render Brady's S3 one-skill guard from ``ONE_SKILL_GUARD_TEMPLATE``.

    ``extra_skills`` are the EXTRA skills a teacher tried to cram into one
    mini-lesson (QU's ``additional_skills``), in the teacher's words. Only the
    naturally-joined names are dynamic; the rest of the sentence is constant.
    Returns ``''`` when there is no extra to name (empty / all-blank input),
    so the guard stays inert — emptiness IS the boolean (back-compat).

    This is the TEACHER-FACING half of S3; ``deferred_skills`` (above) is the
    shared normalizer the generator-facing half reads too."""
    cleaned = deferred_skills(extra_skills)
    if not cleaned:
        return ""
    return ONE_SKILL_GUARD_TEMPLATE.format(extra=_natural_join(cleaned))
