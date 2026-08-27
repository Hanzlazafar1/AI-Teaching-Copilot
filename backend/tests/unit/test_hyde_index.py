"""Unit tests for Phase 11.12 — HyDE embedding cache fingerprint + diff logic.

No network, no filesystem except ``tmp_path`` for the save/load round-trip.
These tests pin the semantics of the fingerprint (what changes invalidate
the cache) and the diff (which entries the script will re-embed).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from retrieval.hyde_index import (
    IndexDiff,
    compute_fingerprint,
    diff_library_against_cache,
    load_index_with_fingerprints,
    save_index_with_fingerprints,
)
from retrieval.ml_library import LibraryEntry


def _entry(ml_id: str, hydes: list[str], title: str = "title") -> LibraryEntry:
    return LibraryEntry(
        ml_id=ml_id,
        skill_title=title,
        hyde_summaries=hydes,
        grade_levels=["3-5"],
        writing_modes=["Inform"],
        pie_tags=["I"],
        pie_tags_by_band={"3-5": ["I"]},
        lesson_triggers=[],
        book_reference="Teal book p. 64",
        page_number=64,
        source_document="Launching the Writers Workshop 3-12.pdf",
        source_chunk_id=f"chunk-{ml_id}",
        complete_ml_text="...",
        priority_tier=1,
    )


# ---------------------------------------------------------------------------
# compute_fingerprint — what invalidates vs. what doesn't
# ---------------------------------------------------------------------------


class TestFingerprintSemantics:
    def test_same_input_same_hash(self):
        a = compute_fingerprint(["how do I X", "what is Y"], "model-a")
        b = compute_fingerprint(["how do I X", "what is Y"], "model-a")
        assert a == b

    def test_hyde_text_change_invalidates(self):
        a = compute_fingerprint(["how do I X"], "model-a")
        b = compute_fingerprint(["how do I Y"], "model-a")
        assert a != b

    def test_hyde_reordering_invalidates(self):
        """Embeddings are stored as a positional list. Swapping HyDE order
        means position 0's vector is now for HyDE "Y" instead of "X" — that
        IS a cache miss even though the set is unchanged."""
        a = compute_fingerprint(["X", "Y"], "model-a")
        b = compute_fingerprint(["Y", "X"], "model-a")
        assert a != b

    def test_model_change_invalidates(self):
        """Switching embedding models must force a full rebuild — old and
        new vectors have different dimensions / semantics and can't be
        mixed in one index."""
        a = compute_fingerprint(["hi"], "text-embedding-3-large")
        b = compute_fingerprint(["hi"], "text-embedding-3-xl")
        assert a != b

    def test_unicode_hydes_produce_stable_hash(self):
        """Author-written HyDEs can contain smart quotes, em-dashes, etc.
        The fingerprint must handle them without crashing or depending on
        the locale."""
        hyde = "How can I use “quotation marks” in 6th-grade writing — really?"
        h = compute_fingerprint([hyde], "model-a")
        # Deterministic across calls — same hash each time.
        assert h == compute_fingerprint([hyde], "model-a")
        # And it's a full sha256 — 64 hex chars.
        assert len(h) == 64

    def test_empty_hyde_list_has_stable_hash(self):
        """Edge case: an entry with zero HyDEs shouldn't crash the hasher.
        It's legal — ``has_cached_vecs`` handles the downstream logic."""
        assert compute_fingerprint([], "model-a") == compute_fingerprint([], "model-a")

    def test_other_metadata_doesnt_affect_hash(self):
        """Only the HyDEs feed the embedding input, so title/grade/etc.
        changes MUST NOT trigger a re-embed. Verify by computing the hash
        directly — the function only takes (hydes, model), so this is
        structurally guaranteed, but we assert to pin the API shape."""
        hydes = ["same hyde"]
        # If someone adds a parameter to compute_fingerprint, this test
        # should be updated deliberately.
        h1 = compute_fingerprint(hydes, "m")
        h2 = compute_fingerprint(hydes, "m")
        assert h1 == h2


# ---------------------------------------------------------------------------
# diff_library_against_cache
# ---------------------------------------------------------------------------


class TestDiff:
    def test_empty_cache_puts_everything_in_to_embed(self):
        entries = [_entry("a", ["hi"]), _entry("b", ["bye"])]
        diff = diff_library_against_cache(
            entries, cached_embeddings={}, cached_fingerprints={},
            model="m", cached_model=None,
        )
        assert diff.to_embed == ["a", "b"]
        assert diff.reused == []
        assert diff.orphaned == []

    def test_matching_fingerprint_is_reused(self):
        entries = [_entry("a", ["hi"])]
        fp = compute_fingerprint(["hi"], "m")
        diff = diff_library_against_cache(
            entries,
            cached_embeddings={"a": [[0.1, 0.2]]},
            cached_fingerprints={"a": fp},
            model="m", cached_model="m",
        )
        assert diff.reused == ["a"]
        assert diff.to_embed == []

    def test_hyde_change_flips_to_embed(self):
        entries = [_entry("a", ["NEW hyde"])]
        old_fp = compute_fingerprint(["OLD hyde"], "m")
        diff = diff_library_against_cache(
            entries,
            cached_embeddings={"a": [[0.1]]},
            cached_fingerprints={"a": old_fp},
            model="m", cached_model="m",
        )
        assert diff.to_embed == ["a"]
        assert diff.reused == []

    def test_orphaned_entries_surfaced(self):
        """ml_ids in the cache but no longer in the library get surfaced
        for pruning — the script drops them from the output."""
        entries = [_entry("a", ["hi"])]
        fp_a = compute_fingerprint(["hi"], "m")
        diff = diff_library_against_cache(
            entries,
            cached_embeddings={"a": [[0.1]], "zombie": [[0.9]]},
            cached_fingerprints={"a": fp_a, "zombie": "whatever"},
            model="m", cached_model="m",
        )
        assert "zombie" in diff.orphaned
        assert "a" not in diff.orphaned

    def test_mismatched_vector_count_forces_re_embed(self):
        """Crash-recovery safety: a cache with fewer vectors than the entry
        has HyDEs is a partial cache (e.g., mid-embed crash). Re-embed."""
        entries = [_entry("a", ["h1", "h2", "h3"])]  # 3 hydes expected
        fp = compute_fingerprint(["h1", "h2", "h3"], "m")
        diff = diff_library_against_cache(
            entries,
            cached_embeddings={"a": [[0.1], [0.2]]},  # only 2 vectors
            cached_fingerprints={"a": fp},
            model="m", cached_model="m",
        )
        assert diff.to_embed == ["a"]

    def test_force_flag_ignores_cache(self):
        entries = [_entry("a", ["hi"])]
        fp = compute_fingerprint(["hi"], "m")
        diff = diff_library_against_cache(
            entries,
            cached_embeddings={"a": [[0.1]]},
            cached_fingerprints={"a": fp},
            model="m", cached_model="m",
            force=True,
        )
        assert diff.to_embed == ["a"]
        assert diff.reused == []

    def test_model_change_triggers_full_rebuild(self):
        """Even if fingerprints match, a model switch must re-embed all —
        old vectors aren't compatible with new-model queries."""
        entries = [_entry("a", ["hi"]), _entry("b", ["bye"])]
        fp_a_oldmodel = compute_fingerprint(["hi"], "old-model")
        fp_b_oldmodel = compute_fingerprint(["bye"], "old-model")
        diff = diff_library_against_cache(
            entries,
            cached_embeddings={"a": [[0.1]], "b": [[0.2]]},
            cached_fingerprints={"a": fp_a_oldmodel, "b": fp_b_oldmodel},
            model="new-model", cached_model="old-model",
        )
        assert diff.to_embed == ["a", "b"]
        assert diff.reused == []

    def test_report_lines_sum_to_library_size_plus_orphans(self):
        """Sanity — every entry appears in exactly one bucket; orphans are
        additional to the library."""
        entries = [_entry("a", ["h"]), _entry("b", ["h"])]
        diff = diff_library_against_cache(
            entries,
            cached_embeddings={"a": [[0.1]], "orphan": [[0.5]]},
            cached_fingerprints={"a": compute_fingerprint(["h"], "m")},
            model="m", cached_model="m",
        )
        # 'a' reused, 'b' to_embed, 'orphan' orphaned
        assert set(diff.reused) == {"a"}
        assert set(diff.to_embed) == {"b"}
        assert set(diff.orphaned) == {"orphan"}
        # Report includes all three counts.
        report = "\n".join(diff.as_report_lines())
        assert "reused:" in report and "to_embed:" in report and "orphaned:" in report


# ---------------------------------------------------------------------------
# Round-trip: save + load
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_save_and_reload_preserves_everything(self, tmp_path: Path):
        path = tmp_path / "idx.json"
        save_index_with_fingerprints(
            path,
            embeddings={"a": [[0.1, 0.2]]},
            fingerprints={"a": "deadbeef"},
            model="m",
        )
        embeddings, fingerprints, model = load_index_with_fingerprints(path)
        assert embeddings == {"a": [[0.1, 0.2]]}
        assert fingerprints == {"a": "deadbeef"}
        assert model == "m"

    def test_missing_file_returns_empty_tuple(self, tmp_path: Path):
        embeddings, fingerprints, model = load_index_with_fingerprints(
            tmp_path / "does-not-exist.json"
        )
        assert embeddings == {}
        assert fingerprints == {}
        assert model is None

    def test_old_format_file_still_loadable(self, tmp_path: Path):
        """Backward compat: an existing index file written with the old
        ``{"embeddings": {...}}`` shape (pre-Phase 11.12) must still load.
        We just report empty fingerprints, which the diff treats as
        'cache is stale, re-embed everything'."""
        path = tmp_path / "idx.json"
        path.write_text(json.dumps({"embeddings": {"a": [[0.1]]}}))
        embeddings, fingerprints, model = load_index_with_fingerprints(path)
        assert embeddings == {"a": [[0.1]]}
        assert fingerprints == {}
        assert model is None

    def test_save_creates_parent_directory(self, tmp_path: Path):
        path = tmp_path / "nested" / "dir" / "idx.json"
        save_index_with_fingerprints(
            path, embeddings={}, fingerprints={}, model="m",
        )
        assert path.exists()


# ---------------------------------------------------------------------------
# Integration: save → diff sees a reuse hit on the next run
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_round_trip_produces_zero_work_on_second_run(self, tmp_path: Path):
        """Simulates: build once, then re-run rebuild_hyde_index.py with
        no library changes. Expected: every entry is REUSED, nothing to
        embed, nothing orphaned."""
        entries = [_entry("a", ["h1", "h2"]), _entry("b", ["h3"])]
        model = "text-embedding-3-large"

        # First run — cache is empty, everything is to_embed.
        first = diff_library_against_cache(
            entries, cached_embeddings={}, cached_fingerprints={},
            model=model, cached_model=None,
        )
        assert first.to_embed == ["a", "b"]

        # Pretend the script embedded + saved.
        fake_embeddings = {"a": [[0.1], [0.2]], "b": [[0.3]]}
        fake_fingerprints = {
            "a": compute_fingerprint(["h1", "h2"], model),
            "b": compute_fingerprint(["h3"], model),
        }
        path = tmp_path / "idx.json"
        save_index_with_fingerprints(
            path,
            embeddings=fake_embeddings,
            fingerprints=fake_fingerprints,
            model=model,
        )

        # Second run — load cache, diff. Should be zero work.
        emb, fp, cm = load_index_with_fingerprints(path)
        second = diff_library_against_cache(
            entries,
            cached_embeddings=emb,
            cached_fingerprints=fp,
            model=model, cached_model=cm,
        )
        assert second.to_embed == []
        assert set(second.reused) == {"a", "b"}
        assert second.orphaned == []
