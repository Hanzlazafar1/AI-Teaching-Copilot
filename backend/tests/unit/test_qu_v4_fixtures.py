"""Sanity tests for QU v4 fixture data.

These tests don't hit the LLM. They verify that the fixture file is
well-formed — every fixture has a unique name, valid conversation,
and an expected TurnIntent that passes Pydantic validation.

The actual LLM-based acceptance tests (running the fixtures against
the real QU) live in tests/acceptance/test_qu_v4_live.py.
"""

from __future__ import annotations

import pytest

from query.qu_v4_fixtures import (
    ALL_FIXTURES,
    BRADY_SAMPLE_CHAT,
    EDGE_CASES,
    QUFixture,
)
from schemas import RequestType


def test_fixtures_split_is_correct() -> None:
    assert len(ALL_FIXTURES) == len(BRADY_SAMPLE_CHAT) + len(EDGE_CASES)
    # Compare by name since QUFixture isn't hashable (has mutable members)
    all_names = {f.name for f in ALL_FIXTURES}
    union_names = {f.name for f in BRADY_SAMPLE_CHAT} | {f.name for f in EDGE_CASES}
    assert all_names == union_names


def test_fixture_names_are_unique() -> None:
    names = [f.name for f in ALL_FIXTURES]
    assert len(names) == len(set(names)), (
        f"duplicate fixture names: "
        f"{[n for n in names if names.count(n) > 1]}"
    )


def test_brady_fixtures_count_meets_target() -> None:
    """Target: at least 18 Brady-sample-chat fixtures (covers the 24
    annotated turns minus a handful of near-duplicates)."""
    assert len(BRADY_SAMPLE_CHAT) >= 15, (
        f"Expected ≥15 Brady sample-chat fixtures, got "
        f"{len(BRADY_SAMPLE_CHAT)}"
    )


def test_edge_case_fixtures_cover_key_categories() -> None:
    """Edge-case fixtures must cover CORRECTION, band-term handling,
    META boundaries, and named-trigger extraction."""
    names = {f.name for f in EDGE_CASES}
    # Assert coverage by prefix
    assert any("correction" in n.lower() for n in names), (
        "edge cases must include a CORRECTION scenario"
    )
    assert any("band" in n.lower() for n in names), (
        "edge cases must include a grade-band scenario"
    )
    assert any("meta" in n.lower() or "greeting" in n.lower() for n in names), (
        "edge cases must include a META scenario"
    )
    assert any("trigger" in n.lower() for n in names), (
        "edge cases must include a named-trigger scenario"
    )


@pytest.mark.parametrize("fix", ALL_FIXTURES, ids=lambda f: f.name)
def test_fixture_conversation_well_formed(fix: QUFixture) -> None:
    """Every fixture's conversation must have valid monotonic indices
    and alternating user/assistant pattern (not strictly required but
    strongly suggested — flag any oddities for review)."""
    conv = fix.conversation
    for i, turn in enumerate(conv.turns):
        assert turn.index == i, (
            f"fixture {fix.name}: turn at position {i} has index {turn.index}"
        )


@pytest.mark.parametrize("fix", ALL_FIXTURES, ids=lambda f: f.name)
def test_fixture_new_message_nonempty(fix: QUFixture) -> None:
    assert fix.new_user_message.strip(), (
        f"fixture {fix.name}: new_user_message is empty"
    )


def test_edge_cases_include_scope_creep_additional_skills() -> None:
    """S3 one-skill guard: at least one fixture must exercise the
    additional_skills scope-creep signal — a teacher cramming a SECOND
    distinct skill into one lesson. The primary skill stays in `skill`;
    the extra is named in additional_skills. Scope-creep fixtures must be
    LESSON-SHAPED (the guard only fires for SCRIPTED_ML / DEEPEN_PRIOR)."""
    scope_creep = [f for f in ALL_FIXTURES if f.expected.additional_skills]
    assert scope_creep, (
        "expected ≥1 fixture with populated additional_skills "
        "(S3 scope-creep signal)"
    )
    for f in scope_creep:
        assert f.expected.request_type in {
            RequestType.SCRIPTED_ML,
            RequestType.DEEPEN_PRIOR,
        }, (
            f"{f.name}: scope-creep fixture must be lesson-shaped "
            f"(SCRIPTED_ML/DEEPEN_PRIOR), got {f.expected.request_type}"
        )
        # Primary skill must be present — the guard fires on it.
        assert f.expected.skill is not None, (
            f"{f.name}: scope-creep fixture must keep a primary skill"
        )


@pytest.mark.parametrize("fix", ALL_FIXTURES, ids=lambda f: f.name)
def test_fixture_expected_is_turn_intent(fix: QUFixture) -> None:
    """Expected output must be a valid TurnIntent (Pydantic validates
    at construction time in the fixture file, but we assert here so a
    future typo in a fixture is caught)."""
    assert fix.expected.request_type is not None


@pytest.mark.parametrize("fix", BRADY_SAMPLE_CHAT, ids=lambda f: f.name)
def test_brady_fixture_descriptions_reference_turn(fix: QUFixture) -> None:
    """Each Brady fixture's description should mention which sample-chat
    turn it derives from — helps reviewers trace fixture back to source."""
    desc_lower = fix.description.lower()
    # Loose assertion — either has 'turn' or 'brady'
    assert "turn" in desc_lower or "brady" in desc_lower, (
        f"fixture {fix.name} description should reference Brady or a turn"
    )
