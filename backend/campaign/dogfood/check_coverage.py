"""Fail loudly if any requirement is covered by 0 conversations (the recert's
'day-two half covered by 0 of 66 claims' failure, made a check that can fail)."""
import glob
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))


def uncovered(conversations_dir=None, requirements_path=None):
    conversations_dir = conversations_dir or os.path.join(_HERE, "conversations")
    requirements_path = requirements_path or os.path.join(_HERE, "requirements.json")
    with open(requirements_path) as f:
        required = json.load(f)
    covered = set()
    for p in glob.glob(os.path.join(conversations_dir, "*.json")):
        with open(p) as f:
            covered.update(json.load(f).get("covers", []))
    return [r for r in required if r not in covered]


def main():
    missing = uncovered()
    if missing:
        print("UNCOVERED requirements (add a conversation before the drive):")
        for r in missing:
            print(f"  - {r}")
        sys.exit(1)
    print("Coverage OK — every requirement is touched by ≥1 conversation.")


if __name__ == "__main__":
    main()
