"""u3 LIVE gate — Brady's unit-planning category must get his mode question.

Behaviour-changing → tests-green is NOT sufficient (the Fm5/S3 precedent).
Drives the real /api/chat surface, i.e. what the TEACHER actually receives.

Cases 1-2 are the DEFECT (the drive's exact scenarios). Case 3 is the ESCALATION
the fix must close: the teacher answers grade only, and the app must still ask
for the mode rather than let handlers/plan_unit.py's mandated "For {grade}
{mode} writing" opening invent one ("5th-grade persuasive" = Brady's original
complaint). Cases 4-5 are ANTI-REGRESSION controls: a fully-specified unit must
still generate, and SG2's stage-supplants-grade rule must survive.
"""
import json
import sys

import requests

BASE = "http://127.0.0.1:8040"
MODE_Q = "persuasive, informative, or narrative"
GRADE_Q = "grade level"
INVENTED = ("persuasive", "informative", "narrative", "opinion", "inform")


def ask(msg, sid):
    r = requests.post(f"{BASE}/api/chat", json={
        "message": msg, "session_id": sid, "user_id": sid, "model": "gpt-5.4"}, timeout=240)
    d = r.json()
    resp = d.get("response")
    txt = resp if isinstance(resp, str) else json.dumps(resp)
    return txt, d


ok_all = True
results = []


def check(label, cond, detail):
    global ok_all
    ok_all &= cond
    results.append((label, cond, detail))
    print(f"  => {'PASS' if cond else 'FAIL'} — {detail}")


# --- 1. THE DEFECT: bare unit ask (drive scenario 0) -----------------------
print("\n--- 1. bare unit ask: must ask Brady's MODE question (+ grade) ---")
txt, d = ask("I want to plan a writing unit for my class.", "u3-live-1")
low = txt.lower()
print(f"  reply: {txt[:180]!r}")
check("1 bare-unit-asks-mode", MODE_Q in low and GRADE_Q in low,
      f"mode_q={MODE_Q in low} grade_q={GRADE_Q in low}")

# --- 2. hostile: teacher invites the app to assume (drive scenario 3) ------
print("\n--- 2. hostile 'whatever you think is best': must STILL ask, not assume ---")
txt, d = ask("Just build me a unit plan — whatever grade and writing type you think is best.",
             "u3-live-2")
low = txt.lower()
print(f"  reply: {txt[:180]!r}")
check("2 hostile-still-asks-mode", MODE_Q in low, f"mode_q={MODE_Q in low}")

# --- 3. THE ESCALATION: grade supplied, mode still withheld ----------------
print("\n--- 3. turn-2 grade-only: must ask MODE, must NOT invent one ---")
sid = "u3-live-3"
t1, _ = ask("I want to plan a writing unit for my class.", sid)
print(f"  T1: {t1[:110]!r}")
t2, d2 = ask("5th grade", sid)
low2 = t2.lower()
print(f"  T2: {t2[:180]!r}")
asked_mode = MODE_Q in low2
# "invented" = it produced a unit naming a mode instead of asking for one.
produced_unit = "priority skills" in low2 or (d2.get("sources") or [])
check("3 grade-only-asks-mode", asked_mode and not produced_unit,
      f"asked_mode={asked_mode} produced_unit_instead={bool(produced_unit)}")

# --- 4. CONTROL: fully specified -> must GENERATE, never re-ask ------------
print("\n--- 4. CONTROL fully-specified unit: must generate, not clarify ---")
txt, d = ask("I want to plan a persuasive writing unit for my 5th graders.", "u3-live-4")
low = txt.lower()
print(f"  reply: {txt[:180]!r}")
generated = "priority skills" in low or bool(d.get("sources"))
check("4 control-generates", generated and MODE_Q not in low,
      f"generated={generated} re_asked_mode={MODE_Q in low}")

# --- 5. ANTI-REGRESSION: SG2 stage-supplants-grade must survive ------------
print("\n--- 5. SG2 control: stage stated -> must NOT ask grade ---")
txt, d = ask("Plan a persuasive writing unit for my SPED students; they're still at "
             "the picture-drawing stage.", "u3-live-5")
low = txt.lower()
print(f"  reply: {txt[:180]!r}")
check("5 sg2-no-grade-ask", GRADE_Q not in low, f"asked_grade={GRADE_Q in low}")

print("\n" + "=" * 64)
for label, cond, _ in results:
    print(f"  {'PASS' if cond else 'FAIL'}  {label}")
print(f"u3 LIVE GATE: {'ALL PASS' if ok_all else 'FAILURES — DO NOT SHIP'}")
sys.exit(0 if ok_all else 1)
