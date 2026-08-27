"""F19: the RRF prefetch pool must reach candidate_k, not the old hardcoded 20."""
import pytest
from qdrant_client import models

from retrieval import search


class _FakeClient:
    def __init__(self):
        self.prefetch = None

    async def query_points(self, **kwargs):
        self.prefetch = kwargs["prefetch"]
        return type("R", (), {"points": [object()] * 10})()  # >= min_results


@pytest.mark.asyncio
async def test_main_prefetch_limit_equals_candidate_k():
    client = _FakeClient()
    await search._search_with_relaxation(
        client=client,
        dense_vector=[0.0, 0.0],
        sparse_vector=models.SparseVector(indices=[0], values=[1.0]),
        metadata_filter=models.Filter(must=[]),
        top_k=50,
    )
    assert [pf.limit for pf in client.prefetch] == [50, 50]


# ---------------------------------------------------------------------------
# The trigger supplement must obey the SAME metadata filter as the main pool.
#
# It exists to widen RELEVANCE (surface a trigger-tagged lesson the global top-K
# missed) — never to widen the GRADE BAND. `_fetch_by_trigger` took no
# metadata_filter at all: its filter was lesson_trigger-only, and its results are
# appended straight into the pool, so it silently bypassed the grade filter Wave
# 2b shipped (F20/F67). The citation layer then reads a chunk straight out of
# that pool with no band check of its own, so an out-of-band chunk becomes a
# CITATION to the teacher. (Measured against the rank-based picker of the day,
# select_citation_source, since replaced by resolve_attribution — the pool is
# still the only place the band is enforced.)
#
# Measured: 8 of 245 citations across the campaign's packs are out-of-band — ALL
# paragraphing/topic-sentence at grades 3-4 citing the K-2 book, ZERO from any
# other query family. `pizza-table` is the trigger tagged on BOTH books (3-12
# pp.63-72 / K-2 pp.109-117); "transitions" (road-sign) has no K-2-tagged chunks
# and showed no leak — exactly what this root cause predicts. It contradicts
# Brady in his OWN worked example of that query: "If you have the 'Launching the
# Writer's Workshop Grades 3 through 12' book ... you will find this lesson on
# page 64."
# ---------------------------------------------------------------------------


class _CapturingClient:
    """Records every filter `_fetch_by_trigger` sends to Qdrant."""

    def __init__(self):
        self.query_filter = None
        self.prefetch_filters = []

    async def query_points(self, **kwargs):
        self.query_filter = kwargs.get("query_filter")
        self.prefetch_filters = [pf.filter for pf in kwargs.get("prefetch") or []]
        return type("R", (), {"points": []})()


def _grade_filter() -> models.Filter:
    return models.Filter(must=[
        models.FieldCondition(key="grade_level",
                              match=models.MatchAny(any=["3", "3-5", "3-12"])),
    ])


def _flatten(f):
    """Every FieldCondition key reachable from a (possibly nested) Filter."""
    keys = []
    for group in (getattr(f, "must", None) or [], getattr(f, "should", None) or []):
        for c in group:
            if isinstance(c, models.Filter):
                keys += _flatten(c)
            elif getattr(c, "key", None):
                keys.append(c.key)
    return keys


@pytest.mark.asyncio
async def test_trigger_supplement_applies_the_metadata_filter():
    client = _CapturingClient()
    await search._fetch_by_trigger(
        client, ["pizza-table"], [0.0, 0.0],
        models.SparseVector(indices=[0], values=[1.0]),
        candidate_k=50,
        metadata_filter=_grade_filter(),
    )
    # The grade constraint must reach Qdrant on the query AND both prefetches —
    # a prefetch without it would pull out-of-band candidates into the fusion.
    for f in [client.query_filter, *client.prefetch_filters]:
        keys = _flatten(f)
        assert "lesson_trigger" in keys, "the supplement must still scope to the trigger"
        assert "grade_level" in keys, "the supplement must NOT bypass the grade filter"


@pytest.mark.asyncio
async def test_trigger_supplement_without_a_filter_is_unchanged():
    # BACK-COMPAT: no metadata filter (e.g. a grade-less query) -> trigger-only,
    # exactly as before. The fix must not invent a constraint nobody asked for.
    client = _CapturingClient()
    await search._fetch_by_trigger(
        client, ["pizza-table"], [0.0, 0.0],
        models.SparseVector(indices=[0], values=[1.0]),
        candidate_k=50,
        metadata_filter=None,
    )
    assert _flatten(client.query_filter) == ["lesson_trigger"]


def test_trigger_supplement_cannot_silently_omit_the_filter():
    # THE STRUCTURAL LOCK. The defect was never in _fetch_by_trigger's logic —
    # it was that the caller had metadata_filter in scope (search.py step 3) and
    # simply never handed it over, which nothing could catch because the
    # parameter did not exist. A default of None would re-open exactly that: a
    # future caller could forget it and silently get an unfiltered supplement
    # again.
    #
    # So metadata_filter is REQUIRED and keyword-only: omitting it is now a
    # TypeError, not a silent grade-band bypass. Passing None stays legal and
    # explicit — the caller must DECIDE, and "no filter" is a decision.
    import inspect

    sig = inspect.signature(search._fetch_by_trigger)
    p = sig.parameters.get("metadata_filter")
    assert p is not None, "_fetch_by_trigger must take a metadata_filter"
    assert p.default is inspect.Parameter.empty, (
        "metadata_filter must have NO default — a default lets a caller omit it "
        "and silently bypass the grade filter, which is the original defect"
    )
    assert p.kind is inspect.Parameter.KEYWORD_ONLY, (
        "keyword-only so it can never be passed positionally by accident"
    )
