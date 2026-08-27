"""Metadata filter builder for Qdrant queries.

Translates parsed query fields into Qdrant filter conditions.
Supports grade-level expansion (grade 3 matches K-5, 3-5, 3-12, K-12).
"""

from __future__ import annotations

from qdrant_client import models

# The grade vocabulary (incl. the F67 PK-1 rule and the F20 band expansion) now
# lives in retrieval.grades — a pure module — so retrieval.ml_library can share
# THIS table instead of hand-keeping an inverse of it. Re-exported under the
# original name; every existing `filters.GRADE_RANGE_MAP` reader is unchanged.
#
# It had to move: this module imports qdrant_client, and ml_library (plus its
# tests) must not drag Qdrant in. Keeping two tables is what made all 6 PK-1
# lessons unreachable — F67 taught this side about PK-1 and nobody taught the
# other (recert I5).
from retrieval.grades import GRADE_RANGE_MAP  # noqa: F401  (re-export)


def build_filter(
    *,
    intent: str | None = None,
    grade_level: str | None = None,
    writing_mode: str | None = None,
    writing_trait: str | None = None,
    step_focus: str | None = None,
    strategy_name: str | None = None,
) -> models.Filter:
    """Build a Qdrant metadata filter from parsed query fields.

    Returns a Filter with all applicable conditions as 'must' clauses.
    """
    must: list[models.FieldCondition] = []

    # copilot_mode: filter for mini-lessons only.
    # Coaching queries search ALL modes because lesson_generation chunks
    # contain strategy details that are useful for coaching advice.
    if intent == "mini_lesson":
        must.append(
            models.FieldCondition(
                key="copilot_mode",
                match=models.MatchAny(any=["lesson_generation", "both"]),
            )
        )

    # grade_level: expand to matching ranges
    if grade_level and grade_level in GRADE_RANGE_MAP:
        expanded = GRADE_RANGE_MAP[grade_level]
        must.append(
            models.FieldCondition(
                key="grade_level",
                match=models.MatchAny(any=expanded),
            )
        )

    # writing_mode
    if writing_mode:
        must.append(
            models.FieldCondition(
                key="writing_mode",
                match=models.MatchAny(any=[writing_mode, "all"]),
            )
        )

    # writing_trait — applied only when no specific skill was named.
    #
    # Issue R02 (see FEEDBACK-ISSUES.md): a hard trait filter becomes a
    # silent exclusion trap when QU mis-classifies a specific-skill query.
    # Example: "Teach narrative introductions for grade 9" is structurally
    # an Organization skill, but QU sometimes labels the query's trait as
    # Ideas → Ideas-only filter excludes the correct narrative-intros
    # chunk, and Qdrant returns enough Ideas chunks to avoid triggering
    # relaxation. When the user named a specific skill, the skill's
    # canonical trait (from chunk metadata) is more authoritative than
    # QU's inferred trait on the query string — skip the filter and let
    # the skill + reranker pick the right chunk. Aligns with Brady's
    # B-R04 "priority-weighted re-ranking, not strict tier cascading."
    if writing_trait and not strategy_name:
        must.append(
            models.FieldCondition(
                key="writing_trait",
                match=models.MatchAny(any=[writing_trait, "all"]),
            )
        )

    # step: only filter if explicitly requested
    if step_focus:
        must.append(
            models.FieldCondition(
                key="step",
                match=models.MatchValue(value=step_focus),
            )
        )

    # strategy_name: DO NOT filter — names vary between QU extraction and chunk metadata.
    # Let semantic search + BM25 find strategy-related chunks naturally.
    # (But DOES gate the writing_trait filter above — see comment there.)

    return models.Filter(must=must) if must else models.Filter()


def relax_filter(
    current_filter: models.Filter,
    relaxation_step: int,
) -> models.Filter | None:
    """Progressively relax the filter by dropping conditions.

    relaxation_step:
        1 = drop writing_trait
        2 = drop writing_mode
        3 = drop grade_level

    Returns a new filter with the condition removed, or None if nothing to relax.
    """
    if not current_filter.must:
        return None

    drop_keys = {
        1: "writing_trait",
        2: "writing_mode",
        3: "grade_level",
    }

    key_to_drop = drop_keys.get(relaxation_step)
    if not key_to_drop:
        return None

    new_must = [
        cond for cond in current_filter.must
        if not (isinstance(cond, models.FieldCondition) and cond.key == key_to_drop)
    ]

    # If we didn't actually drop anything, nothing to relax
    if len(new_must) == len(current_filter.must):
        return None

    return models.Filter(must=new_must) if new_must else models.Filter()
