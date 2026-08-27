"""SG2 live gate — Brady: "Not always a grade level... need current writing level."

Behaviour-changing + prompt-touching → tests-green is not sufficient.
Probes 2 and 4 are the ANTI-REGRESSION controls (grade-first-clarify must
survive; SG2's own writing-level ask must survive).
"""
import json
import sys

import requests

BASE = "http://127.0.0.1:8020"
GRADE_Q = "grade level"
LEVEL_Q = ("writing level", "picture", "label", "word", "sentence")


def ask(msg, sid):
    r = requests.post(f"{BASE}/api/chat", json={
        "message": msg, "session_id": sid, "user_id": sid, "model": "gpt-5.4"}, timeout=240)
    d = r.json()
    resp = d.get("response")
    txt = resp if isinstance(resp, str) else json.dumps(resp)
    is_lesson = isinstance(resp, dict) and "step_2b_show" in resp
    return txt, is_lesson, (d.get("session_state") or {})


CASES = [
    # (label, msg, want_lesson, want_grade_question)
    ("1 SPED+picture stage", "Give me a lesson on strong leads for my SPED students; they're still at the picture-drawing stage.", True, False),
    ("2 CONTROL no grade/stage", "Give me a lesson on strong leads.", False, True),
    ("3 MLL+sentence stage", "Give me a lesson on strong leads for my MLL students; they're writing at the sentence level.", True, False),
    ("4 CONTROL subgroup no stage", "Give me a lesson on strong leads for my SPED students.", False, False),
    ("5 stage, NO acronym", "Give me a lesson on strong leads — my kids are still drawing pictures, not writing words yet.", True, False),
]

ok_all = True
for label, msg, want_lesson, want_grade_q in CASES:
    txt, is_lesson, ss = ask(msg, "sg2" + label[0])
    low = txt.lower()
    asks_grade = GRADE_Q in low and not is_lesson
    asks_level = any(k in low for k in LEVEL_Q) and not is_lesson
    ok = (is_lesson == want_lesson) and (asks_grade == want_grade_q)
    if label.startswith("4"):  # must ask the WRITING-LEVEL question, not grade
        ok = (not is_lesson) and asks_level and not asks_grade
    ok_all &= ok
    print(f"\n--- {label} ---")
    print(f"  lesson? {is_lesson} (want {want_lesson}) | asks GRADE? {asks_grade} (want {want_grade_q}) | asks LEVEL? {asks_level}")
    print(f"  writing_level={ss.get('writing_level')!r} subgroup={ss.get('subgroup')!r} grade={ss.get('grade')!r}")
    print(f"  reply[:110]: {txt[:110]!r}")
    print(f"  => {'PASS' if ok else 'FAIL'}")

print("\n" + "=" * 60)
print(f"SG2 LIVE GATE: {'ALL PASS' if ok_all else 'FAILURES — DO NOT SHIP'}")
sys.exit(0 if ok_all else 1)
