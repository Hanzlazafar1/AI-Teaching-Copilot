"""Canonicalization for skill and trigger names.

The architecture's consistency depends on normalizing skill/trigger
names at system entry points. QU might emit "topic sentence" or
"Topic Sentences" or "topic-sentence" — canonicalizer resolves all to
"topic sentences".

Three data sources:
  * data/skill_triggers.json — canonical Smekens triggers + synonyms
  * data/skill_synonyms.json — canonical skill names + synonyms
  * data/meta_techniques.json — pedagogical meta-terms (NEVER skills)

Callers:
  * QU post-processor — normalizes SkillSpec.canonical
  * Handlers (pre-retrieval) — double-check canonical form
  * Validators (trigger_adherence) — compares response triggers to canonical
  * Session updater — uses is_meta_technique to avoid corrupting skill state
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Canonical grade values — matches schemas.intent.GradeValue Literal.
# Kept here (not imported) so canonicalizer has no circular dep on
# schemas. Tests verify both lists stay in sync.
GRADE_ENUM: frozenset[str] = frozenset({
    "K", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12",
    "K-2", "3-5", "6-8", "9-12", "K-12", "all",
})

# Normalization patterns for teacher grade phrasings that map cleanly to
# the enum. These are conservative — if the input doesn't match any
# pattern, we return None and force QU to surface a clarification rather
# than guess.
# Disqualifying phrases — if any appear, we refuse to extract a grade.
# "3rd grade band" is nonsense phrasing from v3's Turn 6 hallucination;
# accepting it would re-introduce the exact bug we're trying to close.
_GRADE_DISQUALIFIERS = (
    re.compile(r"\bgrade\s+band\b", re.IGNORECASE),
    re.compile(r"\bgrade\s+level\s+band\b", re.IGNORECASE),
)

_GRADE_ORDINAL_RE = re.compile(
    r"\b(?:"
    r"(?P<kinder>kindergartn?ers?|kindergartens?|kinder|\bk\b)"
    r"|(?P<ordinal>1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th|11th|12th)"
    r"|(?P<cardinal>grade\s*(?P<num>1[0-2]|[1-9]))"
    r"|(?P<word>first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth)"
    r")\b",
    re.IGNORECASE,
)

_GRADE_BAND_RE = re.compile(
    r"\b(?:"
    r"(?P<explicit>k-2|3-5|6-8|9-12|k-12)"
    r"|(?P<primary>primary|little ones|young writers)"
    r"|(?P<upper>upper elementary|intermediate)"
    r"|(?P<middle>middle school(?:ers)?)"
    r"|(?P<high>high school|secondary)"
    r")\b",
    re.IGNORECASE,
)

_WORD_TO_NUM = {
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5",
    "sixth": "6", "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10",
    "eleventh": "11", "twelfth": "12",
}
_ORDINAL_TO_NUM = {
    "1st": "1", "2nd": "2", "3rd": "3", "4th": "4", "5th": "5",
    "6th": "6", "7th": "7", "8th": "8", "9th": "9", "10th": "10",
    "11th": "11", "12th": "12",
}


def canonicalize_grade(raw: str) -> Optional[str]:
    """Map a teacher-phrasing of grade to a canonical enum value.

    Returns None if the input doesn't map cleanly. Callers should treat
    None as "ambiguous — ask the teacher to clarify" rather than guess.

    Examples:
      "3rd graders"     → "3"
      "3rd grade"       → "3"
      "third grade"     → "3"
      "Grade 4"         → "4"
      "K"               → "K"
      "kindergarten"    → "K"
      "kindergartners"  → "K"
      "high school"     → "9-12"
      "upper elementary"→ "3-5"
      "middle school"   → "6-8"
      "K-2"             → "K-2"
      "3rd grade band"  → None (nonsense phrasing — don't accept)
      ""                → None
      "my older kids"   → None
    """
    if not raw:
        return None
    text = raw.lower().strip()

    # Refuse disqualifying phrases outright. "3rd grade band" contains
    # an ordinal the regex would happily match, but the phrase itself
    # is nonsense (no such thing as "3rd grade band" in Brady's
    # vocabulary). Return None → QU surfaces clarification.
    for dq in _GRADE_DISQUALIFIERS:
        if dq.search(text):
            return None

    # Direct-match enum values (after case normalization)
    for canonical in GRADE_ENUM:
        if text == canonical.lower():
            return canonical

    # Band-detection path — collective terms that Brady treats as
    # ambiguous (the teacher must still specify which grade within the
    # band). We return the band value; the CALLER decides whether to
    # use it or force clarification based on context.
    band_match = _GRADE_BAND_RE.search(text)
    if band_match:
        if band_match.group("explicit"):
            return band_match.group("explicit").replace("k", "K")
        if band_match.group("primary"):
            return "K-2"
        if band_match.group("upper"):
            return "3-5"
        if band_match.group("middle"):
            return "6-8"
        if band_match.group("high"):
            return "9-12"

    # Specific-grade path — ordinal or cardinal reference.
    ordinal_match = _GRADE_ORDINAL_RE.search(text)
    if ordinal_match:
        if ordinal_match.group("kinder"):
            return "K"
        if ordinal_match.group("num"):
            # "grade 4" pattern
            return ordinal_match.group("num")
        ord_group = ordinal_match.group("ordinal")
        if ord_group:
            return _ORDINAL_TO_NUM.get(ord_group.lower())
        word_group = ordinal_match.group("word")
        if word_group:
            return _WORD_TO_NUM.get(word_group.lower())

    return None


class ResolutionKind(str, Enum):
    """What kind of term a raw string resolved to."""

    SKILL = "skill"
    TRIGGER = "trigger"
    META_TECHNIQUE = "meta_technique"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class CanonicalResolution:
    """Result of canonicalizer.resolve()."""

    kind: ResolutionKind
    canonical: str  # the resolved name, or the lowercased input if unknown


class Canonicalizer:
    """Resolves raw skill/trigger strings to canonical form.

    Load once at startup (this class is a cheap singleton candidate).
    All methods are thread-safe after ``__init__`` completes because
    the internal maps are immutable after load.
    """

    def __init__(
        self,
        skill_triggers_path: Path,
        skill_synonyms_path: Path,
        meta_techniques_path: Path,
    ) -> None:
        self._skill_map: dict[str, str] = {}
        self._trigger_map: dict[str, str] = {}
        self._meta_techniques: frozenset[str] = frozenset()

        self._load_skill_synonyms(skill_synonyms_path)
        self._load_skill_triggers(skill_triggers_path)
        self._load_meta_techniques(meta_techniques_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def canonicalize_skill(self, raw: str) -> str:
        """Return canonical skill name for `raw`.

        Lookup order:
          1. Exact match in skill synonyms → canonical skill
          2. Exact match in trigger synonyms → canonical trigger
             (a trigger name IS a skill-level reference, e.g.,
             "pizza-table" is a skill that teaches paragraph support)
          3. Fallback: lowercased, whitespace-normalized input

        Does NOT return None — there's always SOME canonical form
        even if it's just the normalized input. The caller decides
        whether unresolved input is acceptable.
        """
        key = self._normalize(raw)
        if not key:
            return key

        if key in self._skill_map:
            return self._skill_map[key]
        if key in self._trigger_map:
            return self._trigger_map[key]
        return key

    def canonicalize_trigger(self, raw: str) -> Optional[str]:
        """Return canonical Smekens trigger name (e.g., 'pizza-table')
        or None if `raw` isn't a recognized trigger.

        Unlike canonicalize_skill, this DOES return None for unknown
        input — callers need to distinguish "known trigger" from
        "general skill".
        """
        key = self._normalize(raw)
        return self._trigger_map.get(key)

    def is_meta_technique(self, raw: str) -> bool:
        """True if `raw` is a pedagogical technique/method name rather
        than a writing skill.

        Consumers should NOT write meta-techniques into SkillSpec.
        In v3, this check was missing and caused the Turn 5 failure:
        'deepen the think-aloud' → skill overwritten with 'think-aloud'.
        """
        key = self._normalize(raw)
        return key in self._meta_techniques

    def resolve(self, raw: str) -> CanonicalResolution:
        """Bundle canonicalization + classification in one call.

        Returns (kind, canonical). If `raw` is a meta-technique, kind
        is META_TECHNIQUE and canonical is the normalized form (caller
        should usually discard, not write to skill state).
        """
        key = self._normalize(raw)
        if not key:
            return CanonicalResolution(ResolutionKind.UNKNOWN, key)

        if key in self._meta_techniques:
            return CanonicalResolution(ResolutionKind.META_TECHNIQUE, key)

        if key in self._trigger_map:
            return CanonicalResolution(ResolutionKind.TRIGGER, self._trigger_map[key])

        if key in self._skill_map:
            return CanonicalResolution(ResolutionKind.SKILL, self._skill_map[key])

        return CanonicalResolution(ResolutionKind.UNKNOWN, key)

    # ------------------------------------------------------------------
    # Loaders
    # ------------------------------------------------------------------

    def _load_skill_synonyms(self, path: Path) -> None:
        """Populate _skill_map from data/skill_synonyms.json."""
        try:
            with open(path) as fp:
                payload = json.load(fp)
        except FileNotFoundError:
            logger.warning(
                "skill_synonyms.json not found at %s — skill canonicalization "
                "will rely on triggers + normalize fallback only",
                path,
            )
            return

        skills = payload.get("skills", {})
        for canonical, synonyms in skills.items():
            canon_key = self._normalize(canonical)
            self._skill_map[canon_key] = canonical  # self-reference
            for syn in synonyms:
                self._skill_map[self._normalize(syn)] = canonical

    def _load_skill_triggers(self, path: Path) -> None:
        """Populate _trigger_map from data/skill_triggers.json.

        Each canonical trigger name maps to itself; each synonym maps
        to the canonical. Canonical forms are the JSON keys (kebab-case
        in Smekens convention, e.g., 'pizza-table').
        """
        try:
            with open(path) as fp:
                payload = json.load(fp)
        except FileNotFoundError:
            logger.warning(
                "skill_triggers.json not found at %s — trigger canonicalization "
                "will be empty",
                path,
            )
            return

        triggers = payload.get("triggers", {})
        for canonical, entry in triggers.items():
            canon_key = self._normalize(canonical)
            self._trigger_map[canon_key] = canonical
            synonyms = entry.get("synonyms", []) if isinstance(entry, dict) else []
            for syn in synonyms:
                self._trigger_map[self._normalize(syn)] = canonical

    def _load_meta_techniques(self, path: Path) -> None:
        """Populate _meta_techniques from data/meta_techniques.json."""
        try:
            with open(path) as fp:
                payload = json.load(fp)
        except FileNotFoundError:
            logger.warning(
                "meta_techniques.json not found at %s — is_meta_technique "
                "will always return False (no protection against writing "
                "pedagogical terms into skill state)",
                path,
            )
            return

        terms = payload.get("techniques", [])
        self._meta_techniques = frozenset(self._normalize(t) for t in terms)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize(raw: str) -> str:
        """Lowercase, strip, collapse internal whitespace.

        Does NOT strip hyphens — "pizza-table" and "pizza table" are
        kept as distinct lookup keys because skill_triggers.json maps
        both forms explicitly. Strip-hyphens would conflate them and
        could break canonical-form round-trips.
        """
        if raw is None:
            return ""
        return " ".join(raw.lower().strip().split())


# ----------------------------------------------------------------------
# Module-level singleton helper
# ----------------------------------------------------------------------

_DEFAULT_ROOT = Path(__file__).resolve().parent
_instance: Optional[Canonicalizer] = None


def get_canonicalizer() -> Canonicalizer:
    """Lazy singleton. Loads data files on first call.

    Tests that need custom data files can instantiate Canonicalizer
    directly with explicit paths.
    """
    global _instance
    if _instance is None:
        _instance = Canonicalizer(
            skill_triggers_path=_DEFAULT_ROOT / "data" / "skill_triggers.json",
            skill_synonyms_path=_DEFAULT_ROOT / "data" / "skill_synonyms.json",
            meta_techniques_path=_DEFAULT_ROOT / "data" / "meta_techniques.json",
        )
    return _instance
