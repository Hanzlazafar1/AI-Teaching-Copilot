"""Invariant checkers for the Brady Protected Set.

Shared by the offline baseline gate (tests/unit/test_baseline_invariants.py) and
the live golden-master (tests/acceptance/test_protected_baseline.py). Each checker
takes a ChatResponse dict and returns (ok: bool, detail: str). See §1c of
session-management/implementation-strategy.md.
"""
from __future__ import annotations

import re
from typing import Any, Iterator

from validation.citations import _K2_FULL_TITLE_RE, _TEAL_FULL_TITLE_RE
from validation.endings import scripted_ml_grade_band
from validation.policy import validate_no_forbidden_words

_STEP3 = ("help me with the next", "turn and talk", "back to me", "this is some of what")
_LESSON_STEPS = ("step_1_introduce", "step_2a_tell", "step_2b_show", "step_3_interact", "step_4_close")
_FIRST_PERSON = re.compile(r"\b(i|i'?m|i'?ll|i'?ve|i'?d)\b", re.IGNORECASE)
# Fm4 header: "Grade X", "Grade X | <Mode adjective>", or "Grade X | Management"
# (mirrors handlers/formatting.format_lesson_header). Anything else — notably the
# raw "Grade: N | Mode: …" form or an empty header — must fail.
#
# The `grade` group is what `cites_own_grade_band` bands. It is a CAPTURE on the
# header pattern `header_correct` already uses rather than a second "what is a
# header?" pattern of its own: two patterns claiming to define the header would
# drift, and then the two checkers would disagree about which response is even
# graded. (`header_correct` only reads the match's truthiness, so adding the
# group changes nothing it accepts or rejects.)
_HEADER_RE = re.compile(
    r"^Grade (?P<grade>\S+)( \| (Informative|Persuasive|Narrative|Management))?$"
)

#: The literal a `[[src:<chunk_id>]]` marker opens with — see `no_marker_survives`.
#:
#: DELIBERATELY NOT DERIVED from either pattern in handlers/citation.py, and that
#: independence is the whole value of this invariant. citation.py splits marker
#: recognition from marker removal by CONTRACT (a narrow `_MARKER_RE` the prompt
#: promises; a wider `_MARKER_SWEEP_RE` that removes) precisely because the
#: scrubber mangles 11 of 710 corpus ids into a shape the narrow grammar rejects.
#: This is the THIRD contract in that family — AUDIT — and it must be wider than
#: both, because a check built from the sweep's own pattern is a tautology: the
#: sweep removes exactly what the sweep matches, so such a check could never fail
#: and would certify the sweep against itself.
#:
#: Wider than `_MARKER_RE`: catches the scrubber-mangled `[[src:ccss- -…]]` (a
#: SPACE, outside the pinned id class). Wider than `_MARKER_SWEEP_RE` too: that
#: one still needs a closing `]]`, on the same line, within 200 chars — this
#: needs nothing but the opening literal, so a marker that escapes the sweep's
#: bounds is still caught here rather than shipped.
_MARKER_PREFIX = "[[src:"

#: The two Launch books, keyed by the grade band each one serves.
#:
#: The regexes are the app's OWN canonical answer to "does this text name book
#: X?" (validation/citations.py, where `validate_book_citation` and the scrubber
#: both read them) — they already tolerate the writer/writer's and "K-2"/"K 2"
#: spellings a model emits. Reusing them keeps this from becoming a third
#: divergent answer, the lesson validation/citations.py:126 records about
#: PAGE_TOKEN.
#:
#: The keys are `scripted_ml_grade_band`'s two bands, so "which book does this
#: grade belong to?" is answered by the same function the app's own Brady-E1
#: close uses. That coherence is the point: if the app closes a lesson "Now it's
#: your turn!" (its 3-12 decision) it must not, in the same breath, point the
#: teacher at the K-2 book.
_BAND_TITLE_RE = {
    "K-2": _K2_FULL_TITLE_RE,
    "3-12": _TEAL_FULL_TITLE_RE,
}


def _lesson(resp: dict) -> dict | None:
    r = resp.get("response")
    return r if isinstance(r, dict) else None


def _text(resp: dict) -> str:
    r = resp.get("response")
    if isinstance(r, dict):
        return " ".join(str(r.get(k) or "") for k in _LESSON_STEPS)
    return str(r or "")


def _walk_strings(value: Any) -> Iterator[str]:
    """Every string anywhere in a delivered payload, whatever its shape."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _walk_strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _walk_strings(v)


def _delivered_text(resp: dict) -> str:
    """EVERY string the teacher is delivered — deliberately wider than `_text`.

    `_text` joins the five lesson STEP fields only. On a structured SCRIPTED_ML
    response that cannot see `book_citation` — the field the Fm5 footer actually
    ships in (handlers/scripted_ml.py::_build_outcome puts it there, and
    routes_v4.py:211-213 ships `structured` and discards `response_text`). A
    citation invariant reading `_text` would therefore be blind to every
    SCRIPTED_ML citation in the pack and pass vacuously on all 9 of them: the
    unfailable check this pair of invariants exists to end. Measured on
    baseline-2026-07-16: `_text` sees 3 of the 11 cases that cite a book;
    this sees all 11.

    Walks the structure rather than naming fields, so a field added to the
    payload later is swept without anyone remembering to come back here.
    `source_chunk_id` — the one field a teacher must never see — is popped
    before delivery (scripted_ml.py::_finalize_ml_delivery), so everything this
    walk reaches is teacher-visible by construction.

    Scoped to `resp["response"]`, like every other checker here: the sibling
    top-level keys (`sources`, `parsed_query`, …) are the frontend's debug
    sidebar, not the answer.
    """
    return "\n".join(_walk_strings(resp.get("response")))


def four_step(resp):
    les = _lesson(resp)
    ok = bool(les) and all((les.get(k) or "").strip() for k in _LESSON_STEPS)
    return ok, "structured 5-field lesson" if ok else "not a structured lesson"


def depth_2a2b(resp):
    """SCRIPTED_ML: Step 2B is much longer than Step 1 + first-person modeling.
    THINK_ALOUD (string monologue): substantial first-person modeling."""
    les = _lesson(resp)
    if les:
        s1 = len((les.get("step_1_introduce") or "").split())
        s2b_text = les.get("step_2b_show") or ""
        s2b = len(s2b_text.split())
        ok = s2b >= 3 * max(s1, 1) and bool(_FIRST_PERSON.search(s2b_text))
        return ok, f"2B words={s2b} vs step1={s1}, first_person={bool(_FIRST_PERSON.search(s2b_text))}"
    txt = _text(resp)
    ok = len(txt.split()) >= 80 and bool(_FIRST_PERSON.search(txt))
    return ok, f"monologue words={len(txt.split())}, first_person={bool(_FIRST_PERSON.search(txt))}"


def smekens_step3(resp):
    les = _lesson(resp)
    s3 = (les.get("step_3_interact") or "").lower() if les else _text(resp).lower()
    missing = [p for p in _STEP3 if p not in s3]
    return (not missing), f"missing={missing}"


def no_forbidden(resp):
    errs = validate_no_forbidden_words(_text(resp))
    return (errs == []), f"errors={errs}"


def _ending(resp, needle):
    # Fold the Unicode right single quote (’) to a straight apostrophe before
    # matching. LLMs emit "Let's go be writers!" / "Now it's your turn!" with
    # either quote style; the grade-band close VALIDATOR already normalizes it
    # (validation/endings.py `_normalize_close`), so this golden-master checker
    # must too — otherwise it flakes on quote style, not on the actual ending.
    text = _text(resp).lower().replace("’", "'")
    return (needle in text), f"'{needle}' present"


def ending_k2(resp):
    return _ending(resp, "let's go be writers")


def ending_3_12(resp):
    return _ending(resp, "now it's your turn")


def ending_how_to_teach(resp):
    from validation.endings import required_closing_phrases
    phrases = required_closing_phrases("HOW_TO_TEACH")
    text = _text(resp).lower().replace("’", "'")
    return any(p in text for p in phrases), f"one of {list(phrases)} present"


def ending_plan_unit(resp):
    from validation.endings import required_closing_phrases
    phrase = required_closing_phrases("PLAN_UNIT")[0]
    return (phrase in _text(resp).lower()), f"'{phrase}' present"


def names_strategy_explained(resp):
    return _ending(resp, "pizza")  # pizza-table case: the named strategy must appear


def grade_locks(resp):
    les = _lesson(resp)
    g = (les or {}).get("grade_level") if les else (resp.get("session_state") or {}).get("grade")
    return (str(g) == "4"), f"grade={g} (expect carried 4)"


def _header_value(resp: dict) -> str:
    """The header string to validate. For a structured lesson (SCRIPTED_ML) it's
    the payload's `header` field (Fm4); for a text handler (the 5 markdown
    handlers, e.g. MANAGEMENT) it's the first non-empty line of the response,
    where the header is prepended as its own leading block."""
    les = _lesson(resp)
    if les is not None:
        return les.get("header") or ""
    return next((ln.strip() for ln in str(resp.get("response") or "").splitlines() if ln.strip()), "")


def header_correct(resp):
    """Fm4: the leading 'Grade X[ | <Mode adjective|Management>]' header is
    well-formed. Rejects the raw 'Grade: N | Mode: …' form and an empty/absent
    header. Works for both the structured-lesson and text-handler response shapes."""
    h = _header_value(resp)
    return bool(_HEADER_RE.match(h)), f"header={h!r}"


def no_marker_survives(resp):
    """A `[[src:` marker must NEVER reach a teacher — on any case, any handler.

    The per-claim citation design (plan (2)) has the model POINT at the block it
    built each claim from and code SPEAK the citation from that chunk's typed
    metadata. The marker is the pointing: internal syntax, resolved and removed
    before delivery. A surviving one is strictly worse than an uncited response —
    it is machine syntax in a lesson a teacher is about to read aloud.

    `handlers/citation.py::resolve_markers` states that guarantee first among
    its three ("No marker is EVER teacher-visible"). Until this checker, NOTHING
    in the live gate could observe it: the whole safety net was citation-blind
    (11 invariant keys, none about citations), so every "zero new regressions"
    claim on citation work was unfailable on the dimension that work changed.

    Substring, not regex, and not either citation.py pattern — see _MARKER_PREFIX
    for why this must be wider than the code it audits.
    """
    text = _delivered_text(resp)
    n = text.count(_MARKER_PREFIX)
    if not n:
        return True, "no raw markers"
    at = text.index(_MARKER_PREFIX)
    return False, f"{n} raw marker(s) shipped, first at {text[at:at + 60]!r}"


def cites_own_grade_band(resp):
    """A response must not point the teacher at the OTHER band's Launch book.

    Pages COLLIDE across the two books — Teal p.64 is "Add 'leg' sentences per
    'table-top' reason"; K-2 p.64 is "Draw feelings on faces" — so a page number
    is meaningless without the book it belongs to. A grade-3 answer citing the
    K-2 book sends a teacher to a real page of the wrong book: confident,
    correctly formatted, and wrong, with no signal to the reader.

    Engages only when a Launch book is actually cited (an uncited response has
    nothing to be inconsistent with), and then DEMANDS the grade rather than
    shrugging: a citation we cannot band is a citation we cannot check, and
    "cannot check" must read as a failure here, not as a pass. That asymmetry is
    the difference between an invariant and a decoration.

    NOT `citation_grounded` ("the cited page resolves to an in-context chunk"),
    which was considered and rejected on evidence: envelope `sources` carry no
    `page` (839a051), so it degrades to always-pass — and the weaker "cited book
    appears in sources" passes the page-drift defect unchanged, that being the
    defect's own mechanism. Both would be more of exactly what this task exists
    to remove.

    Band mapping is `scripted_ml_grade_band`'s; it resolves a spanning or
    unknown grade to the stricter "3-12" deliberately (see its docstring). A
    header carrying such a grade alongside a K-2 citation therefore fails, which
    is the right way for a safety net to meet a case nobody has thought about.
    """
    text = _delivered_text(resp)
    cited = sorted(band for band, rx in _BAND_TITLE_RE.items() if rx.search(text))
    if not cited:
        return True, "cites no Launch book"
    m = _HEADER_RE.match(_header_value(resp))
    if not m:
        return False, (
            f"cites the {'/'.join(cited)} book but the response states no "
            f"'Grade X' header — the band cannot be verified"
        )
    grade = m.group("grade")
    band = scripted_ml_grade_band(grade)
    wrong = [b for b in cited if b != band]
    if wrong:
        return False, (
            f"Grade {grade} (band {band}) cites the {'/'.join(wrong)} book — "
            f"wrong band; pages collide across the two books"
        )
    return True, f"Grade {grade} (band {band}) cites {'/'.join(cited)}"


CHECKERS = {
    "four_step": four_step,
    "depth_2a2b": depth_2a2b,
    "smekens_step3": smekens_step3,
    "no_forbidden": no_forbidden,
    "ending_k2": ending_k2,
    "ending_3_12": ending_3_12,
    "ending_how_to_teach": ending_how_to_teach,
    "ending_plan_unit": ending_plan_unit,
    "names_strategy_explained": names_strategy_explained,
    "grade_locks": grade_locks,
    "header_correct": header_correct,
    "no_marker_survives": no_marker_survives,
    "cites_own_grade_band": cites_own_grade_band,
}


def check_all(case, resp: dict):
    """Return [(invariant, ok, detail), ...] for one case's ChatResponse dict."""
    return [(inv, *CHECKERS[inv](resp)) for inv in case.invariants]
