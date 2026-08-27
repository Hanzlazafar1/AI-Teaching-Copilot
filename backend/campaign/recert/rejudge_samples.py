"""Production cross-check: re-judge each evidence-pack SAMPLE with the shipping
judge gpt-5.4-mini (from the drive cache — NO re-drive), annotating each sample
with a `production_judge` verdict. This gives the Phase-4 opus adjudicator a
second, production-consistent signal alongside the gpt-4o triage.

HONEST scope: gpt-5.4-mini is the SAME family as the gpt-5.4 generator, so it
carries self-preference bias (skews ALIGNED) and it is NOT calibrated on the
gold set — so it is INFORMATIONAL only, never a gate. A MISALIGNED that survives
even this self-preferring judge is a high-confidence signal; an ALIGNED from it
is weak evidence. Opus remains the authority.

Run after build_evidence.py (clean env):
  env -u OPENAI_API_KEY -u OPENAI_BASE_URL PYTHONPATH=. \
      python3 campaign/recert/rejudge_samples.py
"""
from __future__ import annotations

import collections
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_V4 = os.path.dirname(os.path.dirname(_HERE))
if _V4 not in sys.path:
    sys.path.insert(0, _V4)

from campaign import judge as jm  # noqa: E402
from campaign.drive import Envelope  # noqa: E402

CROSS_MODEL = "gpt-5.4-mini"


def main() -> None:
    jm.JUDGE_MODEL = CROSS_MODEL  # production cross-check judge
    client = jm._ensure_client(None)
    claims = {c["id"]: c for c in
              json.load(open(os.path.join(_HERE, "claims.v2.json")))["claims"]}
    packs_path = os.path.join(_HERE, "evidence-packs.json")
    packs = json.load(open(packs_path))
    tally = collections.Counter()
    n_calls = 0
    for p in packs:
        claim = claims.get(p["claim_id"])
        if claim is None:
            continue
        for s in p.get("samples", []):
            env = Envelope(raw=s.get("envelope") or {}, status="OK")
            try:
                v = jm.judge_claim(claim, env, openai_client=client)
                s["production_judge"] = {"model": CROSS_MODEL, "status": v.status,
                                         "confidence": v.confidence,
                                         "rationale": (v.rationale or "")[:220]}
            except Exception as exc:  # never abort the batch
                s["production_judge"] = {"model": CROSS_MODEL, "status": "ERROR",
                                         "rationale": f"{type(exc).__name__}: {exc}"[:180]}
            tally[s["production_judge"]["status"]] += 1
            n_calls += 1
    json.dump(packs, open(packs_path, "w"), ensure_ascii=False, indent=1)
    edir = os.path.join(_HERE, "evidence")
    os.makedirs(edir, exist_ok=True)
    for p in packs:
        json.dump(p, open(os.path.join(edir, p["claim_id"] + ".json"), "w"),
                  ensure_ascii=False, indent=1)
    print(f"cross-check {CROSS_MODEL}: {n_calls} sample-judgements | by status: {dict(tally)}")


if __name__ == "__main__":
    main()
