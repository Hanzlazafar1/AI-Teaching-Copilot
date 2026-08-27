"""Post-generation policy validators (plan §17) — composite + public interface.

Each hard policy rule is a small pure validator. Wave 0 Part 2 split the
individual validators into focused modules; this module orchestrates them and
RE-EXPORTS every public validator so ``from validation.policy import X`` keeps
working unchanged:

  - forbidden words          -> validation.forbidden_words
  - response endings         -> validation.endings
  - book / page citations    -> validation.citations
  - teacher vocab & triggers -> validation.vocabulary
  - lesson shape (depth,     -> validation.structure
    Step-3, Step-2B, balance)

Validators are pure functions returning a list of human-readable error strings
(empty list = pass). The retry loop aggregates them as feedback for the next
generation attempt so the model can address them all at once.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from generation.lesson import MiniLesson

from validation.forbidden_words import (
    FORBIDDEN_WORD_ERROR_PREFIX,
    is_forbidden_word_error,
    scrub_forbidden_words,
    validate_no_forbidden_words,
)
from validation.endings import (
    ends_with_offer_question,
    is_offer_eligible,
    closer_anchor_phrases,
    required_closing_phrases,
    scripted_ml_grade_band,
    validate_grade_band_close,
    validate_response_ending,
)
from validation.citations import (
    scrub_unverifiable_citations,
    validate_book_citation,
)
from validation.vocabulary import (
    STORY_NARRATIVE_ERROR_PREFIX,
    TRIGGER_USAGE_ERROR_PREFIX,
    is_story_narrative_error,
    is_trigger_usage_error,
    validate_details_not_reasons,
    validate_skill_focus_vocab,
    validate_story_only_narrative,
    validate_trigger_usage,
)
from validation.structure import (
    MIN_MONOLOGUE_PHRASES,
    MONOLOGUE_ERROR_PREFIX,
    STEP_2A_MIN_MULTIPLIER,
    STEP_2B_MIN_MULTIPLIER,
    STEP_2B_MONOLOGUE_PHRASES,
    STEP_3_REQUIRED_PHRASES,
    is_monologue_voice_error,
    validate_lesson_balance,
    validate_lesson_depth,
    validate_step_2b_monologue,
    validate_step_3_phrases,
)


# ---------------------------------------------------------------------------
# Cross-cutting: which errors are semantic enough to trust the LLM's judgment
# ---------------------------------------------------------------------------
def is_llm_trustable_error(error: str) -> bool:
    """Errors from rules whose final call is semantic — the LLM is a
    better judge than a regex. After ≥1 contextual retry, if only these
    remain, ship VALID on the LLM's say-so."""
    return (
        is_forbidden_word_error(error)
        or is_trigger_usage_error(error)
        or is_monologue_voice_error(error)
    )


# ---------------------------------------------------------------------------
# Composite validator for SCRIPTED_ML
# ---------------------------------------------------------------------------


@dataclass
class LessonPolicyResult:
    """Aggregate of all policy errors for a generated MiniLesson."""

    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    def as_feedback_block(self) -> str:
        """Format errors as a feedback block for the next-attempt user prompt.

        Errors are re-ordered so the highest-priority categories (forbidden
        words, then missing literal phrases, then ending) appear first —
        LLMs attend more to earlier constraints, so putting hard bans up
        top improves compliance without any prompt-level rewrite.
        """
        if not self.errors:
            return ""
        # Late import — policy_repair imports nothing from policy, so the
        # direction of the dependency is safe, but keeping this local avoids
        # tangling the module import graph.
        from validation.policy_repair import sort_errors_by_priority

        ordered = sort_errors_by_priority(self.errors)
        bullets = "\n".join(f"- {e}" for e in ordered)
        return (
            "Your previous lesson violated these policy rules — address ALL "
            "of them on the next attempt:\n"
            f"{bullets}"
        )


def validate_lesson_policy(
    lesson: MiniLesson,
    *,
    retrieved_context: str,
    response_text: str,
    user_skill_phrase: str = "",
    triggered_trigger_names: list[str] | None = None,
    grade: str | None = None,
    mode: str | None = None,
) -> LessonPolicyResult:
    """Run every SCRIPTED_ML policy validator and collect errors.

    `response_text` is the serialized lesson (typically JSON or concatenated
    step text) — used for response-wide checks like forbidden words,
    trigger usage, and book citation. Structural checks (format +
    completeness) are handled elsewhere — this function assumes structure
    already passed.

    `grade`/`mode` (the intent's grade band and writing mode) gate the Brady
    N1 vocabulary rule — K-1 opinion/persuasive lessons must say "details",
    never "reasons" — and drive the Brady E1 grade-band Step 4 close (K-2
    "Let's go be writers!" / 3-12 "Now it's your turn!"). N1/N2 default to
    inert when `grade`/`mode` are ``None`` (unchanged callers see no new
    errors); E1 is a hard non-negotiable so it does NOT default to inert —
    an unthreaded `grade` resolves to the stricter "3-12" band rather than
    skipping the check (see `validation.endings.scripted_ml_grade_band`).
    """
    result = LessonPolicyResult()
    result.errors.extend(validate_no_forbidden_words(response_text))
    result.errors.extend(validate_lesson_depth(lesson))
    result.errors.extend(validate_step_3_phrases(lesson))
    result.errors.extend(validate_step_2b_monologue(lesson))
    result.errors.extend(
        validate_skill_focus_vocab(lesson, user_skill_phrase)
    )
    result.errors.extend(
        validate_trigger_usage(response_text, triggered_trigger_names or [])
    )
    result.errors.extend(validate_book_citation(response_text, retrieved_context))
    result.errors.extend(validate_lesson_balance(lesson))
    result.errors.extend(validate_details_not_reasons(response_text, grade, mode))
    result.errors.extend(validate_story_only_narrative(response_text, mode))
    result.errors.extend(
        validate_grade_band_close(lesson, scripted_ml_grade_band(grade))
    )
    return result


# ---------------------------------------------------------------------------
# Composite validator for markdown responses (HOW_TO_TEACH / PLAN_UNIT /
# COACHING_GENERAL / MANAGEMENT). Applies the same forbidden-words,
# trigger-usage, book-citation, and ending checks — but not lesson-specific
# checks (depth, Step 3 phrases, etc.).
# ---------------------------------------------------------------------------


def validate_markdown_response(
    *,
    query_type: str,
    response_text: str,
    retrieved_context: str,
    triggered_trigger_names: list[str] | None = None,
    grade: str | None = None,
    mode: str | None = None,
) -> list[str]:
    """Policy validator for all non-JSON (markdown) templates. Returns
    aggregated error strings (empty = pass).

    `grade`/`mode` gate the Brady N1/N2 vocabulary rules on the text path
    exactly as `validate_lesson_policy` gates them for SCRIPTED_ML: N1
    ("details", never "reasons") fires only in K-1 persuasive writing; N2
    ("story" is narrative-only) fires only for Inform/Persuade. Both default
    inert when grade/mode is None, so callers that don't thread them see no
    behavior change. FLAG-only (no scrub) — they feed the retry loop. On the
    markdown path N2 is additionally treated as LLM-trustable (see
    handlers/_base_text.py) so a legitimate non-narrative "story" the LLM
    keeps after one nudge ships VALID, honoring Brady's intent (he bans
    mislabeling the PIECE a story, not the word in metaphor/idiom).
    """
    errors: list[str] = []
    errors.extend(validate_no_forbidden_words(response_text))
    errors.extend(
        validate_trigger_usage(response_text, triggered_trigger_names or [])
    )
    errors.extend(validate_book_citation(response_text, retrieved_context))
    errors.extend(validate_response_ending(query_type, response_text))
    errors.extend(validate_details_not_reasons(response_text, grade, mode))
    errors.extend(validate_story_only_narrative(response_text, mode))
    return errors


__all__ = [
    # composite
    "LessonPolicyResult",
    "validate_lesson_policy",
    "validate_markdown_response",
    "is_llm_trustable_error",
    # forbidden_words
    "scrub_forbidden_words",
    "validate_no_forbidden_words",
    "is_forbidden_word_error",
    "FORBIDDEN_WORD_ERROR_PREFIX",
    # endings
    "validate_response_ending",
    "closer_anchor_phrases",
    "required_closing_phrases",
    "scripted_ml_grade_band",
    "validate_grade_band_close",
    "ends_with_offer_question",
    "is_offer_eligible",
    # citations
    "scrub_unverifiable_citations",
    "validate_book_citation",
    # vocabulary
    "validate_skill_focus_vocab",
    "validate_trigger_usage",
    "validate_details_not_reasons",
    "validate_story_only_narrative",
    "is_trigger_usage_error",
    "TRIGGER_USAGE_ERROR_PREFIX",
    "is_story_narrative_error",
    "STORY_NARRATIVE_ERROR_PREFIX",
    # structure
    "validate_lesson_depth",
    "validate_step_3_phrases",
    "validate_step_2b_monologue",
    "validate_lesson_balance",
    "STEP_2A_MIN_MULTIPLIER",
    "STEP_2B_MIN_MULTIPLIER",
    "STEP_2B_MONOLOGUE_PHRASES",
    "STEP_3_REQUIRED_PHRASES",
    "MIN_MONOLOGUE_PHRASES",
    "MONOLOGUE_ERROR_PREFIX",
    "is_monologue_voice_error",
]
