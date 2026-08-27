"""Capture the Brady golden baseline.

Runs the Protected-Set against the live backend and saves the responses as the
pre-change reference the safety net diffs against (implementation-strategy.md §1a).

Run from copilot-v4 with the backend up:
    python3 scripts/capture_golden_baseline.py            # -> tests/golden/baseline-<date>.json
    python3 scripts/capture_golden_baseline.py --base http://127.0.0.1:8000 --out /path.json
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

# Ensure copilot-v4 is importable no matter how this script is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests  # noqa: E402
from tests.protected_set import PROTECTED_SET  # noqa: E402

# The prompt context is an input, not an output — omit it to keep the baseline lean.
_DROP_KEYS = {"retrieved_context"}


def _post(base: str, message: str, session_id: str) -> dict:
    r = requests.post(
        f"{base}/api/chat",
        json={"message": message, "session_id": session_id},
        timeout=180,
    )
    r.raise_for_status()
    return r.json()


def capture(base: str) -> list[dict]:
    out: list[dict] = []
    for c in PROTECTED_SET:
        sid = f"golden-{c.id}-{uuid.uuid4().hex[:6]}"
        for pm in c.prior_messages:
            _post(base, pm, sid)  # set up session context first
        resp = _post(base, c.message, sid)
        resp = {k: v for k, v in resp.items() if k not in _DROP_KEYS}
        out.append({
            "id": c.id,
            "message": c.message,
            "prior_messages": list(c.prior_messages),
            "response": resp,
        })
        print(f"  captured {c.id}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    out_path = (
        Path(args.out) if args.out
        else Path(__file__).resolve().parents[1] / "tests" / "golden" / "baseline-2026-07-16.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    data = capture(args.base)
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"wrote {len(data)} cases -> {out_path}")


if __name__ == "__main__":
    main()
