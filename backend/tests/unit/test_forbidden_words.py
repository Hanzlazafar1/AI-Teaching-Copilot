"""Tests for validation/forbidden_words.py (Wave 0 Part 2 test colocation)."""
from __future__ import annotations

import pytest

from validation.forbidden_words import (
    scrub_forbidden_words,
    validate_no_forbidden_words,
)


class TestForbiddenWords:
    def test_clean_text_passes(self):
        assert validate_no_forbidden_words(
            "Today students will turn and talk about transitions."
        ) == []

    @pytest.mark.parametrize("word", ["discuss", "activity", "I'll listen in"])
    def test_flags_forbidden_word(self, word):
        errors = validate_no_forbidden_words(f"Students will {word} in groups.")
        assert errors
        assert word in errors[0]

    def test_case_insensitive(self):
        assert validate_no_forbidden_words("DISCUSS the lesson.")

    def test_professional_development_flagged(self):
        errors = validate_no_forbidden_words("Complete the professional development module.")
        assert errors
        assert "professional development" in errors[0]

    def test_certificate_flagged(self):
        assert validate_no_forbidden_words("Get your certificate.")

    def test_word_boundary_protects_innocent_substrings(self):
        # 'discusse' is a different word; shouldn't match 'discuss'.
        assert validate_no_forbidden_words("The activitynomy of teaching.") == []


class TestForbiddenWordScrubber:
    """Bucket B — retry-exhaustion scrubber (R2-K2 fix).

    When the generator can't comply with the forbidden-word rule after
    retries, the scrubber substitutes safe replacements so the user never
    sees 'discuss' / 'activity' / PD framing. This is the last line of
    defense for Brady's 'never, never, never' rule.
    """

    def test_scrubs_discuss_to_turn_and_talk(self):
        out, subs = scrub_forbidden_words("Students discuss the lesson.")
        assert "discuss" not in out.lower() or "turn-and-talk" in out
        assert subs == ["discuss"]

    def test_scrubs_activity_to_mini_lesson(self):
        out, subs = scrub_forbidden_words("We do an activity about voice.")
        assert "activity" not in out.lower()
        assert "mini-lesson" in out
        assert subs == ["activity"]

    def test_scrubs_professional_development(self):
        out, subs = scrub_forbidden_words(
            "Brady, if you're interested in our professional development options..."
        )
        assert "professional development" not in out.lower()
        assert "instructional coaching" in out
        assert subs == ["professional development"]

    def test_scrubs_certificate_to_empty(self):
        out, subs = scrub_forbidden_words("Complete the course to receive your certificate.")
        assert "certificate" not in out.lower()
        assert subs == ["certificate"]

    def test_no_scrub_on_clean_text(self):
        text = "Today students will turn and talk about transitions."
        out, subs = scrub_forbidden_words(text)
        assert out == text
        assert subs == []

    def test_scrubbed_text_passes_validator(self):
        """Post-scrub validation must succeed — we never ship forbidden
        words even after retry exhaustion."""
        dirty = "Students will discuss during the activity."
        clean, subs = scrub_forbidden_words(dirty)
        assert validate_no_forbidden_words(clean) == []
        assert set(subs) == {"discuss", "activity"}

    def test_multiple_occurrences_all_scrubbed(self):
        """Every occurrence gets replaced, not just the first."""
        dirty = "Discussion today includes an activity plus another activity."
        clean, subs = scrub_forbidden_words(dirty)
        assert "activity" not in clean.lower()
        assert "discussion" not in clean.lower()
        assert len(subs) >= 3  # one 'discussion' + two 'activity'

    # -- Newline / paragraph preservation (Task 8 review fix, Brady #11) --
    #
    # This scrubber is wired onto the full multi-paragraph delivery text
    # (_build_text_outcome). Its whitespace-cleanup step must NEVER collapse
    # the "\n\n" paragraph breaks Brady non-negotiable #11 requires. Two
    # guarantees: (1) on clean text (no substitution) the cleanup is skipped
    # entirely, so output is byte-identical; (2) even when a substitution
    # DOES trigger the cleanup, it collapses only spaces/tabs, never newlines.

    def test_clean_multiparagraph_text_is_byte_identical(self):
        """Regression guard: with NO forbidden word, the scrubber returns
        the input unchanged — including every newline. The old
        unconditional `re.sub(r"\\s{2,}", " ", ...)` flattened "\\n\\n" into
        a single space here (\\s matches newlines), collapsing paragraphs."""
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        out, subs = scrub_forbidden_words(text)
        assert out == text
        assert subs == []

    def test_clean_markdown_list_is_byte_identical(self):
        """A numbered list with a blank line before it must survive intact —
        the paragraph break in front of the list is structural."""
        text = "Try these:\n\n1. First\n2. Second"
        out, subs = scrub_forbidden_words(text)
        assert out == text
        assert subs == []

    def test_multiparagraph_with_forbidden_word_preserves_breaks(self):
        """When a forbidden word IS present, it gets substituted AND the
        "\\n\\n" paragraph break is preserved (cleanup collapses spaces/tabs
        only, via the [^\\S\\n] class)."""
        text = "Let's discuss the plan.\n\nThen do the activity together."
        out, subs = scrub_forbidden_words(text)
        assert "\n\n" in out  # paragraph break survived
        assert "discuss" not in out.lower()
        assert "activity" not in out.lower()
        assert set(subs) == {"discuss", "activity"}

    def test_empty_replacement_artifact_still_cleaned_when_subs_fire(self):
        """The gated cleanup must still run when a substitution happens: the
        empty-string replacements ("certificate"→"" / "PD sign-off"→"")
        leave a double space that has to be collapsed. This proves gating on
        `subs` didn't disable the cleanup where it's actually needed."""
        out, subs = scrub_forbidden_words("Get your certificate now.")
        assert "certificate" not in out.lower()
        assert "  " not in out  # no lingering double space
        assert subs == ["certificate"]
