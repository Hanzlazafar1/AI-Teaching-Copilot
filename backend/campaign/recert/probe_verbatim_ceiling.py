"""Is VERBATIM_AUTO's 0.90 threshold reachable AT ALL? (offline, sampled)

Phase-1 evidence for the verbatim cluster. The seam trace (probe_verbatim.py)
showed named-lesson asks scoring 0.73-0.86 — under the 0.90 VERBATIM bar — so
the LLM ad-libs instead of pulling the book lesson (April non-neg #7).

That was 3 anecdotes. This measures the DISTRIBUTION over a deterministic
sample of the 214-entry library, for the exact scenario Brady describes ("if
the user asks or names a specific lesson... it would pull on the exact lesson
described in the book"):

  A. teacher names the lesson by its EXACT book title  <- Brady's case
  B. the entry's own HyDE, verbatim                    <- theoretical ceiling

If (A) sits far below 0.90 while (B) clears it, the threshold isn't calibrated
against anything a teacher would type, and "cosine of the whole message" is the
wrong signal for "did the teacher NAME this lesson" — a title-match question.

Run:
  cd copilot-v4 && env -u OPENAI_API_KEY -u OPENAI_BASE_URL PYTHONPATH=. \
      python3 -u campaign/recert/probe_verbatim_ceiling.py
"""
import asyncio
import statistics

from retrieval.embedder import embed_query
from retrieval.library_precheck import (
    ASK_USER_CONFIDENCE_THRESHOLD,
    VERBATIM_CONFIDENCE_THRESHOLD,
)
from retrieval.ml_library import get_library

SAMPLE_N = 30
CONCURRENCY = 8


def _concrete_grade(entry) -> str:
    g = str((entry.grade_levels or ["5"])[0])
    if g.upper().startswith("K") or g.upper().startswith("PK"):
        return "K"
    return g.split("-")[0]


async def main() -> None:
    library = get_library()
    entries = library.entries
    step = max(1, len(entries) // SAMPLE_N)
    sample = entries[::step][:SAMPLE_N]
    print(f"library entries: {len(entries)}; deterministic sample: {len(sample)}\n",
          flush=True)

    sem = asyncio.Semaphore(CONCURRENCY)

    async def probe(entry):
        grade = _concrete_grade(entry)
        named = f"Give me the '{entry.skill_title}' mini-lesson for grade {grade}."
        hyde = (entry.hyde_summaries or [""])[0]
        async with sem:
            emb_named = await embed_query(named)
            emb_hyde = await embed_query(hyde) if hyde else None
        m_named = library.find_matches(emb_named, user_grade=grade, top_k=1)
        conf_named = m_named[0].confidence if m_named else -1.0
        hit = m_named[0].entry.skill_title if m_named else "(none)"
        conf_hyde = -1.0
        if emb_hyde is not None:
            m_hyde = library.find_matches(emb_hyde, user_grade=grade, top_k=1)
            conf_hyde = m_hyde[0].confidence if m_hyde else -1.0
        return entry.skill_title, conf_named, conf_hyde, hit == entry.skill_title

    rows = await asyncio.gather(*(probe(e) for e in sample))
    for title, conf_named, conf_hyde, correct in rows:
        print(f"  named={conf_named:.4f}  hyde={conf_hyde:.4f}  "
              f"{'HIT ' if correct else 'MISS'} {title!r}", flush=True)

    named_vals = [r[1] for r in rows if r[1] >= 0]
    hyde_vals = [r[2] for r in rows if r[2] >= 0]
    fires = [r for r in rows if r[1] >= VERBATIM_CONFIDENCE_THRESHOLD]
    asks = [r for r in rows
            if ASK_USER_CONFIDENCE_THRESHOLD <= r[1] < VERBATIM_CONFIDENCE_THRESHOLD]

    print("\n" + "=" * 68)
    print(f"A. teacher names the EXACT book title (n={len(named_vals)}):")
    print(f"     max={max(named_vals):.4f}  median={statistics.median(named_vals):.4f}"
          f"  min={min(named_vals):.4f}")
    print(f"B. entry's own HyDE verbatim (ceiling, n={len(hyde_vals)}):")
    print(f"     max={max(hyde_vals):.4f}  median={statistics.median(hyde_vals):.4f}"
          f"  min={min(hyde_vals):.4f}")
    print()
    print(f"VERBATIM_AUTO (>= {VERBATIM_CONFIDENCE_THRESHOLD}) fires on "
          f"{len(fires)}/{len(rows)} exact-title asks")
    print(f"ASK_USER_SINGLE ([{ASK_USER_CONFIDENCE_THRESHOLD:.2f}, "
          f"{VERBATIM_CONFIDENCE_THRESHOLD})) on {len(asks)}/{len(rows)}")
    print(f"correct entry ranked #1 on {sum(1 for r in rows if r[3])}/{len(rows)}")


if __name__ == "__main__":
    asyncio.run(main())
