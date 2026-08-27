"""Fix ③ SHIP-GATE — offline QU probe for unknown_subgroup_acronym.

WHAT THIS MEASURES (read before citing it):
  The OFFLINE QU call only: understand() -> TurnIntent.unknown_subgroup_acronym
  (the field the SG1 clarify gate consumes, handlers/clarify.py:180). It does
  NOT measure the visible reply. It isolates ONE question: does QU now flag an
  unfamiliar acronym naming an intervention block/program/grouping ("our WIN
  block"), and — the load-bearing half — does it STAY null on the recognized
  families, ordinary caps, subject blocks, strategy/editing acronyms, and grade
  bands?

  Over-firing (asking "what does that stand for?" for a normal word) is the
  harmful direction. GATE BAR (S3 precedent): WIN/positives fire >= 2/3 each
  AND 0 negative over-fires. Any negative firing -> DO NOT SHIP / tighten.

  Run under:  env -u OPENAI_API_KEY -u OPENAI_BASE_URL python3 campaign/dogfood/probe_win_acronym.py
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
from schemas import Conversation, Turn, Role  # noqa: E402

N = 3


def empty():
    return Conversation(session_id="probe", turns=[])


# The EXACT recert-R15 context in which the bug was first observed (0/9). Proves
# the real-world reproduction is fixed, not just clean-room phrasings.
def r15_context():
    return Conversation(session_id="probe-r15", turns=[
        Turn(index=0, role=Role.USER,
             text="Can you give me a writing lesson for my RTI kids?"),
        Turn(index=1, role=Role.ASSISTANT,
             text="What's their current writing level — are they at the picture, "
                  "label, word, or sentence stage?"),
        Turn(index=2, role=Role.USER,
             text="Most of them are writing simple sentences right now."),
        Turn(index=3, role=Role.ASSISTANT,
             text="Since your RTI group is at the sentence stage, I'd keep the "
                  "lesson narrow: one sentence skill at a time. A strong next "
                  "lesson is word spacing."),
    ])


WIN_TURN2 = (
    "This is helpful. One thing though — a handful of these kids are also in "
    "our WIN block, so I want to make sure the lesson works for them too. Can "
    "you tweak it with that in mind?"
)

# (label, message, context_factory)  -- expect unknown_subgroup_acronym SET.
POSITIVE = [
    ("P1  WIN block (exact bug + R15 context)", WIN_TURN2, r15_context),
    ("P2  WIN block, isolation",
     "Can you give me a writing lesson for the kids in our WIN block?", empty),
    ("P3  WIN block students",
     "Give me a sentence-writing lesson for my WIN block students.", empty),
    ("P4  MTSS kids",
     "How do I support my MTSS kids with organization?", empty),
    ("P5  TAG students (prompt's own control)",
     "How do I support my TAG students with organization?", empty),
    ("P6  invented PAWS block (no 'intervention' hint)",
     "Give me a lesson on leads for my PAWS block.", empty),
    ("P7  invented ROAR kids (no 'intervention' hint)",
     "Can you make a sentence lesson for my ROAR kids?", empty),
]

# (label, message, context_factory)  -- expect unknown_subgroup_acronym NULL.
NEGATIVE = [
    # --- the 4 recognized families -> subgroup, never unknown ---
    ("N1  SPED (family)",  "Can you give me a lesson on leads for my SPED students?", empty),
    ("N2  MLL (family)",   "How do I teach paragraphing to my MLL students?", empty),
    ("N3  MLs (family)",   "Give me a sentence lesson for my MLs.", empty),
    ("N4  EL (family)",    "A lesson on topic sentences for my EL students.", empty),
    ("N5  ELL (family)",   "How do I support my ELL students with organization?", empty),
    ("N6  RTI (family)",   "Can you give me a writing lesson for my RTI kids?", empty),
    # --- ordinary caps / proper nouns ---
    ("N7  'One day' ordinary cap",
     "My students always start their stories with 'One day'. How do I teach stronger leads?", empty),
    ("N8  proper-noun student name Max",
     "How do I help my student Max write complete sentences?", empty),
    # --- subject / content-area time blocks (the sharp boundary vs WIN block) ---
    ("N9  ELA block (subject)",
     "How do I teach topic sentences during my ELA block?", empty),
    ("N10 reading block (subject)",
     "What writing mini-lesson works well during my reading block?", empty),
    # --- strategy / editing acronyms + trait names (name a strategy, not students) ---
    ("N11 RACE strategy",  "How do I teach my students to use the RACE strategy in their writing?", empty),
    ("N12 OREO structure", "Can you give me a lesson using the OREO structure for opinion writing?", empty),
    ("N13 CUPS editing",   "How do I teach editing with CUPS?", empty),
    ("N14 ARMS revising",  "How do I teach revising with ARMS?", empty),
    ("N15 trait name Word Choice",
     "How do I teach Word Choice to my 4th graders?", empty),
    # --- grade bands (handled by the grade enum, not a subgroup) ---
    ("N16 K-2 band",       "Give me a lesson on labels for K-2.", empty),
    ("N17 grades 3-5 band","How do I teach paragraphing for grades 3-5?", empty),
]


async def _fire(client, model, msg, ctxfn):
    """Return (fires, [per-run (acronym, subgroup)])."""
    fires = 0
    detail = []
    for _ in range(N):
        intent = await understand(ctxfn(), msg, client=client, model=model)
        usa = (intent.unknown_subgroup_acronym or "").strip()
        sg = (intent.subgroup or "").strip()
        if usa:
            fires += 1
        detail.append((usa, sg))
    return fires, detail


async def main():
    client = get_openai_client()
    model = settings.openai_query_model
    print(f"QU model = {model}   N = {N} runs/case\n")

    print("=" * 84)
    print("POSITIVE set (expect unknown_subgroup_acronym SET; bar >= 2/3)")
    print("=" * 84)
    pos_pass = 0
    for label, msg, ctxfn in POSITIVE:
        fires, detail = await _fire(client, model, msg, ctxfn)
        acronyms = ",".join(sorted({a for a, _ in detail if a}) or {"-"})
        ok = fires >= 2
        pos_pass += ok
        print(f"  [{fires}/{N}] {'PASS' if ok else 'MISS':4} {label:44} -> {acronyms}")

    print("\n" + "=" * 84)
    print("NEGATIVE set (expect NULL; ANY fire = OVER-FIRE = do not ship)")
    print("=" * 84)
    neg_clean = 0
    overfires = []
    for label, msg, ctxfn in NEGATIVE:
        fires, detail = await _fire(client, model, msg, ctxfn)
        sgs = ",".join(sorted({s for _, s in detail if s}) or {"-"})
        acr = ",".join(sorted({a for a, _ in detail if a}) or {"-"})
        clean = fires == 0
        neg_clean += clean
        if not clean:
            overfires.append((label, acr))
        print(f"  [{fires}/{N}] {'ok' if clean else 'OVER-FIRE':9} {label:40} "
              f"subgroup={sgs:6} unknown={acr}")

    print("\n" + "=" * 84)
    print(f"POSITIVE fired >=2/3: {pos_pass}/{len(POSITIVE)}")
    print(f"NEGATIVE stayed null : {neg_clean}/{len(NEGATIVE)}   over-fires: {len(overfires)}")
    for label, acr in overfires:
        print(f"    OVER-FIRE: {label}  -> {acr}")
    gate = (pos_pass == len(POSITIVE)) and (len(overfires) == 0)
    print(f"\nQU SHIP-GATE: {'PASS' if gate else 'FAIL — tighten the prompt / DO NOT SHIP'}")
    print("  (bar: every positive fires >=2/3 AND 0 negative over-fires)")
    sys.exit(0 if gate else 1)


asyncio.run(main())
