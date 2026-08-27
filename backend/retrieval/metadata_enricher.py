"""Metadata enrichment — Phase 1 of BRADY-ALIGNMENT-PLAN.md.

Pure functions that extract new metadata fields from existing chunk data.
Each extractor returns (value, confidence) where:
  - 1.0: high confidence (exact pattern match)
  - 0.6-0.9: medium confidence (partial match, needs review)
  - 0.0: cannot extract (value=None)

Threshold for flagging manual review: confidence < 0.9

See BRADY-ALIGNMENT-PLAN.md Section 5 (Phase 1) for schema design.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LAUNCH_3_12_MARKER = "3-12"
LAUNCH_K2_MARKER = "K-2"

# Stopwords for topic keyword extraction
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "this", "that", "these", "those",
        "have", "has", "had", "been", "being", "what", "when", "where",
        "why", "how", "can", "will", "would", "could", "should", "might",
        "may", "are", "was", "were", "from", "into", "your", "their",
        "they", "them", "there", "here", "into", "about", "using", "use",
    }
)


# ---------------------------------------------------------------------------
# book_name
# ---------------------------------------------------------------------------


def extract_book_name(source_document: str | None) -> tuple[str | None, float]:
    """Map source_document → canonical book name.

    'Launching the Writers Workshop 3-12.pdf' → ("Teal", 1.0)
    'Launching the Writers Workshop K-2.pdf'  → ("K-2", 1.0)
    Other                                      → (None, 0.0)

    Requires the 'Launching' marker — previously this matched any filename
    containing '3-12' or 'K-2', which wrongly tagged episode scripts like
    'Ep 4 3-12 Script.pdf' and 'Ep 4 PK-2 Script.pdf' as Launch book chunks.
    """
    if not source_document:
        return None, 0.0
    sd = source_document
    if "Launching" not in sd and "launching" not in sd:
        return None, 0.0
    if LAUNCH_3_12_MARKER in sd or "3 12" in sd:
        return "Teal", 1.0
    if LAUNCH_K2_MARKER in sd or re.search(r"\bK\s*2\b", sd):
        return "K-2", 1.0
    return None, 0.0


# ---------------------------------------------------------------------------
# chapter_number
# ---------------------------------------------------------------------------


def extract_chapter_number(section_name: str | None) -> tuple[int | None, float]:
    """Parse 'Section N: ...' → N.

    "Section 8: Teaching Ideas — ML #7: ..." → (8, 1.0)
    "Overview: How to Use This Book"         → (None, 0.0)
    """
    if not section_name:
        return None, 0.0
    m = re.match(r"^\s*Section\s+(\d+)[\s:,—-]", section_name)
    if m:
        return int(m.group(1)), 1.0
    return None, 0.0


# ---------------------------------------------------------------------------
# mini_lesson_number
# ---------------------------------------------------------------------------


def extract_ml_number(
    section_name: str | None,
    content: str | None = None,
    chunk_id: str | None = None,
) -> tuple[int | None, float]:
    """Parse 'ML #N' or 'Mini-Lesson #N' → N.

    Tries in order:
      1. section_name (high confidence)
      2. content first 5 lines (medium-high confidence)
      3. chunk_id pattern '-ml(\\d+)-' (medium confidence)
    """
    if section_name:
        m = re.search(r"(?:ML|Mini-Lesson)\s*#\s*(\d+)", section_name)
        if m:
            return int(m.group(1)), 1.0

    if content:
        n = _extract_ml_number_from_content(content)
        if n is not None:
            return n, 0.9

    if chunk_id:
        m = re.search(r"-ml(\d+)-", chunk_id.lower())
        if m:
            return int(m.group(1)), 0.8

    return None, 0.0


# ---------------------------------------------------------------------------
# skill_title
# ---------------------------------------------------------------------------


def extract_skill_title(
    section_name: str | None,
    content: str | None = None,
    strategy_name: str | None = None,
) -> tuple[str | None, float]:
    """Extract the skill title from section_name, falling back to content/strategy_name.

    High confidence (1.0): "Section 8: Teaching Ideas — ML #7: Add interest with Snapple details"
                           → ("Add interest with Snapple details", 1.0)

    Medium (0.7): ML variants: "ML #N Part X:", "ML #N Alternative:", "ML #N Follow-Up"

    Fallback from content (0.8): When section_name uses comma format without title,
                                  extract title from first-line content after the section header.

    Fallback from strategy_name (0.5): Lower confidence — strategy_name is kebab-case and
                                        may not match the original lesson title verbatim.
    """
    if not section_name:
        return None, 0.0

    # Pattern 1: Standard "— ML #N: Title" or "— Mini-Lesson #N: Title"
    m = re.search(
        r"—\s*(?:ML|Mini-Lesson)\s*#\s*\d+\s*:\s*(.+?)\s*$",
        section_name,
    )
    if m:
        return m.group(1).strip(), 1.0

    # Pattern 2: "ML #N Part X: Title" or "ML #N Alternative: Title" etc.
    m = re.search(
        r"(?:ML|Mini-Lesson)\s*#\s*\d+\s*(?:Part\s*\d+|Alternative|Additional(?:\s+Resources)?|Follow-Up(?:\s+Lessons)?)\s*:?\s*(.*)\s*$",
        section_name,
    )
    if m:
        title = m.group(1).strip()
        if title:
            return title, 0.7  # medium — non-standard pattern
        return None, 0.5  # Follow-Up Lessons with no title

    # Pattern 3: Comma-format "Section N: Topic, Mini-Lesson #N" (sections 10-13 in 3-12)
    m = re.search(r",\s*(?:ML|Mini-Lesson)\s*#\s*\d+\s*$", section_name)
    if m:
        # Title not in section_name — try content first line
        if content:
            title_from_content = _extract_title_from_content(content)
            if title_from_content:
                return title_from_content, 0.8

        # Fallback: strategy_name (lower confidence)
        if strategy_name:
            return _format_strategy_name_as_title(strategy_name), 0.5

    # Pattern 3.5: section_name has NO ML marker but content does
    # (e.g., K-2 Section 8 Drawing Pictures: all MLs share section_name="Section 8: Drawing Pictures",
    # but content has "MINI-LESSON #N: Title" in the header)
    if content and not re.search(r"(?:ML|Mini-Lesson)", section_name):
        title_from_content = _extract_title_from_content(content)
        if title_from_content:
            return title_from_content, 0.9  # Content-header extraction is reliable

    # Pattern 4: Section header after em-dash without ML marker
    # e.g., "Step 1 | Introduction — Coaching Language Stems"
    # e.g., "Script 1 — Don't Just Teach the Skill — ..."
    # These extractions are reliable (spot-checked 15 samples — all correct).
    m = re.search(r"—\s*(.+?)\s*$", section_name)
    if m:
        title = m.group(1).strip()
        # Exclude things that are clearly not lesson titles
        if title and not title.startswith(("ML ", "Mini-Lesson")):
            return title, 0.9

    return None, 0.0


def _extract_title_from_content(content: str) -> str | None:
    """Extract lesson title from content — scans first 5 lines.

    Handles two formats:
      Line 1:  'Launching the Writer's Workshop: ... — Section N: Topic, Mini-Lesson #N: TITLE'
      Line 3+: 'MINI-LESSON #N: Title' (K-2 Section 8 Drawing Pictures style)
    """
    first_lines = content.split("\n", 5)[:5]
    for line in first_lines:
        # Match "MINI-LESSON #N: Title" (case-insensitive, handles caps headers)
        m = re.search(
            r"(?:MINI-LESSON|Mini-Lesson|ML)\s*#\s*\d+\s*:\s*(.+?)\s*$",
            line,
            re.IGNORECASE,
        )
        if m:
            return m.group(1).strip()
    return None


def _extract_ml_number_from_content(content: str) -> int | None:
    """Extract ML number from content — scans first 5 lines for 'MINI-LESSON #N'."""
    first_lines = content.split("\n", 5)[:5]
    for line in first_lines:
        m = re.search(
            r"(?:MINI-LESSON|Mini-Lesson|ML)\s*#\s*(\d+)",
            line,
            re.IGNORECASE,
        )
        if m:
            return int(m.group(1))
    return None


def _format_strategy_name_as_title(strategy_name: str) -> str:
    """Convert kebab-case strategy_name to a Title Case guess."""
    words = strategy_name.replace("-", " ").split()
    return " ".join(w.capitalize() for w in words)


# ---------------------------------------------------------------------------
# is_scripted_lesson
# ---------------------------------------------------------------------------


def derive_is_scripted_lesson(chunk: dict[str, Any]) -> tuple[bool, float]:
    """True if the chunk is part of a scripted mini-lesson.

    A Launch book mini-lesson IS a scripted lesson — the book's textbook_lesson
    entries are Smekens' canonical scripted MLs (what Brady's ML Library draws
    from verbatim). Older versions of this function only recognized
    lesson_script / think_aloud_script content_types, which wrongly left 185
    Launch MLs flagged False.
    """
    # Explicit scripted example (skill docs, demonstrations)
    if chunk.get("is_scripted_example") is True:
        return True, 1.0
    # Scripted content types from skill docs / think-aloud scripts
    ct = (chunk.get("content_type") or "").lower()
    if ct in ("lesson_script", "think_aloud_script"):
        return True, 1.0
    # Launch book mini-lessons are canonical Smekens scripted MLs
    book_name = chunk.get("book_name")
    ml_number = chunk.get("ml_number") or chunk.get("mini_lesson_number")
    if book_name in ("Teal", "K-2") and ml_number is not None:
        return True, 1.0
    return False, 1.0


# ---------------------------------------------------------------------------
# priority_rank
# ---------------------------------------------------------------------------

_PRIORITY_LAUNCH_BOOK = 1
_PRIORITY_ML_LIBRARY = 2  # populated post-Phase 4
_PRIORITY_PIE_ESSENTIALS = 3  # populated post-Phase 14
_PRIORITY_EPISODE = 4
_PRIORITY_OTHER = 5


def derive_priority_rank(chunk: dict[str, Any]) -> tuple[int, float]:
    """Assign base priority tier 1-5 based on chunk source.

    Phase 1 scope: we can only assign 1, 4, 5 confidently.
    Ranks 2 (ML Library) and 3 (PIE) are populated in later phases.

    Rank-1 (Launch book) requires the 'launching' marker — previously we also
    matched bare '3-12' / 'k-2' substrings, which wrongly promoted 37 episode
    chunks like 'Ep 4 3-12 Script.pdf' to rank-1 alongside real Launch pages.
    """
    source_cat = (chunk.get("source_category") or "").lower()
    source_doc = (chunk.get("source_document") or "").lower()

    # Launch book chunks — require the 'launching' marker in the filename
    if "launching" in source_doc:
        return _PRIORITY_LAUNCH_BOOK, 1.0

    # Episode scripts
    if source_cat == "episode_script":
        return _PRIORITY_EPISODE, 1.0

    # Core methodology and other
    return _PRIORITY_OTHER, 1.0


# ---------------------------------------------------------------------------
# topic_keywords
# ---------------------------------------------------------------------------


def extract_topic_keywords(
    section_name: str | None,
    content: str | None,
    max_keywords: int = 10,
) -> tuple[list[str], float]:
    """Extract significant topic keywords from section_name + content.

    Strategy: words > 4 chars from section_name + first 200 words of content,
    minus stopwords, deduplicated.

    Confidence is 0.7 — heuristic, not perfect.
    """
    words: list[str] = []
    if section_name:
        words.extend(re.findall(r"[A-Za-z]+", section_name.lower()))
    if content:
        first_200 = " ".join(content.split()[:200])
        words.extend(re.findall(r"[A-Za-z]+", first_200.lower()))

    significant = [
        w for w in words
        if len(w) > 4 and w not in _STOPWORDS
    ]

    # Dedupe preserving order
    seen: set[str] = set()
    keywords: list[str] = []
    for w in significant:
        if w not in seen:
            seen.add(w)
            keywords.append(w)
        if len(keywords) >= max_keywords:
            break

    return keywords, 0.7 if keywords else 0.0


# ---------------------------------------------------------------------------
# book_reference (formatter — depends on Phase 2 page_number)
# ---------------------------------------------------------------------------


def format_book_reference(
    book_name: str | None,
    chapter_number: int | None,
    ml_number: int | None,
    page_number: int | None = None,
) -> tuple[str | None, float]:
    """Format book + chapter + ML + page into citation string.

    With page: "Teal book p. 64 (Section 8, ML #5)"
    Without page: "Teal book, Section 8, ML #5"
    Without ML: "Teal book, Section 8"
    """
    if not book_name:
        return None, 0.0

    parts: list[str] = [f"{book_name} book"]

    if page_number is not None:
        parts.append(f"p. {page_number}")

    if chapter_number is not None:
        inner = f"Section {chapter_number}"
        if ml_number is not None:
            inner += f", ML #{ml_number}"
        parts.append(f"({inner})" if page_number else inner)

    reference = " ".join(parts) if page_number else ", ".join(parts)

    confidence = 1.0 if page_number is not None else 0.8
    return reference, confidence


# ---------------------------------------------------------------------------
# Main enrichment function
# ---------------------------------------------------------------------------


def tag_chunk_with_triggers(
    chunk: dict[str, Any],
    triggers: dict[str, Any],
) -> dict[str, Any]:
    """Scan chunk content + skill_title for Smekens trigger synonyms.

    Sets `lesson_trigger` to a list of canonical trigger names present.
    Mutates and returns the chunk.
    """
    text_to_search = " ".join(
        [
            chunk.get("content") or "",
            chunk.get("skill_title") or "",
            chunk.get("section_name") or "",
            chunk.get("strategy_name") or "",
        ]
    ).lower()

    found: list[str] = []
    for trigger_name, data in triggers.items():
        for syn in data.get("synonyms", []):
            # Word-boundary match on normalized case
            if _synonym_matches(syn.lower(), text_to_search):
                found.append(trigger_name)
                break  # one synonym match is enough for this trigger

    # Always set lesson_trigger (possibly empty) — overwrites stale values
    chunk["lesson_trigger"] = sorted(set(found))
    return chunk


def _synonym_matches(synonym: str, text: str) -> bool:
    """Check if synonym appears in text with word-boundary semantics.

    Handles:
      - Whole-word matches (avoid 'pat' matching 'paternal')
      - Smart-quote apostrophes
      - Hyphen-whitespace flexibility ("table-top" ≈ "table top")
      - Single-letter token protection: 'P-A-T' decomposes to 3 one-letter
        tokens with `[-\\s]+` joiners, which would otherwise match any
        "p a t" in normal prose (e.g. "develop a topic"). For such cases
        we require literal matching with word boundaries.
    """
    # Normalize smart quotes
    syn = synonym.replace("\u2019", "'").replace("\u2018", "'")
    hay = text.replace("\u2019", "'").replace("\u2018", "'")

    # Short single-word synonym: strict word-boundary match
    if " " not in syn and "-" not in syn and len(syn) <= 4:
        pattern = r"\b" + re.escape(syn) + r"\b"
        return bool(re.search(pattern, hay))

    # Tokenize on space/hyphen
    parts = re.split(r"[-\s]+", syn)
    parts = [p for p in parts if p]
    if not parts:
        return False

    # Single-letter tokens (e.g. 'P-A-T' → ['p','a','t']) are dangerous with
    # flexible joiners — require exact literal matching with word boundaries.
    if any(len(p) == 1 for p in parts):
        pattern = r"\b" + re.escape(syn) + r"\b"
        return bool(re.search(pattern, hay))

    # Multi-word/hyphenated synonym: allow hyphen/space flex between tokens.
    # Wrap with \b only when the first/last char is a word char — this prevents
    # matches inside longer words (e.g. 'table-top' must not match the
    # 'ble top' hidden inside 'debata**ble top**ic') without breaking synonyms
    # that start/end with non-word chars like quotes ('"done" list').
    body = r"[-\s]+".join(re.escape(p) for p in parts)
    pre = r"\b" if parts[0][0].isalnum() else ""
    post = r"\b" if parts[-1][-1].isalnum() else ""
    flex_pattern = pre + body + post
    return bool(re.search(flex_pattern, hay))


def apply_pacing_metadata(
    chunk: dict[str, Any],
    pacing: dict[str, Any],
) -> dict[str, Any]:
    """Populate pie_tags_by_band, page_number, and refreshed book_reference.

    Matches chunk's skill_title against pacing.json entries. An ML can appear
    in multiple grade bands with potentially different pie_tags per band.

    Mutates and returns the chunk.
    """
    title = chunk.get("skill_title")
    book_name = chunk.get("book_name")
    if not title or not book_name:
        return chunk

    # Determine which book's pacing to search
    book_key = "launch_3_12" if book_name == "Teal" else "launch_k2"
    book_pacing = pacing.get(book_key, {})

    pie_tags_by_band: dict[str, list[str]] = {}
    page_from_pacing: int | None = None
    mode_to_tag = {"Persuade": "P", "Inform": "I", "Entertain": "E"}

    normalized_chunk_title = _normalize_for_match(title)
    chunk_words = _significant_words(normalized_chunk_title)

    for band, modes in book_pacing.items():
        band_tags: list[str] = []
        for mode, items in modes.items():
            for item in items:
                pacing_title_norm = _normalize_for_match(item["title"])
                if _titles_match(
                    normalized_chunk_title,
                    pacing_title_norm,
                    chunk_words,
                    _significant_words(pacing_title_norm),
                ):
                    band_tags.append(mode_to_tag[mode])
                    if page_from_pacing is None and item.get("page"):
                        page_from_pacing = item["page"]
                    break  # avoid double-tagging same mode
        if band_tags:
            pie_tags_by_band[band] = band_tags

    if pie_tags_by_band:
        chunk["pie_tags_by_band"] = pie_tags_by_band

    if page_from_pacing is not None:
        chunk["page_number"] = page_from_pacing
        # Refresh book_reference with page
        ref, _ = format_book_reference(
            book_name,
            chunk.get("chapter_number"),
            chunk.get("ml_number"),
            page_number=page_from_pacing,
        )
        if ref:
            chunk["book_reference"] = ref

    return chunk


def _normalize_for_match(title: str) -> str:
    """Normalize title for fuzzy matching between chunks and pacing data.

    Lowercase, strip punctuation incl. smart quotes and ® symbol, collapse whitespace.
    """
    s = title.lower()
    s = s.replace("\u201c", "").replace("\u201d", "")  # smart quotes
    s = s.replace("\u2018", "").replace("\u2019", "")  # apostrophes
    s = s.replace("\u2014", "-").replace("\u2013", "-")  # em/en dash
    s = s.replace("\xae", "")  # ®
    s = s.replace("/", " ")  # treat slash as word separator (persuasive/argumentative)
    s = re.sub(r"[^\w\s-]", "", s)  # drop other punctuation
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _strip_parentheticals(title: str) -> str:
    """Remove parenthetical expressions like '(Storyboard)'."""
    return re.sub(r"\s*\([^)]*\)\s*", " ", title).strip()


_MATCH_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "for", "with", "in", "on", "at",
    "-", "&",
})


def _significant_words(normalized_title: str) -> frozenset[str]:
    """Return significant words (>2 chars, not stopwords) as a frozenset."""
    return frozenset(
        w for w in normalized_title.split()
        if len(w) > 2 and w not in _MATCH_STOPWORDS
    )


def _titles_match(
    chunk_norm: str,
    pacing_norm: str,
    chunk_words: frozenset[str],
    pacing_words: frozenset[str],
) -> bool:
    """Return True if a chunk title matches a pacing title.

    Matching strategy (first successful wins):
      1. Exact normalized match
      2. Match after stripping parentheticals from either side
      3. All significant words of pacing title appear in chunk title
         (chunk may be more specific — "Craft persuasive/argumentative intros"
          matches pacing "Craft persuasive intros")
    """
    if chunk_norm == pacing_norm:
        return True

    chunk_stripped = _normalize_for_match(_strip_parentheticals(chunk_norm))
    pacing_stripped = _normalize_for_match(_strip_parentheticals(pacing_norm))
    if chunk_stripped and chunk_stripped == pacing_stripped:
        return True

    # Subset match: all pacing words present in chunk words
    if pacing_words and pacing_words.issubset(chunk_words):
        # Guard: require at least 2 significant words to avoid spurious matches
        if len(pacing_words) >= 2:
            return True

    return False


def enrich_chunk(chunk: dict[str, Any]) -> tuple[dict[str, Any], dict[str, float]]:
    """Apply all Phase 1 extractors to a single chunk.

    Returns:
        (enriched_chunk, confidence_by_field) — original chunk dict with new fields added,
        plus a dict of per-field confidence scores for flagging.

    New fields added (null where not extractable):
        book_name, chapter_number, mini_lesson_number_v2 (shadow of existing),
        skill_title, is_scripted_lesson, priority_rank, topic_keywords,
        book_reference (partial — page_number filled in Phase 2),
        pie_tags_by_band (empty — Phase 2), lesson_trigger (empty — Phase 3),
        page_number (null — Phase 2)
    """
    enriched = dict(chunk)  # shallow copy
    confidences: dict[str, float] = {}

    book_name, c_book = extract_book_name(chunk.get("source_document"))
    enriched["book_name"] = book_name
    confidences["book_name"] = c_book

    chapter, c_ch = extract_chapter_number(chunk.get("section_name"))
    enriched["chapter_number"] = chapter
    confidences["chapter_number"] = c_ch

    ml_num, c_ml = extract_ml_number(
        chunk.get("section_name"),
        content=chunk.get("content"),
        chunk_id=chunk.get("chunk_id"),
    )
    enriched["ml_number"] = ml_num
    confidences["ml_number"] = c_ml

    skill_title, c_st = extract_skill_title(
        chunk.get("section_name"),
        chunk.get("content"),
        chunk.get("strategy_name"),
    )
    enriched["skill_title"] = skill_title
    confidences["skill_title"] = c_st

    # Use `enriched` so the derivation sees the book_name/ml_number we just set.
    is_scripted, c_is = derive_is_scripted_lesson(enriched)
    enriched["is_scripted_lesson"] = is_scripted
    confidences["is_scripted_lesson"] = c_is

    priority, c_pr = derive_priority_rank(chunk)
    enriched["priority_rank"] = priority
    confidences["priority_rank"] = c_pr

    keywords, c_kw = extract_topic_keywords(
        chunk.get("section_name"),
        chunk.get("content"),
    )
    enriched["topic_keywords"] = keywords
    confidences["topic_keywords"] = c_kw

    # Format book_reference with what we have (page_number populated in Phase 2)
    book_ref, c_br = format_book_reference(book_name, chapter, ml_num, page_number=None)
    enriched["book_reference"] = book_ref
    confidences["book_reference"] = c_br

    # Fields populated in later phases — explicit null to make schema consistent
    enriched.setdefault("pie_tags_by_band", {})  # Phase 2
    enriched.setdefault("lesson_trigger", [])  # Phase 3
    enriched.setdefault("page_number", None)  # Phase 2 will backfill for Launch book chunks

    return enriched, confidences
