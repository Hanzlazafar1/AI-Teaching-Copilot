"""Vocabulary preservation — teacher wording + Smekens trigger naming.

Split out of validation/policy.py (Wave 0 Part 2). skill_focus must preserve
the teacher's phrasing; a retrieved Smekens trigger must be named in the
response. Re-exported from validation.policy.
"""
from __future__ import annotations

import re

from generation.lesson import MiniLesson


# Stable prefix the retry loop uses to recognise the trigger-usage rule as
# inherently semantic. Consumed by validation.policy.is_llm_trustable_error.
TRIGGER_USAGE_ERROR_PREFIX = "Retrieved context matched the Smekens trigger"


def is_trigger_usage_error(error: str) -> bool:
    return error.startswith(TRIGGER_USAGE_ERROR_PREFIX)


# Stable prefix so the markdown retry loop can recognise the Brady N2
# ("story" is narrative-only) rule as LLM-trustable on the free-form prose
# path — see handlers._base_text._is_markdown_trustable_error. Kept distinct
# from validation.policy.is_llm_trustable_error so SCRIPTED_ML's structured
# path stays NON-trustable for N2. validate_story_only_narrative below emits
# strings that begin with exactly this prefix.
STORY_NARRATIVE_ERROR_PREFIX = "Brady N2:"


def is_story_narrative_error(error: str) -> bool:
    return error.startswith(STORY_NARRATIVE_ERROR_PREFIX)


# Whole-word match so "reasonable"/"reasoning" don't false-positive; the
# singular "reason" counts (reasons?). Case-insensitive for headings/emphasis.
_REASONS_RE = re.compile(r"\breasons?\b", re.IGNORECASE)


def validate_details_not_reasons(
    text: str,
    grade: str | None,
    mode: str | None,
) -> list[str]:
    """Brady N1: in K-1 opinion/persuasive writing the word "reasons" is never
    used — students give "details" (or "details why"). Grades 2-12 DO use
    "reasons", and that grade-conditional nuance is carried by the generation
    prompt (Task 1), so the validator stays silent outside the K-1 persuasive
    case rather than fighting the prompt.
    """
    if mode != "Persuade" or grade not in {"K", "1"}:
        return []
    if _REASONS_RE.search(text or ""):
        return [
            "Brady N1: use 'details' (not 'reasons') — in K-1 opinion/persuasive "
            "writing the word 'reasons' is never used; say 'details' or "
            "'details why'."
        ]
    return []


# Whole-word match for the narrative family so "storyline"/"history" don't
# false-positive: "story" (singular), "storytelling", and the plural "stories"
# all count. Case-insensitive for headings/emphasis.
_STORY_RE = re.compile(r"\bstor(?:y|ytelling|ies)\b", re.IGNORECASE)


def validate_story_only_narrative(
    text: str,
    mode: str | None,
) -> list[str]:
    """Brady N2: "story"/"storytelling"/"stories" belongs to narrative writing
    only (the Entertain mode). In informative or persuasive writing the piece is
    never called a "story" — the teacher language is "your writing piece" (or
    "your informative/persuasive piece"). The rule stays silent for narrative
    (Entertain), for the multi-mode "all" catch-all, and when the caller hasn't
    threaded a mode through (None) — mirroring the N1 gate above.
    """
    if mode in (None, "Entertain", "all"):
        return []
    if _STORY_RE.search(text or ""):
        piece = "informative" if mode == "Inform" else "persuasive"
        return [
            "Brady N2: 'story'/'storytelling' is only for narrative. For "
            f"{mode.lower()} writing say 'your writing piece' / 'your "
            f"{piece} piece'."
        ]
    return []


def validate_skill_focus_vocab(
    lesson: MiniLesson,
    user_skill_phrase: str,
) -> list[str]:
    """If the teacher named a skill with a specific phrase (e.g., "topic
    sentence and supporting details"), that exact wording must appear in
    skill_focus. The library may have a different internal title for the
    same skill, but the user's vocabulary wins in the output.
    """
    if not user_skill_phrase:
        return []
    errors: list[str] = []
    user = user_skill_phrase.strip().lower()
    if user not in (lesson.skill_focus or "").lower():
        errors.append(
            f"skill_focus must preserve the teacher's wording "
            f"('{user_skill_phrase}'). Current skill_focus: "
            f"'{lesson.skill_focus}'. Rewrite skill_focus to include the "
            f"teacher's original phrasing verbatim."
        )
    return errors


def _normalize_for_trigger(text: str) -> str:
    """Lowercase + collapse hyphens/underscores/apostrophes to spaces.
    Used on both trigger and response before matching so surface noise
    doesn't block a semantically-correct reference."""
    text = text.lower()
    text = re.sub(r"[-_']", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _trigger_is_named(trigger: str, response: str) -> bool:
    """True if the response names the trigger — exact phrase match OR
    stem-prefix match on every content word.

    Verbs inflect ('magnify' → 'magnifying', 'zoom' → 'zooming') and nouns
    pluralize ('strategy' → 'strategies'), so a literal substring check
    misses natural teacher/coach language. We instead require every
    content word of the trigger (≥4 chars) to appear as the prefix of
    some word in the response — handles inflection without needing a
    lemmatizer and stays specific enough to avoid collisions.
    """
    norm_resp = _normalize_for_trigger(response)
    norm_trig = _normalize_for_trigger(trigger)
    if not norm_trig:
        return True
    # Fast path — canonical or natural-form substring
    if norm_trig in norm_resp:
        return True
    # Stem-prefix path — every content word must match some response word
    resp_words = re.findall(r"\w+", norm_resp)
    content_words = [w for w in norm_trig.split() if len(w) >= 4]
    if not content_words:
        # Pure short-word trigger ("in up", etc.) — fall back to substring
        return norm_trig in norm_resp
    for cword in content_words:
        # Prefix length: drop the last 2 chars so common inflections
        # (-ing, -ed, -es, -ies) all match, but keep at least 4 chars
        # so collisions ("magn*" ≠ "magnetic") stay unlikely.
        prefix = cword[: max(4, len(cword) - 2)]
        if not any(rw.startswith(prefix) for rw in resp_words):
            return False
    return True


def validate_trigger_usage(
    response_text: str,
    triggered_trigger_names: list[str],
) -> list[str]:
    """If the retrieval layer matched a canonical Smekens trigger (e.g.,
    the query mentioned "paragraphing" which expanded to pizza-table), the
    generated response must reference that trigger by name. Otherwise the
    teacher asked "how do I teach paragraphing" and got back advice that
    didn't name the Smekens strategy — missing the whole point.

    Naming is matched by stem-prefix so natural inflections count —
    "magnifying close-up" satisfies the 'magnify-close-up' trigger.
    """
    if not triggered_trigger_names:
        return []
    errors: list[str] = []
    for trigger in triggered_trigger_names:
        if _trigger_is_named(trigger, response_text or ""):
            continue
        natural = trigger.replace("-", " ").lower()
        errors.append(
            f"{TRIGGER_USAGE_ERROR_PREFIX} '{trigger}', so the response "
            f"should name this Smekens strategy by term — that way the "
            f"teacher can find it in the source material. Natural "
            f"inflections and hyphenation count (e.g., 'magnifying close-"
            f"up' satisfies 'magnify-close-up'). If you are genuinely "
            f"describing a DIFFERENT strategy than '{natural}' — or the "
            f"retrieved chunks were off-topic for this teacher's question "
            f"— leave the response as written. Otherwise add an explicit "
            f"reference to the '{natural}' strategy."
        )
    return errors
