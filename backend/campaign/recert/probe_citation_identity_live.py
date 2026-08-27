"""BEFORE picture for citation defect (c): does the page we cite belong to the
lesson we actually taught?

WHAT THIS MEASURES (read before citing it): the LIVE API — real retrieval, real
generation, the real delivered payload. Deliberately NOT the offline selector:
probe_citation_identity.py already covers that and is the BEFORE picture for the
*selector*. This one exists because (c) is about the gap between the cited page
and the GENERATED lesson, which only a driven turn can show.

Drive automatically; READ BY HAND. Do NOT add an automatic verdict: N1 forces
"details" where the PIE list says "reasons", so a similarity-argmax judge
manufactures false mismatches (logs.md, 2026-07-17 AM).

------------------------------------------------------------------------------
CORRECTIONS TO THE TASK BRIEF'S DRAFT (each verified against the code, not the
record — the brief is requirements, not scripture):

1. ENDPOINT is `/api/chat`, not `/chat`. `routes_v4.py:56` — `APIRouter(prefix="/api")`.
   The draft would have 404'd on every turn.

2. THE DRAFT READ ONLY ONE OF THE TWO DELIVERY SHAPES. It took the citation from
   `response["book_citation"]` only. That field exists ONLY on the SCRIPTED_ML
   (structured) path (`scripted_ml.py:677-678`). `select_citation_source` has
   THREE production callers (spec §2 fact 4): SCRIPTED_ML (structured field),
   HOW_TO_TEACH (`how_to_teach.py:197-221`) and COACHING (`coaching.py:270-294`)
   — the latter two deliver the citation as a TEXT FOOTER inside the response
   STRING, where `.get()` on a str-typed body silently yields nothing.
   `routes_v4.py:211` picks the shape: structured dict, else text.
   Two of the brief's six cases (paragraphing g3 -> HOW_TO_TEACH; and any case
   that routes to COACHING) would have been recorded as UNCITED while citing
   perfectly well — manufacturing a false presence rate on the exact number the
   plan is judged against. We parse BOTH shapes.

3. `top_chunk_page` CANNOT come from the envelope. `SourceInfo`
   (`api/models.py`) carries chunk_id / source_document / content_type /
   relevance_score / source_tier and NO page — the phantom-page finding
   (`839a051`): 0 of 9,942 sources ever had one. We resolve the page OFFLINE
   from `data/scripted_ml_library.json` (`source_chunk_id` -> `page_number`,
   214/214 populated) so the field is real rather than a silent None.

4. We record `intent` and `response_kind` per turn. Without them a hand-reader
   cannot tell which producer built the citation, and (c) is producer-specific
   (spec §2 fact 8 puts it on SCRIPTED_ML).

5. EVERY REQUEST CARRIES ITS OWN `user_id`. Found the expensive way on the
   BEFORE drive: `config.py:85` sets `rate_limit_per_hour: int = 50` and
   `routes_v4.py:86` buckets an absent `user_id` to the SHARED literal
   "anonymous". This probe issues exactly 6*5 + 2*5*2 = 50 requests, so it sat
   ON the ceiling and the 50th+ turn died with a 429 — silently costing a
   deepen pair. A rate the harness truncated is not a rate. Per-request
   user_ids keep each turn in its own bucket, so the AFTER drive stays
   comparable to this one instead of losing whichever turns happen to land
   last.
------------------------------------------------------------------------------
"""
import asyncio
import json
import os
import re
import uuid

import httpx

API = os.environ.get("PROBE_API", "http://127.0.0.1:8000")
_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(_HERE, "..", "..", "data", "scripted_ml_library.json")

CASES = [
    ("topic-sentences g3", "Give me a 3rd grade lesson on topic sentences", "3"),
    ("paragraphing g3", "How do I teach paragraph writing to 3rd graders?", "3"),
    ("strong-leads g5", "Give me a 5th grade lesson on strong leads", "5"),
    ("sensory-details g4", "Give me a 4th grade lesson on adding sensory details", "4"),
    ("supporting-details g3", "Give me a 3rd grade lesson on supporting details", "3"),
    ("conclusions g5", "Give me a 5th grade lesson on writing conclusions", "5"),
]
RUNS = 5

# Defect (b): the SAME lesson's page drifts across a deepen (recorded p.63->p.76).
# DEEPEN_PRIOR delegates to handle_scripted_ml (_finalize_ml_delivery's docstring:
# "which also covers DEEPEN_PRIOR"), so (b) runs through the very path this plan
# fixes — the spec filed it under plan (2) on the assumption it did not.
# Turn 2 must stay on the SAME lesson, so its page must not move.
DEEPEN_CASES = [
    ("deepen topic-sentences g3",
     "Give me a 3rd grade lesson on topic sentences",
     "Can you go deeper on that same lesson?", "3"),
    ("deepen strong-leads g5",
     "Give me a 5th grade lesson on strong leads",
     "Go deeper on that same one.", "5"),
]

# The ONE Fm5 template (`handlers/citation.py:20-23`):
#   "If you have the '<book>' book, you'll find this lesson on p.<N>."
# Tolerant on quote style: the deterministic builder emits straight quotes, but
# the text path runs through markdown scrubbers/handlers, so do not assume.
_CITE_RE = re.compile(
    r"If you have the ['‘’\"]?(?P<book>[^'‘’\"]+?)['‘’\"]?\s+book,\s*"
    r"you['’]ll find this lesson on p\.\s*(?P<page>\d+)",
    re.IGNORECASE,
)
# Anything page-shaped that is NOT our template — e.g. an LLM-leaked
# "(Launching the Writers Workshop 3-12, page 64)" parenthetical. Recorded so a
# hand-reader can see a citation the template regex would miss.
_OTHER_PAGE_RE = re.compile(r"(?:p\.|page[s]?\s+)(\d+)", re.IGNORECASE)


def _load_chunk_pages():
    """source_chunk_id -> (book_reference, page_number) from the ML library.

    The envelope's sources carry no page (correction 3), so the only honest way
    to report what the TOP retrieved chunk's page was is to resolve it here.
    """
    try:
        with open(_LIB) as f:
            entries = json.load(f)["entries"]
    except (OSError, KeyError, json.JSONDecodeError):
        return {}
    return {
        e["source_chunk_id"]: (e.get("book_reference"), e.get("page_number"))
        for e in entries
        if e.get("source_chunk_id")
    }


_CHUNK_PAGES = _load_chunk_pages()


def _extract_citation(body):
    """Return (cited_book, cited_page, citation_sentence) across BOTH delivery
    shapes (correction 2). `response` is a MiniLesson dict on the structured
    path and a markdown string on every text path."""
    resp = body.get("response")
    if isinstance(resp, dict):
        sentence = resp.get("book_citation") or ""
    elif isinstance(resp, str):
        sentence = resp
    else:
        sentence = ""
    m = _CITE_RE.search(sentence or "")
    if not m:
        return None, None, None
    return m.group("book").strip(), int(m.group("page")), m.group(0)


def _teacher_text(body):
    """What the teacher actually sees, as text — for hand-reading."""
    resp = body.get("response")
    if isinstance(resp, dict):
        return "\n\n".join(
            f"{k}: {v}" for k, v in resp.items() if isinstance(v, str)
        )
    return resp if isinstance(resp, str) else ""


def _record(body, label, run, query, grade):
    resp = body.get("response")
    structured = resp if isinstance(resp, dict) else {}
    cited_book, cited_page, sentence = _extract_citation(body)
    sources = body.get("sources") or []
    top = sources[0] if sources else {}
    top_id = top.get("chunk_id")
    top_book, top_page = _CHUNK_PAGES.get(top_id, (None, None))
    text = _teacher_text(body)
    other = sorted({int(p) for p in _OTHER_PAGE_RE.findall(text)})
    return {
        "label": label,
        "run": run,
        "query": query,
        "grade": grade,
        "intent": body.get("intent"),
        "response_kind": "structured" if isinstance(resp, dict) else "text",
        "quality": body.get("quality"),
        "skill_focus": structured.get("skill_focus"),
        "grade_level": structured.get("grade_level"),
        # writing_mode is LOAD-BEARING for reading (c) by hand, and easy to
        # miss: the Teal book indexes the SAME skill by mode on ADJACENT pages
        # — p.90 persuasive intros / p.92 informative intros / p.94 narrative
        # intros (p.91/93/95 the conclusions). So "is the cited page this
        # lesson?" cannot be answered from the skill alone; a strong-leads
        # lesson taught in INFORM mode belongs to p.92, and p.94 is a mis-cite
        # that looks correct in every title-level check.
        "writing_mode": structured.get("writing_mode"),
        "cited_book": cited_book,
        "cited_page": cited_page,
        "citation_sentence": sentence,
        "citation_present": cited_page is not None,
        "top_chunk_id": top_id,
        "top_chunk_doc": top.get("source_document"),
        "top_chunk_book": top_book,
        "top_chunk_page": top_page,
        "other_page_mentions": other,
        "step_2a_tell": (structured.get("step_2a_tell") or "")[:600],
        "text_excerpt": text[:900] if not structured else "",
        "sources": [
            {
                "chunk_id": s.get("chunk_id"),
                "source_document": s.get("source_document"),
                "page": _CHUNK_PAGES.get(s.get("chunk_id"), (None, None))[1],
            }
            for s in sources[:6]
        ],
    }


async def _post(client, message, session_id, user_id=None):
    # user_id: correction 5 — never let turns share the "anonymous" rate-limit
    # bucket. A 429 mid-drive silently truncates the very rate we are measuring.
    r = await client.post(
        f"{API}/api/chat",
        json={
            "message": message,
            "session_id": session_id,
            "user_id": user_id or f"probe-{uuid.uuid4()}",
        },
        timeout=180,
    )
    r.raise_for_status()
    return r.json()


async def one(client, label, query, grade, i):
    body = await _post(client, query, f"probe-{label}-{i}")
    return _record(body, label, i, query, grade)


async def deepen(client, label, q1, q2, grade, i):
    """(b): drive turn 1, then a deepen on the SAME session, and record BOTH
    pages. Only the PAIR exposes the drift — a single turn cannot.

    Both turns share ONE user_id — a real teacher deepening their own lesson.
    (The store keys on session_id alone, so this is realism, not a
    requirement; the rate-limit bucket is what makes it matter.)
    """
    sid = f"probe-{label}-{i}"
    uid = f"probe-user-{label}-{i}".replace(" ", "-")
    b1 = await _post(client, q1, sid, user_id=uid)
    b2 = await _post(client, q2, sid, user_id=uid)
    r1 = _record(b1, label, i, q1, grade)
    r2 = _record(b2, label, i, q2, grade)
    return {
        "label": label,
        "run": i,
        "grade": grade,
        "multi_turn": True,
        "turn1_skill_focus": r1["skill_focus"],
        "turn1_intent": r1["intent"],
        "turn1_cited_book": r1["cited_book"],
        "turn1_cited_page": r1["cited_page"],
        "turn2_skill_focus": r2["skill_focus"],
        "turn2_intent": r2["intent"],
        "turn2_cited_book": r2["cited_book"],
        "turn2_cited_page": r2["cited_page"],
        # A drift is only a DEFECT if turn 2 is still the same lesson — read the
        # skill_focus pair by hand before counting it (brief Step 4).
        "drifted": (r1["cited_book"], r1["cited_page"]) != (r2["cited_book"], r2["cited_page"]),
        "turn1": r1,
        "turn2": r2,
    }


async def main():
    out = []
    async with httpx.AsyncClient() as client:
        for label, query, grade in CASES:
            for i in range(RUNS):
                try:
                    out.append(await one(client, label, query, grade, i))
                except Exception as e:  # noqa: BLE001
                    out.append({"label": label, "run": i, "error": repr(e)})
        for label, q1, q2, grade in DEEPEN_CASES:
            for i in range(RUNS):
                try:
                    out.append(await deepen(client, label, q1, q2, grade, i))
                except Exception as e:  # noqa: BLE001
                    out.append({"label": label, "run": i, "multi_turn": True, "error": repr(e)})
    path = os.path.join(_HERE, "citation_before.json")
    with open(path, "w") as f:
        json.dump(out, f, indent=2)

    singles = [r for r in out if not r.get("multi_turn")]
    pairs = [r for r in out if r.get("multi_turn")]
    errors = [r for r in out if r.get("error")]
    cited = sum(1 for r in singles if r.get("citation_present"))
    print(f"{len(singles)} single turns | citation PRESENT on {cited}/{len(singles)}")
    print(f"{len(pairs)} deepen pairs | raw page-moved on "
          f"{sum(1 for r in pairs if r.get('drifted'))}/{len(pairs)} "
          f"(NOT the defect rate — read skill_focus by hand)")
    if errors:
        print(f"!! {len(errors)} ERRORS — a sub-second failure measures NOTHING; "
              f"check the backend is up before recording anything")
    print(f"wrote {path}")
    print("NOW READ IT BY HAND: for each turn, does cited_page belong to the "
          "lesson step_2a_tell/text_excerpt actually teaches, IN THE CITED BOOK "
          "(pages collide across books)? Record the rate in the spec.")


asyncio.run(main())
