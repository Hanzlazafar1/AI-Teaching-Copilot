"""Framework-rules and known-terms loader — the live-loaded globals backing
:func:`get_framework_rules` / :func:`get_known_terms`.

Loaded once at application startup via :func:`init_prompts` from chunk
files (single source of truth). System-prompt construction for the active
scripted-ML path lives in handlers/scripted_ml_prompt.py, not here.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

# Loaded once at module import time
_FRAMEWORK_RULES: str = ""
_KNOWN_TERMS: set[str] = set()


def _load_framework_rules() -> str:
    """Load the 4-step framework rules from chunk file."""
    path = Path(settings.framework_chunks_file)
    if not path.exists():
        logger.error("Framework chunks file not found: %s", path)
        return "(Framework rules unavailable)"

    with open(path) as f:
        chunks = json.load(f)

    rules = "\n\n".join(c["content"] for c in chunks)
    logger.info(
        "Loaded %d framework chunks (%d chars) from %s",
        len(chunks),
        len(rules),
        path,
    )
    return rules


# Core terms that are reliably Smekens but don't show up as
# ``strategy_name`` / ``writing_trait`` / ``writing_mode`` on chunks —
# framework vocabulary, book-general concepts, protocol moves. These are
# corpus-INDEPENDENT so a fresh chunk import doesn't need to re-learn
# them.
_CORPUS_TERMS_CURATED_CORE: frozenset[str] = frozenset(
    {
        # Brand / methodology
        "smekens", "smekens education", "smekens education methodology",
        # 4-step framework artifacts
        "mini-lesson", "mini lesson", "4-step framework", "four-step framework",
        "gradual release", "i do", "we do", "you do",
        # Protocol moves
        "turn and talk", "turn-and-talk", "back to me", "help me with the next",
        "think aloud", "think-aloud",
        # Named Smekens strategies / triggers that may not appear as a
        # chunk-level strategy_name but are referenced throughout
        "slinky test", "slinky-test", "physical trigger", "done list",
        "growing rubric", "four essential skills", "collect facts",
        "topic sentences", "topic sentence", "elaboration", "text evidence",
        "counterclaim", "scr", "statement citation response",
        "writers workshop", "writer's workshop", "quick write",
        "red light green light", "test lady", "author's voice",
        "authentic voice", "show don't tell", "dead verbs", "retired verbs",
        "handy man", "pizza table", "pizza-table", "tables and legs",
        "road sign", "road-sign",
        # 6+1 Traits (trait names as proper nouns)
        "ideas", "organization", "voice", "word choice",
        "sentence fluency", "conventions", "6+1 traits", "6+1 trait",
        # Writing modes as canonical Smekens vocabulary
        "inform", "persuade", "entertain",
        "informational writing", "persuasive writing", "narrative writing",
    }
)


def _load_known_terms() -> set[str]:
    """Build the Smekens-vocabulary set used by :func:`grounding_check`.

    Goal: grounding_check should never flag a legitimate Smekens term as
    ungrounded. Hand-curating the full list is fragile (every corpus
    addition can introduce a new strategy name), so this function now
    derives most of the set from chunk metadata at startup:

    * ``strategy_name`` on every chunk (primary source)
    * ``writing_trait`` / ``writing_mode`` on every chunk where set
      (trait/mode names as proper nouns)
    * ``lesson_trigger`` entries (named Smekens triggers live here)
    * Plus the curated corpus-INDEPENDENT core
      (``_CORPUS_TERMS_CURATED_CORE``) for methodology vocabulary that
      isn't attached to any specific chunk.

    Each extracted term is lowercased and added in both its native form
    and a hyphen/space normalized variant so responses that write
    ``"slinky-test"`` and ``"slinky test"`` are both recognized. Malformed
    chunks (missing fields, non-iterable trigger lists, etc.) are skipped
    rather than raising — a broken chunk file should not take down the
    grounding check entirely.
    """
    terms: set[str] = set()
    chunks_dir = Path(settings.chunks_dir)

    if not chunks_dir.exists():
        logger.warning(
            "Chunks directory %s not found — grounding set limited to curated core",
            chunks_dir,
        )
        terms.update(_CORPUS_TERMS_CURATED_CORE)
        return terms

    for filepath in chunks_dir.glob("*.json"):
        try:
            with open(filepath) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping malformed chunk file %s: %s", filepath, exc)
            continue
        if not isinstance(data, list):
            continue
        for chunk in data:
            if not isinstance(chunk, dict):
                continue
            _absorb_term(terms, chunk.get("strategy_name"))
            _absorb_term(terms, chunk.get("writing_trait"))
            _absorb_term(terms, chunk.get("writing_mode"))
            triggers = chunk.get("lesson_trigger")
            if isinstance(triggers, (list, tuple)):
                for t in triggers:
                    _absorb_term(terms, t)

    terms.update(_CORPUS_TERMS_CURATED_CORE)
    logger.info(
        "Built grounding term set: %d terms (%d from corpus metadata, "
        "%d from curated core)",
        len(terms),
        len(terms) - len(_CORPUS_TERMS_CURATED_CORE),
        len(_CORPUS_TERMS_CURATED_CORE),
    )
    return terms


def _absorb_term(bucket: set[str], raw: Any) -> None:
    """Add ``raw`` (and its hyphen/space variant) to ``bucket`` if it is
    a usable term. Tolerates None, non-strings, empty strings, and the
    placeholder value ``"all"`` which some chunks use for "any grade /
    any trait" (not a vocabulary term)."""
    if not isinstance(raw, str):
        return
    lower = raw.strip().lower()
    if not lower or lower == "all":
        return
    bucket.add(lower)
    if "-" in lower:
        bucket.add(lower.replace("-", " "))
    elif " " in lower:
        bucket.add(lower.replace(" ", "-"))


def init_prompts() -> None:
    """Initialize prompts at application startup. Call once."""
    global _FRAMEWORK_RULES, _KNOWN_TERMS
    _FRAMEWORK_RULES = _load_framework_rules()
    _KNOWN_TERMS = _load_known_terms()


def get_framework_rules() -> str:
    """Return the loaded framework rules string."""
    return _FRAMEWORK_RULES


def get_known_terms() -> set[str]:
    """Return the known Smekens terms set."""
    return _KNOWN_TERMS
