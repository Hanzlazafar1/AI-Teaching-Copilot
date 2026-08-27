"""Tests for config.py — settings loading and defaults."""

from config import settings


def test_settings_load():
    """Settings should load from .env without errors."""
    assert settings.openai_api_key != ""
    assert "gpt-5.4" in settings.openai_generation_model
    assert "gpt-5.4-mini" in settings.openai_judge_model
    assert "gpt-5.4-mini" in settings.openai_query_model


def test_settings_defaults():
    """Default values should be sensible."""
    assert settings.embedding_dimensions == 3072
    assert settings.judge_score_threshold == 85.0
    assert settings.max_generation_attempts == 3
    assert settings.generation_temperatures == [0.3, 0.4, 0.5]
    # Bumped 60 → 90 in Phase 11.9 to give the targeted-repair retry
    # headroom after the main 3-attempt loop.
    assert settings.route_timeout_seconds == 90.0
    assert settings.quality_floor_score == 40.0


def test_settings_retrieval_defaults():
    """Retrieval defaults should match the plan."""
    assert settings.retrieval_top_k_lesson == 10
    assert settings.retrieval_top_k_coaching == 8
    assert settings.context_token_budget == 10000
    assert settings.min_results_before_relaxation == 5


def test_settings_exclude_files():
    """Should exclude framework chunks file only (textbooks are ingested)."""
    excludes = settings.ingest_exclude_files
    assert "01-master-4step.json" in excludes
    assert len(excludes) == 1
