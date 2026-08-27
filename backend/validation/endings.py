"""Response-ending validator — required closing phrase per query_type (§17.2).

Split out of validation/policy.py (Wave 0 Part 2). Pure stdlib string checks —
no MiniLesson import (validate_grade_band_close below duck-types the lesson
via getattr rather than importing the class, to keep this module dependency-
light). Re-exported from validation.policy.
"""
from __future__ import annotations

import re


# --- Brady's two HOW_TO_TEACH closers (single source of truth) -------------
#
# The single-skill form is the exact line the prompt tells the model to write
# (handlers/how_to_teach.py). The multi-skill form is Brady's refinement for an
# outline that enumerates MORE THAN ONE sub-skill (docx para 332, annotating
# image52.png; narrated @40869): "this skill" has no referent when 3-5 skills
# were just listed, so a multi-skill outline closes with the pick-list question
# instead. VERBATIM — do not reword.
#
# Named ONCE here and shared by BOTH sides so the emitter and the validator can
# never drift, mirroring how REQUIRED_CLOSE_PHRASE (below) is shared with the
# SCRIPTED_ML prompt builder:
#   * the ending VALIDATOR (validate_response_ending) accepts EITHER — both
#     fragments are registered in _ENDING_REQUIRED["HOW_TO_TEACH"] below;
#   * the delivery-seam EMITTER swaps single -> multi when the rendered outline
#     lists >1 skill (handlers._base_text._swap_multi_skill_closer, Brady C8).
HOW_TO_TEACH_SINGLE_SKILL_CLOSER_FRAGMENT = "are you ready for a scripted mini-lesson"
HOW_TO_TEACH_MULTI_SKILL_CLOSER = (
    "Which of these skills do you want to start with? "
    "You can't teach them all in a single lesson."
)
# The distinctive lowercase fragment the validator keys on, DERIVED from the
# constant (its first sentence, lowercased) so the two cannot drift apart.
HOW_TO_TEACH_MULTI_SKILL_CLOSER_FRAGMENT = (
    HOW_TO_TEACH_MULTI_SKILL_CLOSER.split("?")[0].lower()
)


_ENDING_REQUIRED = {
    "HOW_TO_TEACH": (
        HOW_TO_TEACH_SINGLE_SKILL_CLOSER_FRAGMENT,
        HOW_TO_TEACH_MULTI_SKILL_CLOSER_FRAGMENT,
    ),
    # Brady x1 — his response-shapes table (feedback.docx paras 32-33, "Good"
    # in RED = tested-and-approved; video @5682): "'Plan a unit' gets list of
    # priority skills. To be followed by 'Is this helpful? Would you like a
    # general outline of this unit?'". Two sentences, so BOTH fragments are
    # registered with the OFFER first — _isolate_closing_question anchors on
    # the earliest match and moves the WHOLE compound onto its own paragraph
    # (same shape as COACHING_GENERAL/MANAGEMENT below).
    #
    # "is this helpful" is deliberately NOT registered here even though it is
    # Brady's first sentence: COACHING_GENERAL already claims that fragment,
    # and accepting it alone would let a PLAN_UNIT response pass while DROPPING
    # the outline offer — the thing this closer exists to make. The offer is
    # the load-bearing half; requiring it is what keeps the E6 flow reachable
    # (unit -> outline -> lesson).
    #
    # NOT "which of these skills": that is Brady's HOW_TO_TEACH refinement for
    # multi-skill outlines (docx para 332, annotating image52.png; narrated at
    # transcript @40869) — now registered on HOW_TO_TEACH above and emitted by
    # the delivery seam (Brady C8, _swap_multi_skill_closer). Wave 2c's E5b
    # mis-assigned it here and dropped it entirely (a mirrored swap); the x1 fix
    # removed it from PLAN_UNIT, and C8 gave it its correct home on HOW_TO_TEACH.
    "PLAN_UNIT": ("general outline of this unit",),
    "COACHING_GENERAL": ("does this make sense", "is this helpful"),
    # Brady E3 (28:30, doc 128): a MANAGEMENT overview closes with "This was an
    # overview. Which ONE area or SINGLE routine would you like to start with?"
    # — NOT the generic coaching closer. Keyed on the closer's distinctive
    # fragments (any one satisfies); "this was an overview" comes FIRST so the
    # delivery-seam _isolate_closing_question anchors on it and moves the WHOLE
    # closer onto its own paragraph. The prompt side lives in
    # handlers/_prompt_rules.MANAGEMENT_CLOSING_QUESTION_RULE.
    "MANAGEMENT": ("this was an overview", "which one area", "single routine"),
    # v4: THINK_ALOUD closes with an offer to wrap the monologue in a lesson.
    "THINK_ALOUD": ("want me to wrap this in a scripted mini-lesson",),
    # SCRIPTED_ML ending is optional — no entry here means no check.
}

_ENDING_CHECK_WINDOW = 500  # chars from the end to inspect


def required_closing_phrases(query_type: str) -> tuple[str, ...]:
    """Public accessor for a query_type's required closing phrase(s)
    (empty tuple if none registered). Lets delivery-seam normalizers use
    the SAME source of truth as validate_response_ending without importing
    the private _ENDING_REQUIRED dict."""
    return tuple(_ENDING_REQUIRED.get(query_type, ()))


# Where a query_type's closing BLOCK starts — the anchor the delivery-seam
# isolator (handlers._base_text._isolate_closing_question, Brady E5a) inserts
# its paragraph break in front of.
#
# For every type whose REQUIRED phrase opens its closer these coincide, so the
# accessor below falls back to _ENDING_REQUIRED and nothing changes. PLAN_UNIT
# is the one type where "what must be present" and "where the closer starts"
# genuinely differ, so they are registered apart rather than overloading one
# tuple with two jobs:
#
#   Brady x1's closer is TWO sentences — "Is this helpful? Would you like a
#   general outline of this unit?" — and its REQUIRED half sits MID-SENTENCE.
#   Anchoring on the requirement splits his sentence in half; observed live:
#       "Is this helpful? Would you like a\n\ngeneral outline of this unit?"
#   The correct anchor is "is this helpful" — but that CANNOT be a PLAN_UNIT
#   requirement: COACHING_GENERAL owns the fragment, so accepting it alone
#   would let a PLAN_UNIT response pass while dropping the outline offer, which
#   is the whole reason the closer exists (it opens the E6 unit->outline flow).
_CLOSER_ANCHORS = {
    "PLAN_UNIT": ("is this helpful",),
}


def closer_anchor_phrases(query_type: str) -> tuple[str, ...]:
    """Phrases marking the START of a query_type's closing block, for the
    delivery-seam isolator. Defaults to the required closing phrases — correct
    for every type whose requirement opens its closer — so a new closer only
    needs an entry in _CLOSER_ANCHORS when the two genuinely differ."""
    return tuple(_CLOSER_ANCHORS.get(query_type) or required_closing_phrases(query_type))


# Brady E4: coaching/management responses were ending with TWO questions — a
# natural next-step offer AND the forced generic "Does this make sense? Is
# this helpful?" closer stacked on top of it. A concrete next-step offer
# (e.g. "Want me to map out a week of lessons?") is an acceptable SINGLE
# closing question on its own, so these two query_types also accept an
# offer phrase as an ALTERNATIVE to the generic closer below — additive,
# not a replacement: the generic closer alone still passes on its own.
#
# Acceptance is anchored to an actual closing QUESTION: the tail must end
# with "?" AND an offer phrase must appear in that closing sentence (the
# last _OFFER_WINDOW chars). Without the anchor an offer phrase buried in a
# declarative sentence ("...your writers are ready for independent work.")
# would falsely pass, reintroducing the very missing-ending defect this
# validator exists to catch.
_OFFER_ELIGIBLE = {"COACHING_GENERAL", "MANAGEMENT"}
_OFFER_WINDOW = 160  # chars of the closing sentence to scan for an offer phrase
_OFFER_RE = re.compile(
    r"\b(want me to|would you like|shall i|should i|do you want|ready for"
    r"|can i|how about i|would it help)\b",
    re.IGNORECASE,
)


def ends_with_offer_question(text: str) -> bool:
    """True when `text` ends with a concrete next-step OFFER phrased as a
    question — the rstripped tail ends with "?" AND an offer stem appears in
    the closing sentence (the last _OFFER_WINDOW chars).

    Single source of truth for "a valid offer close", shared by
    validate_response_ending (E4 acceptance — an offer is an acceptable SINGLE
    closing question for the offer-eligible query_types) and, on the delivery
    seam, handlers._base_text._dedupe_closing_question (E4 dedup — which only
    strips a redundant generic closer when what remains STILL ends with a
    valid offer question). The "?" anchor is essential: an offer stem buried in
    a declarative sentence ("...your writers are ready for independent work.")
    is NOT a closing question and must not pass, or the missing-ending defect
    this validator exists to catch would slip back in.
    """
    tail = (text or "").rstrip()
    return tail.endswith("?") and bool(_OFFER_RE.search(tail[-_OFFER_WINDOW:]))


def is_offer_eligible(query_type: str) -> bool:
    """query_types whose closer may be a concrete next-step offer question
    (COACHING_GENERAL / MANAGEMENT) in place of the generic "Does this make
    sense?" closer. Single source of truth for both the ending validator and
    the delivery-seam dedup — every OTHER query_type keeps its own registered
    closing phrase and gets no offer exemption."""
    return query_type in _OFFER_ELIGIBLE


def validate_response_ending(query_type: str, response_text: str) -> list[str]:
    """The response must end with the template's designated closing phrase.

    Plan §17.2. SCRIPTED_ML has no entry here (intentionally) — its close is
    grade-band specific, not a single fixed phrase; see
    validate_grade_band_close below for that enforcement.

    Brady E4: for COACHING_GENERAL/MANAGEMENT only, a concrete next-step
    offer is also accepted as the single closing question — see
    _OFFER_ELIGIBLE / _OFFER_RE above.
    """
    required = _ENDING_REQUIRED.get(query_type)
    if not required:
        return []
    tail = (response_text or "").rstrip()[-_ENDING_CHECK_WINDOW:].lower()
    if not any(phrase in tail for phrase in required):
        if is_offer_eligible(query_type) and ends_with_offer_question(response_text):
            return []
        return [
            f"Response for query_type={query_type} must end with one of "
            f"{list(required)}. Current ending (last {_ENDING_CHECK_WINDOW} "
            f"chars): ...{tail[-120:]!r}"
        ]
    return []


# ---------------------------------------------------------------------------
# SCRIPTED_ML Step 4 grade-band close (Brady E1 / non-negotiable #10).
#
# SCRIPTED_ML has no entry in _ENDING_REQUIRED above because its close isn't
# a single fixed phrase — it's grade-band specific: K-2 lessons end "Let's
# go be writers!"; grades 3-12 end "Now it's your turn!". Previously any
# lesson could end "Let's go be writers!" (or omit a close entirely)
# regardless of grade — that was the F60 bug. Enforcement lives in
# validate_lesson_policy (validation/policy.py), which has the grade AND the
# structured MiniLesson's step_4_close field; validate_response_ending above
# only sees free text + query_type, so it can't apply this rule.
# ---------------------------------------------------------------------------


def scripted_ml_grade_band(grade: str | None) -> str:
    """2-way band for the Smekens close: K-2 vs 3-12.

    Every specific grade (K,1,2 / 3..12) and every clean GradeValue band
    (K-2, 3-5, 6-8, 9-12, K-12, all) maps here. K-12/all/unknown fall to
    "3-12" deliberately — a scripted mini-lesson is grade-specific in
    practice, so the stricter default beats staying silent.
    """
    return "K-2" if str(grade or "").strip() in {"K", "1", "2", "K-2"} else "3-12"


# The two exact non-negotiable close phrases, keyed by band. SINGLE SOURCE
# OF TRUTH: the generation prompt builder imports this dict too
# (handlers/scripted_ml_prompt.py), so the instruction the model is given
# and the check it must pass can never drift apart.
REQUIRED_CLOSE_PHRASE: dict[str, str] = {
    "K-2": "Let's go be writers!",
    "3-12": "Now it's your turn!",
}


def _normalize_close(text: str) -> str:
    """Lowercase and fold the Unicode right single quote (U+2019 ’) to a
    straight apostrophe. LLMs frequently emit smart quotes in contractions
    ("Now it’s your turn!"), which would otherwise fail a straight-quote
    substring match and falsely flag a compliant lesson on Brady's
    non-negotiable #10. Same class of fix validation/forbidden_words.py
    applies via its ``['’]`` character class (see lines 19, 35 there).
    """
    return text.lower().replace("’", "'")


def validate_grade_band_close(lesson, grade_band: str) -> list[str]:
    """Brady E1 (Smekens non-negotiable #10): K-2 lessons close Step 4 with
    "Let's go be writers!"; grades 3-12 close with "Now it's your turn!".

    `lesson` is duck-typed (any object with a `step_4_close` attribute,
    typically a `generation.lesson.MiniLesson`) so this module doesn't need
    to import the schema.
    """
    phrase = REQUIRED_CLOSE_PHRASE.get(
        grade_band, REQUIRED_CLOSE_PHRASE["3-12"]
    )
    # Needle: the phrase, apostrophe-normalized, with the trailing "!"
    # dropped so a close ending in "." still matches (Brady's own library
    # uses both — e.g. scripts/phase14_data/drawing_labeling_mls.py).
    needed = _normalize_close(phrase).rstrip("!")
    close = _normalize_close(getattr(lesson, "step_4_close", "") or "")
    return [] if needed in close else [
        f"Brady E1 (Smekens non-negotiable): a grade-band {grade_band} scripted "
        f"mini-lesson must end Step 4 with \"{phrase}\"."]
