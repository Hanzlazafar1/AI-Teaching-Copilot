"""Acceptance test harness for Brady-alignment work.

These tests exercise the live HTTP API (uvicorn on localhost:8000).
They are expensive (real OpenAI calls) and slow. Run deliberately:

    pytest tests/acceptance/ -m acceptance

Prerequisites:
    - Backend server running on localhost:8000 (see SCREENS.md)
    - OPENAI_API_KEY set and funded
"""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

import pytest
import requests

# Reuse the scrubber's own page-token grammar so the B-P05 assertion can never
# demand a page-form the scrubber would strip (Fm5 reconciliation, Task 3).
from validation.citations import _CITED_PAGE_RE


# Override with `BRADY_API_BASE=http://localhost:8001 pytest …` when v3
# runs on a non-default port (e.g. v2 is still listening on 8000).
API_BASE = os.environ.get("BRADY_API_BASE", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = 120  # seconds per turn


# ---------------------------------------------------------------------------
# Connection check (skip entire suite if backend not running)
# ---------------------------------------------------------------------------


def _backend_available() -> bool:
    try:
        r = requests.get(f"{API_BASE}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.skipif(
        not _backend_available(),
        reason=f"Backend not reachable at {API_BASE}",
    ),
]


# ---------------------------------------------------------------------------
# Data classes for cleaner assertions
# ---------------------------------------------------------------------------


@dataclass
class TurnResponse:
    """Parsed /api/chat response with helpful accessors."""

    raw: dict[str, Any]
    elapsed: float

    @property
    def text(self) -> str:
        """Return response body as plain text regardless of type."""
        r = self.raw.get("response", "")
        if isinstance(r, dict):
            import json as _json
            return _json.dumps(r)
        return str(r)

    @property
    def is_lesson(self) -> bool:
        """True if response body is a MiniLesson dict."""
        return isinstance(self.raw.get("response"), dict) and "step_1_introduce" in (
            self.raw.get("response") or {}
        )

    @property
    def lesson(self) -> dict[str, Any]:
        """Return the MiniLesson dict (empty if not a lesson)."""
        r = self.raw.get("response")
        return r if isinstance(r, dict) else {}

    @property
    def parsed_query(self) -> dict[str, Any]:
        return self.raw.get("parsed_query") or {}

    @property
    def intent(self) -> str:
        return self.parsed_query.get("intent") or self.raw.get("intent") or ""

    @property
    def query_type(self) -> str:
        """Extended QU field added in Phase 5. May not exist pre-implementation."""
        return self.parsed_query.get("query_type") or ""

    @property
    def quality(self) -> str:
        return self.raw.get("quality") or ""

    @property
    def score(self) -> Optional[float]:
        return self.raw.get("judge_score")

    @property
    def sources(self) -> list[dict[str, Any]]:
        return self.raw.get("sources") or []

    @property
    def retrieved_context(self) -> str:
        return self.raw.get("retrieved_context") or ""

    @property
    def ungrounded_terms(self) -> list[str]:
        return self.raw.get("ungrounded_terms") or []

    @property
    def top_source(self) -> dict[str, Any]:
        return self.sources[0] if self.sources else {}

    def source_section_names(self) -> list[str]:
        """Return section_name for each source if available."""
        # section_name is not in current SourceInfo but may be in retrieved_context
        # Fall back to chunk_id pattern scanning
        out: list[str] = []
        for s in self.sources:
            out.append(s.get("chunk_id", ""))
        return out


# ---------------------------------------------------------------------------
# Multi-turn session helper
# ---------------------------------------------------------------------------


class ChatSession:
    """Stateful HTTP chat client for multi-turn acceptance tests."""

    def __init__(self, user_id: str = "acceptance-test") -> None:
        self.session_id = str(uuid.uuid4())
        self.user_id = user_id
        self.turns: list[TurnResponse] = []

    def send(self, message: str) -> TurnResponse:
        start = time.time()
        resp = requests.post(
            f"{API_BASE}/api/chat",
            json={
                "message": message,
                "session_id": self.session_id,
                "user_id": self.user_id,
            },
            timeout=REQUEST_TIMEOUT,
        )
        elapsed = time.time() - start
        assert resp.status_code == 200, (
            f"HTTP {resp.status_code}: {resp.text[:300]}"
        )
        turn = TurnResponse(raw=resp.json(), elapsed=elapsed)
        self.turns.append(turn)
        return turn

    @property
    def last(self) -> TurnResponse:
        return self.turns[-1]


@pytest.fixture
def chat() -> Iterator[ChatSession]:
    """Fresh ChatSession per test."""
    yield ChatSession()


@pytest.fixture
def fresh_session_id() -> str:
    """Unique session_id for tests that manage their own calls."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Property-based assertion helpers (reusable across tests)
# ---------------------------------------------------------------------------


def assert_top_source_matches(
    response: TurnResponse,
    pattern: str,
    in_first_n: int = 3,
) -> None:
    """Assert at least one of the top-N sources has chunk_id matching pattern (regex)."""
    rx = re.compile(pattern, re.IGNORECASE)
    top_n = response.sources[:in_first_n]
    hits = [s for s in top_n if rx.search(s.get("chunk_id", ""))]
    assert hits, (
        f"Expected chunk_id matching /{pattern}/ in top {in_first_n} sources. "
        f"Got: {[s.get('chunk_id') for s in top_n]}"
    )


def assert_source_from_book(
    response: TurnResponse,
    book_hint: str,
    in_first_n: int = 3,
) -> None:
    """Assert at least one of the top-N sources is from the given book.

    book_hint: 'Teal' (3-12), 'K-2', 'launch', etc.
    """
    top_n = response.sources[:in_first_n]
    pattern_map = {
        "teal": r"lww312|3-12|3 12",
        "k-2": r"\bk2\b|k-2|K 2",
        "launch": r"lww312|\bk2\b|Launching",
    }
    pattern = pattern_map.get(book_hint.lower(), book_hint)
    rx = re.compile(pattern, re.IGNORECASE)
    hits = [
        s for s in top_n
        if rx.search(s.get("chunk_id", "") + " " + s.get("source_document", ""))
    ]
    assert hits, (
        f"Expected source from {book_hint!r} book in top {in_first_n}. "
        f"Got: {[(s.get('chunk_id'), s.get('source_document')) for s in top_n]}"
    )


def assert_response_ends_with_any(
    response: TurnResponse,
    endings: list[str],
    window: int = 500,
) -> None:
    """Assert response text ends with one of the approved prompts (case-insensitive)."""
    tail = response.text.rstrip()[-window:].lower()
    matched = [e for e in endings if e.lower() in tail]
    assert matched, (
        f"Expected response to end with one of {endings!r}. "
        f"Last {window} chars: {tail[-200:]!r}"
    )


def assert_no_forbidden_words(response: TurnResponse, words: list[str]) -> None:
    """Assert none of the forbidden words appear in the response text."""
    text = response.text.lower()
    found: list[str] = []
    for w in words:
        # Word-boundary match to avoid false positives (e.g. "activity" vs "passivity")
        if re.search(rf"\b{re.escape(w.lower())}\b", text):
            found.append(w)
    assert not found, (
        f"Forbidden words found in response: {found}. "
        f"Response preview: {text[:200]!r}"
    )


def assert_lesson_step_ratio(
    response: TurnResponse,
    step_2b_over_step_1: float = 3.0,
    step_2a_over_step_1: float = 2.0,
) -> None:
    """Assert Step 2A ≥ 2× Step 1 and Step 2B ≥ 3× (enforced floor) Step 1 (word counts)."""
    assert response.is_lesson, "Response is not a MiniLesson"
    l = response.lesson
    s1 = len((l.get("step_1_introduce") or "").split())
    s2a = len((l.get("step_2a_tell") or "").split())
    s2b = len((l.get("step_2b_show") or "").split())
    assert s1 > 0, "Step 1 is empty"
    assert s2a >= step_2a_over_step_1 * s1, (
        f"Step 2A too short: {s2a} words < {step_2a_over_step_1}× Step 1 ({s1})"
    )
    assert s2b >= step_2b_over_step_1 * s1, (
        f"Step 2B too short: {s2b} words < {step_2b_over_step_1}× Step 1 ({s1})"
    )


def assert_step_3_has_required_phrases(response: TurnResponse) -> None:
    """Assert Step 3 contains the required Smekens phrases."""
    assert response.is_lesson, "Response is not a MiniLesson"
    s3 = (response.lesson.get("step_3_interact") or "").lower()
    required = [
        "help me with the next",
        "turn and talk",
        "back to me",
        "this is some of what",
    ]
    missing = [p for p in required if p not in s3]
    assert not missing, f"Step 3 missing required phrases: {missing}. Got: {s3[:300]!r}"


def assert_step_2b_has_internal_monologue(response: TurnResponse) -> None:
    """Assert Step 2B contains think-aloud/monologue language."""
    assert response.is_lesson, "Response is not a MiniLesson"
    s2b = (response.lesson.get("step_2b_show") or "").lower()
    phrases = [
        "i close my eyes",
        "i wonder",
        "i think to myself",
        "let me try",
        "that doesn't work",
        "hmm",
    ]
    hits = [p for p in phrases if p in s2b]
    assert len(hits) >= 2, (
        f"Step 2B should contain ≥2 internal-monologue phrases. "
        f"Found: {hits}. Step 2B preview: {s2b[:300]!r}"
    )


def assert_book_citation_present(response: TurnResponse) -> None:
    """If a retrieved chunk is from a Launch book AND the response cites it,
    the citation must name a real page in a form the scrubber recognizes.

    Reconciled for Fm5 (Brady's softer / conditional citation, 2026-07-14).
    Brady's preferred wording is "If you have the {book} book, then you'll
    find this lesson on p.{N}." — a soft ``p.N`` page token and NO mandatory
    "digital resources" reminder. The old assert hard-required ``page\\s*\\d+``
    AND the literal "digital resources", which Brady's OWN form fails. So:

      * accept any page token the scrubber accepts — reuse the scrubber's
        ``_CITED_PAGE_RE`` (``page N`` / ``p. N`` / ``pg. N`` / ``pp. N``) so
        this assertion can never demand a page-form the scrubber would strip;
        and
      * treat "digital resources" as OPTIONAL — the organizer-location
        pointer is a separate feature the LLM MAY still add, not a hard
        requirement of a book citation.

    Still enforced: when a Launch chunk is cited, a recognizable page token
    must be present (a book pointer with no page is not a usable citation).

    NOTE (Brady demo): the exact softer wording + dropping "digital
    resources" as *required* are Brady's documented Fm5 preference and remain
    his to confirm / tweak at demo.
    """
    has_launch_source = any(
        "lww312" in (s.get("chunk_id") or "").lower()
        or re.search(r"\bk2\b", s.get("chunk_id") or "", re.I)
        for s in response.sources
    )
    if not has_launch_source:
        return  # no citation required
    text = response.text
    assert _CITED_PAGE_RE.search(text), (
        f"Launch book chunk in sources but no page token (page N / p. N) "
        f"in response. Text tail: {text[-300:]!r}"
    )


def assert_skill_focus_preserves(response: TurnResponse, expected_phrase: str) -> None:
    """Assert lesson's skill_focus field preserves the user's requested phrase."""
    assert response.is_lesson, "Response is not a MiniLesson"
    skill_focus = (response.lesson.get("skill_focus") or "").lower()
    assert expected_phrase.lower() in skill_focus, (
        f"Expected skill_focus to contain {expected_phrase!r}. Got {skill_focus!r}"
    )
