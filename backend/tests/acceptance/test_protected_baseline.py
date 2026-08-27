"""Live golden-master (wave-boundary regression gate).

Re-runs the Brady Protected Set against the live backend and asserts the same
invariants the offline baseline satisfies. Skips automatically when no backend
is up. This is the slow, high-fidelity check run at each wave boundary — not the
per-change gate (that's tests/unit). See implementation-strategy.md §1c.

Run:  (backend up)  python3 -m pytest tests/acceptance/test_protected_baseline.py -q
"""
from __future__ import annotations

import os
import uuid

import pytest
import requests

from tests.protected_invariants import check_all
from tests.protected_set import PROTECTED_SET

API_BASE = os.environ.get("BRADY_API_BASE", "http://127.0.0.1:8000").rstrip("/")


def _server_up() -> bool:
    try:
        return requests.get(f"{API_BASE}/health", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.skipif(not _server_up(), reason=f"backend not reachable at {API_BASE}"),
]


def _post(message: str, session_id: str) -> dict:
    r = requests.post(
        f"{API_BASE}/api/chat",
        json={"message": message, "session_id": session_id},
        timeout=180,
    )
    r.raise_for_status()
    return r.json()


@pytest.mark.parametrize("case", PROTECTED_SET, ids=lambda c: c.id)
def test_live_protected_invariants(case):
    sid = f"gm-{case.id}-{uuid.uuid4().hex[:6]}"
    for pm in case.prior_messages:
        _post(pm, sid)  # establish session context first
    resp = _post(case.message, sid)
    failures = [f"{inv}: {detail}" for inv, ok, detail in check_all(case, resp) if not ok]
    assert not failures, f"{case.id} live invariant failures:\n" + "\n".join(failures)
