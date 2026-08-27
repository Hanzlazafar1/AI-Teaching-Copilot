"""Task 5 (C10 emotional-validation) LIVE-GATE — end-to-end backend drive.

Complements the offline QU probe (probe_frustration_qu.py, which gates the
SIGNAL). This gates the TEACHER-VISIBLE reply:
  * C10 (Brady's own frustrated opener) x3 fresh sessions -> the reply OPENS
    with validation of the frustration AND still offers a real next step.
  * a frustrated PLAN_UNIT turn -> opens cleanly (reviewer Minor 1: the
    validate-first rule vs. PLAN_UNIT's "use the opening verbatim" — eyeball it
    still reads well).
  * a CALM ask -> NO validation opener (the no-op holds through delivery).

PRINTS every reply for HAND-READING — the heuristic flags are a helper, the
hand-read is the authority (dogfood method: drive live, read by hand). Fresh
user_id per call (the anonymous 50/hr bucket threw 54 HTTP 429s once).
"""
import json
import os
import sys
import uuid

import requests

BASE = os.environ.get("FRUST_API", "http://127.0.0.1:8091")

# LLM-authored, so match on empathy MEANING, not one phrase. Brady's exemplar:
# "This is not unusual - it's hard for students to...". Hand-read confirms.
VALIDATION_MARKERS = [
    "not unusual", "it's hard", "it is hard", "that's hard", "so hard",
    "really hard", "understandable", "makes sense that", "you're not alone",
    "not alone", "normal to feel", "it's normal", "tough", "challenging",
    "i hear you", "i know how", "hang in there", "frustrat", "hard for students",
]
BANNED = ["discuss", "activity", "activities", "i'll listen in",
          "professional development", "certificate", "chunk", "retrieval",
          "embedding"]


def send(msg, sid):
    r = requests.post(f"{BASE}/api/chat", json={
        "message": msg, "session_id": sid,
        "user_id": f"frust-{uuid.uuid4()}", "model": "gpt-5.4",
    }, timeout=240)
    r.raise_for_status()
    return r.json()


def text_of(body):
    resp = body.get("response")
    return resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)


def show(label, msg, body, want_validation):
    txt = text_of(body)
    low = txt.lower()
    opening = txt[:320].replace("\n", " ")
    tail = txt.rstrip()[-160:].replace("\n", " ")
    val = [m for m in VALIDATION_MARKERS if m in low[:400]]  # in the OPENING
    banned = [b for b in BANNED if b in low]
    intent = body.get("intent")
    print(f"\n{'='*74}\n{label}\n  msg: {msg!r}\n  intent={intent} quality={body.get('quality')}")
    print(f"  OPENING: {opening}")
    print(f"  TAIL   : ...{tail}")
    print(f"  validation-markers in opening: {val}")
    print(f"  banned-word hits: {banned}")
    if want_validation:
        ok = bool(val) and not banned
        print(f"  => want VALIDATION + no-banned: {'heuristic-PASS' if ok else 'HAND-READ NEEDED'}")
    else:
        ok = (not val) and not banned
        print(f"  => want NO validation (no-op): {'heuristic-PASS' if ok else 'HAND-READ NEEDED'}")
    return ok


def main():
    results = {}
    # C10 x3 — Brady's own case
    for i in range(1, 4):
        b = send("I'm so frustrated — my 2nd graders just can't write a complete "
                 "sentence and I don't know what to do.", f"frustC10-{i}")
        results[f"C10 run {i} (validate+next-step)"] = show(
            f"C10 FRUSTRATED run {i} (expect validation opener + real next step)",
            "I'm so frustrated — my 2nd graders...", b, want_validation=True)

    # frustrated PLAN_UNIT — the verbatim-opener eyeball (reviewer Minor 1)
    b = send("I'm so frustrated, I don't even know where to start — can you help me "
             "plan a persuasive writing unit for my 4th graders?", "frustPU")
    results["frustrated PLAN_UNIT opens cleanly"] = show(
        "FRUSTRATED PLAN_UNIT (expect validation AND a clean unit opening)",
        "I'm so frustrated ... plan a persuasive unit ...", b, want_validation=True)

    # calm no-over-fire end-to-end
    b = send("How do I teach topic sentences to 3rd graders?", "calmHTT")
    results["calm HOW_TO_TEACH no over-fire"] = show(
        "CALM HOW_TO_TEACH (expect NO validation opener)",
        "How do I teach topic sentences to 3rd graders?", b, want_validation=False)

    print("\n" + "=" * 74)
    for k, v in results.items():
        print(f"  {'heuristic-PASS' if v else 'HAND-READ':14} {k}")
    print("\nNOTE: verdicts are HEURISTIC. Hand-read every OPENING above before "
          "declaring the gate PASS.")


if __name__ == "__main__":
    main()
