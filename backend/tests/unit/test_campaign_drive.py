"""Unit tests for the campaign drive client (``campaign/drive.py``).

The drive client is the verification campaign's HTTP front-end to
``/api/chat``. Per the design spec (§6) *upstream errors are non-verdicts*:
throttles / provider outages / timeouts must NEVER surface as a real answer
and must NEVER crash the run. These tests pin that contract with fully
mocked HTTP — no live backend, no real network.
"""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest
import requests

from campaign import drive

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_response(status_code: int, payload=None, *, headers=None) -> Mock:
    """Build a stand-in for a ``requests.Response``."""
    m = Mock()
    m.status_code = status_code
    m.json.return_value = {} if payload is None else payload
    m.text = "" if payload is None else json.dumps(payload)
    m.headers = headers or {}
    return m


_OK_PAYLOAD = {
    "response": "Here is your mini-lesson.",
    "intent": "coaching_general",
    "quality": "validated",
    "sources": [{"chunk_id": "c1", "source_tier": 1}],
    "retrieved_context": "ctx",
    "judge_score": 0.92,
    "session_state": {"turn_count": 1, "grade": "3"},
    "parsed_query": {"intent": "COACHING_GENERAL"},
    "follow_up_question": None,
    "request_id": "req-1",
}


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def test_envelope_attribute_access_proxies_to_raw():
    env = drive.Envelope(raw=dict(_OK_PAYLOAD), status="OK")
    assert env.status == "OK"
    assert env.ok is True
    assert env.response == "Here is your mini-lesson."
    assert env.intent == "coaching_general"
    assert env.quality == "validated"
    assert env.judge_score == 0.92
    assert env.sources[0]["source_tier"] == 1
    assert env.session_state["turn_count"] == 1
    # follow_up_question is present-but-null in the real envelope.
    assert env.follow_up_question is None


def test_envelope_get_and_missing_attribute():
    env = drive.Envelope(raw={"response": "hi"}, status="OK")
    assert env.get("response") == "hi"
    assert env.get("nope", "default") == "default"
    with pytest.raises(AttributeError):
        _ = env.totally_absent_key


def test_non_verdict_envelope_is_not_ok():
    env = drive.Envelope(raw={}, status="NON_VERDICT", http_status=503, error="boom")
    assert env.status == "NON_VERDICT"
    assert env.ok is False
    assert env.http_status == 503
    assert env.error == "boom"
    assert env.raw == {}


# ---------------------------------------------------------------------------
# Cache path resolution — env-derived, never the dead prior-session hardcode
# ---------------------------------------------------------------------------


def test_default_cache_path_env_and_fallback(monkeypatch, tmp_path):
    # $CAMPAIGN_CACHE_PATH wins when set (the runner points it at the current
    # session scratchpad).
    monkeypatch.setenv("CAMPAIGN_CACHE_PATH", str(tmp_path / "c.jsonl"))
    assert drive._default_cache_path() == str(tmp_path / "c.jsonl")
    # Unset -> a repo-relative fallback, NEVER the dead 5aa6dda2 scratchpad.
    monkeypatch.delenv("CAMPAIGN_CACHE_PATH", raising=False)
    p = drive._default_cache_path()
    assert "5aa6dda2" not in p
    assert p.endswith(".campaign_cache.jsonl")


def test_session_uses_env_cache_path_when_not_passed(monkeypatch, tmp_path):
    # A Session built without an explicit cache_path resolves the env default
    # lazily at construction (honoring an env set after import).
    target = str(tmp_path / "sess.jsonl")
    monkeypatch.setenv("CAMPAIGN_CACHE_PATH", target)
    sess = drive.Session("http://host:8765")
    assert sess.cache_path == target


# ---------------------------------------------------------------------------
# Backoff is always capped at 30s (never honor Retry-After literally)
# ---------------------------------------------------------------------------


def test_backoff_delay_always_capped_at_30():
    for attempt in range(10):
        d = drive._backoff_delay(attempt)
        assert 0 <= d <= drive.MAX_BACKOFF == 30


def test_backoff_delay_ignores_huge_retry_after():
    # A malicious/naive server sending Retry-After: 3600 must NOT make us sleep
    # for an hour — cap at 30s.
    for attempt in range(10):
        d = drive._backoff_delay(attempt, retry_after=3600)
        assert 0 <= d <= 30


# ---------------------------------------------------------------------------
# .send() retry / non-verdict behaviour
# ---------------------------------------------------------------------------


def test_send_retries_on_503_then_returns_ok(tmp_path):
    cache = tmp_path / "cache.jsonl"
    posts = [_fake_response(503), _fake_response(200, _OK_PAYLOAD)]
    sleeps: list[float] = []
    with patch("campaign.drive.requests.post", side_effect=posts) as mpost, patch(
        "campaign.drive.time.sleep", side_effect=lambda s: sleeps.append(s)
    ):
        sess = drive.Session("http://host:8765", user_id="u1", cache_path=str(cache))
        env = sess.send("hello")

    assert env.status == "OK"
    assert env.ok is True
    assert env.response == "Here is your mini-lesson."
    assert env.intent == "coaching_general"
    assert mpost.call_count == 2  # 503 retried, then 200
    # backoff happened and every sleep was capped at 30s
    assert sleeps
    assert all(s <= 30 for s in sleeps)

    # request contract: message/session_id/user_id/model
    body = mpost.call_args_list[0].kwargs["json"]
    assert body["message"] == "hello"
    assert body["user_id"] == "u1"
    assert body["session_id"] == sess.session_id
    assert body["model"] == "gpt-4o"
    assert mpost.call_args_list[0].args[0] == "http://host:8765/api/chat"


def test_send_persistent_503_returns_non_verdict_without_raising(tmp_path):
    cache = tmp_path / "cache.jsonl"
    with patch(
        "campaign.drive.requests.post", return_value=_fake_response(503)
    ) as mpost, patch("campaign.drive.time.sleep") as msleep:
        sess = drive.Session("http://host:8765", cache_path=str(cache))
        env = sess.send("hello")  # must NOT raise

    assert env.status == "NON_VERDICT"
    assert env.ok is False
    assert env.http_status == 503
    assert env.raw == {}
    assert mpost.call_count == drive.MAX_ATTEMPTS
    # every backoff sleep capped at 30s
    assert all(call.args[0] <= 30 for call in msleep.call_args_list)


def test_send_caps_retry_after_header_at_30(tmp_path):
    cache = tmp_path / "cache.jsonl"
    throttled = _fake_response(503, headers={"Retry-After": "3600"})
    posts = [throttled, _fake_response(200, _OK_PAYLOAD)]
    sleeps: list[float] = []
    with patch("campaign.drive.requests.post", side_effect=posts), patch(
        "campaign.drive.time.sleep", side_effect=lambda s: sleeps.append(s)
    ):
        sess = drive.Session("http://host:8765", cache_path=str(cache))
        env = sess.send("hello")

    assert env.status == "OK"
    assert sleeps
    assert all(s <= 30 for s in sleeps)  # never slept the literal 3600


def test_send_retries_on_timeout_then_succeeds(tmp_path):
    cache = tmp_path / "cache.jsonl"
    posts = [requests.exceptions.Timeout("slow"), _fake_response(200, _OK_PAYLOAD)]
    with patch("campaign.drive.requests.post", side_effect=posts) as mpost, patch(
        "campaign.drive.time.sleep"
    ):
        sess = drive.Session("http://host:8765", cache_path=str(cache))
        env = sess.send("hello")

    assert env.status == "OK"
    assert mpost.call_count == 2


def test_send_persistent_connection_error_is_non_verdict(tmp_path):
    cache = tmp_path / "cache.jsonl"
    with patch(
        "campaign.drive.requests.post",
        side_effect=requests.exceptions.ConnectionError("down"),
    ), patch("campaign.drive.time.sleep"):
        sess = drive.Session("http://host:8765", cache_path=str(cache))
        env = sess.send("hello")  # must NOT raise

    assert env.status == "NON_VERDICT"
    assert "ConnectionError" in (env.error or "")


# ---------------------------------------------------------------------------
# Identity + sequential turns
# ---------------------------------------------------------------------------


def test_two_sessions_get_distinct_user_ids():
    s1 = drive.Session("http://host:8765")
    s2 = drive.Session("http://host:8765")
    assert s1.user_id != s2.user_id
    assert s1.session_id != s2.session_id


def test_explicit_user_id_is_kept():
    s = drive.Session("http://host:8765", user_id="fixed-user")
    assert s.user_id == "fixed-user"


def test_turn_idx_increments_sequentially(tmp_path):
    cache = tmp_path / "cache.jsonl"
    with patch(
        "campaign.drive.requests.post", return_value=_fake_response(200, _OK_PAYLOAD)
    ), patch("campaign.drive.time.sleep"):
        sess = drive.Session("http://host:8765", cache_path=str(cache))
        e0 = sess.send("a")
        e1 = sess.send("b")
    assert e0.turn_idx == 0
    assert e1.turn_idx == 1
    assert sess.turn_idx == 2


# ---------------------------------------------------------------------------
# JSONL cache — one line per send (OK and NON_VERDICT alike)
# ---------------------------------------------------------------------------


def test_cache_appends_one_line_per_send(tmp_path):
    cache = tmp_path / "cache.jsonl"
    with patch(
        "campaign.drive.requests.post", return_value=_fake_response(200, _OK_PAYLOAD)
    ), patch("campaign.drive.time.sleep"):
        sess = drive.Session("http://host:8765", user_id="u1", cache_path=str(cache))
        sess.send("one")
        sess.send("two")

    lines = cache.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    rec0 = json.loads(lines[0])
    assert rec0["session_id"] == sess.session_id
    assert rec0["turn_idx"] == 0
    assert rec0["status"] == "OK"
    assert rec0["message"] == "one"
    assert rec0["user_id"] == "u1"
    assert rec0["envelope"]["response"] == "Here is your mini-lesson."

    rec1 = json.loads(lines[1])
    assert rec1["turn_idx"] == 1
    assert rec1["message"] == "two"


def test_non_verdict_send_still_caches_one_line(tmp_path):
    cache = tmp_path / "cache.jsonl"
    with patch(
        "campaign.drive.requests.post", return_value=_fake_response(500)
    ), patch("campaign.drive.time.sleep"):
        sess = drive.Session("http://host:8765", cache_path=str(cache))
        env = sess.send("boom")

    assert env.status == "NON_VERDICT"
    lines = cache.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["status"] == "NON_VERDICT"
    assert rec["http_status"] == 500
    assert rec["envelope"] == {}
