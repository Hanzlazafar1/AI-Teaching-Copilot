"""dogfood_send.py — the ONE drive primitive for the dogfood pass.

POSTs a single teacher turn to the live app, APPENDS the full envelope to a
per-session transcript, and prints the app's reply to stdout (so a dynamic
teacher-agent can read it and choose its next turn). Faithful CAPTURE only —
no judging. Gotchas in the plan's Global Constraints / spec §7.
"""
import argparse
import datetime
import json
import os
import uuid

import httpx

API = os.environ.get("DOGFOOD_API", "http://127.0.0.1:8088")
_HERE = os.path.dirname(os.path.abspath(__file__))
TRANSCRIPTS = os.path.join(_HERE, "transcripts")


def _do_post(api, payload):
    """The one network call; patched in tests."""
    with httpx.Client(timeout=180) as client:
        r = client.post(f"{api}/api/chat", json=payload)
        r.raise_for_status()
        return r.json()


def _count_lines(path):
    if not os.path.exists(path):
        return 0
    with open(path) as f:
        return sum(1 for _ in f)


def send(session_id, message, user_id=None, api=API, transcripts_dir=TRANSCRIPTS):
    os.makedirs(transcripts_dir, exist_ok=True)
    path = os.path.join(transcripts_dir, f"{session_id}.jsonl")
    turn_index = _count_lines(path)
    user_id = user_id or f"dogfood-{uuid.uuid4()}"

    body = _do_post(api, {"message": message, "session_id": session_id, "user_id": user_id})

    resp = body.get("response")
    reply_text = resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)
    record = {
        "turn_index": turn_index,
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "session_id": session_id,
        "user_id": user_id,
        "message": message,
        "response": resp,  # dict OR string, verbatim
        "response_kind": "structured" if isinstance(resp, dict) else "text",
        "intent": body.get("intent"),
        "quality": body.get("quality"),
        "sources": body.get("sources"),
        "retrieved_context": body.get("retrieved_context"),
        "header": resp.get("header") if isinstance(resp, dict) else None,
        "one_skill_guard": resp.get("one_skill_guard") if isinstance(resp, dict) else None,
        "book_citation": resp.get("book_citation") if isinstance(resp, dict) else None,
    }
    with open(path, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record, reply_text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", required=True)
    ap.add_argument("--message", required=True)
    ap.add_argument("--user", default=None)
    ap.add_argument("--api", default=API)
    args = ap.parse_args()
    _, reply = send(args.session, args.message, user_id=args.user, api=args.api)
    print(reply)  # stdout = the app's reply, for a teacher-agent to read


if __name__ == "__main__":
    main()
