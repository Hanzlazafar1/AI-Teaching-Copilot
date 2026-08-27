"""Which claims grade the SAME teacher move? (contradiction first-pass filter)

WHY THIS EXISTS
`nn-dig-into-same-lesson` (safety-non-negotiable) and `c2-ask-which-facets-first`
(important) were derived from ADJACENT SENTENCES of one Brady passage, by
different builders, and never reconciled. On the identical trigger, c2 REQUIRED
the reply to ask which facets of the original lesson broke down "instead of
immediately dumping a full generic re-teach", while nn-dig's (invented)
zero-tolerance clause CONVICTED naming those facets — and permitted the very
re-teach c2 forbids. The safety tier wins any tie, so our own claim set pushed
the app toward the generic restatement that IS Brady's complaint in that same
passage ("it basically restated it again... it didn't actually give me a day two").

That is a whole defect class: the campaign decomposes one Brady passage into
several claims, and nothing checks that they agree.

WHAT THIS MEASURES — and what it does NOT
It flags claims whose scenarios share a normalised PIVOT TURN (the final teacher
message), i.e. two rubrics scoring one response. CROSS-TIER overlaps are called
out because that is the dangerous shape: the higher tier silently overrides the
lower one.

⚠️ IT IS A FILTER, NOT A PROOF, IN BOTH DIRECTIONS:
  * Overlap != contradiction. Most overlaps are complementary (nn2 grades 2A/2B
    depth while e2 grades the follow-up question on the same lesson). A human
    must read the pair.
  * It CANNOT see a contradiction between rules probed with DIFFERENT scenarios.
    A rubric's rule applies in production far beyond its own probes — nn-dig's
    "never propose a new skill" governed every reteach turn, not just the one it
    drove. Two claims can contradict without ever sharing a pivot.

Run:  python3 campaign/recert/audit_claim_overlap.py
"""
from __future__ import annotations

import collections
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))
_TIER_ORDER = {"safety-non-negotiable": 0, "non-negotiable": 1, "important": 2, "minor": 3}


def _norm(turn: str) -> str:
    """Collapse a teacher message to its shape: grades vary, the move does not."""
    t = turn.lower().strip()
    t = re.sub(r"\b(grade\s*)?(k|\d{1,2})(st|nd|rd|th)?\b", "#G", t)
    t = re.sub(r"[^a-z#\s]", " ", t)
    return " ".join(t.split())


def main() -> None:
    claims = json.load(open(os.path.join(_HERE, "claims.v2.json")))["claims"]
    tier_of = {c["id"]: c.get("tier", "") for c in claims}

    by_pivot: dict[str, set] = collections.defaultdict(set)
    for c in claims:
        for s in c.get("scenarios", []) or []:
            turns = s.get("turns") or []
            if turns:
                by_pivot[_norm(turns[-1])].add(c["id"])

    shared = {k: v for k, v in by_pivot.items() if len(v) > 1}
    cross = 0
    print(f"claims: {len(claims)} | pivot turns graded by >1 claim: {len(shared)}\n")
    for pivot, ids in sorted(shared.items(), key=lambda kv: -len(kv[1])):
        tiers = {tier_of[i] for i in ids}
        is_cross = len(tiers) > 1
        cross += is_cross
        print(f'"{pivot[:76]}"{"   <-- CROSS-TIER" if is_cross else ""}')
        for cid in sorted(ids, key=lambda i: _TIER_ORDER.get(tier_of[i], 9)):
            print(f"      [{tier_of[cid]:22}] {cid}")
        print()
    print(f"cross-tier overlaps (a drifted higher tier silently wins): {cross}")
    print("Overlap is NOT contradiction — read each pair. And this cannot see")
    print("contradictions between claims probed with different scenarios.")


if __name__ == "__main__":
    main()
