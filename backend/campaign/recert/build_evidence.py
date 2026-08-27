"""Phase-4 evidence-pack builder.

Joins the drive's per-probe primary verdicts (drive-results.jsonl; carries
claim_id) with the full driven envelopes (drive-cache.jsonl; carries
session_id + message + envelope) by matching a claim's scenario turn-texts to
the cached session messages. Produces one evidence pack per claim — the input
the Phase-4 opus multi-lens adjudication reads (claim + rubric + primary
verdict distribution + a few FULL sample envelopes: response, sources+tier,
session_state, parsed_query, follow_up). Envelopes are trimmed (retrieved_context
dropped) to keep packs adjudicable.

Run after the drive (re-run safe): PYTHONPATH not needed.
  python3 campaign/recert/build_evidence.py
"""
from __future__ import annotations

import collections
import json
import os
import re

_HERE = os.path.dirname(os.path.abspath(__file__))

# The assembled context's page headers ("| Page: 110").
_PAGE_RE = re.compile(r"Page:\s*([0-9]+)")


def _retrieved_pages(env: dict) -> list:
    """The book pages actually assembled for this turn, from the `Page:` headers.

    This is the evidence a citation-provenance check needs: Brady's rule (Fm5 /
    "stay silent rather than lie") is that a cited page must be one we actually
    retrieved, and handlers/citation.py::resolve_attribution enforces exactly
    that against these headers (it replaced select_citation_source, but kept the
    page-in-context gate unchanged — only WHICH chunk gets cited changed).

    It replaces a PHANTOM field. `_trim_env` used to emit `"page": s.get("page")`
    per source — but `api/models.py::SourceInfo` has no `page` field at all, so
    it was None for every source in every pack: 0 of 9,942 driven sources carried
    one. The Phase-4 violation lens was nonetheless instructed to check "citing
    an unretrieved page", making that check UNANSWERABLE across all 66 claims —
    an adjudicator that "verified citation provenance" was reading a dead field.
    (Inert-field class: always confirm a field is populated before trusting a
    check that reads it.)

    `retrieved_context` itself stays dropped — it is ~23KB per turn and would
    make packs unadjudicable. Only the page numbers are lifted out.
    """
    ctx = env.get("retrieved_context")
    if not ctx:
        return []
    seen = {int(p) for p in _PAGE_RE.findall(str(ctx))}
    return sorted(seen)


def _trim_env(env: dict) -> dict:
    srcs = []
    for s in (env.get("sources") or [])[:8]:
        if isinstance(s, dict):
            srcs.append({"source_tier": s.get("source_tier"),
                         "source_document": s.get("source_document")})
    return {
        "response": env.get("response"),
        "sources": srcs,
        # Real, populated provenance evidence — see _retrieved_pages.
        "retrieved_pages": _retrieved_pages(env),
        "session_state": env.get("session_state"),
        "parsed_query": env.get("parsed_query") or env.get("intent"),
        "follow_up_question": env.get("follow_up_question"),
        "quality": env.get("quality"),
    }


def main() -> None:
    claims = {c["id"]: c for c in
              json.load(open(os.path.join(_HERE, "claims.v2.json")))["claims"]}
    rpath = os.path.join(_HERE, "drive-results.jsonl")
    cpath = os.path.join(_HERE, "drive-cache.jsonl")
    results = [json.loads(l) for l in open(rpath) if l.strip()] if os.path.exists(rpath) else []
    sess = collections.defaultdict(list)
    if os.path.exists(cpath):
        for l in open(cpath):
            if not l.strip():
                continue
            r = json.loads(l)
            sess[r["session_id"]].append((r.get("turn_idx", 0), r.get("message", ""), r.get("envelope") or {}))
    for sid in sess:
        sess[sid].sort(key=lambda x: x[0])
    msgseq_to_sids = collections.defaultdict(list)
    for sid, turns in sess.items():
        msgseq_to_sids[tuple(m for _, m, _ in turns)].append(sid)

    vby = collections.defaultdict(list)
    for r in results:
        vby[r["claim_id"]].append(r)

    packs = []
    for cid, claim in claims.items():
        vs = vby.get(cid, [])
        dec = [v for v in vs if v["status"] in ("ALIGNED", "MISALIGNED")]
        aligned = sum(1 for v in dec if v["status"] == "ALIGNED")
        pass_rate = (aligned / len(dec)) if dec else None
        samples = []
        for si, sc in enumerate(claim.get("scenarios", [])):
            turns = tuple(sc.get("turns", []))
            sids = msgseq_to_sids.get(turns, [])
            # NO SILENT TRUNCATION. We show the adjudicator the first 2 of N
            # driven sessions, deterministically — NOT a stratified or
            # worst-case sample. Two independent re-adjudications found this
            # hides real deviations: a claim whose 2 samples were clean scored
            # ALIGNED while 2 of its 10 probes had never demonstrated the rule at
            # all (they were merely not violations), concealing a sibling defect.
            # Until sampling is made representative, the pack must at least SAY
            # what it dropped — a bounded sample that looks like full coverage is
            # how "pass_rate 1.0" gets over-read.
            n_dropped = max(0, len(sids) - 2)
            for sid in sids[:2]:
                convo = sess[sid]  # already sorted by turn_idx
                sample = {"scenario_idx": si, "tier": sc.get("tier"),
                          "turns": list(turns), "expected": sc.get("expected", ""),
                          "sessions_driven_for_this_scenario": len(sids),
                          "sessions_not_sampled": n_dropped,
                          "sampling": "first-2-deterministic (NOT stratified, NOT worst-case)",
                          # The pivotal final turn stays where adjudicators expect it.
                          "envelope": _trim_env(convo[-1][2])}
                # A multi-turn scenario's evidence is the EXCHANGE. This used to
                # be `sess[sid][-1]` only, so every earlier turn was dropped from
                # the pack and any rubric about a FLOW ("asks before it delivers")
                # was adjudicated on the delivery alone — the e9 adjudicator had
                # to go read drive-cache.jsonl by hand to recover Turn 1, and the
                # u3 re-drive showed the same blindness manufacturing a
                # MISALIGNED @0.95 on a correct clarify-then-deliver flow.
                if len(convo) > 1:
                    sample["prior_turns"] = [
                        {"turn_idx": ti, "message": msg, "envelope": _trim_env(env)}
                        for ti, msg, env in convo[:-1]
                    ]
                samples.append(sample)
        packs.append({
            "claim_id": cid, "tier": claim.get("tier"), "surface": claim.get("surface"),
            "judge_method": claim.get("judge_method"), "observable": claim.get("observable"),
            "requirement": claim.get("requirement"), "rubric": claim.get("rubric", ""),
            "source": claim.get("source", ""),
            "n_probes": len(vs), "n_decisive": len(dec), "aligned": aligned, "pass_rate": pass_rate,
            "verdict_counts": dict(collections.Counter(v["status"] for v in vs)),
            "primary_verdicts": [{"scenario_idx": v["scenario_idx"], "status": v["status"],
                                  "confidence": v["confidence"],
                                  "rationale": (v.get("rationale") or "")[:300]} for v in vs],
            "samples": samples,
        })
    json.dump(packs, open(os.path.join(_HERE, "evidence-packs.json"), "w"),
              ensure_ascii=False, indent=1)
    # Also emit one file per claim so Phase-4 agents read a small pack by path
    # (avoids passing the whole 300KB+ array through workflow args).
    edir = os.path.join(_HERE, "evidence")
    os.makedirs(edir, exist_ok=True)
    for p in packs:
        json.dump(p, open(os.path.join(edir, p["claim_id"] + ".json"), "w"),
                  ensure_ascii=False, indent=1)

    print("claims:", len(packs), "| probes joined:", len(results),
          "| per-claim packs ->", edir)
    need = [p for p in packs if (p["pass_rate"] is not None and p["pass_rate"] < 1.0)
            or p["tier"] in ("safety-non-negotiable", "non-negotiable")
            or p["verdict_counts"].get("MISALIGNED", 0) > 0]
    print("need-adjudication (any MISALIGNED / non-neg / <100% pass):", len(need))
    nosample = [p["claim_id"] for p in packs if not p["samples"]]
    print("claims with NO sampled envelope (join miss or not-yet-driven):", len(nosample))
    if nosample:
        print("  ", nosample[:12])


if __name__ == "__main__":
    main()
