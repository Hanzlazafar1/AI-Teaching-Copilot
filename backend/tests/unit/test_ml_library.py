"""Unit tests for retrieval/ml_library.py — Phase 4 of BRADY-ALIGNMENT-PLAN.md."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

from retrieval.ml_library import (
    LibraryEntry,
    LibraryMatch,
    MLLibrary,
    cosine_similarity,
    is_grade_compatible,
)

ROOT = Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_empty_vector(self):
        assert cosine_similarity([], [1.0, 2.0]) == 0.0

    def test_zero_vector(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


# ---------------------------------------------------------------------------
# Grade compatibility
# ---------------------------------------------------------------------------


class TestGradeCompatibility:
    def test_user_grade_in_band(self):
        assert is_grade_compatible(["3-5"], "4") is True

    def test_user_grade_out_of_band(self):
        assert is_grade_compatible(["3-5"], "6") is False

    def test_exact_match(self):
        assert is_grade_compatible(["4"], "4") is True

    def test_single_grade_mismatch(self):
        assert is_grade_compatible(["4"], "5") is False

    def test_all_grades(self):
        assert is_grade_compatible(["all"], "7") is True

    def test_k_12(self):
        assert is_grade_compatible(["K-12"], "3") is True

    def test_k_2_matches_K(self):
        assert is_grade_compatible(["K-2"], "K") is True

    def test_multiple_bands_any_match(self):
        assert is_grade_compatible(["3-5", "6-8"], "6") is True

    def test_no_user_grade_always_compatible(self):
        assert is_grade_compatible(["3-5"], None) is True


# ---------------------------------------------------------------------------
# Library loading and matching
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_library() -> MLLibrary:
    entries = [
        LibraryEntry(
            ml_id="lib-snapple",
            skill_title="Add interest with Snapple details",
            hyde_summaries=[
                "How do I teach Snapple details?",
                "Mini-lesson on adding interesting facts",
            ],
            grade_levels=["3-5", "6-8", "9-12"],
            writing_modes=["Inform"],
            pie_tags=["I"],
            pie_tags_by_band={"3-5": ["I"], "6-8": ["I"], "9-12": ["I"]},
            lesson_triggers=["snapple-details"],
            book_reference="Teal book p. 66 (Section 8, ML #7)",
            page_number=66,
            source_document="Launching the Writers Workshop 3-12.pdf",
            source_chunk_id="lww312-s8-ml07-snapple-details",
            complete_ml_text="Step 1 — Introduce...",
            priority_tier=1,
        ),
        LibraryEntry(
            ml_id="lib-tabletop",
            skill_title="Add 'leg' sentences per 'table-top' reason",
            hyde_summaries=[
                "How do I teach paragraphing to 4th graders?",
                "Lesson on pizza table strategy",
                "Topic sentence and supporting details",
            ],
            grade_levels=["6-8", "9-12"],
            writing_modes=["Persuade", "Inform"],
            pie_tags=["P", "I"],
            pie_tags_by_band={"6-8": ["P", "I"], "9-12": ["P", "I"]},
            lesson_triggers=["pizza-table"],
            book_reference="Teal book p. 64 (Section 8, ML #5)",
            page_number=64,
            source_document="Launching the Writers Workshop 3-12.pdf",
            source_chunk_id="lww312-s8-ml05-table-top-leg-sentences",
            complete_ml_text="Step 1 — Introduce...",
            priority_tier=1,
        ),
    ]
    lib = MLLibrary(entries)
    # Mock embeddings: 4-d vectors based on a deterministic hash
    def fake_embed(text: str) -> list[float]:
        # Simple deterministic mock: assign a unique direction per key phrase
        if "snapple" in text.lower() or "interesting facts" in text.lower():
            return [1.0, 0.0, 0.0, 0.0]
        if "paragraph" in text.lower() or "pizza table" in text.lower() or "topic sentence" in text.lower():
            return [0.0, 1.0, 0.0, 0.0]
        return [0.0, 0.0, 1.0, 0.0]

    lib.build_index_sync(fake_embed)
    return lib


class TestMLLibrary:
    def test_load_from_file(self):
        lib = MLLibrary.load()
        assert lib.size > 0

    def test_size_reflects_entries(self, mock_library):
        assert mock_library.size == 2

    def test_has_embeddings(self, mock_library):
        assert mock_library.has_embeddings() is True

    def test_find_match_snapple_query(self, mock_library):
        # Query resembling "snapple" should prefer the Snapple entry
        query_emb = [1.0, 0.0, 0.0, 0.0]
        matches = mock_library.find_matches(query_emb, user_grade="6", top_k=2)
        assert len(matches) == 2
        assert matches[0].entry.ml_id == "lib-snapple"
        assert matches[0].confidence == pytest.approx(1.0)

    def test_find_match_paragraph_query(self, mock_library):
        query_emb = [0.0, 1.0, 0.0, 0.0]  # 'paragraph' / 'pizza' direction
        matches = mock_library.find_matches(query_emb, user_grade="7", top_k=2)
        assert matches[0].entry.ml_id == "lib-tabletop"

    def test_grade_compatibility_flagged(self, mock_library):
        # User grade 5 — snapple (3-5,6-8,9-12) compatible; tabletop (6-8,9-12) not
        query_emb = [1.0, 0.0, 0.0, 0.0]
        matches = mock_library.find_matches(query_emb, user_grade="5", top_k=2)
        snapple = next(m for m in matches if m.entry.ml_id == "lib-snapple")
        tabletop = next(m for m in matches if m.entry.ml_id == "lib-tabletop")
        assert snapple.grade_compatible is True
        assert tabletop.grade_compatible is False

    def test_find_best_in_grade_filters_out_incompatible(self, mock_library):
        query_emb = [0.0, 1.0, 0.0, 0.0]
        matches = mock_library.find_best_in_grade(query_emb, user_grade="5", top_k=5)
        # tabletop (6-8, 9-12) excluded; only snapple remains (3-5, 6-8, 9-12)
        ids = [m.entry.ml_id for m in matches]
        assert "lib-tabletop" not in ids

    def test_matched_hyde_returned(self, mock_library):
        query_emb = [1.0, 0.0, 0.0, 0.0]
        matches = mock_library.find_matches(query_emb, top_k=1)
        # One of the Snapple HyDEs should be returned
        assert matches[0].matched_hyde in mock_library.entries[0].hyde_summaries

    def test_no_user_grade_all_compatible(self, mock_library):
        query_emb = [0.0, 1.0, 0.0, 0.0]
        matches = mock_library.find_matches(query_emb, user_grade=None, top_k=2)
        assert all(m.grade_compatible for m in matches)

    def test_find_matches_raises_without_index(self):
        lib = MLLibrary([])  # no index built
        with pytest.raises(RuntimeError):
            lib.find_matches([1.0], top_k=1)

    def test_save_and_load_index_roundtrip(self, mock_library, tmp_path):
        path = tmp_path / "embeddings.json"
        mock_library.save_index(path)
        assert path.exists()

        # Fresh library with same entries but no index
        fresh = MLLibrary(mock_library.entries)
        assert not fresh.has_embeddings()
        fresh.load_index(path)
        assert fresh.has_embeddings()

        # Query on the reloaded index produces the same top match as the original
        query_emb = [1.0, 0.0, 0.0, 0.0]
        original = mock_library.find_matches(query_emb, top_k=1)[0]
        reloaded = fresh.find_matches(query_emb, top_k=1)[0]
        assert reloaded.entry.ml_id == original.entry.ml_id
        assert reloaded.confidence == pytest.approx(original.confidence)

    def test_save_without_index_raises(self, tmp_path):
        lib = MLLibrary([])
        with pytest.raises(RuntimeError):
            lib.save_index(tmp_path / "x.json")


# ---------------------------------------------------------------------------
# Library data integrity (runs against real data/scripted_ml_library.json)
# ---------------------------------------------------------------------------


class TestLibraryDataIntegrity:
    """Verify actual library file has expected structure."""

    def test_library_loads(self):
        lib = MLLibrary.load()
        assert lib.size >= 30, f"Expected ≥30 entries, got {lib.size}"

    def test_every_entry_has_ml_id(self):
        lib = MLLibrary.load()
        for e in lib.entries:
            assert e.ml_id, f"Entry missing ml_id: {e}"
            assert e.ml_id.startswith("lib-")

    def test_every_entry_has_hyde(self):
        lib = MLLibrary.load()
        for e in lib.entries:
            assert len(e.hyde_summaries) >= 1, f"Entry {e.ml_id} has no HyDEs"

    def test_every_entry_has_complete_text(self):
        lib = MLLibrary.load()
        for e in lib.entries:
            assert len(e.complete_ml_text) >= 100, (
                f"Entry {e.ml_id} has too little text ({len(e.complete_ml_text)} chars)"
            )

    def test_critical_brady_lessons_present(self):
        """Spot-check: Brady's mentioned lessons must exist in the library."""
        lib = MLLibrary.load()
        ids = {e.ml_id for e in lib.entries}
        required = [
            "lib-lww312-s8-ml05-table-top-leg-sentences",
            "lib-lww312-s8-ml07-snapple-details",
            "lib-lww312-s9-ml11-transitions-within-paragraphs",
            "lib-k2-s8-ml9-magnify-close-up-details",
            "lib-k2-s10-ml14-dissected-web",
            "lib-k2-s12-ml5-slinky-test",
            "lib-k2-s1-ml3-topic-test",
            "lib-lww312-s4-ml1-done-list",
        ]
        missing = [r for r in required if r not in ids]
        assert not missing, f"Critical Brady lessons missing from library: {missing}"

    def test_critical_lessons_have_custom_hyde(self):
        """Brady-critical lessons should have ≥3 manually-written HyDEs."""
        lib = MLLibrary.load()
        critical_ids = {
            "lib-lww312-s8-ml05-table-top-leg-sentences",
            "lib-lww312-s8-ml07-snapple-details",
            "lib-k2-s8-ml9-magnify-close-up-details",
            "lib-k2-s10-ml14-dissected-web",
            "lib-k2-s12-ml5-slinky-test",
        }
        for e in lib.entries:
            if e.ml_id in critical_ids:
                assert len(e.hyde_summaries) >= 3, (
                    f"Critical entry {e.ml_id} has only {len(e.hyde_summaries)} HyDEs"
                )

    def test_grade_levels_reflect_book_audience(self):
        """Launch 3-12 entries apply to all grade 3-12 bands (per Brady's own
        usage, e.g. pizza-table at grade 4 even though pacing flags it for 6-8+9-12).
        K-2 entries apply to K-2 only. No entry should have a narrow band that
        would spuriously exclude a grade within its book's audience.
        """
        lib = MLLibrary.load()
        for e in lib.entries:
            src = (e.source_document or "").lower()
            if "k-2" in src or e.ml_id.startswith("lib-k2-"):
                assert e.grade_levels == ["K-2"], (
                    f"K-2 entry {e.ml_id} has grade_levels={e.grade_levels}"
                )
            elif "3-12" in src or e.ml_id.startswith("lib-lww312-"):
                assert e.grade_levels == ["3-5", "6-8", "9-12"], (
                    f"Launch 3-12 entry {e.ml_id} has grade_levels={e.grade_levels}"
                )

    def test_prebuilt_index_on_disk(self):
        """data/ml_library_embeddings.json should exist and cover every entry."""
        from pathlib import Path
        index_path = ROOT / "data" / "ml_library_embeddings.json"
        assert index_path.exists(), (
            f"Pre-built index missing at {index_path}. "
            "Run: python3 scripts/build_ml_library_index.py"
        )
        lib = MLLibrary.load()
        lib.load_index(index_path)
        assert lib.has_embeddings()
        missing = [e.ml_id for e in lib.entries if not lib._hyde_embeddings.get(e.ml_id)]
        assert not missing, f"Pre-built index missing embeddings for: {missing[:5]}"
