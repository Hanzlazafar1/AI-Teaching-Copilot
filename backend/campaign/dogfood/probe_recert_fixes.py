"""Live-gate the 5 recert fixes (④③⑤①②). Drives the exact recert cases against a
fresh backend and prints the key signal per case for hand-reading. Read, don't
trust — heuristics below are helpers, not verdicts."""
import re
import sys
import uuid

import dogfood_send as ds

API = "http://127.0.0.1:8092"


def _sid(tag):
    return f"recertfix-{tag}-{uuid.uuid4().hex[:8]}"


def _cites(text):
    if not isinstance(text, str):
        return []
    return re.findall(r"on (?:p\.?\s*\d+|pages [\d, ]+\d)", text)


def drive(tag, turns):
    sid = _sid(tag)
    uid = sid
    out = []
    for msg in turns:
        rec, reply = ds.send(sid, msg, user_id=uid, api=API)
        out.append((msg, rec, reply))
    return out


def show_text(reply, head=340, tail=200):
    t = reply if isinstance(reply, str) else "[STRUCTURED]"
    t1 = t[:head].replace("\n", " ")
    t2 = t[-tail:].replace("\n", " ") if len(t) > head + tail else ""
    print(f"    HEAD: {t1}")
    if t2:
        print(f"    TAIL: {t2}")


def main():
    print("=" * 78)
    print("④ FRUSTRATION — turn 0 must OPEN with validation, still ask grade")
    print("=" * 78)
    for msg, rec, reply in drive("frust", [
        "I'm honestly at my wit's end — I've tried everything and my kids still can't write a paragraph.",
    ]):
        print(f">>> {msg}")
        show_text(reply)
        print(f"    opens-with-validation: {'I hear you' in (reply if isinstance(reply,str) else '')}")

    print("\n" + "=" * 78)
    print("③ ACRONYM — turn 2 'WIN block' must ASK what WIN stands for")
    print("=" * 78)
    for msg, rec, reply in drive("winacr", [
        "Can you give me a writing lesson for my RTI kids?",
        "Most of them are writing simple sentences right now.",
        "This is helpful. One thing though — a handful of these kids are also in our WIN block, so I want to make sure the lesson works for them too. Can you tweak it with them in mind?",
    ]):
        print(f">>> {msg}")
        show_text(reply)
        r = reply if isinstance(reply, str) else ""
        print(f"    asks-acronym: {bool(re.search(r'stand for|what.*acronym|WIN.{0,10}mean', r, re.I))}")

    print("\n" + "=" * 78)
    print("⑤ TITLE-GARBLE — follow-up 'more on that' skill_focus must be a REAL skill, not 'That'")
    print("=" * 78)
    for msg, rec, reply in drive("deictic", [
        "Give me a scripted mini-lesson on transitions between paragraphs.",
        "4th grade",
        "Give me more on that.",
    ]):
        print(f">>> {msg}  [intent={rec.get('intent')}]")
        resp = rec.get("response")
        if isinstance(resp, dict):
            print(f"    skill_focus={resp.get('skill_focus')!r} | lesson_title={resp.get('lesson_title')!r}")
            s1 = (resp.get("step_1_introduce") or "")[:180].replace("\n", " ")
            print(f"    step_1: {s1}")
        else:
            show_text(reply, 180, 0)

    print("\n" + "=" * 78)
    print("①② CITATION — P09: turn0 cites p.64; turn1 '4th grade' must NOT cite p.57 (silent or p.64)")
    print("=" * 78)
    for msg, rec, reply in drive("pizza", [
        "Is there a pizza table lesson?",
        "4th grade",
        "Wait, what page is the pizza table lesson actually on?",
    ]):
        print(f">>> {msg}  [intent={rec.get('intent')}]")
        print(f"    CITES: {_cites(reply)}")
        show_text(reply, 260, 160)

    print("\n" + "=" * 78)
    print("①② CONTROL — a lesson that IS retrieved must STILL cite (no over-suppression)")
    print("=" * 78)
    for msg, rec, reply in drive("ctl", [
        "How do I teach 3rd graders to write a strong topic sentence?",
    ]):
        print(f">>> {msg}  [intent={rec.get('intent')}]")
        print(f"    CITES: {_cites(reply)}")
        show_text(reply, 260, 160)


if __name__ == "__main__":
    main()
