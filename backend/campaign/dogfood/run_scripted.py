"""Run a scripted conversation: feed its fixed turns to dogfood_send in order,
under one session_id + one pinned user_id. Prints each app reply."""
import argparse
import json
import sys
import uuid

import dogfood_send as ds
import schema


def run_scripted(spec, api=ds.API):
    errs = schema.validate(spec)
    if errs:
        raise ValueError(f"invalid spec {spec.get('id')}: {errs}")
    session_id = f"dogfood-{spec['id']}"
    user_id = f"dogfood-{spec['id']}-{uuid.uuid4()}"
    for turn in spec["turns"]:
        _, reply = ds.send(session_id, turn, user_id=user_id, api=api)
        print(f"\n>>> {turn}\n<<< {reply[:600]}")
    return session_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec_path")
    ap.add_argument("--api", default=ds.API)
    args = ap.parse_args()
    with open(args.spec_path) as f:
        spec = json.load(f)
    sid = run_scripted(spec, api=args.api)
    print(f"\nwrote transcripts/{sid}.jsonl", file=sys.stderr)


if __name__ == "__main__":
    main()
