"""Tests for ingest.py — chunk loading, validation, ID generation."""

import json
from pathlib import Path

from ingest import (
    VALID_COPILOT_MODES,
    VALID_GRADE_LEVELS,
    VALID_WRITING_MODES,
    VALID_WRITING_TRAITS,
    chunk_id_to_point_id,
    load_chunks,
    validate_chunk,
)


class TestChunkIdToPointId:
    """Deterministic point ID generation."""

    def test_same_input_same_output(self):
        id1 = chunk_id_to_point_id("test-chunk-123")
        id2 = chunk_id_to_point_id("test-chunk-123")
        assert id1 == id2

    def test_different_inputs_different_outputs(self):
        id1 = chunk_id_to_point_id("chunk-a")
        id2 = chunk_id_to_point_id("chunk-b")
        assert id1 != id2

    def test_positive_int64(self):
        pid = chunk_id_to_point_id("any-string")
        assert pid > 0
        assert pid < 2**63


class TestValidateChunk:
    """Metadata validation against closed sets."""

    def test_valid_chunk_no_warnings(self):
        chunk = {
            "chunk_id": "test-1",
            "grade_level": "3",
            "writing_trait": "Ideas",
            "writing_mode": "Inform",
            "copilot_mode": "both",
            "content": "Some content here.",
        }
        warnings = validate_chunk(chunk, "test.json", 0)
        assert warnings == []

    def test_invalid_grade_level(self):
        chunk = {
            "chunk_id": "test-2",
            "grade_level": "13",
            "content": "Content.",
        }
        warnings = validate_chunk(chunk, "test.json", 0)
        assert any("grade_level" in w for w in warnings)

    def test_invalid_writing_trait(self):
        chunk = {
            "chunk_id": "test-3",
            "writing_trait": "Creativity",  # not a valid trait
            "content": "Content.",
        }
        warnings = validate_chunk(chunk, "test.json", 0)
        assert any("writing_trait" in w for w in warnings)

    def test_empty_content_warning(self):
        chunk = {"chunk_id": "test-4", "content": ""}
        warnings = validate_chunk(chunk, "test.json", 0)
        assert any("empty content" in w for w in warnings)

    def test_6_12_is_valid(self):
        chunk = {
            "chunk_id": "test-5",
            "grade_level": "6-12",
            "content": "Content.",
        }
        warnings = validate_chunk(chunk, "test.json", 0)
        assert warnings == []


class TestLoadChunks:
    """Chunk loading from disk."""

    def test_loads_chunks(self):
        chunks = load_chunks()
        assert len(chunks) > 0

    def test_excludes_framework(self):
        chunks = load_chunks()
        for c in chunks:
            assert c.get("source_document") != "01-master-4step.json"

    def test_excludes_textbooks(self):
        chunks = load_chunks()
        chunk_ids = {c["chunk_id"] for c in chunks}
        # No chunk IDs starting with textbook prefixes
        assert not any(cid.startswith("textbook-3-12") for cid in chunk_ids)

    def test_all_chunks_have_content(self):
        chunks = load_chunks()
        for c in chunks:
            assert c.get("content"), f"Chunk {c.get('chunk_id')} has no content"

    def test_all_chunks_have_chunk_id(self):
        chunks = load_chunks()
        for c in chunks:
            assert c.get("chunk_id"), f"Missing chunk_id in {c}"


class TestValidSets:
    """Verify the valid metadata sets are correct."""

    def test_valid_grades_include_ranges(self):
        assert "K" in VALID_GRADE_LEVELS
        assert "K-2" in VALID_GRADE_LEVELS
        assert "6-12" in VALID_GRADE_LEVELS
        assert "K-12" in VALID_GRADE_LEVELS

    def test_valid_traits(self):
        assert "Ideas" in VALID_WRITING_TRAITS
        assert "Organization" in VALID_WRITING_TRAITS
        assert "all" in VALID_WRITING_TRAITS

    def test_valid_modes(self):
        assert "Inform" in VALID_WRITING_MODES
        assert "Persuade" in VALID_WRITING_MODES
        assert "Entertain" in VALID_WRITING_MODES
        assert "all" in VALID_WRITING_MODES

    def test_valid_copilot_modes(self):
        assert "lesson_generation" in VALID_COPILOT_MODES
        assert "coaching" in VALID_COPILOT_MODES
        assert "both" in VALID_COPILOT_MODES
