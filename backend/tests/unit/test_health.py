"""Unit tests for Phase 11.6 — deep health probes + endpoints.

We stub each probe to isolate the aggregator / caching / endpoint logic
from real Qdrant or OpenAI calls. That keeps these tests fast (no network)
and deterministic (no depending on whether the Qdrant data dir exists).
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from api.health import (
    PROBE_CACHE_TTL,
    ProbeResult,
    _reset_probe_cache_for_tests,
    run_readiness_probes,
)


@pytest.fixture(autouse=True)
def reset_cache():
    """Each test starts with a clean probe cache so success memoization from
    one test doesn't bleed into another."""
    _reset_probe_cache_for_tests()
    yield
    _reset_probe_cache_for_tests()


# ---------------------------------------------------------------------------
# Aggregator — run_readiness_probes
# ---------------------------------------------------------------------------


class TestRunReadinessProbes:
    @pytest.mark.asyncio
    async def test_all_ok_returns_true_plus_three_results(self):
        async def _qdrant_ok():
            return ProbeResult("qdrant", ok=True)

        def _library_ok():
            return ProbeResult("library_index", ok=True, detail="183 entries")

        async def _openai_ok():
            return ProbeResult("openai", ok=True)

        with patch("api.health._probe_qdrant", _qdrant_ok), \
             patch("api.health._probe_library_index", _library_ok), \
             patch("api.health._probe_openai", _openai_ok):
            ok, results = await run_readiness_probes()
        assert ok is True
        names = {r.name for r in results}
        assert names == {"qdrant", "library_index", "openai"}

    @pytest.mark.asyncio
    async def test_any_failure_makes_overall_false(self):
        async def _qdrant_fail():
            return ProbeResult("qdrant", ok=False, detail="conn refused")

        def _library_ok():
            return ProbeResult("library_index", ok=True)

        async def _openai_ok():
            return ProbeResult("openai", ok=True)

        with patch("api.health._probe_qdrant", _qdrant_fail), \
             patch("api.health._probe_library_index", _library_ok), \
             patch("api.health._probe_openai", _openai_ok):
            ok, results = await run_readiness_probes()
        assert ok is False
        failing = [r for r in results if not r.ok]
        assert len(failing) == 1 and failing[0].name == "qdrant"

    @pytest.mark.asyncio
    async def test_all_probes_run_even_if_first_fails(self):
        """Don't short-circuit — on-call needs the full picture ('only
        Qdrant is down' vs 'everything is down')."""
        calls: list[str] = []

        async def _qdrant():
            calls.append("qdrant")
            return ProbeResult("qdrant", ok=False)

        def _library():
            calls.append("library_index")
            return ProbeResult("library_index", ok=True)

        async def _openai():
            calls.append("openai")
            return ProbeResult("openai", ok=True)

        with patch("api.health._probe_qdrant", _qdrant), \
             patch("api.health._probe_library_index", _library), \
             patch("api.health._probe_openai", _openai):
            await run_readiness_probes()
        assert set(calls) == {"qdrant", "library_index", "openai"}


# ---------------------------------------------------------------------------
# Success caching — successful probes are memoized, failures are NOT.
# ---------------------------------------------------------------------------


class TestProbeCache:
    @pytest.mark.asyncio
    async def test_successful_probe_is_cached(self):
        call_count = 0

        async def _probe():
            nonlocal call_count
            call_count += 1
            return ProbeResult("openai", ok=True)

        with patch("api.health._probe_qdrant", _probe), \
             patch("api.health._probe_library_index",
                   lambda: ProbeResult("library_index", ok=True)), \
             patch("api.health._probe_openai",
                   lambda: ProbeResult("openai", ok=True)):
            await run_readiness_probes()
            await run_readiness_probes()
            await run_readiness_probes()
        # Only the first call should have actually invoked the probe;
        # subsequent calls served from the success cache.
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_failing_probe_is_rerun_on_every_call(self):
        """Critical: do NOT cache failures. If OpenAI has a 10-second blip,
        we must be ready within 10 seconds, not stuck at "unhealthy" for
        the full 30-second TTL."""
        call_count = 0

        async def _probe_openai_failing():
            nonlocal call_count
            call_count += 1
            return ProbeResult("openai", ok=False, detail="timeout")

        with patch("api.health._probe_qdrant",
                   lambda: ProbeResult("qdrant", ok=True)), \
             patch("api.health._probe_library_index",
                   lambda: ProbeResult("library_index", ok=True)), \
             patch("api.health._probe_openai", _probe_openai_failing):
            await run_readiness_probes()
            await run_readiness_probes()
            await run_readiness_probes()
        # Every call must re-probe because the previous call failed.
        assert call_count == 3


# ---------------------------------------------------------------------------
# HTTP endpoints — uses the real FastAPI app wiring.
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """Build a minimal app that mirrors main.py's /health routes but stubs
    the probes so this test doesn't need Qdrant/OpenAI running."""
    from api.request_context import RequestIdMiddleware

    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/health")
    async def _legacy():
        return {"status": "ok", "version": "4.0.0"}

    @app.get("/health/live")
    async def _live():
        return {"status": "ok", "version": "4.0.0"}

    @app.get("/health/ready")
    async def _ready():
        overall_ok, probes = await run_readiness_probes()
        body = {
            "status": "ok" if overall_ok else "degraded",
            "version": "4.0.0",
            "probes": [p.to_dict() for p in probes],
        }
        if overall_ok:
            return body
        return JSONResponse(status_code=503, content=body)

    return TestClient(app)


class TestHealthEndpoints:
    def test_live_always_ok(self, client):
        r = client.get("/health/live")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        assert r.headers.get("X-Request-ID")  # plumbing still active

    def test_legacy_health_is_alias_of_live(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "version": "4.0.0"}

    def test_ready_200_when_all_probes_pass(self, client):
        async def _ok(name):
            return ProbeResult(name, ok=True)

        with patch("api.health._probe_qdrant",
                   lambda: _ok("qdrant")), \
             patch("api.health._probe_library_index",
                   lambda: ProbeResult("library_index", ok=True)), \
             patch("api.health._probe_openai",
                   lambda: _ok("openai")):
            r = client.get("/health/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert {p["name"] for p in body["probes"]} == {
            "qdrant", "library_index", "openai",
        }

    def test_ready_503_when_any_probe_fails(self, client):
        async def _qdrant_fail():
            return ProbeResult("qdrant", ok=False, detail="conn refused")

        async def _openai_ok():
            return ProbeResult("openai", ok=True)

        with patch("api.health._probe_qdrant", _qdrant_fail), \
             patch("api.health._probe_library_index",
                   lambda: ProbeResult("library_index", ok=True)), \
             patch("api.health._probe_openai", _openai_ok):
            r = client.get("/health/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "degraded"
        # Per-probe detail exposed so on-call can see WHICH subsystem is down.
        qdrant = [p for p in body["probes"] if p["name"] == "qdrant"][0]
        assert qdrant["ok"] is False
        assert "conn refused" in qdrant["detail"]
