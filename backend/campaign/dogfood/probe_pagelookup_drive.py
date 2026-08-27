"""Task 8 (C2 deictic page-lookup) LIVE-GATE — end-to-end backend drive.

Bug: "what page is that lesson on?" re-ran retrieval on the referent-less query,
cited a CONFIDENT WRONG page off a generic chunk, right after hedging it could
not confirm one. Part-1 fix: on a refers_to_prior location-lookup, resolve
markers against EMPTY chunks -> markers swept, NO page emitted (silence). Brady:
"better to stay silent than lie." (Part 2 = cite the RIGHT page is deferred.)

Gate: the page-lookup turn STAYS SILENT (no "you'll find this lesson on p.N",
no raw [[src: marker), never a wrong page. NO-OVER-FIRE: a normal turn and a
CONTENT follow-up ("go deeper") still cite. PRINTS for HAND-READING.
"""
import json
import os
import re
import uuid

import requests

BASE = os.environ.get("PAGELOOKUP_API", "http://127.0.0.1:8091")
CITE_RE = re.compile(r"you'll find this lesson on|you will find this lesson on|\bon p\.?\s*\d+", re.IGNORECASE)
RAW_MARKER = "[[src:"


def send(msg, sid, uid):
    r = requests.post(f"{BASE}/api/chat", json={
        "message": msg, "session_id": sid, "user_id": uid, "model": "gpt-5.4",
    }, timeout=240)
    r.raise_for_status()
    return r.json()


def txt(resp):
    return resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)


def cite_present(t):
    return bool(CITE_RE.search(t))


def show(label, resp, want_citation):
    t = txt(resp)
    cited = cite_present(t)
    raw = RAW_MARKER in t
    verdict = "ok" if (cited == want_citation and not raw) else "HAND-READ"
    print(f"\n--- {label}")
    print(f"    citation present: {cited}  (want {want_citation})   raw marker leaked: {raw}")
    print(f"    reply[:340]: {t[:340].replace(chr(10),' ')}")
    return (cited == want_citation) and not raw


def run_c2(i):
    sid, uid = f"plC2-{i}", f"pl-{uuid.uuid4()}"
    send("How do I teach paragraph writing to 3rd graders?", sid, uid)   # outline (grade stated)
    send("Yes, give me the scripted mini-lesson.", sid, uid)             # SCRIPTED_ML
    b = send("What page is that lesson on?", sid, uid)                    # <-- the page-lookup
    print(f"\n===== C2 run {i} (paragraphing -> scripted ML -> 'what page?' — expect SILENCE) =====")
    return show("C2 page-lookup turn", b.get("response"), want_citation=False)


def run_ts08():
    sid, uid = "plTS08", f"pl-{uuid.uuid4()}"
    send("Give me a scripted mini-lesson on Snapple details for 6th grade", sid, uid)
    b = send("What page is this lesson on?", sid, uid)
    print("\n===== TS08 (Snapple details -> 'what page is this lesson on?' — expect SILENCE, no wrong page) =====")
    return show("TS08 page-lookup turn", b.get("response"), want_citation=False)


def run_no_overfire():
    # a NORMAL how-to-teach (not a page-lookup) SHOULD still cite
    b = send("How do I teach transitions to 4th graders?", "plNOF", f"pl-{uuid.uuid4()}")
    ok1 = show("no-over-fire: normal HOW_TO_TEACH (expect a citation)", b.get("response"), want_citation=True)
    # a CONTENT follow-up ("go deeper") is refers_to_prior but NOT a location-lookup -> should still cite
    sid, uid = "plDEEP", f"pl-{uuid.uuid4()}"
    send("How do I teach topic sentences to 4th graders?", sid, uid)
    b = send("Can you go deeper on that same lesson?", sid, uid)
    ok2 = show("no-over-fire: content follow-up 'go deeper' (expect a citation, NOT silenced)",
               b.get("response"), want_citation=True)
    return ok1, ok2


def main():
    c2 = [run_c2(i) for i in range(1, 4)]
    ts08 = run_ts08()
    nof1, nof2 = run_no_overfire()
    print("\n" + "=" * 74)
    print(f"  C2 page-lookup SILENT: {sum(c2)}/3   TS08 SILENT: {'ok' if ts08 else 'CHECK'}")
    print(f"  no-over-fire normal-cites: {'ok' if nof1 else 'CHECK'}   deeper-still-cites: {'ok' if nof2 else 'CHECK'}")
    print("\nNOTE: HAND-READ — the page-lookup turns must NOT print a page; the "
          "normal/deeper turns SHOULD still carry a citation. 'go deeper' citing is "
          "model-dependent (may be honest silence too) — read it, don't fail it blindly.")


if __name__ == "__main__":
    main()
