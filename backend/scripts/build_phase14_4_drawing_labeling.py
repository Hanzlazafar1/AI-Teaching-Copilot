"""Build Phase 14.4 chunks + library entries for Drawing/Labeling/Early
Sentences MLs.

Similar shape to scripts/build_phase14_1_persuasive.py but:
  * ML data has per-ML `writing_mode` (Inform for most, "all" for adjective ML)
  * ML data has per-ML `related_ml_id` cross-reference (for titles that
    supplement an existing K-2 library entry)
  * Chunks carry `lesson_trigger = ["early_writer", ...]` (EARLY_WRITER
    marker per user's chosen scheme — no schema change)

Run --dry-run first.

Usage:
    python3 scripts/build_phase14_4_drawing_labeling.py            # write
    python3 scripts/build_phase14_4_drawing_labeling.py --dry-run  # inspect
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
from phase14_data.drawing_labeling_mls import ALL_DRAWING_LABELING_MLS  # noqa: E402


_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


def slugify(text: str) -> str:
    return "-".join(_WORD_RE.findall(text.lower()))


def grade_band(grade: str) -> str:
    if grade in {"PK-1", "K", "1", "2"}:
        return "K-2"
    if grade in {"3", "4", "5"}:
        return "3-5"
    if grade in {"6", "7", "8"}:
        return "6-8"
    return "9-12"


def topic_keywords(content: str, skill_title: str, top_k: int = 20) -> list[str]:
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


def build_chunk(ml: dict[str, Any]) -> dict[str, Any]:
    grade_slug = "pk1" if ml["grade"] == "PK-1" else ml["grade"].lower()
    chunk_id = f"drawing-labeling-{grade_slug}-ml{ml['ml_number']}-{slugify(ml['skill_title'])}"
    band = grade_band(ml["grade"])
    audience = "ELEM"

    content = ml["content"].strip()
    mode = ml["writing_mode"]
    pie_tags_by_band = {band: ["I"]} if mode == "Inform" else {band: ["P", "I", "E"]}

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
        "writing_mode": mode,
        "strategy_name": slugify(ml["skill_title"])[:80],
        "is_scripted_example": False,
        "audience": audience,
        "page_number": ml["source_page"],
        "section_name": f"Drawing/Labeling/Early Sentences — ML #{ml['ml_number']}: {ml['skill_title']}",
        "day_number": ml["day_number"],
        "mini_lesson_number": ml["ml_number"],
        "episode_number": None,
        "chunk_index": 0,
        "content": content,
        "book_name": None,
        "chapter_number": None,
        "ml_number": ml["ml_number"],
        "skill_title": ml["skill_title"],
        "is_scripted_lesson": True,
        "priority_rank": 1,
        "topic_keywords": topic_keywords(content, ml["skill_title"]),
        "book_reference": f"Smekens Drawing/Labeling/Early Sentences — ML #{ml['ml_number']}: {ml['skill_title']}",
        "pie_tags_by_band": pie_tags_by_band,
        "lesson_trigger": ml["lesson_triggers"],
        # Cross-reference to existing K-2 library entry (when this ML
        # supplements one with the same skill title at a different grade).
        "related_ml_id": ml.get("related_ml_id"),
    }


def build_library_entry(chunk: dict[str, Any], ml: dict[str, Any]) -> dict[str, Any]:
    ml_id = f"lib-{chunk['chunk_id']}"
    band = grade_band(ml["grade"])
    mode = ml["writing_mode"]
    writing_modes = ["Inform"] if mode == "Inform" else ["Entertain", "Inform", "Persuade"]
    pie_tags = ["I"] if mode == "Inform" else ["E", "I", "P"]
    pie_tags_by_band = {band: pie_tags}
    return {
        "ml_id": ml_id,
        "skill_title": ml["skill_title"],
        "hyde_summaries": list(ml["hyde_summaries"]),
        "grade_levels": [ml["grade"]],
        "writing_modes": writing_modes,
        "pie_tags": pie_tags,
        "pie_tags_by_band": pie_tags_by_band,
        "lesson_triggers": list(ml["lesson_triggers"]),
        "book_reference": chunk["book_reference"],
        "page_number": chunk["page_number"],
        "source_document": chunk["source_document"],
        "source_chunk_id": chunk["chunk_id"],
        "complete_ml_text": chunk["content"],
        "priority_tier": 1,
        # Cross-reference for retrieval reranker to surface age-appropriate
        # variant when a user searches for the shared skill name.
        "related_ml_id": ml.get("related_ml_id"),
    }


def next_chunk_file_index() -> int:
    """14.4 lands as chunks/37-drawing-labeling-early-writer.json.

    37 leaves room for the 6 persuasive ML files (31-36) shipped from the
    Phase 14.1 branch — those merge first and claim those slots. Using a
    fixed number here avoids a merge conflict on the filename.
    """
    return 37


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
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    existing_chunk_ids = _load_existing_chunk_ids()
    existing_lib_ids = _load_existing_library_ids()

    built: list[tuple[dict, dict]] = []
    skipped: list[str] = []
    for ml in ALL_DRAWING_LABELING_MLS:
        chunk = build_chunk(ml)
        if chunk["chunk_id"] in existing_chunk_ids:
            skipped.append(chunk["chunk_id"])
            continue
        lib = build_library_entry(chunk, ml)
        if lib["ml_id"] in existing_lib_ids:
            skipped.append(lib["ml_id"])
            continue
        built.append((chunk, lib))

    if skipped:
        print(f"[skipped {len(skipped)} already-present]")
    if not built:
        print("Nothing to build.")
        return 0

    next_idx = next_chunk_file_index()
    out_name = f"{next_idx:02d}-drawing-labeling-early-writer.json"
    print(f"Built {len(built)} new MLs → chunks/{out_name}")
    for chunk, lib in built:
        related = chunk.get("related_ml_id")
        related_note = f", related={related}" if related else ""
        print(f"  - {chunk['chunk_id']}  "
              f"grade={chunk['grade_level']} trait={chunk['writing_trait']} "
              f"mode={chunk['writing_mode']}  "
              f"({len(chunk['content']):,} chars, {len(lib['hyde_summaries'])} HyDEs"
              f"{related_note})")

    if args.dry_run:
        print("\n[dry-run: no files written]")
        return 0

    out_path = CHUNKS_DIR / out_name
    chunks = [c for c, _ in built]
    out_path.write_text(json.dumps(chunks, indent=2, ensure_ascii=False) + "\n")
    print(f"  wrote {out_path}")

    data = json.loads(LIBRARY_PATH.read_text())
    data["entries"].extend([lib for _, lib in built])
    LIBRARY_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"  appended {len(built)} entries → {LIBRARY_PATH} "
          f"(total now {len(data['entries'])})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
