"""Phase-2 calibration runner for the Brady full-scope re-cert (campaign v2).

Scores the campaign judge (gpt-4o @ temp 0) against the extended gold set
(`brady_gold_v2.jsonl` = existing 20 + new-behavior exemplars). BLOCKING gate:
false-ALIGNED rate must be 0.0 (the judge must never call a Brady-MISALIGNED
response ALIGNED). Writes `calibration.json`; prints PASS/HALT + offenders.

Usage (from copilot-v4, clean env):
  env -u OPENAI_API_KEY -u OPENAI_BASE_URL PYTHONPATH=. \
      python3 campaign/recert/calibrate_recert.py
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_V4 = os.path.dirname(os.path.dirname(_HERE))
if _V4 not in sys.path:
    sys.path.insert(0, _V4)

from campaign import calibrate as cal  # noqa: E402
from campaign import judge as jm  # noqa: E402


def main() -> None:
    gold_path = os.path.join(_HERE, "brady_gold_v2.jsonl")
    gold = cal.load_gold(gold_path)
    client = jm._ensure_client(None)
    res = cal.calibrate(jm.judge_claim, gold, threshold=0.0, openai_client=client)
    out = {
        "n": res.n, "false_aligned": res.false_aligned,
        "false_misaligned": res.false_misaligned, "n_uncertain": res.n_uncertain,
        "false_aligned_rate": res.false_aligned_rate,
        "false_misaligned_rate": res.false_misaligned_rate,
        "threshold": res.threshold, "halt": res.halt, "offenders": res.offenders,
    }
    json.dump(out, open(os.path.join(_HERE, "calibration.json"), "w"), indent=2)
    print(json.dumps({k: out[k] for k in (
        "n", "false_aligned", "false_aligned_rate", "false_misaligned",
        "n_uncertain", "halt")}))
    if res.offenders:
        print("OFFENDERS (judge said ALIGNED on a Brady-MISALIGNED gold item):")
        for o in res.offenders:
            print("  ", o.get("claim_id"), "| label=", o.get("brady_label"),
                  "-> verdict=", o.get("verdict_status"), "|", (o.get("rationale") or "")[:120])
    print("CALIBRATION:", "HALT — judge too lenient, FIX before driving"
          if res.halt else "PASS (0 false-ALIGNED)")


if __name__ == "__main__":
    main()
