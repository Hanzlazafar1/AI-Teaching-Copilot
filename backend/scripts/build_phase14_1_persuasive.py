"""Build Phase 14.1 chunks + library entries for grade-level persuasive MLs.

Reads hand-authored ML data from `scripts/phase14_data/persuasive_mls_*.py`
and emits:
  * `chunks/NN-persuasive-<grade>.json` — one chunk per ML, whole-ML shape
  * appends new entries to `data/scripted_ml_library.json` (preserving the
    existing 183 entries)

Run in --dry-run mode first to inspect output without touching disk.

Usage:
    python3 scripts/build_phase14_1_persuasive.py            # write
    python3 scripts/build_phase14_1_persuasive.py --dry-run  # inspect only
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_DIR = ROOT / "chunks"
LIBRARY_PATH = ROOT / "data" / "scripted_ml_library.json"

sys.path.insert(0, str(ROOT / "scripts"))
from phase14_data.persuasive_mls_K import ALL_K_MLS  # noqa: E402
from phase14_data.persuasive_mls_Gr1 import ALL_GR1_MLS  # noqa: E402
from phase14_data.persuasive_mls_Gr2 import ALL_GR2_MLS  # noqa: E402
from phase14_data.persuasive_mls_Gr3 import ALL_GR3_MLS  # noqa: E402
from phase14_data.persuasive_mls_Gr4 import ALL_GR4_MLS  # noqa: E402
from phase14_data.persuasive_mls_Gr5 import ALL_GR5_MLS  # noqa: E402


ALL_MLS: list[dict[str, Any]] = (
    ALL_K_MLS + ALL_GR1_MLS + ALL_GR2_MLS + ALL_GR3_MLS + ALL_GR4_MLS + ALL_GR5_MLS
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


def slugify(text: str) -> str:
    """Lowercase-hyphenated slug from a human skill title."""
    return "-".join(_WORD_RE.findall(text.lower()))


def grade_band(grade: str) -> str:
    """Map single grade to its PIE band."""
    if grade == "K" or grade in {"1", "2"}:
        return "K-2"
    if grade in {"3", "4", "5"}:
        return "3-5"
    if grade in {"6", "7", "8"}:
        return "6-8"
    return "9-12"


def topic_keywords(content: str, skill_title: str, top_k: int = 20) -> list[str]:
    """Extract a small set of keyword-ish tokens. Mirrors the existing
    chunker's shape — lowercase, stopwords removed, dedup preserving order."""
    stop = {
        "the","and","a","an","of","to","for","in","on","at","is","it","this","that",
        "with","as","by","or","be","are","was","were","you","your","we","our","i",
        "me","my","he","she","his","her","they","them","their","if","then","else",
        "not","no","yes","but","so","do","does","did","about","into","out","up","down",
        "will","can","could","should","would","what","how","why","when","where","which",
        "all","any","some","more","most","like","one","two","three","from","have","has",
        "had","also","after","before","over","under","just","than","there","here","too",
        "only","own","very","each","now","next","today","yesterday","back","time","step",
        "students","write","writing","writer","writers","lesson","say","said","turn","talk",
    }
    seen: dict[str, int] = {}
    # Prioritize skill_title tokens first (high signal).
    for tok in (skill_title + " " + content).lower().split():
        clean = _WORD_RE.findall(tok)
        for w in clean:
            if len(w) < 4 or w in stop:
                continue
            seen.setdefault(w, len(seen))
            if len(seen) >= top_k:
                break
        if len(seen) >= top_k:
            break
    return [w for w, _ in sorted(seen.items(), key=lambda kv: kv[1])]


# ---------------------------------------------------------------------------
# Chunk + library-entry construction
# ---------------------------------------------------------------------------


def build_chunk(ml: dict[str, Any]) -> dict[str, Any]:
    """Construct a whole-ML chunk dict from hand-authored ML data."""
    day = ml.get("day_number")
    day_slug = f"-day{day}" if day else ""
    chunk_id = f"persuasive-{ml['grade']}-ml{ml['ml_number']}{day_slug}-{slugify(ml['skill_title'])}"
    band = grade_band(ml["grade"])
    audience = "ELEM" if ml["grade"] in {"K", "1", "2", "3", "4", "5"} else "SEC"

    content = ml["content"].strip()

    return {
        "chunk_id": chunk_id,
        "source_document": ml["source_pdf"],
        "tier": 1,
        "content_type": "lesson_script",
        "source_category": "ml_library",
        "copilot_mode": "both",
        "step": "overview",
        "grade_level": ml["grade"],
        "writing_trait": ml["writing_trait"],
        "writing_mode": "Persuade",
        "strategy_name": slugify(ml["skill_title"]),
        "is_scripted_example": False,
        "audience": audience,
        "page_number": ml["source_page"],
        "section_name": f"Smekens Persuasive Grade {ml['grade']} — SKILL #{ml['ml_number']}"
                        + (f" (Day {day})" if day else ""),
        "day_number": day,
        "mini_lesson_number": ml["ml_number"],
        "episode_number": None,
        "chunk_index": 0,  # one chunk per ML = index 0 within the file section
        "content": content,
        "book_name": None,  # standalone Smekens PDF, not a Launch book
        "chapter_number": None,
        "ml_number": ml["ml_number"],
        "skill_title": ml["skill_title"],
        "is_scripted_lesson": True,
        "priority_rank": 1,
        "topic_keywords": topic_keywords(content, ml["skill_title"]),
        "book_reference": f"Smekens Persuasive Grade {ml['grade']}, SKILL #{ml['ml_number']}"
                          + (f" (Day {day})" if day else "") + " (© 2017)",
        "pie_tags_by_band": {band: ["P"]},
        "lesson_trigger": ml["lesson_triggers"],
    }


def build_library_entry(chunk: dict[str, Any], ml: dict[str, Any]) -> dict[str, Any]:
    """Construct a library entry that mirrors the existing schema 1:1."""
    ml_id = f"lib-{chunk['chunk_id']}"
    band = grade_band(ml["grade"])
    return {
        "ml_id": ml_id,
        "skill_title": ml["skill_title"],
        "hyde_summaries": list(ml["hyde_summaries"]),
        "grade_levels": [ml["grade"]],
        "writing_modes": ["Persuade"],
        "pie_tags": ["P"],
        "pie_tags_by_band": {band: ["P"]},
        "lesson_triggers": list(ml["lesson_triggers"]),
        "book_reference": chunk["book_reference"],
        "page_number": chunk["page_number"],
        "source_document": chunk["source_document"],
        "source_chunk_id": chunk["chunk_id"],
        "complete_ml_text": chunk["content"],
        "priority_tier": 1,
    }


# ---------------------------------------------------------------------------
# Output files
# ---------------------------------------------------------------------------


def grade_file_suffix(grade: str) -> str:
    return f"K" if grade == "K" else f"gr{grade}"


def chunks_filename(grade: str, next_index: int) -> str:
    return f"{next_index:02d}-persuasive-{grade_file_suffix(grade)}.json"


def next_chunk_file_index() -> int:
    existing = sorted(int(p.stem.split("-", 1)[0]) for p in CHUNKS_DIR.glob("[0-9][0-9]-*.json"))
    return (existing[-1] + 1) if existing else 1


def group_by_grade(entries: list[tuple[dict, dict]]) -> dict[str, list[tuple[dict, dict]]]:
    by_grade: dict[str, list[tuple[dict, dict]]] = {}
    for chunk, lib in entries:
        by_grade.setdefault(chunk["grade_level"], []).append((chunk, lib))
    return by_grade


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _load_existing_library_ids() -> set[str]:
    data = json.loads(LIBRARY_PATH.read_text())
    return {e["ml_id"] for e in data["entries"]}


def _load_existing_chunk_ids() -> set[str]:
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
    ap.add_argument("--dry-run", action="store_true", help="Print plan, write nothing")
    args = ap.parse_args()

    # Idempotency: skip MLs whose chunks or library entries already exist
    existing_chunk_ids = _load_existing_chunk_ids()
    existing_lib_ids = _load_existing_library_ids()

    built: list[tuple[dict, dict]] = []
    skipped: list[str] = []
    seen_chunk_ids: set[str] = set()
    seen_ml_ids: set[str] = set()
    for ml in ALL_MLS:
        chunk = build_chunk(ml)
        if chunk["chunk_id"] in existing_chunk_ids or chunk["chunk_id"] in seen_chunk_ids:
            skipped.append(chunk["chunk_id"])
            continue
        seen_chunk_ids.add(chunk["chunk_id"])
        lib = build_library_entry(chunk, ml)
        if lib["ml_id"] in existing_lib_ids or lib["ml_id"] in seen_ml_ids:
            skipped.append(lib["ml_id"])
            continue
        seen_ml_ids.add(lib["ml_id"])
        built.append((chunk, lib))

    if skipped:
        print(f"[skipped {len(skipped)} already-present entries: "
              f"{', '.join(skipped[:3])}{'…' if len(skipped) > 3 else ''}]")

    if not built:
        print("Nothing new to build.")
        return 0

    by_grade = group_by_grade(built)
    next_idx = next_chunk_file_index()

    print(f"Built {len(built)} new MLs across {len(by_grade)} grade(s).")
    for grade, entries in sorted(by_grade.items()):
        fname = chunks_filename(grade, next_idx)
        print(f"  grade={grade!r}: {len(entries)} chunk(s) → {fname}")
        for chunk, lib in entries:
            print(f"    - {chunk['chunk_id']}  ({len(chunk['content']):,} chars content, "
                  f"{len(lib['hyde_summaries'])} HyDEs)")
        next_idx += 1

    if args.dry_run:
        print("\n[dry-run: no files written]")
        return 0

    # Write per-grade chunk files (new file per grade — never overwrite existing)
    next_idx = next_chunk_file_index()
    for grade, entries in sorted(by_grade.items()):
        fname = chunks_filename(grade, next_idx)
        out_path = CHUNKS_DIR / fname
        chunks = [c for c, _ in entries]
        out_path.write_text(json.dumps(chunks, indent=2, ensure_ascii=False) + "\n")
        print(f"  wrote {out_path}")
        next_idx += 1

    # Append new entries to library
    data = json.loads(LIBRARY_PATH.read_text())
    data["entries"].extend([lib for _, lib in built])
    LIBRARY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"  appended {len(built)} entries → {LIBRARY_PATH} "
          f"(total now {len(data['entries'])})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
