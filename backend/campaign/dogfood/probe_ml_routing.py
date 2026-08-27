"""SHIP-GATE — offline QU probe for the BARE mini-lesson request routing nudge.

WHAT THIS MEASURES (read before citing it):
  The OFFLINE QU call only: understand() -> TurnIntent.request_type. It does NOT
  measure the visible reply. It isolates ONE question: does a BARE mini-lesson
  request ("give me a mini lesson", no skill named) now classify as SCRIPTED_ML
  — so the app ASKS "what grade? what skill?" — instead of drifting to COACHING
  (which invents a skill and gives prose) or META?

  The load-bearing half is the NEGATIVE set: a LOOKUP ("is there a mini-lesson
  for X?") must STAY COACHING — the nudge must not swallow lookups into
  SCRIPTED_ML. Over-broadening is the harmful direction.

  NOTE: this classification is a documented KNIFE'S EDGE (the same input has
  returned SCRIPTED_ML via the live endpoint and COACHING via a direct call), so
  read the rates, not a single run. The deterministic clarify-resume fix is the
  guarantee for the FOLLOW-UP half; this nudge only hardens the INITIAL request.

  GATE BAR: positives >= 5/6 SCRIPTED_ML each AND 0 lookup regressions
  (every negative stays non-SCRIPTED_ML).

  Run under:  env -u OPENAI_API_KEY -u OPENAI_BASE_URL python3 campaign/dogfood/probe_ml_routing.py
  (a stale shell OPENAI_API_KEY shadows the good .env key -> 401).
"""
import asyncio
import os
import sys

CV4 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, CV4)

from config import settings  # noqa: E402
from api.dependencies import get_openai_client  # noqa: E402
from query.qu_v4 import understand  # noqa: E402
from schemas import Conversation  # noqa: E402

N = 6

POSITIVE = [
    "give me a mini lesson",
    "give me a mini-lesson",
    "can you make me a mini-lesson",
    "I need a scripted lesson",
    "mini lesson please",
]

# Must NOT become SCRIPTED_ML — these are lookups/questions, not lesson requests.
NEGATIVE = [
    "is there a mini-lesson for topic sentences?",
    "does a lesson exist for transitions?",
    "is there a pizza table lesson?",
]

# Named-skill control: was already SCRIPTED_ML, must stay SCRIPTED_ML.
CONTROL = ["give me a lesson on topic sentences"]


async def run_one(msg, client, model):
    out = []
    for _ in range(N):
        intent = await understand(Conversation(session_id="probe", turns=[]),
                                  msg, client=client, model=model)
        out.append(intent.request_type.value)
    return out


async def main():
    client = get_openai_client()
    model = settings.openai_query_model
    print(f"model={model}  N={N}\n")

    print("POSITIVE — expect SCRIPTED_ML (bar: >=5/6 each)")
    pos_fail = []
    for msg in POSITIVE:
        res = await run_one(msg, client, model)
        hits = sum(1 for r in res if r == "SCRIPTED_ML")
        flag = "OK " if hits >= 5 else "LOW"
        print(f"  [{flag}] {hits}/{N} SCRIPTED_ML  {msg!r}  {res}")
        if hits < 5:
            pos_fail.append((msg, hits))

    print("\nNEGATIVE (lookups) — must stay NON-SCRIPTED_ML (bar: 0 regressions)")
    neg_fail = []
    for msg in NEGATIVE:
        res = await run_one(msg, client, model)
        bad = sum(1 for r in res if r == "SCRIPTED_ML")
        flag = "OK " if bad == 0 else "REGRESSION"
        print(f"  [{flag}] {bad}/{N} wrongly SCRIPTED_ML  {msg!r}  {res}")
        if bad:
            neg_fail.append((msg, bad))

    print("\nCONTROL — named skill, expect SCRIPTED_ML")
    for msg in CONTROL:
        res = await run_one(msg, client, model)
        hits = sum(1 for r in res if r == "SCRIPTED_ML")
        print(f"  [{'OK ' if hits >= 5 else 'LOW'}] {hits}/{N}  {msg!r}  {res}")

    print("\n=== GATE:",
          "PASS" if not pos_fail and not neg_fail else "FAIL",
          "===")
    if pos_fail:
        print("  positives below bar:", pos_fail)
    if neg_fail:
        print("  LOOKUP REGRESSIONS (do not ship):", neg_fail)


if __name__ == "__main__":
    asyncio.run(main())
