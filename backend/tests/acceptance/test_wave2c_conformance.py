"""Wave 2c conformance — live scenarios (property-based, skip-if-no-server).

Assert the app's OWN production validators hold on live output; single- AND
multi-turn. Generic, not overfit to Brady's example phrasings — every check is
an invariant computed by the shipped validators themselves:

  * N2 (validation.vocabulary.validate_story_only_narrative): an informative
    coaching reply must not mislabel the piece a "story" — enforced on turn 1
    and carried across a multi-turn session; a legitimate metaphorical "story"
    must NOT be forced to LOW (N2 is LLM-trustable on the markdown path).
  * E4 (validation.endings): a coaching reply closes with a SINGLE question —
    never a concrete next-step offer AND the generic "Does this make sense?"
    closer stacked together — and validate_response_ending must accept it. This
    live test is an invariant GUARD (validate_response_ending passes for one OR
    two questions); the dedup logic itself is proven by the Task 5 unit tests.

Skips automatically when no backend is up. It carries its OWN skip guard — a
conftest-level ``pytestmark`` does not propagate to sibling test modules — and
mirrors tests/acceptance/test_protected_baseline.py. ``API_BASE`` is imported
from the acceptance conftest so this guard checks the exact base URL the shared
``chat`` fixture connects to.

Run:  (backend up)  python3 -m pytest tests/acceptance/test_wave2c_conformance.py -q
"""
from __future__ import annotations

import pytest
import requests

from validation.policy import validate_response_ending, validate_story_only_narrative
from validation.endings import _OFFER_RE  # reuse the SoT offer regex (no hand-typed list)
from tests.acceptance.conftest import API_BASE  # same base the `chat` fixture connects to


def _server_up() -> bool:
    try:
        return requests.get(f"{API_BASE}/health", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.skipif(not _server_up(), reason=f"backend not reachable at {API_BASE}"),
]


class TestN2MarkdownLive:
    """Brady N2 on the live markdown path — 'story' stays narrative-only."""

    def test_informative_coaching_no_story_misuse(self, chat):
        text = chat.send(
            "For 3rd grade informative writing, how do I teach strong conclusions?"
        ).text
        assert validate_story_only_narrative(text, mode="Inform") == [], text[:400]

    def test_informative_mode_carries_multiturn(self, chat):
        # Reuse the SAME chat object → its session_id threads the informative
        # framing set on turn 1 into turn 2, which must still stay N2-clean.
        chat.send("I'm planning a 4th grade informative writing unit.")
        text = chat.send("How should I teach using precise vocabulary?").text
        assert validate_story_only_narrative(text, mode="Inform") == [], text[:400]

    def test_metaphorical_story_does_not_ship_low(self, chat):
        # De-overfit probe: an informative topic that invites "the data tells a
        # story". N2 is LLM-trustable on the markdown path, so a lone legitimate
        # 'story' must NOT force LOW / an empty body. Property: a real,
        # non-trivial reply comes back.
        resp = chat.send(
            "How do I teach 5th graders to interpret a data table in an "
            "informative report?"
        )
        assert resp.text and len(resp.text) > 50


class TestE4SingleQuestionLive:
    """Brady E4 on the live coaching path — a SINGLE closing question."""

    def test_coaching_single_closing_question(self, chat):
        text = chat.send(
            "What's a good way to help 5th graders add supporting details?"
        ).text
        tail = text[-220:]
        has_offer = bool(_OFFER_RE.search(tail))
        has_generic = (
            "does this make sense" in tail.lower()
            or "is this helpful" in tail.lower()
        )
        assert not (has_offer and has_generic), tail
        assert validate_response_ending("COACHING_GENERAL", text) == []
