"""Collect the recert Workflow's judge verdicts from its journal into verdicts.json
+ print the ratification worklist. Classifies each agent result by payload:
drive agents return a string; judge agents return {conversation_id in briefIds};
calibration agents return {conversation_id starting 'cal'}."""
import glob
import json
import os
import sys
from collections import Counter, defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))


def brief_ids():
    ids = []
    for p in glob.glob(os.path.join(_HERE, "conversations", "*.json")):
        ids.append(os.path.basename(p)[:-5])
    return set(ids)


def collect(journal_path):
    ids = brief_ids()
    judge, calib, drive = {}, {}, 0
    for line in open(journal_path):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("type") != "result":
            continue
        rv = rec.get("result")
        if isinstance(rv, str):
            drive += 1
            continue
        if not isinstance(rv, dict):
            continue
        cid = rv.get("conversation_id", "")
        if cid in ids:
            judge[cid] = rv           # last wins (dedup retries)
        elif str(cid).startswith("cal"):
            calib[cid] = rv
    return ids, judge, calib, drive


def main():
    journal = sys.argv[1]
    ids, judge, calib, drive = collect(journal)

    # --- write verdicts.json (sorted R* then P*) ---
    def k(x):
        return (x[0], int(x[1:]))
    verdicts = [judge[i] for i in sorted(judge, key=k)]
    out = os.path.join(_HERE, "verdicts.json")
    with open(out, "w") as f:
        json.dump(verdicts, f, indent=2, ensure_ascii=False)

    print(f"drive results: {drive} | judge convos: {len(judge)}/{len(ids)} | calibration: {len(calib)}")
    missing = sorted(ids - set(judge), key=k)
    if missing:
        print(f"!!! MISSING judge verdicts for: {missing}")

    # --- calibration recap ---
    print("\n=== CALIBRATION ===")
    for cid in sorted(calib):
        vs = calib[cid].get("verdicts", [])
        print(f"  {cid}: {vs[0].get('verdict') if vs else '??'}")

    # --- verdict tally + per-target rollup ---
    tally = Counter()
    per_target = defaultdict(Counter)
    non_aligned = []
    observations = []
    for cid in sorted(judge, key=k):
        conv = judge[cid]
        for v in conv.get("verdicts", []):
            verdict = v.get("verdict")
            tally[verdict] += 1
            per_target[v.get("target_id")][verdict] += 1
            if verdict != "ALIGNED":
                non_aligned.append((cid, v.get("target_id"), verdict,
                                    v.get("turn_index"), v.get("reasoning", "")))
        obs = (conv.get("unprompted_observations") or "").strip()
        if obs:
            observations.append((cid, obs))

    print("\n=== VERDICT TALLY (all judge verdicts) ===")
    for k2 in ("ALIGNED", "PARTIAL", "MISALIGNED", "NOT_APPLICABLE", "NOT_BUILT"):
        if tally.get(k2):
            print(f"  {k2}: {tally[k2]}")

    print("\n=== PER-TARGET ROLLUP (target: verdict counts) ===")
    for t in sorted(per_target):
        print(f"  {t}: {dict(per_target[t])}")

    print(f"\n=== NON-ALIGNED WORKLIST ({len(non_aligned)}) — hand-ratify each ===")
    for cid, tid, verdict, turn, reason in non_aligned:
        print(f"  [{cid} · target {tid} · {verdict} · turn {turn}] {reason[:200]}")

    print(f"\n=== UNPROMPTED OBSERVATIONS ({len(observations)} conversations) ===")
    for cid, obs in observations:
        print(f"  --- {cid} ---\n  {obs[:600]}\n")

    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
