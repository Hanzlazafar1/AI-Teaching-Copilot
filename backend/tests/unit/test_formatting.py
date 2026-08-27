"""Tests for the deterministic text helpers in `handlers/formatting.py`.

`handlers/formatting.py` is the single source of truth for the
"Grade X | <adjective|label>" header rendered by every handler — the 5
markdown handlers (via `_base_text`) and SCRIPTED_ML (via `scripted_ml`) —
and for Brady's S3 one-skill-per-mini-lesson guard. These lock the three
existing header shapes plus the optional `label` keyword, and the guard's
exact Brady-verbatim wording, its natural-join, and its constant-frame
(anti-Fm5) invariant — only the named extra skill(s) may ever vary.
"""

from __future__ import annotations

import pytest

from handlers.formatting import (
    ONE_SKILL_GUARD_TEMPLATE,
    MODE_ADJECTIVES,
    deferred_skills,
    format_lesson_header,
    format_one_skill_guard,
    format_unit_opening,
)


# ---------------------------------------------------------------------------
# PLAN_UNIT's mandated opening sentence.
#
# handlers/plan_unit.py told the model its opening was a "verbatim shape
# (substitute the specific grade and mode from session context)":
#     "For {grade} {mode} writing, here are the priority skills in order:"
# ...while feeding it "Grade: (not specified)" and the RAW ModeSpec enum. The
# gap does not degrade the sentence, it ORDERS the model to invent one. Measured
# live 4/4 on the grade-less SG2 path: "For K-2 persuade writing, ..." — an
# invented grade band AND the internal enum, in one sentence. Grade-stated
# control: 0/4.
#
# Both halves are Brady rules already on record: he objected to "an assumption
# of a very narrow group", and his Fm4 decision rejected "Mode: Inform" because
# it leaks an internal token (-> "Grade 3 | Informative"). MODE_ADJECTIVES has
# been the canonical teacher-facing vocabulary since Fm4 — plan_unit just never
# used it.
#
# So the sentence is CONSTRUCTED here (the Fm5 deterministic precedent) rather
# than substituted by the model: with nothing to substitute, there is no grade
# to invent and no enum to echo.
# ---------------------------------------------------------------------------


def test_unit_opening_grade_and_mode():
    assert format_unit_opening("5", "Persuade") == (
        "For 5 persuasive writing, here are the priority skills in order:"
    )


def test_unit_opening_uses_bradys_vocabulary_never_the_enum():
    # Fm4's rule, applied to the same words: the teacher never sees the enum.
    for enum_value, adjective in MODE_ADJECTIVES.items():
        opening = format_unit_opening("3", enum_value)
        assert adjective.lower() in opening
        assert enum_value.lower() not in opening.lower().replace(adjective.lower(), "")


def test_unit_opening_omits_a_grade_nobody_stated():
    # THE DEFECT. No grade -> the sentence must not name one. It stays a valid
    # opening; it simply says only what is known.
    opening = format_unit_opening(None, "Persuade")
    assert opening == "For persuasive writing, here are the priority skills in order:"
    for invented in ("K-2", "3-5", "6-8", "9-12", "K-12", "not specified", "None"):
        assert invented.lower() not in opening.lower()


def test_unit_opening_mode_all_is_not_a_mode_word():
    # "all" is ModeSpec's mode-AGNOSTIC marker, not a mode. It must never render
    # as "For 5 all writing".
    assert format_unit_opening("5", "all") == (
        "For 5 writing, here are the priority skills in order:"
    )


def test_unit_opening_neither_known():
    assert format_unit_opening(None, None) == "Here are the priority skills in order:"


def test_grade_and_mode(): assert format_lesson_header("3", "Inform") == "Grade 3 | Informative"
def test_persuade(): assert format_lesson_header("8", "Persuade") == "Grade 8 | Persuasive"
def test_entertain(): assert format_lesson_header("2", "Entertain") == "Grade 2 | Narrative"
def test_mode_none_grade_only(): assert format_lesson_header("4", None) == "Grade 4"
def test_mode_all_grade_only(): assert format_lesson_header("4", "all") == "Grade 4"
def test_no_grade_empty(): assert format_lesson_header(None, "Inform") == ""
def test_label_overrides_mode(): assert format_lesson_header("1", "Inform", label="Management") == "Grade 1 | Management"
def test_label_no_grade_empty(): assert format_lesson_header(None, None, label="Management") == ""
def test_adjectives_map(): assert MODE_ADJECTIVES == {"Inform": "Informative", "Persuade": "Persuasive", "Entertain": "Narrative"}


# --- Brady S3: one-skill-per-mini-lesson guard (deterministic template) -------
# `format_one_skill_guard` is the anti-Fm5 code guard: a fixed Brady-verbatim
# body whose ONLY dynamic part is the naturally-joined extra skill(s). No LLM
# ever reformats it. These lock the exact wording, the natural-join shapes, the
# constant-frame invariant, and the inert-on-empty back-compat contract.


def test_guard_template_is_brady_verbatim():
    # The exact wording is a contract — it must never drift (character-for-char).
    assert ONE_SKILL_GUARD_TEMPLATE == (
        "Mini-lessons are focused on one skill at a time. "
        "Adding in {extra} would come in a second or future mini-lesson."
    )


def test_guard_single_extra():
    assert format_one_skill_guard(["transitions"]) == (
        "Mini-lessons are focused on one skill at a time. "
        "Adding in transitions would come in a second or future mini-lesson."
    )


def test_guard_two_extras_join_with_and():
    assert format_one_skill_guard(["introductions", "conclusions"]) == (
        "Mini-lessons are focused on one skill at a time. "
        "Adding in introductions and conclusions would come in a second or future mini-lesson."
    )


def test_guard_three_extras_oxford_join():
    assert format_one_skill_guard(["transitions", "introductions", "conclusions"]) == (
        "Mini-lessons are focused on one skill at a time. "
        "Adding in transitions, introductions, and conclusions "
        "would come in a second or future mini-lesson."
    )


def test_guard_only_the_slot_is_dynamic():
    # Everything outside the {extra} slot is byte-for-byte constant regardless
    # of the extra — the anti-Fm5 guarantee (only the named skill may vary).
    prefix, suffix = ONE_SKILL_GUARD_TEMPLATE.split("{extra}")
    for extra in ("conclusions", "adding a hook", "strong verbs"):
        out = format_one_skill_guard([extra])
        assert out.startswith(prefix) and out.endswith(suffix)
        assert out[len(prefix):len(out) - len(suffix)] == extra


def test_guard_only_fills_the_slot():
    # The function does nothing but substitute the joined extras into the slot.
    assert format_one_skill_guard(["voice"]) == ONE_SKILL_GUARD_TEMPLATE.format(extra="voice")


def test_guard_empty_is_inert():
    # Emptiness IS the boolean: no extra -> no guard (back-compat inert).
    assert format_one_skill_guard([]) == ""


def test_guard_strips_whitespace_and_drops_blanks():
    assert format_one_skill_guard(["  transitions  "]) == (
        "Mini-lessons are focused on one skill at a time. "
        "Adding in transitions would come in a second or future mini-lesson."
    )
    assert format_one_skill_guard(["", "   "]) == ""


def test_guard_braces_in_extra_are_literal():
    # str.format does not re-interpret substituted values, so a skill name with
    # braces is inserted verbatim (no injection / KeyError).
    assert format_one_skill_guard(["a {weird} skill"]) == (
        "Mini-lessons are focused on one skill at a time. "
        "Adding in a {weird} skill would come in a second or future mini-lesson."
    )


# --- Brady S3: `deferred_skills` — THE shared scope-creep normalizer ----------
# The S3 guard tells the teacher a skill is deferred; the SCRIPTED_ML prompt
# tells the generator not to teach it. Those two must never disagree, or the app
# ships a self-contradicting payload (promises to defer a skill, then teaches it
# in full). They can only be provably consistent if BOTH derive "is a skill
# deferred, and which" from ONE normalizer — this one. `format_one_skill_guard`
# and `scripted_ml_prompt._render_one_skill_scope_block` are its only callers;
# the tie is locked in tests/unit/test_s3_scope_enforcement.py.


@pytest.mark.parametrize(
    "raw, expected",
    [
        ([], []),                                    # the overwhelming default
        (["transitions"], ["transitions"]),
        (["  transitions  "], ["transitions"]),      # stripped
        (["", "   "], []),                           # all-blank -> inert
        (["", "transitions", "  "], ["transitions"]),  # blanks dropped, order kept
        (["introductions", "conclusions"], ["introductions", "conclusions"]),
    ],
)
def test_deferred_skills_normalizes(raw, expected):
    assert deferred_skills(raw) == expected


def test_deferred_skills_is_the_guards_own_boolean():
    """Emptiness IS the boolean, and it is the SAME boolean the guard uses.
    Catches a future edit that makes the guard fire on input the normalizer
    calls empty (or vice versa) — which would decouple guard from generator."""
    for raw in ([], [""], ["  "], ["transitions"], ["  x  "], ["", "y"]):
        assert bool(deferred_skills(raw)) == bool(format_one_skill_guard(raw))


def test_deferred_skills_does_not_mutate_input():
    raw = ["  transitions  ", ""]
    deferred_skills(raw)
    assert raw == ["  transitions  ", ""]
