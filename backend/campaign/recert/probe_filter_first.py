"""P2 — does filtering in-grade BEFORE truncating actually fix the pool?

Compares, on the same realistic named asks:
  CURRENT   find_matches(top_k=5) -> filter by grade   (truncate, then filter)
  PROPOSED  find_best_in_grade(top_k=5)                (over-fetch, filter, truncate)

The review warns over-fetch alone is NOT sufficient: it takes "separation
undefined" to 0% while correct-pin sits at 47%, because the statistic degrades
into "is the rest of my grade band unrelated?" (always yes). Test both claims.
"""
import asyncio, collections
from retrieval.embedder import embed_query
from retrieval.library_precheck import TOP_K_CANDIDATES
from retrieval.ml_library import get_library

async def main():
    lib = get_library()
    groups = collections.defaultdict(list)
    for e in lib.entries:
        groups[e.skill_title].append(e)
    parallel = {t: v for t, v in groups.items()
                if len(v) > 1 and all(len(e.grade_levels) == 1 for e in v)}
    sem = asyncio.Semaphore(8)

    async def probe(title, grade, ids):
        async with sem:
            emb = await embed_query(f"Give me the '{title}' mini-lesson for grade {grade}.")
        cur = [m for m in lib.find_matches(emb, user_grade=grade, top_k=TOP_K_CANDIDATES)
               if m.grade_compatible]
        new = lib.find_best_in_grade(emb, user_grade=grade, top_k=TOP_K_CANDIDATES)
        def stat(pool):
            hit = bool(pool) and pool[0].entry.ml_id in ids
            sep = (pool[0].confidence - pool[1].confidence) if len(pool) > 1 else None
            return hit, len(pool), sep
        return (title, grade) + stat(cur) + stat(new)

    tasks = []
    for title, entries in parallel.items():
        by_grade = collections.defaultdict(list)
        for e in entries:
            by_grade[e.grade_levels[0]].append(e.ml_id)
        for grade, ids in by_grade.items():
            tasks.append(probe(title, grade, set(ids)))
    rows = await asyncio.gather(*tasks)

    print(f"{'title':34s} {'g':3s} | CURRENT hit pool sep      | FILTER-FIRST hit pool sep")
    print("-" * 96)
    for t, g, h1, n1, s1, h2, n2, s2 in sorted(rows):
        f1 = f"{s1:.4f}" if s1 is not None else " n/a  "
        f2 = f"{s2:.4f}" if s2 is not None else " n/a  "
        print(f"{t[:33]:34s} {g:3s} | {str(h1):5s} {n1:4d} {f1:8s} | {str(h2):5s} {n2:4d} {f2:8s}")

    def summarize(label, hits, pools, seps):
        n = len(hits)
        und = sum(1 for s in seps if s is None)
        print(f"\n{label}")
        print(f"  correct entry ranked #1 in pool : {sum(hits)}/{n}")
        print(f"  separation UNDEFINED            : {und}/{n}")
        print(f"  median in-grade pool size       : {sorted(pools)[len(pools)//2]}")
        real = [s for s in seps if s is not None]
        if real:
            print(f"  median separation               : {sorted(real)[len(real)//2]:.4f}")

    summarize("CURRENT (truncate-then-filter)", [r[2] for r in rows], [r[3] for r in rows], [r[4] for r in rows])
    summarize("FILTER-FIRST (find_best_in_grade)", [r[5] for r in rows], [r[6] for r in rows], [r[7] for r in rows])

asyncio.run(main())
