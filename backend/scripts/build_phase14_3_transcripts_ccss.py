"""Build Phase 14.3 chunks — workshop transcripts + Common Core Standards.

Produces three chunk files:
  * chunks/40-inform-transcript.json      — one chunk per section of
    "Inform 2.5h transcript.docx" (29 sections)
  * chunks/41-pers-transcript.json        — one chunk per section of
    "Pers 2.5h transcript.docx"  (16 sections)
  * chunks/42-ccss-writing-standards.json — one chunk per page of
    "Common Core State Standards-- K-12 writing.pdf" (11 pages)

No library promotion, no HyDEs — these are coaching-narrative and
standards-reference content. Transcripts surface on broad coaching queries
("how do I teach the research report?"); CCSS chunks surface on
grade-and-standard queries ("what's the grade 5 writing standard?").

Usage:
    python3 scripts/build_phase14_3_transcripts_ccss.py            # write
    python3 scripts/build_phase14_3_transcripts_ccss.py --dry-run  # inspect
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import fitz
import docx as docxmod

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_DIR = ROOT / "chunks"
SHARED = Path("/home/mudassir/work/shafi/smekensrar/braddy-feedback-16april/shared-drive/Tier 1 Content")

INFORM_PDF = "Inform 2.5h transcript.docx"
PERS_PDF = "Pers 2.5h transcript.docx"
CCSS_PDF = "Common Core State Standards-- K-12 writing.pdf"

_WORD_RE = re.compile(r"[a-zA-Z0-9]+")
_SECTION_RE = re.compile(r"^Section\s+(\d+):?\s*(.*)", re.I)


def slugify(text: str, max_len: int = 80) -> str:
    s = "-".join(_WORD_RE.findall(text.lower()))
    return s[:max_len].rstrip("-")


def topic_keywords(content: str, title: str, top_k: int = 20) -> list[str]:
    stop = {
        "the","and","a","an","of","to","for","in","on","at","is","it","this","that",
        "with","as","by","or","be","are","was","were","you","your","we","our","i",
        "their","these","those","not","no","yes","but","so","do","does","did",
        "about","into","out","up","down","will","can","could","should","would",
        "what","how","why","when","where","all","any","some","more","most","like",
        "one","two","three","from","have","has","had","also","after","before",
        "over","under","just","than","there","here","too","only","own","very",
        "each","now","students","write","writing","writer","writers","lesson",
        "grade","skill","skills","say","said","turn","talk","today","yesterday",
    }
    seen: dict[str, int] = {}
    for tok in (title + " " + content).lower().split():
        for w in _WORD_RE.findall(tok):
            if len(w) < 4 or w in stop:
                continue
            seen.setdefault(w, len(seen))
            if len(seen) >= top_k:
                break
        if len(seen) >= top_k:
            break
    return [w for w, _ in sorted(seen.items(), key=lambda kv: kv[1])]


# ---------------------------------------------------------------------------
# Transcript extraction
# ---------------------------------------------------------------------------


def extract_transcript_sections(path: Path) -> tuple[str, list[tuple[int, str, str]]]:
    """Return (doc_title, [(section_num, section_title, section_body)])."""
    d = docxmod.Document(str(path))
    paras = [p.text for p in d.paragraphs]
    # Doc title = first non-empty paragraph
    doc_title = next((p for p in paras if p.strip()), path.stem)

    # Find section boundaries
    sections: list[tuple[int, int, str]] = []  # (para_idx, num, title)
    for i, p in enumerate(paras):
        m = _SECTION_RE.match(p.strip())
        if m:
            sections.append((i, int(m.group(1)), m.group(2).strip().rstrip(".")))

    # Extract body: text between this header and the next
    result: list[tuple[int, str, str]] = []
    for i, (start_idx, num, title) in enumerate(sections):
        end_idx = sections[i + 1][0] if i + 1 < len(sections) else len(paras)
        body_paras = [p for p in paras[start_idx + 1:end_idx] if p.strip()]
        body = "\n\n".join(body_paras).strip()
        result.append((num, title, body))
    return doc_title, result


def build_transcript_chunk(doc_title: str, source_doc: str, writing_mode: str,
                           num: int, title: str, body: str,
                           slug_prefix: str) -> dict:
    full_content = f"{doc_title} — Section {num}: {title}\n\n{body}"
    slug = f"{slug_prefix}-section-{num:02d}-{slugify(title)}"
    # pie_tags_by_band: all bands tagged with the relevant mode
    mode_letter = {"Inform": "I", "Persuade": "P", "Entertain": "E"}.get(writing_mode, "I")
    pie = {b: [mode_letter] for b in ("K-2", "3-5", "6-8", "9-12")}
    return {
        "chunk_id": slug,
        "source_document": source_doc,
        "tier": 1,
        "content_type": "training_transcript",
        "source_category": "workshop_transcript",
        "copilot_mode": "coaching",
        "step": "overview",
        "grade_level": "K-12",
        "writing_trait": "all",
        "writing_mode": writing_mode,
        "strategy_name": None,
        "is_scripted_example": False,
        "audience": "K-12",
        "page_number": None,
        "section_name": f"Section {num}: {title}",
        "day_number": None,
        "mini_lesson_number": None,
        "episode_number": None,
        "chunk_index": num,
        "content": full_content,
        "book_name": None,
        "chapter_number": None,
        "ml_number": None,
        "skill_title": title,
        "is_scripted_lesson": False,
        "priority_rank": 4,  # supplementary narrative
        "topic_keywords": topic_keywords(body, title),
        "book_reference": f"Smekens {doc_title}, Section {num}: {title}",
        "pie_tags_by_band": pie,
        "lesson_trigger": [],
    }


# ---------------------------------------------------------------------------
# CCSS extraction (per page)
# ---------------------------------------------------------------------------

# Narrowest VALID_GRADE_LEVELS band spanning a set of detected bands.
# Prevents the F67-data bug: "-".join(["K-2","3-5",...]) -> invalid "K-2-3-5-...".
_BAND_LO = {"K-2": 0, "3-5": 3, "6-8": 6, "9-12": 9, "K-12": 0}
_BAND_HI = {"K-2": 2, "3-5": 5, "6-8": 8, "9-12": 12, "K-12": 12}
# (lo, hi) -> valid band, in ascending-narrowness order per lo.
_VALID_SPANS = [
    (0, 2, "K-2"), (0, 5, "K-5"), (0, 12, "K-12"),
    (3, 5, "3-5"), (3, 12, "3-12"),
    (6, 8, "6-8"), (6, 12, "6-12"),
    (9, 12, "9-12"),
]


def _collapse_bands_to_valid(bands: list[str]) -> str:
    if len(bands) == 1:
        return bands[0]
    lo = min(_BAND_LO[b] for b in bands)
    hi = max(_BAND_HI[b] for b in bands)
    for slo, shi, name in _VALID_SPANS:
        if slo <= lo and hi <= shi:
            return name
    return "K-12"  # widest fallback (always valid)


def _page_grade_metadata(page_text: str) -> tuple[str, dict]:
    """Infer grade_level + pie_tags_by_band from the dominant grades on a page."""
    has_k12 = "Anchor Standards" in page_text
    has_k2 = any(m in page_text for m in ("Kindergartners:", "Grade 1 students:", "Grade 2 students:"))
    has_3to5 = any(f"Grade {g} students:" in page_text for g in (3, 4, 5))
    has_6to8 = any(f"Grade {g} students:" in page_text for g in (6, 7, 8))
    has_9plus = "Grades 9–10 students:" in page_text or "Grades 11–12 students:" in page_text

    bands = []
    if has_k2:
        bands.append("K-2")
    if has_3to5:
        bands.append("3-5")
    if has_6to8:
        bands.append("6-8")
    if has_9plus:
        bands.append("9-12")
    if has_k12 and not bands:
        bands = ["K-2", "3-5", "6-8", "9-12"]
    if not bands:
        bands = ["K-12"]

    grade_level = _collapse_bands_to_valid(bands)
    # CCSS chunks cover all three modes (W.1 opinion, W.2 informative, W.3 narrative)
    pie = {b: ["P", "I", "E"] for b in bands if b in ("K-2", "3-5", "6-8", "9-12")}
    return grade_level, pie


def build_ccss_chunks() -> list[dict]:
    p = SHARED / CCSS_PDF
    doc = fitz.open(p)
    out = []
    for page_num in range(len(doc)):
        page = doc[page_num]
        text = page.get_text("text", sort=True).strip()
        grade_level, pie = _page_grade_metadata(text)

        # Title: try to extract from first meaningful line
        first_lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:5]
        # Prefer a line that says "Writing Standards" or "Anchor Standards"
        title = next(
            (ln for ln in first_lines if "Writing Standards" in ln or "Anchor Standards" in ln),
            f"CCSS page {page_num + 1}",
        )

        slug = f"ccss-page-{page_num + 1:02d}-{slugify(title)[:50]}"
        content = f"Common Core State Standards — ELA Writing (page {page_num + 1})\n{title}\n\n{text}"

        out.append({
            "chunk_id": slug,
            "source_document": CCSS_PDF,
            "tier": 1,
            "content_type": "standards_alignment",
            "source_category": "standards",
            "copilot_mode": "both",
            "step": "overview",
            "grade_level": grade_level,
            "writing_trait": "all",
            "writing_mode": "all",
            "strategy_name": None,
            "is_scripted_example": False,
            "audience": "K-12",
            "page_number": page_num + 1,
            "section_name": title,
            "day_number": None,
            "mini_lesson_number": None,
            "episode_number": None,
            "chunk_index": page_num,
            "content": content,
            "book_name": None,
            "chapter_number": None,
            "ml_number": None,
            "skill_title": title,
            "is_scripted_lesson": False,
            "priority_rank": 3,
            "topic_keywords": topic_keywords(text, title),
            "book_reference": f"Common Core State Standards for ELA Writing, page {page_num + 1}",
            "pie_tags_by_band": pie,
            "lesson_trigger": [],
        })
    doc.close()
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _existing_chunk_ids() -> set[str]:
    seen: set[str] = set()
    for p in CHUNKS_DIR.glob("*.json"):
        try:
            for c in json.loads(p.read_text()):
                if isinstance(c, dict) and "chunk_id" in c:
                    seen.add(c["chunk_id"])
        except (json.JSONDecodeError, OSError):
            pass
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    existing = _existing_chunk_ids()

    # Inform transcript
    inform_doc, inform_sections = extract_transcript_sections(SHARED / INFORM_PDF)
    inform_chunks = []
    for num, title, body in inform_sections:
        chunk = build_transcript_chunk(inform_doc, INFORM_PDF, "Inform", num, title, body, "inform-transcript")
        if chunk["chunk_id"] in existing:
            continue
        inform_chunks.append(chunk)

    # Pers transcript
    pers_doc, pers_sections = extract_transcript_sections(SHARED / PERS_PDF)
    pers_chunks = []
    for num, title, body in pers_sections:
        chunk = build_transcript_chunk(pers_doc, PERS_PDF, "Persuade", num, title, body, "pers-transcript")
        if chunk["chunk_id"] in existing:
            continue
        pers_chunks.append(chunk)

    # CCSS
    ccss_chunks_all = build_ccss_chunks()
    ccss_chunks = [c for c in ccss_chunks_all if c["chunk_id"] not in existing]

    print(f"Inform transcript: {len(inform_chunks)} chunks (avg {sum(len(c['content']) for c in inform_chunks)//max(1,len(inform_chunks))} chars)")
    print(f"Pers transcript:   {len(pers_chunks)} chunks (avg {sum(len(c['content']) for c in pers_chunks)//max(1,len(pers_chunks))} chars)")
    print(f"CCSS:              {len(ccss_chunks)} chunks (avg {sum(len(c['content']) for c in ccss_chunks)//max(1,len(ccss_chunks))} chars)")
    print(f"TOTAL: {len(inform_chunks) + len(pers_chunks) + len(ccss_chunks)} new chunks")

    if args.dry_run:
        print("\n[dry-run: no files written]")
        return 0

    if inform_chunks:
        p = CHUNKS_DIR / "40-inform-transcript.json"
        p.write_text(json.dumps(inform_chunks, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {p}")
    if pers_chunks:
        p = CHUNKS_DIR / "41-pers-transcript.json"
        p.write_text(json.dumps(pers_chunks, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {p}")
    if ccss_chunks:
        p = CHUNKS_DIR / "42-ccss-writing-standards.json"
        p.write_text(json.dumps(ccss_chunks, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {p}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
