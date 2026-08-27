"""Phase 11.9 — classify policy errors for the targeted-repair retry.

After the main generation retry loop exhausts, we
check whether the remaining policy violations are ones we can fix with a
cheap single-shot "repair" prompt (edit the existing best lesson) rather
than another full regeneration. The alternative — more retries, higher
temperature, or loosened prompts — either trades one flake for another or
doubles cost on the happy path.

Scope of what's repairable (deliberate, conservative):
  * Forbidden words (substitution)
  * Missing Step 3 Smekens phrases (phrase insertion)
  * Missing response ending (append phrase)

NOT repairable — these still ship as ``low_quality`` until structurally
regenerated:
  * Depth-ratio violations (requires lengthening a step, not editing)
  * Step 2B monologue count (requires narrative rewrite)
  * Book citation / trigger usage / skill_focus vocab / example preservation
    (borderline; defer until we see whether the three above fix most flakes)

Errors are classified by stable prefix-matching on the validator output.
This is tighter coupling than ideal but avoids a breaking refactor to
structured error types. The classifier is thoroughly unit-tested so a
validator message change surfaces as a failure immediately.
"""

from __future__ import annotations

import enum
import re
from typing import Iterable


class RepairKind(str, enum.Enum):
    """How (if at all) a given policy error can be fixed by a text-only edit."""

    FORBIDDEN_WORD = "forbidden_word"
    MISSING_STEP3_PHRASE = "missing_step3_phrase"
    MISSING_ENDING = "missing_ending"
    # Everything else — structural or not-yet-supported. The main retry loop
    # has already tried 3 times with feedback; shipping low_quality is the
    # honest behavior.
    OTHER = "other"


# Prefixes taken from validation/policy.py. The forbidden-word prefix is
# imported (not re-declared) to keep a single source of truth — the retry
# loop in handlers uses the same symbol to detect trust-the-LLM cases.
_STEP3_PREFIX = "Step 3 is missing the required Smekens phrase"
_ENDING_PREFIX = "Response for query_type="


def classify_error(error: str) -> RepairKind:
    """Return the repair kind for one policy-error string.

    Matching is case-sensitive and prefix-anchored so a substring appearance
    of (for example) the word "forbidden" inside some other validator's
    message can't mis-classify it.
    """
    from validation.policy import is_forbidden_word_error  # avoid import cycle
    if not error:
        return RepairKind.OTHER
    if is_forbidden_word_error(error):
        return RepairKind.FORBIDDEN_WORD
    if error.startswith(_STEP3_PREFIX):
        return RepairKind.MISSING_STEP3_PHRASE
    if error.startswith(_ENDING_PREFIX):
        return RepairKind.MISSING_ENDING
    return RepairKind.OTHER


def partition_repairable(
    errors: Iterable[str],
) -> tuple[list[str], list[str]]:
    """Split a list of errors into (repairable, structural).

    Repairable = anything whose :class:`RepairKind` is NOT ``OTHER``.
    """
    repairable: list[str] = []
    structural: list[str] = []
    for e in errors:
        if classify_error(e) is RepairKind.OTHER:
            structural.append(e)
        else:
            repairable.append(e)
    return repairable, structural


# ---------------------------------------------------------------------------
# Instruction extraction — each repairable error becomes one bullet in the
# repair prompt. Instructions are intentionally prescriptive: the model is
# being told "apply THIS edit," not "figure out what's wrong."
# ---------------------------------------------------------------------------


# Regex to pull the forbidden word out of the validator message
# "Forbidden word 'discuss' appears in the response. ..."
_FORBIDDEN_WORD_EXTRACT = re.compile(r"forbidden word '([^']+)'", re.IGNORECASE)

# Suggested replacements (kept in sync with the ones in
# validation/policy.py's _SUGGESTED_REPLACEMENTS — duplicated here because
# this module must work even if that map changes; the replacement hint is
# advisory for the LLM, not a hard contract).
_REPLACEMENT_HINTS: dict[str, str] = {
    "discuss": "'turn and talk'",
    "activity": "'mini-lesson', 'practice', or 'try'",
    "i'll listen in": "a specific teacher move",
    "professional development": "(remove entirely)",
    "pd sign-off": "(remove entirely)",
    "certificate": "(remove entirely)",
}


# Pull the missing-phrase list out of the Step 3 validator's message:
# "Step 3 is missing the required Smekens phrase(s): 'help me with the next'. ..."
_STEP3_MISSING_EXTRACT = re.compile(r"phrase\(s\):\s*([^.]+)\.", re.IGNORECASE)


# Pull the required ending list out of the response-ending validator:
# "Response for query_type=COACHING_GENERAL must end with one of ['does this make sense', ...]. ..."
_ENDING_LIST_EXTRACT = re.compile(r"must end with one of\s*(\[[^\]]+\])", re.IGNORECASE)


def _instruction_for_forbidden(error: str) -> str:
    m = _FORBIDDEN_WORD_EXTRACT.search(error)
    word = m.group(1) if m else "the forbidden word"
    replacement = _REPLACEMENT_HINTS.get(word.lower(), "remove or rephrase")
    return (
        f"Remove every occurrence of the word '{word}' from the lesson. "
        f"Replace with {replacement} where it fits the sentence. Do not "
        f"reword anything else."
    )


def _instruction_for_step3(error: str) -> str:
    m = _STEP3_MISSING_EXTRACT.search(error)
    missing = m.group(1).strip() if m else "the missing Smekens phrase(s)"
    return (
        f"Step 3 must contain the literal phrase(s) {missing} as an EXACT "
        f"substring. Insert the missing phrase(s) naturally into Step 3 "
        f"without removing or rewording what is already there."
    )


def _instruction_for_ending(error: str) -> str:
    m = _ENDING_LIST_EXTRACT.search(error)
    endings = m.group(1) if m else "the required closing phrase"
    return (
        f"Replace the last sentence of Step 4 with one of the approved "
        f"closing phrases {endings}. Do not change any other step."
    )


_INSTRUCTION_BUILDERS = {
    RepairKind.FORBIDDEN_WORD: _instruction_for_forbidden,
    RepairKind.MISSING_STEP3_PHRASE: _instruction_for_step3,
    RepairKind.MISSING_ENDING: _instruction_for_ending,
}


def extract_repair_instructions(errors: Iterable[str]) -> list[str]:
    """Turn a list of repairable error strings into prescriptive instructions
    the repair prompt can hand to the LLM.

    Errors classified as ``OTHER`` are silently skipped — callers should use
    :func:`partition_repairable` first and decide their own fate for those.
    """
    out: list[str] = []
    for e in errors:
        kind = classify_error(e)
        builder = _INSTRUCTION_BUILDERS.get(kind)
        if builder is None:
            continue
        out.append(builder(e))
    return out


# ---------------------------------------------------------------------------
# Feedback-ordering priority (§11.9 #2): forbidden-word errors go FIRST in
# the retry-loop feedback block. LLMs attend more to earlier constraints;
# putting a hard textual ban at the top of the prompt improves compliance
# on the forbidden-word dimension without any model-side change.
# ---------------------------------------------------------------------------

_ERROR_PRIORITY: dict[RepairKind, int] = {
    RepairKind.FORBIDDEN_WORD: 0,       # highest priority — hard bans first
    RepairKind.MISSING_STEP3_PHRASE: 1,  # literal phrase requirements next
    RepairKind.MISSING_ENDING: 2,        # ending phrase requirements
    RepairKind.OTHER: 3,                 # depth / monologue / structural
}


def sort_errors_by_priority(errors: Iterable[str]) -> list[str]:
    """Stable-sort errors so highest-priority fixes appear first in feedback.

    Stable so the within-category order the validator emitted is preserved
    (e.g., multiple forbidden words stay in their original scan order).
    """
    return sorted(
        errors,
        key=lambda e: _ERROR_PRIORITY[classify_error(e)],
    )
