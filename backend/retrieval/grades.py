"""The ONE grade vocabulary — which range tags cover which concrete grade.

Pure stdlib, zero deps: `retrieval.filters` imports `qdrant_client`, so the
shared vocabulary cannot live there without dragging Qdrant into
`retrieval.ml_library` (and its tests).

WHY this module exists (recert 2026-07-16, I5). This fact was maintained by
hand in TWO places, as inverses of each other:

  * `filters.GRADE_RANGE_MAP`  — grade -> range tags that include it (Qdrant side)
  * `ml_library._BAND_RANGES`  — band  -> member grades            (library side)

F67 taught the Qdrant side that early-writer content is tagged "PK-1" and must
be retrieved for a grade-K/1 query. Nobody taught the library side. So
`is_grade_compatible(["PK-1"], "K")` returned **False** and all 6 PK-1
drawing/labeling lessons were unreachable at EVERY concrete grade — dead data,
silently. Adding "PK-1" to the second table would have been the patch that
leaves a third divergence available; deriving both from one table removes the
class.

`is_grade_compatible(entry_grades, user_grade)` is exactly the inverse lookup
of this map — "is any of the entry's tags among the tags that cover this
grade?" — so the library side is now derived, not restated.
"""
from __future__ import annotations

# Maps a specific grade to all range tags that include it.
GRADE_RANGE_MAP: dict[str, list[str]] = {
    "K":  ["K", "K-2", "K-5", "K-12"],
    "1":  ["1", "K-2", "K-5", "K-12"],
    "2":  ["2", "K-2", "K-5", "K-12"],
    "3":  ["3", "3-5", "K-5", "3-12", "K-12"],
    "4":  ["4", "3-5", "K-5", "3-12", "K-12"],
    "5":  ["5", "3-5", "K-5", "3-12", "K-12"],
    "6":  ["6", "6-8", "6-12", "3-12", "K-12"],
    "7":  ["7", "6-8", "6-12", "3-12", "K-12"],
    "8":  ["8", "6-8", "6-12", "3-12", "K-12"],
    "9":  ["9", "9-12", "6-12", "3-12", "K-12"],
    "10": ["10", "9-12", "6-12", "3-12", "K-12"],
    "11": ["11", "9-12", "6-12", "3-12", "K-12"],
    "12": ["12", "9-12", "6-12", "3-12", "K-12"],
}

# F67: PK-1 is a chunk-tag-only value (early-writer drawing/labeling content is
# tagged "PK-1"); QU never emits it as a grade, so it belongs in the K/1 VALUE
# lists (not as a key). A grade-K/1 query must retrieve PK-1 content.
for _early in ("K", "1"):
    if "PK-1" not in GRADE_RANGE_MAP[_early]:
        GRADE_RANGE_MAP[_early].append("PK-1")

# F20: QU can emit band grades (grade_to_band -> "K-2"/"3-5"/"6-8"/"9-12"), which
# previously fell through the `grade_level in GRADE_RANGE_MAP` guard and skipped
# the filter entirely. Expand each band to the set-union of its constituent
# single-grade rows (derived, not hand-authored, so no cross-grade leak).
_BAND_MEMBERS = {
    "K-2": ("K", "1", "2"),
    "3-5": ("3", "4", "5"),
    "6-8": ("6", "7", "8"),
    "9-12": ("9", "10", "11", "12"),
}
for _band, _members in _BAND_MEMBERS.items():
    _union: list[str] = []
    for _m in _members:
        for _range in GRADE_RANGE_MAP[_m]:
            if _range not in _union:
                _union.append(_range)
    if _band not in _union:
        _union.append(_band)
    GRADE_RANGE_MAP[_band] = _union


# Range tags that cover every grade, so they never need to appear in a row.
UNIVERSAL_RANGE_TAGS = frozenset({"all", "K-12"})


def range_tags_for_grade(user_grade: str) -> list[str]:
    """Every range tag that covers `user_grade` (empty if the grade is unknown)."""
    return GRADE_RANGE_MAP.get(str(user_grade).strip(), [])
