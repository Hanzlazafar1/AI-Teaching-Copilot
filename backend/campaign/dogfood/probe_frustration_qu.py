"""Task 5 (C10 emotional-validation) LIVE-GATE — offline QU probe.

WHAT THIS MEASURES (read before citing it):
  The OFFLINE QU call only — understand() -> TurnIntent.expressed_frustration.
  It does NOT measure the teacher-visible reply (that is the separate C10
  backend re-drive). It isolates ONE question: does the new deterministic QU
  signal fire True when the teacher voices frustration, and — the load-bearing
  half, Brady's asymmetry — does it STAY False on calm/neutral asks?

  Over-firing (validating a calm teacher condescendingly) is the harmful
  direction. GATE BAR: 0 false positives on the CALM set (any calm run firing
  True = DO NOT SHIP / tune the rule), mirroring the S3 gate's "0/30 false
  positives" standard. Under-firing on a FRUSTRATED case is a weaker miss but
  reported too.

  The CALM set is deliberately adversarial: it packs the words a naive rule
  would trip on — "struggle", "hard", "help", a leading "I'm..." — used
  descriptively, NOT as the teacher's own distress.
"""
import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import settings  # noqa: E402
from api.dependencies import get_openai_client  # noqa: E402
from query.qu_v4 import understand  # noqa: E402
from schemas import Conversation  # noqa: E402

N = 3  # runs per case (catch stochastic flip)

# Expect expressed_frustration=True — the teacher voices distress / being stuck.
FRUSTRATED = [
    # C10's exact opener (the dogfood case this fix exists for):
    "I'm so frustrated — my 2nd graders just can't write a complete sentence and I don't know what to do.",
    "I've tried everything and my students still can't write a topic sentence.",
    "I'm at my wit's end. They just won't revise their writing no matter what I do.",
    "This isn't working. I've taught paragraphing three times and they still don't get it.",
    "I don't know what to do anymore — my kids freeze every time I ask them to write.",
    "Honestly I'm so overwhelmed, my 4th graders can't organize a single paragraph.",
    "Ugh, nothing I try is helping them add details to their writing.",
    "I'm really struggling here — my ELL students just aren't picking up sentence structure and I'm out of ideas.",
    "Help, I feel like I'm drowning. My 1st graders won't even attempt to write words.",
    "I feel like a failure — I've modeled leads a dozen times and they still just write 'One day'.",
]

# Expect expressed_frustration=False — calm asks, incl. adversarial edge cases
# that use struggle/hard/help/"I'm" DESCRIPTIVELY, not as distress.
CALM = [
    "How do I teach topic sentences to 3rd graders?",
    "Give me a 5th grade scripted mini-lesson on strong verbs.",
    "Help me plan a 4th grade persuasive writing unit.",
    "What's the difference between revising and editing?",
    "How do I set up writing workshop routines?",
    # EDGE: "struggle" stated descriptively (not the teacher's distress):
    "My students struggle with paragraphing. How do I teach it?",
    # EDGE: "hard" descriptive:
    "My 2nd graders find sentence writing hard. What's a good lesson?",
    "Show me a think-aloud for teaching leads.",
    "Can you give me a lesson on adding details for my SPED students at the label stage?",
    "What is the pizza-table strategy?",
    # EDGE: leading "I'm" but calm/planning:
    "I'm teaching narrative writing next week. How should I introduce dialogue?",
    "My kids are working on opinion writing. What's a good mini-lesson on reasons?",
    "How do I teach transitions to 6th graders?",
    "Plan a 3rd grade informative unit for me.",
    "Which Smekens strategy helps with organization?",
    # positive affect:
    "My students are ready for a lesson on strong leads. Give me one for grade 4.",
    "What does the slinky test teach?",
    "I want to work on sentence variety with my 7th graders.",
    # EDGE: "help" but neutral/curious, not distress:
    "How can I help my students write better conclusions?",
    "Give me a management overview for setting up independent writing time.",
]


async def _fire_rate(client, model, msg):
    fired = 0
    for _ in range(N):
        intent = await understand(
            Conversation(session_id="frustprobe", turns=[]),
            msg,
            client=client,
            model=model,
        )
        if intent.expressed_frustration:
            fired += 1
    return fired


async def main():
    client = get_openai_client()
    model = settings.openai_query_model
    print(f"QU model = {model}   N = {N} runs/case\n")

    print("=" * 72)
    print("FRUSTRATED set (expect True) — under-fire = a miss")
    print("=" * 72)
    frust_hits = Counter()
    for msg in FRUSTRATED:
        f = await _fire_rate(client, model, msg)
        frust_hits[msg] = f
        flag = "ok" if f == N else ("PARTIAL" if f else "MISS")
        print(f"  [{f}/{N}] {flag:8} {msg[:70]}")

    print("\n" + "=" * 72)
    print("CALM set (expect False) — ANY fire = OVER-FIRE = do not ship")
    print("=" * 72)
    calm_over = Counter()
    for msg in CALM:
        f = await _fire_rate(client, model, msg)
        calm_over[msg] = f
        flag = "ok" if f == 0 else "OVER-FIRE"
        print(f"  [{f}/{N}] {flag:9} {msg[:69]}")

    print("\n" + "=" * 72)
    frust_true = sum(1 for m in FRUSTRATED if frust_hits[m] == N)
    frust_any = sum(1 for m in FRUSTRATED if frust_hits[m] > 0)
    calm_clean = sum(1 for m in CALM if calm_over[m] == 0)
    calm_overfires = sum(1 for m in CALM if calm_over[m] > 0)
    print(f"FRUSTRATED fired all {N}/{N}: {frust_true}/{len(FRUSTRATED)}  "
          f"(fired at least once: {frust_any}/{len(FRUSTRATED)})")
    print(f"CALM stayed False all runs: {calm_clean}/{len(CALM)}  "
          f"(OVER-FIRING cases: {calm_overfires})")
    gate = (calm_overfires == 0) and (frust_any == len(FRUSTRATED))
    print(f"\nQU GATE: {'PASS' if gate else 'FAIL — tune the rule / DO NOT SHIP'}")
    print("  (bar: 0 calm over-fires AND every frustrated case fires >=1/N)")
    sys.exit(0 if gate else 1)


asyncio.run(main())
