"""Does SEPARATION discriminate "named lesson" from "browse"? (offline)

Phase-1 evidence, verbatim cluster. Established so far:
  * VERBATIM_AUTO (>= 0.90 raw cosine) fires on 0/30 exact-title asks
    (max 0.87, median 0.77) -> the path is dead; every named ask ad-libs.
  * The RANKING is good (25/30 correct entry at #1), and the HyDEs carry
    Brady's jargon ("pizza table" -> 'Add "leg" sentences per "table-top"
    reason'), which no book TITLE contains. So the embedding mechanism is
    sound; the raw-cosine THRESHOLD on top of it is what's miscalibrated.

Hypothesis under test: a NAMED ask concentrates on one entry (big gap between
#1 and #2), while a BROWSE ask spreads across many (small gap). If so, the
scale-free separation between #1 and #2 discriminates the two cases where an
absolute cosine cannot — and it degrades gracefully as phrasing varies.

Run:
  cd copilot-v4 && env -u OPENAI_API_KEY -u OPENAI_BASE_URL PYTHONPATH=. \
      python3 -u campaign/recert/probe_verbatim_margin.py
"""
import asyncio

from retrieval.embedder import embed_query
from retrieval.ml_library import get_library

# (label, message, grade, should_serve_verbatim)
CASES = [
    # --- NAMED: Brady's rule says pull the exact book lesson ---------------
    ("NAMED pizza-table (Brady's own example)",
     "Is there a pizza table lesson for 5th grade?", "5", True),
    ("NAMED pizza-table K-2",
     "Give me the pizza table lesson for 1st grade.", "1", True),
    ("NAMED snapple (bare)",
     "Give me the Snapple details mini-lesson for 5th grade.", "5", True),
    ("NAMED snapple (natural)",
     "Give me the Smekens scripted mini-lesson on adding interest with "
     "Snapple details for a 5th-grade informative piece.", "5", True),
    ("NAMED snapple (mode pressure)",
     "Give me the 'Snapple details' scripted mini-lesson for my 5th-grade "
     "PERSUASIVE essay.", "5", True),
    ("NAMED show-dont-tell",
     "I want the show don't tell lesson for 4th grade.", "4", True),
    ("NAMED revision bingo",
     "Do you have the Revision BINGO lesson for 5th grade?", "5", True),

    # --- NOT NAMED: browse / generic -> generation is correct -------------
    ("BROWSE persuasive",
     "Give me a persuasive lesson for 5th grade.", "5", False),
    ("BROWSE strong leads",
     "Give me a lesson on strong leads for 3rd grade.", "3", False),
    ("BROWSE organization",
     "How do I teach organization to 4th graders?", "4", False),
    ("BROWSE details generic",
     "I need a lesson about adding details for 5th grade.", "5", False),
]


async def main() -> None:
    library = get_library()
    print(f"library entries: {len(library.entries)}\n", flush=True)
    print(f"{'sep':>7} {'conf1':>7} {'conf2':>7}  {'want':>8}  label / top-1 title")
    print("-" * 100)

    rows = []
    for label, msg, grade, want in CASES:
        emb = await embed_query(msg)
        matches = library.find_matches(emb, user_grade=grade, top_k=5)
        in_grade = [m for m in matches if m.grade_compatible]
        if len(in_grade) < 2:
            print(f"{'--':>7} {'--':>7} {'--':>7}  {str(want):>8}  {label} "
                  f"(<2 in-grade candidates)")
            continue
        c1, c2 = in_grade[0].confidence, in_grade[1].confidence
        sep = c1 - c2
        rows.append((label, sep, c1, want, in_grade[0].entry.skill_title))
        print(f"{sep:7.4f} {c1:7.4f} {c2:7.4f}  {str(want):>8}  {label}\n"
              f"{'':>25}  -> {in_grade[0].entry.skill_title!r}", flush=True)

    named = [r for r in rows if r[3]]
    browse = [r for r in rows if not r[3]]
    print("\n" + "=" * 68)
    if named:
        print(f"NAMED  separation: min={min(r[1] for r in named):.4f}  "
              f"max={max(r[1] for r in named):.4f}")
    if browse:
        print(f"BROWSE separation: min={min(r[1] for r in browse):.4f}  "
              f"max={max(r[1] for r in browse):.4f}")
    if named and browse:
        lo, hi = min(r[1] for r in named), max(r[1] for r in browse)
        print(f"\nSEPARABLE? named-min={lo:.4f} vs browse-max={hi:.4f} -> "
              f"{'YES, disjoint' if lo > hi else 'NO, overlapping'}")


if __name__ == "__main__":
    asyncio.run(main())
