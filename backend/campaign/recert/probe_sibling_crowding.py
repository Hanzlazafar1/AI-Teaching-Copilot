"""P2/B3 — do grade-parallel siblings crowd the correct entry out of the pool?

The review measured this and I must not take it on faith; my earlier probe
(probe_verbatim_ceiling) CANNOT see it, because querying an entry with its own
HyDE makes it #1 by construction, so it beats its siblings trivially.

The real case needs a REALISTIC teacher query — one that matches every
grade-version of a lesson roughly equally. Brady's 24 MLs are grade-parallel:
'Determine the strongest side' has 12 entries (K,1,2,3,4,5 x day1,day2),
'Recognize opinion topics' and 'Write an opinion' have 6 each. library_precheck
takes the GLOBAL top-5 (TOP_K_CANDIDATES=5) and only THEN filters by grade
(:179-180), so out-grade siblings can consume every slot before the filter runs.

Reports, per (title, grade):
  * is the correct in-grade entry inside the global top-5?   <- crowding
  * how many in-grade candidates survive?                     <- pool size
  * how many of the top-5 are out-grade siblings?             <- who ate the slots
  * separation between the top-2 in-grade entries             <- the I1 twin case

Run:
  cd copilot-v4 && env -u OPENAI_API_KEY -u OPENAI_BASE_URL PYTHONPATH=. \
      python3 -u campaign/recert/probe_sibling_crowding.py
"""
import asyncio
import collections

from retrieval.embedder import embed_query
from retrieval.library_precheck import TOP_K_CANDIDATES
from retrieval.ml_library import get_library

CONCURRENCY = 8


async def main() -> None:
    lib = get_library()
    groups = collections.defaultdict(list)
    for e in lib.entries:
        groups[e.skill_title].append(e)
    # Grade-parallel groups: the same title published per concrete grade.
    parallel = {
        t: v
        for t, v in groups.items()
        if len(v) > 1 and all(len(e.grade_levels) == 1 for e in v)
    }
    print(f"grade-parallel titles: {len(parallel)} "
          f"({sum(len(v) for v in parallel.values())} entries); "
          f"TOP_K_CANDIDATES={TOP_K_CANDIDATES}\n", flush=True)

    sem = asyncio.Semaphore(CONCURRENCY)

    async def probe(title, grade, expected_ids):
        msg = f"Give me the '{title}' mini-lesson for grade {grade}."
        async with sem:
            emb = await embed_query(msg)
        top = lib.find_matches(emb, user_grade=grade, top_k=TOP_K_CANDIDATES)
        in_grade = [m for m in top if m.grade_compatible]
        hit = [m for m in top if m.entry.ml_id in expected_ids]
        siblings_out = [
            m for m in top
            if m.entry.skill_title == title and not m.grade_compatible
        ]
        sep = (in_grade[0].confidence - in_grade[1].confidence) if len(in_grade) > 1 else None
        return {
            "title": title, "grade": grade,
            "correct_in_top5": bool(hit),
            "in_grade_pool": len(in_grade),
            "out_grade_siblings_in_top5": len(siblings_out),
            "sep": sep,
        }

    tasks = []
    for title, entries in parallel.items():
        by_grade = collections.defaultdict(list)
        for e in entries:
            by_grade[e.grade_levels[0]].append(e.ml_id)
        for grade, ids in by_grade.items():
            tasks.append(probe(title, grade, set(ids)))

    rows = await asyncio.gather(*tasks)

    crowded = [r for r in rows if not r["correct_in_top5"]]
    empty_pool = [r for r in rows if r["in_grade_pool"] == 0]
    undefined_sep = [r for r in rows if r["sep"] is None]
    twins = [r for r in rows if r["sep"] is not None and r["sep"] < 0.02]

    for r in sorted(rows, key=lambda r: (r["title"], r["grade"])):
        flag = "CROWDED-OUT" if not r["correct_in_top5"] else "ok         "
        sep = f"{r['sep']:.4f}" if r["sep"] is not None else "  n/a "
        print(f"  {flag}  {r['title'][:34]:36s} g={r['grade']:<2s} "
              f"in-grade-pool={r['in_grade_pool']}  "
              f"out-grade-siblings-in-top5={r['out_grade_siblings_in_top5']}  "
              f"sep={sep}", flush=True)

    n = len(rows)
    print("\n" + "=" * 72)
    print(f"probes: {n}")
    print(f"  correct entry CROWDED OUT of the top-{TOP_K_CANDIDATES}: {len(crowded)}/{n}")
    print(f"  in-grade pool EMPTY (-> precheck SKIPs, LLM ad-libs):     {len(empty_pool)}/{n}")
    print(f"  separation UNDEFINED (<2 in-grade candidates):            {len(undefined_sep)}/{n}")
    print(f"  in-grade TWINS (sep < 0.02 -> I1 disambiguate case):      {len(twins)}/{n}")


if __name__ == "__main__":
    asyncio.run(main())
