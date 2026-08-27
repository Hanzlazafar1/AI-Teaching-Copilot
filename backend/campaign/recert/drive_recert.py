"""Phase-3 drive runner for the Brady full-scope re-certification (campaign v2).

Thin orchestration over campaign.run.run_campaign: loads claims.v2.json +
manifest.v2.json, drives every planned probe against the LIVE backend (fresh
multi-turn session per probe), judges the pivotal turn with the campaign judge
(gpt-4o), and appends resumable results. The FULL envelopes (response +
sources/source_tier + parsed_query + session_state + follow_up) land in the
drive cache JSONL — that cache is what Phase 4's opus multi-lens adjudication
re-reads (no re-drive).

Usage (from copilot-v4, clean env, backend already up on the manifest port):
  env -u OPENAI_API_KEY -u OPENAI_BASE_URL RATE_LIMIT_PER_HOUR=1000000 \
      PYTHONPATH=. python3 campaign/recert/drive_recert.py [--dry-run]

Resumable: re-running skips probes already completed with a real verdict and
re-drives NON_VERDICT (upstream-error) ones. Kill-switch = manifest caps
(runaway backstop only; cost-no-object per the run directive).
"""
from __future__ import annotations

import collections
import json
import os
import sys

import requests

_HERE = os.path.dirname(os.path.abspath(__file__))
_V4 = os.path.dirname(os.path.dirname(_HERE))  # copilot-v4
if _V4 not in sys.path:
    sys.path.insert(0, _V4)

from campaign import judge as judge_mod  # noqa: E402
from campaign import run as run_mod  # noqa: E402


def _load_claims(path: str) -> list:
    data = json.load(open(path, encoding="utf-8"))
    return data["claims"] if isinstance(data, dict) else data


def _health(base_url: str) -> bool:
    try:
        r = requests.get(f"{base_url}/health/ready", timeout=10)
        return r.status_code == 200
    except Exception as exc:
        print(f"health check failed: {exc}")
        return False


def _tally(results_path: str) -> dict:
    by = collections.Counter()
    ok = collections.Counter()
    if not os.path.exists(results_path):
        return {}
    for line in open(results_path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        by[rec.get("status")] += 1
        ok[bool(rec.get("ok"))] += 1
    return {"by_status": dict(by), "ok_true": ok[True], "ok_false_nonverdict": ok[False]}


def main() -> None:
    dry = "--dry-run" in sys.argv
    claims = _load_claims(os.path.join(_HERE, "claims.v2.json"))
    manifest = json.load(open(os.path.join(_HERE, "manifest.v2.json"), encoding="utf-8"))
    base_url = manifest["backend"]["base_url"]
    results_path = os.path.join(_HERE, "drive-results.jsonl")
    cache_path = os.path.join(_HERE, "drive-cache.jsonl")
    os.environ["CAMPAIGN_CACHE_PATH"] = cache_path

    probes = run_mod.plan_probes(claims, manifest)
    tier_n = collections.Counter(p.tier for p in probes)
    print(f"claims={len(claims)}  planned_probes={len(probes)}  by_tier={dict(tier_n)}")
    est = sum(manifest.get("per_turn_cost", {}).get(
        next((c.get("surface", "") for c in claims if c["id"] == p.claim_id), ""),
        manifest.get("per_turn_cost", {}).get("default", 0.035)) * (len(p.turns) or 1)
        for p in probes)
    print(f"est_cost_usd~{est:.2f}  (cap={manifest['caps']['dollar_cap_usd']})")
    if dry:
        print("dry-run: not driving.")
        return

    if not _health(base_url):
        print(f"BACKEND NOT READY at {base_url} — start it first. Aborting.")
        sys.exit(2)

    caps = manifest.get("caps", {})
    budget = run_mod.CostMeter(
        dollar_cap=caps.get("dollar_cap_usd"),
        call_cap=caps.get("drive_turn_cap"),
        per_turn_cost=manifest.get("per_turn_cost"),
    )
    client = judge_mod._ensure_client(None)
    summary = run_mod.run_campaign(
        claims, manifest, base_url, results_path,
        openai_client=client, cache_path=cache_path, budget=budget,
    )
    print("SUMMARY:", json.dumps(summary))
    print("TALLY:", json.dumps(_tally(results_path)))


if __name__ == "__main__":
    main()
