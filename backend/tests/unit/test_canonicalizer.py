"""Unit tests for canonicalizer.Canonicalizer.

These tests lock in the behavior that the QU/session refactor relies on:
  * skill synonyms resolve to their canonical form
  * trigger synonyms resolve to the canonical Smekens trigger name
  * pedagogical meta-techniques are recognized (must not be written as
    skills — this is the Turn 5 bug fix)
  * unknown input falls back to normalized string (never raises)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from canonicalizer import (
    GRADE_ENUM,
    Canonicalizer,
    ResolutionKind,
    canonicalize_grade,
    get_canonicalizer,
)


@pytest.fixture(scope="module")
def canon() -> Canonicalizer:
    """Real canonicalizer loaded from v4's data directory."""
    root = Path(__file__).resolve().parents[2]
    return Canonicalizer(
        skill_triggers_path=root / "data" / "skill_triggers.json",
        skill_synonyms_path=root / "data" / "skill_synonyms.json",
        meta_techniques_path=root / "data" / "meta_techniques.json",
    )


# ----------------------------------------------------------------------
# Skill canonicalization
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("topic sentence", "topic sentences"),
        ("topic sentences", "topic sentences"),
        ("Topic Sentences", "topic sentences"),
        ("topic-sentence", "topic sentences"),
        ("topic sentence and supporting details", "topic sentences"),
        ("main idea sentence", "topic sentences"),
        ("transitions between paragraphs", "transitions"),
        ("transition words", "transitions"),
        ("paragraph writing", "paragraph writing"),
        ("paragraphs", "paragraph writing"),
        ("writing paragraphs", "paragraph writing"),
        ("supporting details", "supporting details"),
        ("leg sentences", "supporting details"),
        ("elaborate", "elaboration"),
        ("counterclaim", "counterclaim"),
        ("they say i say", "counterclaim"),
        ("research", "collect facts and details"),
        ("jot fact phrases", "collect facts and details"),
        ("read find say jot", "collect facts and details"),
    ],
)
def test_canonicalize_skill_hits_known_synonyms(
    canon: Canonicalizer, raw: str, expected: str
) -> None:
    assert canon.canonicalize_skill(raw) == expected


def test_canonicalize_skill_unknown_falls_back_normalized(canon: Canonicalizer) -> None:
    """Unknown input must not raise — it returns normalized form.

    The caller (QU post-processor, handler) decides whether unresolved
    skill names are acceptable; canonicalizer never fails closed.
    """
    assert canon.canonicalize_skill("some brand new skill") == "some brand new skill"
    assert canon.canonicalize_skill("  EXTRA   whitespace  ") == "extra whitespace"


def test_canonicalize_skill_empty_string(canon: Canonicalizer) -> None:
    assert canon.canonicalize_skill("") == ""
    assert canon.canonicalize_skill("   ") == ""


# ----------------------------------------------------------------------
# Trigger canonicalization
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("pizza table", "pizza-table"),
        ("pizza-table", "pizza-table"),
        ("Pizza Table", "pizza-table"),
        ("tables and legs", "pizza-table"),
        ("table-top and legs", "pizza-table"),
        ("leg sentences", "pizza-table"),
        ("road sign", "road-sign"),
        ("colored yarn", "road-sign"),
        ("slinky test", "slinky-test"),
        ("slinky", "slinky-test"),
        ("tower test", "tower-test"),
        ("done list", "done-list"),
        ("help tent", "help-tent"),
        ("read find say jot", "read-find-say-jot"),
        ("4-step research process", "read-find-say-jot"),
    ],
)
def test_canonicalize_trigger_hits_known_synonyms(
    canon: Canonicalizer, raw: str, expected: str
) -> None:
    assert canon.canonicalize_trigger(raw) == expected


def test_canonicalize_trigger_unknown_returns_none(canon: Canonicalizer) -> None:
    """Unlike skill, trigger returns None for unknown input so callers
    can distinguish 'known trigger' from 'generic skill reference'."""
    assert canon.canonicalize_trigger("not a real smekens thing") is None
    assert canon.canonicalize_trigger("") is None


# ----------------------------------------------------------------------
# Meta-technique detection (the Turn 5 bug fix)
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "think-aloud",
        "think aloud",
        "Think Aloud",
        "THINKING ALOUD",
        "mini-lesson",
        "mini lesson",
        "minilesson",
        "turn-and-talk",
        "turn and talk",
        "t&t",
        "gradual release",
        "gradual release of responsibility",
        "i do we do you do",
        "explicit instruction",
        "4-step framework",
        "scripted mini-lesson",
        "writing workshop",
        "anchor chart",
    ],
)
def test_meta_technique_recognized(canon: Canonicalizer, raw: str) -> None:
    """These MUST be recognized as pedagogical techniques, not skills.

    This is the fix for v3's Turn 5 bug: 'deepen the think-aloud' got
    QU.strategy_name='think-aloud' which then overwrote active.skill.
    In v4, is_meta_technique guards skill updates so 'think-aloud'
    never becomes SkillSpec.canonical.
    """
    assert canon.is_meta_technique(raw), (
        f"{raw!r} must be recognized as a meta-technique "
        f"(pedagogical method, not a writing skill)"
    )


@pytest.mark.parametrize(
    "raw",
    [
        "topic sentences",
        "transitions",
        "pizza-table",
        "supporting details",
        "voice",
        "slinky test",
        "counterclaim",
    ],
)
def test_real_skills_not_meta_techniques(canon: Canonicalizer, raw: str) -> None:
    """Real writing skills must NOT be flagged as meta-techniques,
    otherwise the session updater would refuse to write them."""
    assert not canon.is_meta_technique(raw), (
        f"{raw!r} must NOT be flagged as a meta-technique — it's a real skill"
    )


# ----------------------------------------------------------------------
# Unified resolve() API
# ----------------------------------------------------------------------


def test_resolve_skill(canon: Canonicalizer) -> None:
    r = canon.resolve("topic sentence")
    assert r.kind is ResolutionKind.SKILL
    assert r.canonical == "topic sentences"


def test_resolve_trigger(canon: Canonicalizer) -> None:
    r = canon.resolve("pizza table")
    assert r.kind is ResolutionKind.TRIGGER
    assert r.canonical == "pizza-table"


def test_resolve_meta(canon: Canonicalizer) -> None:
    r = canon.resolve("think-aloud")
    assert r.kind is ResolutionKind.META_TECHNIQUE
    assert r.canonical == "think-aloud"


def test_resolve_unknown(canon: Canonicalizer) -> None:
    r = canon.resolve("random made up skill")
    assert r.kind is ResolutionKind.UNKNOWN
    assert r.canonical == "random made up skill"


def test_resolve_priority_meta_over_skill(canon: Canonicalizer) -> None:
    """Meta-technique check wins over skill check.

    If someone adds 'think-aloud' to skill_synonyms.json by mistake,
    the meta-technique list should still protect session state from
    corruption. This test locks that priority.
    """
    r = canon.resolve("think-aloud")
    assert r.kind is ResolutionKind.META_TECHNIQUE


# ----------------------------------------------------------------------
# Singleton helper
# ----------------------------------------------------------------------


def test_get_canonicalizer_singleton() -> None:
    """get_canonicalizer() returns same instance on repeated calls."""
    a = get_canonicalizer()
    b = get_canonicalizer()
    assert a is b


# ----------------------------------------------------------------------
# Grade canonicalization — the Turn 6 "3rd grade band" fix
# ----------------------------------------------------------------------


def test_grade_enum_matches_schema_literal() -> None:
    """canonicalizer.GRADE_ENUM must match schemas.intent.GradeValue.
    If one drifts without the other, QU output validation breaks."""
    from typing import get_args

    from schemas.intent import GradeValue

    schema_values = set(get_args(GradeValue))
    assert set(GRADE_ENUM) == schema_values, (
        f"GRADE_ENUM in canonicalizer.py drifted from GradeValue in "
        f"schemas/intent.py. Diff: canonicalizer has "
        f"{set(GRADE_ENUM) - schema_values}, schema has "
        f"{schema_values - set(GRADE_ENUM)}"
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Direct enum matches
        ("K", "K"),
        ("3", "3"),
        ("12", "12"),
        ("K-2", "K-2"),
        ("3-5", "3-5"),
        # Ordinal phrasings
        ("3rd grade", "3"),
        ("3rd graders", "3"),
        ("3rd", "3"),
        ("1st grade", "1"),
        ("5th graders", "5"),
        ("8th grade students", "8"),
        ("12th", "12"),
        # Word forms
        ("third grade", "3"),
        ("fifth graders", "5"),
        ("kindergarten", "K"),
        ("kindergartners", "K"),
        ("kinder", "K"),
        # Cardinal "grade N" phrasings
        ("grade 4", "4"),
        ("grade 10", "10"),
        # Band terms (vague → band code). Brady's own vocabulary:
        # "little ones", "primary", "upper elementary", "middle school"
        # each map to a canonical band. Downstream still asks which
        # specific grade within the band before generating a lesson.
        ("primary", "K-2"),
        ("little ones", "K-2"),
        ("upper elementary", "3-5"),
        ("intermediate", "3-5"),
        ("middle school", "6-8"),
        ("middle schoolers", "6-8"),
        ("high school", "9-12"),
        ("secondary", "9-12"),
        # Full-sentence context — extractor should still find the grade
        ("I teach 3rd graders", "3"),
        ("my 5th grade class", "5"),
        ("we're working with kindergartners", "K"),
    ],
)
def test_canonicalize_grade_recognizes_common_phrasings(
    raw: str, expected: str
) -> None:
    assert canonicalize_grade(raw) == expected


@pytest.mark.parametrize(
    "bad_input",
    [
        "",
        "   ",
        "my older kids",
        "the struggling ones",
        "advanced students",
        "teenagers",
        "3rd grade band",  # the Turn 6 hallucination phrasing — must return None
        "grade 13",  # out of range
        "5th grade band",  # disqualifier catches any "<thing> grade band"
    ],
)
def test_canonicalize_grade_returns_none_for_ambiguous_or_invalid(
    bad_input: str,
) -> None:
    """For inputs that don't cleanly map, return None so QU knows to
    surface missing_required=['grade'] and trigger clarification —
    Brady's 'ask, don't guess' principle.

    Note: 'little ones' / 'primary' / 'upper elementary' are Brady's
    own band terms and DO map to band values (K-2, 3-5). They're
    covered by the band tests. Band results still require downstream
    confirmation before use, but the canonicalizer itself returns the
    band code, not None.
    """
    assert canonicalize_grade(bad_input) is None


def test_canonicalize_grade_result_always_in_enum() -> None:
    """Every non-None result must be a valid enum value. This guards
    against regex-extractor regressions producing values that would
    then fail Pydantic validation downstream."""
    test_cases = [
        "3rd grade", "5th graders", "kindergarten", "grade 10",
        "K-2", "middle school", "high school", "upper elementary",
    ]
    for raw in test_cases:
        result = canonicalize_grade(raw)
        assert result in GRADE_ENUM, (
            f"canonicalize_grade({raw!r}) = {result!r}, not in GRADE_ENUM"
        )
