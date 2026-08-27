"""Task 7 (C1 verb-led lesson title) LIVE-GATE — end-to-end backend drive.

Brady: "I love that it's a verb. It's a statement." Pre-fix a scripted ML was
TITLED with the teacher's bare noun ("Topic sentences"). Post-fix a NEW
model-authored `lesson_title` is a verb-led statement, while `skill_focus`
stays the teacher's exact vocabulary (steps + vocab validator).

Re-drives C1 (topic sentences -> grade 3) and C13 (a NAMED book lesson) 3x.
Prints lesson_title + skill_focus + step_1 for HAND-READING — the verb check is
a human judgement, the heuristic only flags "title == skill_focus" (no rephrase).
"""
import json
import os
import sys
import uuid

import requests

BASE = os.environ.get("VERBTITLE_API", "http://127.0.0.1:8091")
BANNED = ["discuss", "activity", "activities", "professional development", "certificate"]


def send(msg, sid, uid):
    r = requests.post(f"{BASE}/api/chat", json={
        "message": msg, "session_id": sid, "user_id": uid, "model": "gpt-5.4",
    }, timeout=240)
    r.raise_for_status()
    return r.json()


def show(label, resp):
    if not isinstance(resp, dict):
        print(f"  {label}: NOT a structured lesson -> {str(resp)[:140]}")
        return None
    lt = resp.get("lesson_title", "<MISSING>")
    sf = resp.get("skill_focus", "")
    s1 = (resp.get("step_1_introduce") or "")[:150]
    differs = str(lt).strip().lower() != str(sf).strip().lower()
    banned = [b for b in BANNED if b in f"{lt} {sf}".lower()]
    print(f"  {label}: lesson_title={lt!r}")
    print(f"       skill_focus={sf!r}   (title differs from skill_focus: {differs})")
    print(f"       step_1[:150]: {s1}")
    if banned:
        print(f"       !! BANNED in title/skill: {banned}")
    return {"lesson_title": lt, "skill_focus": sf, "differs": differs, "banned": banned}


def run_c1(i):
    sid, uid = f"vtC1-{i}", f"vt-{uuid.uuid4()}"
    send("Give me a scripted mini-lesson on topic sentences.", sid, uid)  # T0: asks grade
    b = send("3rd grade.", sid, uid)  # T1: the lesson
    print(f"\n===== C1 run {i} (topic sentences, grade 3 — expect VERB-LED title, skill_focus='topic sentences') =====")
    return show("C1-lesson", b.get("response"))


def run_c13(i):
    sid, uid = f"vtC13-{i}", f"vt-{uuid.uuid4()}"
    b = send("Is there a 'read up, write down' lesson in the Launch books? Can you "
             "give it to me as a scripted mini-lesson for my 3rd graders?", sid, uid)
    print(f"\n===== C13 run {i} (named 'read up write down' — expect VERB-LED title) =====")
    return show("C13-lesson", b.get("response"))


def main():
    rows = []
    for i in range(1, 4):
        rows.append(("C1", run_c1(i)))
    for i in range(1, 4):
        rows.append(("C13", run_c13(i)))
    print("\n" + "=" * 74)
    ok = [r for _, r in rows if r]
    diff = sum(1 for r in ok if r["differs"])
    clean = sum(1 for r in ok if not r["banned"])
    print(f"  lessons captured: {len(ok)}/6   title-differs-from-skill_focus: {diff}/{len(ok)}   no-banned: {clean}/{len(ok)}")
    print("\nNOTE: HAND-READ every lesson_title — it must be a VERB-LED statement "
          "(starts with a verb / is an action), NOT the bare noun. skill_focus must "
          "stay the teacher's exact wording.")


if __name__ == "__main__":
    main()
