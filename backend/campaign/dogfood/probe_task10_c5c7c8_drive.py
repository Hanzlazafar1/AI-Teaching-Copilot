"""Task 10 consolidated live re-drive — C8 / C5 / C7.

These three were PROMPT-change fixes (Task 2 multi-skill closer, Task 3 S5
order-affirm, Task 4 SG3 stage-per-bullet) whose live behavior was deferred to
this final re-drive. Each is a scripted replay of the dogfood conversation's
agenda. PRINTS for HAND-READING; heuristics only flag.
"""
import json
import os
import uuid

import requests

BASE = os.environ.get("T10_API", "http://127.0.0.1:8091")
MULTI_CLOSER = "which of these skills do you want to start with"
SINGLE_CLOSER = "are you ready for a scripted mini-lesson"


def send(msg, sid, uid):
    r = requests.post(f"{BASE}/api/chat", json={
        "message": msg, "session_id": sid, "user_id": uid, "model": "gpt-5.4",
    }, timeout=240)
    r.raise_for_status()
    return r.json()


def txt(resp):
    return resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)


def run_c8(i):
    sid, uid = f"t10C8-{i}", f"t10-{uuid.uuid4()}"
    t0 = send("I'm getting ready to teach my students how to write from sources.", sid, uid)
    t1 = send("7th grade.", sid, uid)          # -> multi-skill outline
    t2 = send("Let's start with the second one.", sid, uid)  # -> ordinal pick -> ML
    o1 = txt(t1.get("response")).lower()
    multi = MULTI_CLOSER in o1
    single = SINGLE_CLOSER in o1
    r2 = t2.get("response")
    print(f"\n===== C8 run {i} (write-from-sources -> 7th -> 'the second one') =====")
    print(f"  T0 intent={t0.get('intent')} (expect it ASKS grade)")
    print(f"  T1 outline closer: multi-skill={multi}  single-skill={single}  (want multi=True)")
    print(f"  T1 tail: ...{txt(t1.get('response'))[-160:].strip()}")
    print(f"  T2 intent={t2.get('intent')}  skill_focus={r2.get('skill_focus') if isinstance(r2,dict) else 'TEXT'!r}")
    return multi and not single


def run_c5(i):
    sid, uid = f"t10C5-{i}", f"t10-{uuid.uuid4()}"
    t0 = send("Give me one 3rd grade lesson on topic sentences and transitions.", sid, uid)
    send("Plan a 3rd grade persuasive writing unit.", sid, uid)
    t2 = send("Here's the order I'm teaching my persuasive skills: 1) hook, 2) state "
              "your opinion, 3) supporting details, 4) linking words, 5) conclusion. "
              "Does this sequence work?", sid, uid)
    r0 = t0.get("response")
    guard = isinstance(r0, dict) and bool(r0.get("one_skill_guard"))
    a = txt(t2.get("response")).lower()
    affirm = any(k in a for k in ("sound", "works well", "that works", "your order", "your sequence", "makes sense", "solid", "logical"))
    reshuffle = any(k in a for k in ("i'd reorder", "i would reorder", "instead, start", "a better order", "reshuffle", "should be reordered"))
    print(f"\n===== C5 run {i} (one-skill guard -> unit -> ORDER AFFIRM) =====")
    print(f"  T0 one_skill_guard present: {guard}")
    print(f"  T2 (order 'does this work?') affirm-language={affirm} reshuffle-language={reshuffle}")
    print(f"  T2[:320]: {txt(t2.get('response'))[:320].replace(chr(10),' ')}")
    return affirm and not reshuffle


def run_c7(i):
    sid, uid = f"t10C7-{i}", f"t10-{uuid.uuid4()}"
    t0 = send("I teach SPED students and need help with strong leads.", sid, uid)
    t1 = send("They're mostly drawing pictures and labeling.", sid, uid)  # -> stage-aware outline
    a0 = txt(t0.get("response")).lower()
    asks_level = any(k in a0 for k in ("writing level", "stage", "picture", "label", "developmental", "where are your", "what level"))
    o1 = txt(t1.get("response")).lower()
    stage_hits = sum(o1.count(k) for k in ("picture", "label", "drawing"))
    print(f"\n===== C7 run {i} (SPED strong leads -> asks level -> STAGE-PER-BULLET) =====")
    print(f"  T0 asks writing level/stage: {asks_level}")
    print(f"  T1 stage mentions (picture/label/drawing): {stage_hits}  (want >1 = per-bullet)")
    print(f"  T1[:340]: {txt(t1.get('response'))[:340].replace(chr(10),' ')}")
    return asks_level and stage_hits > 1


def main():
    c8 = [run_c8(i) for i in range(1, 4)]
    c5 = [run_c5(i) for i in range(1, 4)]
    c7 = [run_c7(i) for i in range(1, 4)]
    print("\n" + "=" * 74)
    print(f"  C8 multi-skill closer: {sum(c8)}/3    C5 order-affirm: {sum(c5)}/3    C7 stage-per-bullet: {sum(c7)}/3")
    print("\nNOTE: HAND-READ each block. C8: T1 ends with the pick-list closer, T2 is a "
          "grade-7 ML for skill 2. C5: T2 affirms the teacher's order, no reshuffle. "
          "C7: T0 asks the writing level, T1 names the stage in EACH bullet.")


if __name__ == "__main__":
    main()
