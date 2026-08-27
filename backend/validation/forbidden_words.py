"""Forbidden-word ban + last-resort deterministic scrub (Brady non-negotiable #5).

Split out of validation/policy.py (Wave 0 Part 2). One responsibility: detect
and neutralize Smekens-forbidden teacher-voice words ("discuss", "activity",
"I'll listen in", PD talk). Pure string-in / string-out — no MiniLesson dep.
Re-exported from validation.policy for the stable public interface.
"""
from __future__ import annotations

import re


# Whole-word regex patterns. Kept here (not in generation/prompts.py) so the
# validator stays independent — future prompt refactors can't accidentally
# silence the check.
_FORBIDDEN_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bdiscuss(?:ing|es|ed|ion|ions)?\b", "discuss"),
    (r"\bactivit(?:y|ies)\b", "activity"),
    (r"\bi['’]ll\s+listen\s+in\b", "I'll listen in"),
    (r"\bprofessional\s+development\b", "professional development"),
    (r"\bpd\s+sign[-\s]?off\b", "PD sign-off"),
    (r"\bcertificate\b", "certificate"),
)


_SCRUB_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    # Ordered; longer forms replaced first so the bare-word pattern doesn't
    # eat a suffix that another rule would rather rewrite differently.
    # When the generator can't comply after N retries, these are the safe
    # replacements we substitute into the final text. Phrasing chosen to
    # preserve grammatical flow where possible.
    #
    # Interior \s+ in the multi-word phrases below is DELIBERATE (not the
    # newline-eating hazard fixed in validation/citations.py). Reasoning:
    #   * The paragraph-break hazard (\s eating "\n\n") requires a FIXED
    #     COMPOUND — "professional development", "I'll listen in", "PD
    #     sign-off" — to be split exactly across a "\n\n" break. A generator
    #     never ends a paragraph mid-compound, so that case isn't reachable.
    #   * Conversely, switching these to [^\S\n]+ would make a phrase with an
    #     internal soft-wrap "\n" (a single newline mid-sentence) SURVIVE the
    #     scrub — a Brady non-negotiable #5 violation (the stronger "never,
    #     never, never" rule). \s keeps the scrub catching every whitespace
    #     variant of the phrase, which #5 demands.
    # A break sitting BETWEEN two forbidden phrases (each within its own
    # paragraph) is unaffected: the intra-phrase \s+ matches the space inside
    # the compound, never the "\n\n" between paragraphs (see the
    # multi-paragraph tests in test_forbidden_words.py).
    (r"\bdiscussions?\b", "turn-and-talk"),
    (r"\bdiscuss(?:ing|es|ed)?\b", "turn-and-talk"),
    (r"\bactivit(?:y|ies)\b", "mini-lesson"),
    (r"\bi['’]ll\s+listen\s+in\b", "I'll eavesdrop briefly"),
    (r"\bprofessional\s+development\b", "instructional coaching"),
    (r"\bpd\s+sign[-\s]?off\b", ""),
    (r"\bcertificates?\b", ""),
)


def scrub_forbidden_words(text: str) -> tuple[str, list[str]]:
    """Last-resort deterministic rewrite after retry-exhaustion.

    The retry loop prompts the generator to rewrite and usually succeeds.
    When it doesn't, Brady's rule ("never, never, never") still has to be
    honored. Rather than ship ``quality=low_quality`` with the forbidden
    word intact (what the handler used to do — see R2-K2 failure), we
    substitute a safe approximation and log which words we scrubbed so
    observability can track how often this fires.

    Returns (scrubbed_text, list_of_substituted_original_matches). Matches
    the shape the callers expect for logging.
    """
    scrubbed = text
    subs: list[str] = []
    for pattern, replacement in _SCRUB_REPLACEMENTS:
        def _repl(m: "re.Match[str]") -> str:
            subs.append(m.group(0))
            return replacement
        scrubbed = re.sub(pattern, _repl, scrubbed, flags=re.IGNORECASE)
    # Tidy the whitespace/punctuation artifacts left BY the substitutions —
    # chiefly the empty-string replacements ("PD sign-off"→"" /
    # "certificate"→"") that leave a double space or dangling ". .".
    #
    # Gated on `subs`: if nothing was substituted there are no artifacts to
    # clean, so we skip entirely and return the input BYTE-IDENTICAL. This
    # matters because this scrubber now runs on the full multi-paragraph
    # delivery text (Task 8 wired it onto _build_text_outcome), and an
    # unconditional cleanup would rewrite clean text.
    #
    # Character class is [^\S\n] (whitespace that is NOT a newline), never
    # \s — \s matches "\n", so collapsing runs of \s would flatten the
    # "\n\n" paragraph breaks Brady non-negotiable #11 requires. We only
    # ever want to collapse spaces/tabs a substitution left behind, never
    # touch line structure.
    if subs:
        scrubbed = re.sub(r"[^\S\n]{2,}", " ", scrubbed)
        scrubbed = re.sub(r"\.[^\S\n]*\.", ".", scrubbed)
        scrubbed = re.sub(r"[^\S\n]+([.,;:!?])", r"\1", scrubbed)
    return scrubbed, subs


# Stable prefix the retry loop uses to recognise the forbidden-word rule as
# inherently semantic. Consumed by validation.policy.is_llm_trustable_error.
FORBIDDEN_WORD_ERROR_PREFIX = "Forbidden word"


def is_forbidden_word_error(error: str) -> bool:
    """Cheap predicate used by retry loops to branch on rule type."""
    return error.startswith(FORBIDDEN_WORD_ERROR_PREFIX)


def validate_no_forbidden_words(text: str) -> list[str]:
    """Return an error per forbidden word found. Case-insensitive, whole-word.

    Error phrasing is register-aware: the rule is about Smekens teacher-voice
    / pedagogy jargon, not a blanket ban. The LLM receives this on retry as
    the repair instruction and decides per-occurrence whether the usage is
    teacher-register (rewrite) or student-voice example content (keep).
    """
    errors: list[str] = []
    for pattern, display in _FORBIDDEN_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            errors.append(
                f"{FORBIDDEN_WORD_ERROR_PREFIX} '{display}' appears in the response. "
                "This word is forbidden ONLY in Smekens teacher-voice / pedagogy "
                "register (teacher narration, lesson structure, methodology language). "
                "If your usage is inside student-voice example content — a quoted "
                "student sentence, a topic or vocabulary a student would naturally use "
                "in their own writing — leave it as-is. If your usage is in teacher-"
                "register, rewrite the sentence without it."
            )
    return errors
