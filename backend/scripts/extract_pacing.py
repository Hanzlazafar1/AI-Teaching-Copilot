"""Phase 2 — Extract Launch book pacing data into data/launch_book_pacing.json.

Structure discovered via positional word extraction:
  Each pacing line has format "p. N Title" (page ref LEFT of title).
  Right column = Part 2 Mini-Units (Persuasive / Informative / Narrative).
  Left column  = Part 1 launch sections (Writing Topics, Setting Expectations, etc.)

3-12 pacing pages: 5 (Grades 3-5), 6 (Grades 6-8), 7 (Grades 9-12)
K-2 pacing page:   11

Usage:  python3 scripts/extract_pacing.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PACING_PATH = DATA_DIR / "launch_book_pacing.json"

PDF_312 = Path(
    "/home/mudassir/work/shafi/smekensrar/braddy-feedback-16april/"
    "shared-drive/Tier 1 Content/Launching the Writers Workshop Grades 3-12 Digital.pdf"
)
PDF_K2 = Path(
    "/home/mudassir/work/shafi/smekensrar/braddy-feedback-16april/"
    "shared-drive/Tier 1 Content/Launching the Writers Workshop K-2 Digital download.pdf"
)


# ---------------------------------------------------------------------------
# Positional text reconstruction
# ---------------------------------------------------------------------------


def _reconstruct_lines(words: list, y_tolerance: float = 5) -> list[tuple[float, str]]:
    """Group words into lines by y-coordinate. Returns [(y, line_text)] sorted top→bottom."""
    words = sorted(words, key=lambda w: (w[1], w[0]))
    lines: list[list] = []
    current_y = None
    current: list = []
    for w in words:
        y = w[1]
        if current_y is None or abs(y - current_y) <= y_tolerance:
            current.append(w)
            current_y = y
        else:
            lines.append(current)
            current = [w]
            current_y = y
    if current:
        lines.append(current)

    # Render each line: sort by x, join word texts
    out: list[tuple[float, str]] = []
    for line in lines:
        line_sorted = sorted(line, key=lambda x: x[0])
        text = " ".join(w[4] for w in line_sorted)
        y = line[0][1]
        out.append((y, text))
    return out


def _get_column_words(page: fitz.Page, x_min: float, x_max: float) -> list:
    """Return only words whose x0 is within [x_min, x_max]."""
    return [w for w in page.get_text("words") if x_min <= w[0] < x_max]


# ---------------------------------------------------------------------------
# Parse a pacing line — "p. 62 Title"  or "pp. 52-53 Title"
# ---------------------------------------------------------------------------


_LINE_PATTERN = re.compile(r"^\s*p{1,2}\.\s*(\d+)(?:-\d+)?\s+(.+?)\s*$")


def parse_pacing_line(text: str) -> tuple[int, str] | None:
    """Parse 'p. 62 Align with the strongest position' → (62, 'Align with the strongest position').

    Returns None if the line doesn't match the pacing pattern.
    """
    m = _LINE_PATTERN.match(text)
    if m:
        page = int(m.group(1))
        title = m.group(2).strip()
        return page, title
    return None


# ---------------------------------------------------------------------------
# 3-12 book extraction (Grades 3-5, 6-8, 9-12)
# ---------------------------------------------------------------------------

_PART2_HEADERS_312 = {
    "Persuasive/Argumentative Mini-Units": "Persuade",
    "Informative Mini-Units": "Inform",
    "Narrative Mini-Units": "Entertain",
}

# Column x-range for right-column (Part 2) content on 3-12 pacing pages
_RIGHT_COL_X_MIN = 290
_RIGHT_COL_X_MAX = 800


def extract_312_page(pdf_path: Path, page_index: int) -> dict:
    """Extract Part 2 Mini-Unit lists from a 3-12 pacing page."""
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    words = _get_column_words(page, _RIGHT_COL_X_MIN, _RIGHT_COL_X_MAX)
    lines = _reconstruct_lines(words)

    result: dict[str, list[dict]] = {"Persuade": [], "Inform": [], "Entertain": []}
    current_mode: str | None = None

    for _, text in lines:
        stripped = text.strip()
        if stripped in _PART2_HEADERS_312:
            current_mode = _PART2_HEADERS_312[stripped]
            continue

        if current_mode is None:
            continue

        parsed = parse_pacing_line(stripped)
        if parsed:
            page_num, title = parsed
            result[current_mode].append({"title": title, "page": page_num})

    return result


# ---------------------------------------------------------------------------
# K-2 book extraction (page 11 — Part 2 Mini-Unit lists with ML numbers)
# ---------------------------------------------------------------------------

_K2_MODE_HEADERS = {
    # Canonical strings after whitespace collapse
    "Mini-lessons for PERSUASIVE & OPINION WRITING UNITS": "Persuade",
    "Mini-lessons for INFORMATIVE WRITING UNITS": "Inform",
    "Mini-lessons for NARRATIVE WRITING UNITS": "Entertain",
    "Mini-lessons for NARRATIVE WRITING": "Entertain",
    # Fallback headers
    "PERSUASIVE & OPINION WRITING UNITS": "Persuade",
    "INFORMATIVE WRITING UNITS": "Inform",
    "NARRATIVE WRITING UNITS": "Entertain",
    "NARRATIVE WRITING": "Entertain",
}

_K2_ENTRY_PATTERN = re.compile(
    r"ML\s*#\s*(\d+)\s+p{1,2}\.\s*(\d+)(?:-\d+)?\s+(.+?)(?=\s+ML\s*#|\s*$)"
)


def extract_k2_page(pdf_path: Path, page_index: int = 10) -> dict:
    """Extract K-2 page 11 pacing — lines may contain descriptive text + multiple 'ML #N p. M Title' entries.

    Examples of actual layout:
      'Depending on the writing level of P ML #1 p. 12 Share information'
      'students, they will share stories and ML #2 p. 13 Write about what you know'
    """
    doc = fitz.open(pdf_path)
    page = doc[page_index]
    words = page.get_text("words")
    lines = _reconstruct_lines(words)

    result: dict[str, list[dict]] = {"Persuade": [], "Inform": [], "Entertain": []}
    current_mode: str | None = None
    seen_in_mode: set[tuple[int, str]] = set()

    def _reset_mode(mode: str) -> None:
        nonlocal current_mode, seen_in_mode
        current_mode = mode
        seen_in_mode = set()

    for _, text in lines:
        stripped = re.sub(r"\s+", " ", text).strip()

        # Mode header detection — check longest headers first to avoid
        # "NARRATIVE WRITING" matching before "NARRATIVE WRITING UNITS"
        matched = False
        for header, mode in sorted(_K2_MODE_HEADERS.items(), key=lambda kv: -len(kv[0])):
            if header in stripped:
                _reset_mode(mode)
                matched = True
                break
        if matched:
            continue

        if current_mode is None:
            continue

        # Extract all ML entries from the line (there may be multiple or descriptive text before)
        for match in _K2_ENTRY_PATTERN.finditer(stripped):
            ml_num = int(match.group(1))
            page_num = int(match.group(2))
            title = match.group(3).strip()
            key = (ml_num, title)
            if key in seen_in_mode:
                continue  # de-dupe
            seen_in_mode.add(key)
            result[current_mode].append({
                "title": title,
                "page": page_num,
                "ml_number": ml_num,
            })

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    if not PDF_312.exists():
        print(f"ERROR: PDF not found: {PDF_312}", file=sys.stderr)
        return 1
    if not PDF_K2.exists():
        print(f"ERROR: PDF not found: {PDF_K2}", file=sys.stderr)
        return 1

    pacing = {
        "launch_3_12": {
            "3-5": extract_312_page(PDF_312, 4),
            "6-8": extract_312_page(PDF_312, 5),
            "9-12": extract_312_page(PDF_312, 6),
        },
        "launch_k2": {
            "K-2": extract_k2_page(PDF_K2, 10),
        },
    }

    DATA_DIR.mkdir(exist_ok=True)
    with open(PACING_PATH, "w") as f:
        json.dump(pacing, f, indent=2, ensure_ascii=False)

    print(f"Pacing data saved → {PACING_PATH.relative_to(ROOT)}")
    print()
    for book, bands in pacing.items():
        print(f"{book}:")
        for band, modes in bands.items():
            for mode, items in modes.items():
                with_page = sum(1 for i in items if i.get("page") is not None)
                print(f"  {band:5s}  {mode:10s}  {len(items):3d} items  ({with_page} with page)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
