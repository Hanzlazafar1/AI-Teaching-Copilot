"""Coverage gate: fail loudly if any target is exercised by 0 conversations
(static) or answered by 0 genuine verdicts (runtime). The recert's 'day-two
half covered by 0 of 66 claims' failure, turned into a check that can fail."""
import glob
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def _target_ids(targets_path):
    with open(targets_path) as f:
        return {t["id"] for t in json.load(f)}


def static_uncovered(conversations_dir=None, targets_path=None):
    conversations_dir = conversations_dir or os.path.join(_HERE, "conversations")
    targets_path = targets_path or os.path.join(_HERE, "targets.json")
    targets = _target_ids(targets_path)
    covered = set()
    for p in glob.glob(os.path.join(conversations_dir, "*.json")):
        with open(p) as f:
            covered.update(json.load(f).get("covers", []))
    return sorted(targets - covered)


def runtime_uncovered(verdicts_path=None, targets_path=None,
                      exclude=("NOT_APPLICABLE", "NOT_BUILT")):
    verdicts_path = verdicts_path or os.path.join(_HERE, "verdicts.json")
    targets_path = targets_path or os.path.join(_HERE, "targets.json")
    targets = _target_ids(targets_path)
    with open(verdicts_path) as f:
        runs = json.load(f)
    genuine = set()
    for conv in runs:
        for v in conv.get("verdicts", []):
            if v.get("verdict") not in exclude and v.get("target_id"):
                genuine.add(v["target_id"])
    return sorted(targets - genuine)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "static"
    missing = runtime_uncovered() if mode == "runtime" else static_uncovered()
    if missing:
        print(f"UNCOVERED targets ({mode}):")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)
    print(f"Coverage OK ({mode}) — every target exercised.")


if __name__ == "__main__":
    main()
