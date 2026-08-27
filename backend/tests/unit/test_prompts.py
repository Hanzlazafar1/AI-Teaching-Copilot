"""Tests for generation/prompts.py — framework-rules and known-terms loading."""

from generation.prompts import (
    get_framework_rules,
    get_known_terms,
    init_prompts,
)


class TestInitPrompts:
    """Verify startup loading."""

    def test_init_loads_framework(self):
        init_prompts()
        rules = get_framework_rules()
        assert len(rules) > 100
        assert "mini-lesson" in rules.lower() or "mini lesson" in rules.lower()

    def test_init_loads_known_terms(self):
        init_prompts()
        terms = get_known_terms()
        assert len(terms) > 10
        # Curated terms should be present
        assert "slinky test" in terms
        assert "think aloud" in terms
        assert "turn and talk" in terms
