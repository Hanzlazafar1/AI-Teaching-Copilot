"""Task 6 (C14 "number 4" title garble) LIVE-GATE — end-to-end backend drive.

Re-drives C14's REAL 5-turn flow: a COACHING turn renders a numbered skill
list, then "give me number 4". Pre-fix the lesson was TITLED with the raw
directive bullet "Teach students to think small..." because the COACHING list
was never recorded as offered_skills, so the ordinal resolver (+ its
directive-strip) was bypassed and the LLM copied the bullet. Post-fix: number 4
-> item 4, "Teach students to" stripped.

Plus (the fix now also enables these): a MANAGEMENT-overview ordinal pick, and
a NO-FALSE-PICK sanity (a non-ordinal follow-up after a list must NOT become a
mis-picked lesson). PRINTS everything for HAND-READING (dogfood method).
Fresh user_id per conversation (the anonymous 50/hr bucket once threw 429s).
"""
import json
import os
import re
import sys
import uuid

import requests

BASE = os.environ.get("NUM4_API", "http://127.0.0.1:8091")

C14 = [
    "How do I teach opinion writing to my 3rd graders?",
    "That's a lot to cover. Which of these should I start with?",
    "Before I pick a sequence, can you lay out all the separate skills as a "
    "numbered list so I can choose one to try?",
    "Yes, but there are a bunch of them here. Can you number them so I can tell "
    "you which one I want?",
    "give me number 4",
]


def send(msg, sid, uid):
    r = requests.post(f"{BASE}/api/chat", json={
        "message": msg, "session_id": sid, "user_id": uid, "model": "gpt-5.4",
    }, timeout=240)
    r.raise_for_status()
    return r.json()


def numbered_items(text):
    items = {}
    for m in re.finditer(r"(?m)^\s*(\d+)\.\s+(.+)$", text):
        items.setdefault(int(m.group(1)), m.group(2).strip())
    return items


def txt_of(resp):
    return resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)


def run_c14(i):
    sid, uid = f"num4C14-{i}", f"num4-{uuid.uuid4()}"
    t3_items, t4 = {}, None
    for k, msg in enumerate(C14):
        b = send(msg, sid, uid)
        resp = b.get("response")
        if k == 3:
            t3_items = numbered_items(txt_of(resp))
        if k == 4:
            t4, t4_intent = resp, b.get("intent")
    print(f"\n===== C14 run {i} (expect: number 4 -> item 4, no 'Teach students to' title) =====")
    print(f"  T3 offered item 4: {t3_items.get(4, '?? (no item 4 parsed)')[:100]}")
    if isinstance(t4, dict):
        sf = t4.get("skill_focus", "")
        print(f"  T4 intent={t4_intent}  skill_focus: {sf!r}")
        print(f"  T4 step_1[:200]: {(t4.get('step_1_introduce') or '')[:200]}")
        garble = "teach students" in sf.lower()
        print(f"  => 'teach students' in title: {garble}  ({'FAIL-garble' if garble else 'clean title'})")
        return not garble
    print(f"  T4 was NOT a structured lesson (intent={t4_intent}): {txt_of(t4)[:160]}")
    return False


def run_management_pick():
    sid, uid = "num4MGMT", f"num4-{uuid.uuid4()}"
    send("Give me an overview of the writing-workshop management routines to set "
         "up first for my 3rd graders, as a numbered list.", sid, uid)
    b = send("Let's start with number 2.", sid, uid)
    resp, intent = b.get("response"), b.get("intent")
    print("\n===== MANAGEMENT overview -> 'number 2' (fix now enables; hand-read) =====")
    if isinstance(resp, dict):
        print(f"  intent={intent}  skill_focus: {resp.get('skill_focus')!r}")
    print(f"  reply[:260]: {txt_of(resp)[:260]}")


def run_no_false_pick():
    sid, uid = "num4NFP", f"num4-{uuid.uuid4()}"
    send("How do I teach persuasive writing to 3rd graders? List the separate "
         "skills as a numbered list.", sid, uid)
    b = send("Can you explain that whole approach a bit more?", sid, uid)  # NO ordinal anchor
    resp, intent = b.get("response"), b.get("intent")
    is_lesson = isinstance(resp, dict) and "skill_focus" in resp
    print("\n===== NO-FALSE-PICK: list then a NON-ordinal follow-up (expect NOT a picked lesson) =====")
    print(f"  intent={intent}  is_structured_lesson={is_lesson}")
    print(f"  reply[:220]: {txt_of(resp)[:220]}")
    return not is_lesson  # a non-ordinal follow-up should not silently become a mini_lesson pick


def main():
    c14 = [run_c14(i) for i in range(1, 4)]
    run_management_pick()
    nfp = run_no_false_pick()
    print("\n" + "=" * 74)
    print(f"  C14 clean-title runs: {sum(c14)}/3   (heuristic; HAND-READ each above)")
    print(f"  no-false-pick sanity: {'ok' if nfp else 'CHECK — follow-up became a lesson'}")
    print("\nNOTE: hand-read every block — the skill_focus must be item 4's skill, "
          "cleanly named, not the raw 'Teach students to...' directive.")


if __name__ == "__main__":
    main()
