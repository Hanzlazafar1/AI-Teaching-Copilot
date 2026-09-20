"""Offline data-quality guards over the built chunk JSON (no Qdrant, no LLM).
F66: lesson_trigger tags must be canonical. F67: grade_level must be schema-valid."""
import glob
import json
from pathlib import Path

from ingest import VALID_GRADE_LEVELS

_ROOT = Path(__file__).resolve().parent.parent.parent  # copilot-v4/
_CANONICAL_TRIGGERS = set(json.loads((_ROOT / "data" / "skill_triggers.json").read_text(encoding="utf-8"))["triggers"])


def _all_chunks():
    for f in sorted(glob.glob(str(_ROOT / "chunks" / "*.json"))):
        data = json.loads(Path(f).read_text(encoding="utf-8"))
        chunks = data if isinstance(data, list) else data.get("chunks", [data])
        for c in chunks:
            if isinstance(c, dict) and c.get("chunk_id"):
                yield Path(f).name, c


def test_chunk_trigger_vocab_is_canonical():
    """Every chunk's lesson_trigger is a SUBSET of the canonical keys.
    An empty or missing lesson_trigger PASSES (484 of 710 chunks are empty);
    this is a membership check, NOT a non-empty assertion."""
    offenders = []
    for fname, c in _all_chunks():
        for tag in (c.get("lesson_trigger") or []):
            if tag not in _CANONICAL_TRIGGERS:
                offenders.append(f"{fname}:{c['chunk_id']} -> {tag!r}")
    assert not offenders, "non-canonical lesson_trigger tags:\n" + "\n".join(offenders[:40])


def test_chunk_grade_level_is_valid():
    """Every non-empty chunk grade_level is a schema-valid value."""
    offenders = []
    for fname, c in _all_chunks():
        g = str(c.get("grade_level", ""))
        if g and g not in VALID_GRADE_LEVELS:
            offenders.append(f"{fname}:{c['chunk_id']} -> {g!r}")
    assert not offenders, "invalid grade_level values:\n" + "\n".join(offenders)
