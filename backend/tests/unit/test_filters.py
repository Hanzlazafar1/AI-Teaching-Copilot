"""Tests for retrieval/filters.py — metadata filter building and relaxation."""

import pytest
from qdrant_client import models

from retrieval.filters import GRADE_RANGE_MAP, build_filter, relax_filter


class TestGradeRangeMap:
    """Verify grade expansion covers all expected ranges."""

    def test_grade_k_includes_ranges(self):
        expanded = GRADE_RANGE_MAP["K"]
        assert "K" in expanded
        assert "K-2" in expanded
        assert "K-5" in expanded
        assert "K-12" in expanded
        assert "3-5" not in expanded

    def test_grade_3_includes_ranges(self):
        expanded = GRADE_RANGE_MAP["3"]
        assert "3" in expanded
        assert "3-5" in expanded
        assert "K-5" in expanded
        assert "3-12" in expanded
        assert "K-12" in expanded
        assert "K-2" not in expanded

    def test_grade_7_includes_6_12(self):
        expanded = GRADE_RANGE_MAP["7"]
        assert "6-8" in expanded
        assert "6-12" in expanded
        assert "3-12" in expanded

    def test_grade_10_includes_secondary_ranges(self):
        expanded = GRADE_RANGE_MAP["10"]
        assert "9-12" in expanded
        assert "6-12" in expanded
        assert "3-12" in expanded
        assert "K-12" in expanded
        assert "6-8" not in expanded

    def test_all_grades_present(self):
        single = {"K"} | {str(i) for i in range(1, 13)}
        bands = {"K-2", "3-5", "6-8", "9-12"}
        assert set(GRADE_RANGE_MAP.keys()) == single | bands

    def test_band_grade_expands_to_union_of_members(self):
        expanded = GRADE_RANGE_MAP["6-8"]
        for g in ("6", "7", "8", "6-8", "6-12", "3-12", "K-12"):
            assert g in expanded
        # No cross-grade leak: a middle-school query must not pull elementary tags.
        for g in ("K-2", "3-5", "K-5", "K"):
            assert g not in expanded

    def test_pk1_reachable_from_early_grades_only(self):
        assert "PK-1" in GRADE_RANGE_MAP["K"]
        assert "PK-1" in GRADE_RANGE_MAP["1"]
        assert "PK-1" in GRADE_RANGE_MAP["K-2"]
        assert "PK-1" not in GRADE_RANGE_MAP["2"]
        assert "PK-1" not in GRADE_RANGE_MAP["6-8"]


class TestBuildFilter:
    """Verify filter construction from parsed query fields."""

    def test_empty_filter(self):
        f = build_filter()
        assert f.must is None or len(f.must) == 0

    def test_mini_lesson_copilot_mode(self):
        f = build_filter(intent="mini_lesson")
        assert len(f.must) == 1
        cond = f.must[0]
        assert cond.key == "copilot_mode"
        assert "lesson_generation" in cond.match.any
        assert "both" in cond.match.any

    def test_coaching_no_copilot_mode_filter(self):
        """Coaching queries search all copilot_modes (lesson chunks have strategy details)."""
        f = build_filter(intent="coaching")
        copilot_conds = [c for c in (f.must or []) if hasattr(c, 'key') and c.key == "copilot_mode"]
        assert len(copilot_conds) == 0

    def test_grade_level_expansion(self):
        f = build_filter(grade_level="3")
        grade_cond = [c for c in f.must if c.key == "grade_level"][0]
        assert "3" in grade_cond.match.any
        assert "K-5" in grade_cond.match.any
        assert "3-12" in grade_cond.match.any

    def test_writing_mode_includes_all(self):
        f = build_filter(writing_mode="Inform")
        mode_cond = [c for c in f.must if c.key == "writing_mode"][0]
        assert "Inform" in mode_cond.match.any
        assert "all" in mode_cond.match.any

    def test_writing_trait_includes_all(self):
        f = build_filter(writing_trait="Organization")
        trait_cond = [c for c in f.must if c.key == "writing_trait"][0]
        assert "Organization" in trait_cond.match.any
        assert "all" in trait_cond.match.any

    def test_full_filter(self):
        f = build_filter(
            intent="mini_lesson",
            grade_level="3",
            writing_mode="Inform",
            writing_trait="Ideas",
        )
        keys = {c.key for c in f.must}
        assert keys == {"copilot_mode", "grade_level", "writing_mode", "writing_trait"}

    def test_step_focus_exact_match(self):
        f = build_filter(step_focus="step_2b_show")
        step_cond = [c for c in f.must if c.key == "step"][0]
        assert step_cond.match.value == "step_2b_show"

    def test_unknown_grade_ignored(self):
        f = build_filter(grade_level="99")
        grade_conds = [c for c in (f.must or []) if c.key == "grade_level"]
        assert len(grade_conds) == 0

    def test_band_grade_builds_grade_condition(self):
        f = build_filter(grade_level="6-8")
        grade_conds = [c for c in (f.must or []) if getattr(c, "key", None) == "grade_level"]
        assert len(grade_conds) == 1  # band grade no longer silently skips the filter


class TestRelaxFilter:
    """Verify progressive filter relaxation."""

    def test_relax_step1_drops_trait(self):
        original = build_filter(
            intent="mini_lesson",
            grade_level="3",
            writing_mode="Inform",
            writing_trait="Ideas",
        )
        relaxed = relax_filter(original, 1)
        assert relaxed is not None
        keys = {c.key for c in relaxed.must}
        assert "writing_trait" not in keys
        assert "writing_mode" in keys

    def test_relax_step2_drops_mode(self):
        original = build_filter(
            intent="mini_lesson",
            grade_level="3",
            writing_mode="Inform",
        )
        relaxed = relax_filter(original, 2)
        assert relaxed is not None
        keys = {c.key for c in relaxed.must}
        assert "writing_mode" not in keys

    def test_relax_step3_drops_grade(self):
        original = build_filter(
            intent="mini_lesson",
            grade_level="3",
        )
        relaxed = relax_filter(original, 3)
        assert relaxed is not None
        keys = {c.key for c in relaxed.must}
        assert "grade_level" not in keys
        # copilot_mode should remain
        assert "copilot_mode" in keys

    def test_relax_nothing_to_drop(self):
        original = build_filter(intent="mini_lesson")
        # Step 1 drops writing_trait, but there is none
        relaxed = relax_filter(original, 1)
        assert relaxed is None

    def test_relax_empty_filter(self):
        original = build_filter()
        relaxed = relax_filter(original, 1)
        assert relaxed is None


class TestTraitFilterConditional:
    """Issue R02: writing_trait filter must be suppressed when strategy_name
    is set, because QU's stochastic trait inference on specific-skill queries
    can mis-classify (e.g. "narrative introductions" labeled Ideas when the
    chunk's canonical trait is Organization), silently excluding the correct
    chunk. See FEEDBACK-ISSUES.md R02."""

    def test_trait_applied_when_no_strategy_name(self):
        """Broad query ('what to teach for 5th-grade Voice') → trait is the
        primary category signal; filter must apply."""
        f = build_filter(
            grade_level="5",
            writing_trait="Voice",
            strategy_name=None,
        )
        keys = {c.key for c in f.must}
        assert "writing_trait" in keys

    def test_trait_suppressed_when_strategy_name_present(self):
        """Specific skill query ('teach narrative introductions') → skill
        owns trait routing; filter must NOT apply."""
        f = build_filter(
            grade_level="9",
            writing_trait="Ideas",  # QU's misinference
            strategy_name="narrative introductions",
        )
        keys = {c.key for c in f.must}
        assert "writing_trait" not in keys, (
            "writing_trait filter must be suppressed when strategy_name is "
            "set (R02) — otherwise QU's mis-classified trait can silently "
            "exclude the chunk matching the named skill."
        )
        assert "grade_level" in keys  # other filters unaffected

    def test_mode_filter_still_applies_with_strategy_name(self):
        """Only trait is conditional — mode/grade stay authoritative."""
        f = build_filter(
            grade_level="3",
            writing_mode="Inform",
            writing_trait="Ideas",
            strategy_name="topic sentences",
        )
        keys = {c.key for c in f.must}
        assert "writing_trait" not in keys
        assert "writing_mode" in keys
        assert "grade_level" in keys

    def test_falsy_strategy_name_keeps_trait_filter(self):
        """Empty-string strategy_name is 'no skill named'; filter still
        applies for broad queries."""
        f = build_filter(
            grade_level="3",
            writing_trait="Voice",
            strategy_name="",
        )
        keys = {c.key for c in f.must}
        assert "writing_trait" in keys

    def test_no_trait_means_no_filter_regardless_of_strategy(self):
        f = build_filter(
            grade_level="3",
            writing_trait=None,
            strategy_name="transitions",
        )
        keys = {c.key for c in f.must}
        assert "writing_trait" not in keys
