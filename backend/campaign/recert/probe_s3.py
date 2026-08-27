"""S3 live gate — the 4 probes the fix requires before shipping.

Prompt-touching change → tests-green is NOT sufficient (the Fm5 lesson).
Probe 2 (B03) is the critical one: Brady's golden where "topic sentences and
supporting details" is ONE skill and the guard must NOT fire.
"""
import json
import sys

import requests

BASE = "http://127.0.0.1:8020"


def send(msg, sid, uid):
    r = requests.post(f"{BASE}/api/chat", json={
        "message": msg, "session_id": sid, "user_id": uid, "model": "gpt-5.4",
    }, timeout=240)
    return r.json()


def steps_text(resp):
    if not isinstance(resp, dict):
        return str(resp)
    return " ".join(str(resp.get(k, "")) for k in (
        "step_1_introduce", "step_2a_tell", "step_2b_show",
        "step_3_interact", "step_4_close"))


def report(name, env, expect_guard, deferred=None, must_teach=None):
    resp = env.get("response")
    guard = resp.get("one_skill_guard") if isinstance(resp, dict) else None
    st = steps_text(resp).lower()
    print(f"\n--- {name} ---")
    print(f"  guard present: {bool(guard)}  (expected: {expect_guard})")
    if guard:
        print(f"  guard text: {str(guard)[:110]}")
    ok = bool(guard) == expect_guard
    if deferred:
        n = st.count(deferred.lower())
        print(f"  '{deferred}' mentions in steps 1-4: {n}  (want ~0 = not taught)")
        ok = ok and n <= 1
    if must_teach:
        n = st.count(must_teach.lower())
        print(f"  '{must_teach}' taught in steps 1-4: {n} mentions  (want >0)")
        ok = ok and n > 0
    print(f"  => {'PASS' if ok else 'FAIL'}")
    return ok


results = {}

# 1. THE DEFECT CASE — guard fires AND the lesson excludes the deferred skill
e = send("Give me one 3rd grade lesson on topic sentences and transitions.", "s3p1", "s3u1")
results["1 defect-case"] = report("1. defect: topic sentences AND transitions",
                                  e, expect_guard=True, deferred="transition",
                                  must_teach="topic sentence")

# 2. B03 GOLDEN — must NOT fire; supporting details still taught
e = send("Give me a 3rd grade lesson on topic sentences and supporting details.", "s3p2", "s3u2")
results["2 B03 no-fire"] = report("2. B03 GOLDEN: topic sentences AND supporting details (ONE skill)",
                                  e, expect_guard=False, must_teach="detail")

# 3. PLAIN SINGLE SKILL — unchanged, no guard
e = send("Give me a 3rd grade lesson on transitions.", "s3p3", "s3u3")
results["3 single-skill"] = report("3. plain single skill", e, expect_guard=False,
                                   must_teach="transition")

# 4. DEEPEN_PRIOR — guard on the follow-up, lesson stays on primary
send("Give me a 4th grade lesson on adding transitions.", "s3p4", "s3u4")
e = send("Can you also work in topic sentences, in this same lesson?", "s3p4", "s3u4")
results["4 deepen-prior"] = report("4. DEEPEN_PRIOR follow-up crams a 2nd skill",
                                   e, expect_guard=True, deferred="topic sentence")

print("\n" + "=" * 60)
for k, v in results.items():
    print(f"  {k:20} {'PASS' if v else 'FAIL'}")
print(f"S3 LIVE GATE: {'ALL PASS' if all(results.values()) else 'FAILURES — DO NOT SHIP'}")
sys.exit(0 if all(results.values()) else 1)
