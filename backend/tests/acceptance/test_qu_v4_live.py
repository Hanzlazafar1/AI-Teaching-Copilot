"""Live QU v4 acceptance tests — hits the real OpenAI API.

Gated by the V4_QU_LIVE environment variable. Without it set, tests
are SKIPPED (no accidental spending on CI).

Run locally:

    cd copilot-v4
    V4_QU_LIVE=1 OPENAI_API_KEY=... pytest tests/acceptance/test_qu_v4_live.py -v

Expected runtime: ~3-5 seconds per fixture. Total ≈ 2 minutes for
all ~25 fixtures. Cost: ~$0.02/fixture at gpt-4o pricing.

Matching semantics (tolerant — QU output has small non-determinism
even at temperature 0):
  * request_type        — MUST MATCH EXACTLY
  * grade.value         — MUST MATCH if expected set
  * mode.value          — MUST MATCH if expected set
  * trait.value         — MUST MATCH if expected set
  * skill.canonical     — MUST MATCH if expected set (after canonicalization)
  * refers_to_prior     — MUST MATCH if expected True (lenient if False)
  * prior_turn_ref      — MUST MATCH if expected set (exact int)
  * reuse_example_from_prior — MUST MATCH if expected True
  * needs_confirmation  — MUST MATCH if expected True (lenient if False)
  * required_triggers   — expected subset must be contained in actual
                          (order-insensitive; actual may have more)
  * missing_required    — expected subset must be contained in actual

Strict-match fields fail the test; lenient fields warn.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from openai import AsyncOpenAI

from config import settings
from query.qu_v4 import understand
from query.qu_v4_fixtures import ALL_FIXTURES, QUFixture
from schemas import TurnIntent

# Gate the whole module behind V4_QU_LIVE to avoid accidental spend
pytestmark = pytest.mark.skipif(
    os.environ.get("V4_QU_LIVE") != "1",
    reason="Live QU tests — set V4_QU_LIVE=1 to run (requires OPENAI_API_KEY).",
)


# Model to use for tests — mirrors what generation would use.
# Override with V4_QU_LIVE_MODEL if needed for experiments.
# The PRODUCTION QU model (config.settings.openai_query_model = gpt-5.4-mini),
# not a hardcoded literal. This said "gpt-4o" until 2026-07-17 — a model
# CLAUDE.md records as RETIRED — so these 26 fixtures would have certified a
# model we do not ship. Sourcing it from settings means the harness cannot
# drift from production again.
_MODEL = os.environ.get("V4_QU_LIVE_MODEL", settings.openai_query_model)


@pytest.fixture(scope="module")
def client() -> AsyncOpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        pytest.fail("OPENAI_API_KEY must be set for live QU tests")
    return AsyncOpenAI(api_key=api_key)


def _assert_intent_matches(
    actual: TurnIntent,
    expected: TurnIntent,
    fixture_name: str,
) -> None:
    """Tolerant comparison of actual QU output against fixture expected."""
    failures: list[str] = []

    # request_type — exact match
    if actual.request_type is not expected.request_type:
        failures.append(
            f"request_type: expected {expected.request_type.value}, "
            f"got {actual.request_type.value}"
        )

    # grade.value — exact if expected set
    if expected.grade is not None:
        if actual.grade is None:
            failures.append(
                f"grade: expected value={expected.grade.value!r}, got None"
            )
        elif actual.grade.value != expected.grade.value:
            failures.append(
                f"grade.value: expected {expected.grade.value!r}, "
                f"got {actual.grade.value!r}"
            )

    # mode.value — exact if expected set
    if expected.mode is not None:
        if actual.mode is None:
            failures.append(f"mode: expected {expected.mode.value!r}, got None")
        elif actual.mode.value != expected.mode.value:
            failures.append(
                f"mode.value: expected {expected.mode.value!r}, "
                f"got {actual.mode.value!r}"
            )

    # trait.value — exact if expected set
    if expected.trait is not None:
        if actual.trait is None:
            failures.append(f"trait: expected {expected.trait.value!r}, got None")
        elif actual.trait.value != expected.trait.value:
            failures.append(
                f"trait.value: expected {expected.trait.value!r}, "
                f"got {actual.trait.value!r}"
            )

    # skill.canonical — exact if expected set
    if expected.skill is not None:
        if actual.skill is None:
            failures.append(
                f"skill: expected canonical={expected.skill.canonical!r}, got None"
            )
        elif actual.skill.canonical != expected.skill.canonical:
            failures.append(
                f"skill.canonical: expected {expected.skill.canonical!r}, "
                f"got {actual.skill.canonical!r}"
            )

    # refers_to_prior — exact match if expected True (lenient otherwise)
    if expected.refers_to_prior and not actual.refers_to_prior:
        failures.append(
            f"refers_to_prior: expected True, got {actual.refers_to_prior}"
        )

    # prior_turn_ref — exact if expected set
    if expected.prior_turn_ref is not None:
        if actual.prior_turn_ref != expected.prior_turn_ref:
            failures.append(
                f"prior_turn_ref: expected {expected.prior_turn_ref}, "
                f"got {actual.prior_turn_ref}"
            )

    # reuse_example_from_prior — exact if expected True
    if expected.reuse_example_from_prior and not actual.reuse_example_from_prior:
        failures.append(
            f"reuse_example_from_prior: expected True, "
            f"got {actual.reuse_example_from_prior}"
        )

    # needs_confirmation — exact if expected True
    if expected.needs_confirmation and not actual.needs_confirmation:
        failures.append(
            f"needs_confirmation: expected True, "
            f"got {actual.needs_confirmation}"
        )

    # required_triggers — expected subset must be in actual
    if expected.required_triggers:
        actual_set = set(actual.required_triggers)
        expected_set = set(expected.required_triggers)
        missing = expected_set - actual_set
        if missing:
            failures.append(
                f"required_triggers: expected {sorted(expected_set)}, "
                f"actual {sorted(actual_set)}, missing {sorted(missing)}"
            )

    # missing_required — expected subset must be in actual
    if expected.missing_required:
        actual_set = set(actual.missing_required)
        expected_set = set(expected.missing_required)
        missing = expected_set - actual_set
        if missing:
            failures.append(
                f"missing_required: expected {sorted(expected_set)}, "
                f"actual {sorted(actual_set)}, missing {sorted(missing)}"
            )

    if failures:
        pytest.fail(
            f"Fixture {fixture_name} — {len(failures)} mismatch(es):\n"
            + "\n".join(f"  - {f}" for f in failures)
            + f"\n\nActual intent: {actual.model_dump_json(indent=2)}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fix", ALL_FIXTURES, ids=lambda f: f.name)
async def test_qu_fixture_live(
    client: AsyncOpenAI,
    fix: QUFixture,
) -> None:
    """Run one fixture against the live QU model and verify it matches
    the expected TurnIntent."""
    actual = await understand(
        conversation=fix.conversation,
        new_user_message=fix.new_user_message,
        handshakes=fix.handshakes,
        client=client,
        model=_MODEL,
    )
    _assert_intent_matches(actual, fix.expected, fix.name)
