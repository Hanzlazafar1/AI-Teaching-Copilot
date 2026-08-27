"""Deterministic resolution of an ordinal pick against the offered list.

An ORDINAL is arithmetic. A NAME is judgment. This module owns only the
arithmetic: when the teacher's reply unambiguously names a position in the
list we actually offered, code resolves it and the LLM's guess does not get
a vote. Everything else returns None and stays QU's call — a fuzzy title
("Snapple details") is genuine semantic matching and belongs to the model.

Why it exists: with nothing persisted, resolving "number 4" was left to LLM
arithmetic over rendered markdown, which shipped item 3 to a teacher with no
signal anything was wrong (recert 2026-07-16; drive session 16a8e8a5).

Brady's asymmetry governs every ambiguous case: silence is cheap, a wrong
lesson is a lie. When in doubt this returns None rather than a guess.
"""
from __future__ import annotations

import re

_WORD_ORDINALS: dict[str, int] = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11,
    "twelfth": 12,
}

# Form 1 — an explicit pick anchor immediately before a number:
#   "number 4", "no. 4", "#2", "option 3", "item 5"
# The anchor is REQUIRED. A bare "4th" is not a pick: it is far more often a
# grade ("4th grade"), which canonicalizer._GRADE_ORDINAL_RE owns.
_ANCHORED_NUMBER_RE = re.compile(
    r"(?:\bnumber\b|\bno\.|#|\boption\b|\bitem\b)\s*(\d+)\b",
    re.IGNORECASE,
)

# Form 2 — "the third one" / "the 3rd one" / "the fourth lesson".
# The trailing noun is REQUIRED, so "my second graders" and "4th grade" can
# never reach here.
_THE_ORDINAL_RE = re.compile(
    r"\bthe\s+(" + "|".join(_WORD_ORDINALS) + r"|\d+(?:st|nd|rd|th))\s+"
    r"(?:one|lesson|skill|item|option)\b",
    re.IGNORECASE,
)


# A list item: "1. ", "2) ", "- ", "* ", "• ".
_LIST_LINE_RE = re.compile(r"^\s*(?:\d+[.)]\s+|[-*•]\s+)(.+?)\s*$")


def _scan_list_lines(text: str, max_items: int) -> list[str]:
    """Every item of the FIRST list in the text, in order.

    Blank lines do NOT end the list: Brady's Fm2 paragraph-blocks put one
    between every item, and treating a blank as a terminator returned a
    single item holding one whole paragraph. Prose after the list does end it.
    """
    items: list[str] = []
    in_list = False
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _LIST_LINE_RE.match(line)
        if m:
            in_list = True
            items.append(m.group(1))
            if len(items) >= max_items:
                break
        elif in_list:
            break
    return items


def _lead_sentence(item: str) -> str:
    """The sub-skill itself, without the explanation trailing it.

    HOW_TO_TEACH bullets are whole paragraphs — a bolded sub-skill sentence
    followed by why it matters. The skill is the leading sentence.
    """
    plain = re.sub(r"[*_]{1,2}", "", item).strip()
    lead = re.split(r"(?<=\.)\s+", plain, maxsplit=1)[0]
    return lead.strip().rstrip(".:,;")


def extract_offered_skills(text: str, max_items: int = 12) -> list[str]:
    """The skills this response offered the teacher to pick from, in order.

    Any response that renders a countable numbered/bulleted list offers those
    items as picks, whatever handler produced it: a COACHING or MANAGEMENT
    answer that lists options is as pointable as a PLAN_UNIT unit outline
    (Brady C14 — a teacher picked "number 4" off a COACHING list and got the
    raw teacher-directive bullet as the lesson title, because a request_type
    gate here dropped the list before it could be recorded). The result is a
    record of what we ACTUALLY rendered, which is what an ordinal refers to.

    Empty when the text is empty or contains no list. This function does not
    decide a pick is MADE: resolve_ordinal_pick fires only on an explicit
    in-range ordinal anchor, and only against the most recent assistant turn
    (query/qu_v4.py::_last_offered_skills) — so a list the teacher never points
    at stays inert. A structured handler (SCRIPTED_ML) never reaches here at
    all; only the five text handlers record an offered list.
    """
    if not text:
        return []
    return [_lead_sentence(i) for i in _scan_list_lines(text, max_items)]


# A HOW_TO_TEACH bullet is an instruction to the TEACHER ("Teach students to
# build a paragraph"). Naming the lesson's skill with it renders as "today
# we're going to Teach students to build a paragraph" — inside a script read
# aloud to children (measured live: 5/10 of HOW_TO_TEACH picks).
#
# Only these prefixes are strippable, because only these leave a bare verb
# phrase behind — which is what Brady wants a skill called ("I love that it's
# a verb. It's a statement"). "Teach students THE difference between..." and
# "Teach students THAT each table..." are deliberately absent: stripping them
# yields a noun phrase or a dangling clause, which is worse than leaving the
# prefix. Bounded like the E4 dedup — it can only ever return a verb phrase
# or the original string, never a mangled fragment.
_TEACHER_IMPERATIVE_RE = re.compile(
    r"^teach\s+(?:students\s+)?(?:how\s+to|to)\s+(?=\S)",
    re.IGNORECASE,
)


def skill_name_from_offer(item: str) -> str:
    """The skill an offered item names, as the teacher would say it.

    PLAN_UNIT items are already verb-based skill names and pass through
    untouched (0/10 leak live). Only a teacher-directed imperative whose
    remainder is a verb phrase is normalised.
    """
    if not item:
        return item
    return _TEACHER_IMPERATIVE_RE.sub("", item, count=1)


def _ordinals_in(message: str) -> set[int]:
    """Every distinct 1-based position the message points at."""
    found: set[int] = set()
    for m in _ANCHORED_NUMBER_RE.finditer(message):
        found.add(int(m.group(1)))
    for m in _THE_ORDINAL_RE.finditer(message):
        token = m.group(1).lower()
        if token in _WORD_ORDINALS:
            found.add(_WORD_ORDINALS[token])
        else:
            found.add(int(re.sub(r"\D", "", token)))
    return found


def resolve_ordinal_pick(message: str, offered: list[str]) -> str | None:
    """Return the offered item the message names by ordinal, else None.

    None means "not ours to answer" — no ordinal, an out-of-range position,
    or more than one distinct position (which is not a single pick). The
    caller must leave QU's own resolution untouched on None.
    """
    if not message or not offered:
        return None
    positions = _ordinals_in(message)
    if len(positions) != 1:
        return None
    pos = positions.pop()
    if not 1 <= pos <= len(offered):
        return None
    return offered[pos - 1]
