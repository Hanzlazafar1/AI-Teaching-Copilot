"""Campaign judge — turn one Brady-alignment *claim* + a driven *Envelope*
into a :class:`Verdict`.

Module 2 of 4 (drive → **judge** → calibrate → verify) for the Brady-alignment
verification campaign (design spec §7). The judge is the campaign's single
opinion-former: given a claim (which observable to check, by which method) and
the parsed ``/api/chat`` response, it emits ALIGNED / MISALIGNED / UNCERTAIN
with a confidence, a human rationale, and the concrete evidence it saw.

Four dispatch methods (``claim["judge_method"]``):

  * **deterministic** — run the real ``validation/`` validator named in
    ``claim["observable"]`` on the flattened response text. A reported
    violation → MISALIGNED; clean → ALIGNED; validator inapplicable to the
    response shape → UNCERTAIN (never a false ALIGNED).
  * **llm-judge** — gpt-4o @ ``temperature=0`` with the claim's ``rubric`` +
    the response text → a structured :class:`_LLMJudgment`, passed through.
  * **hybrid** — the deterministic validator AND the llm-judge must both pass
    for ALIGNED; a validator failure is authoritative → MISALIGNED; the
    validator passing while the llm disagrees → UNCERTAIN (disagreement).
  * **launch-first** — read ``sources[].source_tier`` + ``source_document`` and
    check, **per ``query_type``**, that the right provenance holds the top
    tier: skill-seeking/COACHING/MANAGEMENT → Launch-first; **PLAN_UNIT →
    PIE-first is CORRECT and must NOT be flagged**.

Honesty rules baked in (spec §1/§6): a NON_VERDICT envelope (upstream error)
is **never scored**; an unknown method/observable → UNCERTAIN, not a crash and
not a silent pass; provenance is classified **independently** of the reranker
so the verifier can catch a reranker bug rather than inherit it.

The LLM client is injected (``openai_client=``) — in tests it is stubbed, so
this module makes **no** network calls under the always-run gate. When None,
a synchronous ``openai.OpenAI`` is built lazily from ``config.settings``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field

from generation.lesson import MiniLesson
from validation.endings import scripted_ml_grade_band, validate_grade_band_close
from validation.forbidden_words import validate_no_forbidden_words
from validation.structure import (
    validate_lesson_depth,
    validate_step_2b_monologue,
    validate_step_3_phrases,
)
from validation.vocabulary import (
    validate_details_not_reasons,
    validate_story_only_narrative,
)

#: The campaign judge model + temperature (spec §7 "Judge control").
JUDGE_MODEL = "gpt-4o"
JUDGE_TEMPERATURE = 0


# ---------------------------------------------------------------------------
# Verdict + LLM structured-output schema
# ---------------------------------------------------------------------------


@dataclass
class Verdict:
    """One judged claim outcome.

    ``status`` is the campaign verdict; ``confidence`` is 1.0 for exact
    deterministic checks and the model's self-reported confidence for LLM
    legs; ``method`` echoes the dispatch used; ``evidence`` carries the
    concrete data the verdict rests on (validator findings, a response
    snippet, or the tier/provenance summary) so the report can quote it.
    """

    status: Literal["ALIGNED", "MISALIGNED", "UNCERTAIN"]
    confidence: float
    rationale: str
    method: str
    evidence: str = ""


class _LLMJudgment(BaseModel):
    """Structured output the campaign judge model must return (temp 0)."""

    status: Literal["ALIGNED", "MISALIGNED", "UNCERTAIN"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


_LLM_JUDGE_SYSTEM = (
    "You are a strict alignment judge for a K-12 writing-coach assistant "
    "grounded in Smekens Education methodology. You are given a RUBRIC (the "
    "specific, documented Brady rule to check) and a RESPONSE (the assistant's "
    "output). Decide whether the RESPONSE is ALIGNED or MISALIGNED with the "
    "RUBRIC. Use UNCERTAIN only when the RESPONSE genuinely does not give you "
    "enough to decide. Judge ONLY the rubric's rule — not overall quality. "
    "Return a status, a calibrated confidence in [0,1], and a one-sentence "
    "rationale that cites concrete evidence from the RESPONSE."
    # Multi-turn probes only (#56). Deliberately worded so context can only
    # make the judge BETTER-INFORMED, never more lenient: earlier turns are
    # evidence for a flow rule, and are explicitly NOT a licence to excuse a
    # RESPONSE that breaks the rubric on its own terms. The false-ALIGNED
    # direction is the campaign's blocking gate.
    " Some inputs also include EARLIER TURNS — the same conversation before "
    "the RESPONSE. They are context, not the thing being judged. When the "
    "RUBRIC describes a FLOW across turns (e.g. 'must ask before it delivers'), "
    "use them as evidence and judge the flow. Otherwise judge the RESPONSE on "
    "its own terms: an earlier turn NEVER excuses a RESPONSE that breaks the "
    "rubric, and never counts as the RESPONSE having done something itself."
)


# ---------------------------------------------------------------------------
# Response flattening + lesson reconstruction
# ---------------------------------------------------------------------------

# A SCRIPTED_ML response is a MiniLesson dict; every other handler returns a
# free-text string. The text validators need one flat string; the lesson-shape
# validators need the structured MiniLesson back.
_LESSON_FIELDS = (
    "skill_focus", "grade_level", "writing_mode",
    "step_1_introduce", "step_2a_tell", "step_2b_show",
    "step_3_interact", "step_4_close",
)
# What the judge FLATTENS into evidence text: the MiniLesson fields PLUS every
# deterministic transform the delivery seam puts on ``structured`` alongside
# them. Those transform keys are NOT MiniLesson model fields, so they are
# deliberately kept out of ``_LESSON_FIELDS`` (the reconstruction whitelist used
# at ``_response_as_lesson``) and added only here — if a transform is missing
# from this tuple the LLM judge never sees it and its claim false-MISALIGNs on a
# feature that actually shipped. Keep in sync with the seam
# (handlers.scripted_ml._finalize_ml_delivery) + its producers:
#   * ``header``          — Fm4 grade|mode header (renders at the top).
#   * ``one_skill_guard`` — Brady S3 guard, set at handlers/__init__.py.
#   * ``book_citation``   — Fm5 soft citation footer, set in _build_outcome.
#   * ``followup``        — Brady E2 teacher-facing customization close.
# Lead-ins first, then the lesson, then the footers — so the flattened text
# mirrors the teacher's reading order and the truncated ``response[:240]``
# evidence snippet leads with the header.
_JUDGE_TEXT_FIELDS = (
    "header", "one_skill_guard", *_LESSON_FIELDS, "book_citation", "followup",
)
# The step fields that must be present for a dict to count as a lesson.
_LESSON_REQUIRED = (
    "step_1_introduce", "step_2b_show", "step_3_interact", "step_4_close",
)


def _get(envelope: Any, key: str, default: Any = None) -> Any:
    """Read a key from an Envelope or a plain dict (both expose ``.get``)."""
    getter = getattr(envelope, "get", None)
    if callable(getter):
        return getter(key, default)
    return default


def _looks_like_lesson(value: Any) -> bool:
    return isinstance(value, dict) and all(k in value for k in _LESSON_REQUIRED)


def _flatten_response(envelope: Any) -> str:
    """Flatten the envelope's ``response`` into one text block.

    A free-text response is returned as-is. A SCRIPTED_ML lesson dict is
    joined from its field values (the Fm4 header plus all the teacher-authored
    prose the text validators must inspect). Any other dict falls back to
    joining its string values so a validator still sees the visible text.
    """
    resp = _get(envelope, "response")
    if isinstance(resp, str):
        return resp
    if _looks_like_lesson(resp):
        return "\n\n".join(str(resp.get(f, "") or "") for f in _JUDGE_TEXT_FIELDS)
    if isinstance(resp, dict):
        return "\n\n".join(str(v) for v in resp.values() if isinstance(v, str))
    return "" if resp is None else str(resp)


def _response_as_lesson(envelope: Any) -> Optional[MiniLesson]:
    """Reconstruct a MiniLesson from a SCRIPTED_ML response dict, else None."""
    resp = _get(envelope, "response")
    if not _looks_like_lesson(resp):
        return None
    try:
        return MiniLesson(**{k: str(resp.get(k, "") or "") for k in _LESSON_FIELDS})
    except Exception:
        return None


def _snippet(text: str, limit: int = 240) -> str:
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"


def _evidence(envelope: Any, errors: Optional[list[str]] = None) -> str:
    parts: list[str] = []
    if errors:
        parts.append("findings: " + " | ".join(errors))
    flat = _flatten_response(envelope)
    if flat:
        parts.append(f"response[:240]={_snippet(flat)!r}")
    return "  ".join(parts)


# ---------------------------------------------------------------------------
# Grade / mode / query_type extraction (claim override → response → parsed →
# session_state), so the parameterized validators get their real inputs.
# ---------------------------------------------------------------------------


# The app renders a lesson's grade_level as either a canonical GradeValue
# ("K", "3", "K-2") or a spelled-out display ("Kindergarten", "Grade 5"). The
# band + young-grade-carve-out checks need the canonical form — else a correct
# K lesson labeled "Kindergarten" bands to 3-12 and fails E1 (a false
# MISALIGNED on a non-negotiable). PK/pre-k entries come first so they win over
# the "kindergarten" substring in "prekindergarten".
_GRADE_WORDS = {
    "prekindergarten": "PK", "pre-kindergarten": "PK", "prek": "PK", "pre-k": "PK",
    "kindergarten": "K", "kinder": "K",
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5",
    "sixth": "6", "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10",
    "eleventh": "11", "twelfth": "12",
}
_CANONICAL_GRADES = {"K", "PK", "K-2", "3-5", "6-8", "9-12", "K-12", "all"}
_GRADE_NUM_RE = re.compile(r"\b(1[0-2]|[1-9])\b")


def _normalize_grade(raw: Optional[str]) -> Optional[str]:
    """Map a display grade to its canonical form (``"Kindergarten"`` -> ``"K"``,
    ``"Grade 5"`` -> ``"5"``); canonical grades/bands pass through unchanged."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s in _CANONICAL_GRADES or (s.isdigit() and 1 <= int(s) <= 12):
        return s
    low = s.lower()
    for word, canon in _GRADE_WORDS.items():
        if word in low:
            return canon
    if "-" not in s:  # don't mangle a band like "3-5"
        m = _GRADE_NUM_RE.search(low)
        if m:
            return m.group(1)
    return s


def _grade(envelope: Any, claim: dict) -> Optional[str]:
    """The turn's grade, NORMALIZED to canonical form so band/carve-out checks
    don't mis-band a spelled-out display grade. Claim override wins, then the
    lesson's grade_level, then parsed_query, then session_state."""
    raw: Optional[str] = None
    if claim.get("grade") is not None:
        raw = str(claim["grade"])
    else:
        resp = _get(envelope, "response")
        pq = _get(envelope, "parsed_query")
        ss = _get(envelope, "session_state")
        if isinstance(resp, dict) and resp.get("grade_level"):
            raw = str(resp["grade_level"])
        elif isinstance(pq, dict) and pq.get("grade_level"):
            raw = str(pq["grade_level"])
        elif isinstance(ss, dict) and ss.get("grade"):
            raw = str(ss["grade"])
    return _normalize_grade(raw)


def _mode(envelope: Any, claim: dict) -> Optional[str]:
    if claim.get("mode") is not None:
        return claim["mode"]
    resp = _get(envelope, "response")
    if isinstance(resp, dict) and resp.get("writing_mode"):
        return resp["writing_mode"]
    pq = _get(envelope, "parsed_query")
    if isinstance(pq, dict) and pq.get("writing_mode"):
        return pq["writing_mode"]
    ss = _get(envelope, "session_state")
    if isinstance(ss, dict):
        return ss.get("writing_mode") or ss.get("mode")
    return None


def _query_type(envelope: Any, claim: dict) -> str:
    pq = _get(envelope, "parsed_query")
    if isinstance(pq, dict) and pq.get("query_type"):
        return pq["query_type"]
    return claim.get("query_type", "DEFAULT")


# ---------------------------------------------------------------------------
# Deterministic validator registry — maps claim["observable"] → an adapter
# that supplies each validator's real signature from the envelope. Adapters
# return list[str] (validator errors; [] = clean) or None (inapplicable).
# ---------------------------------------------------------------------------


def _v_forbidden(claim: dict, envelope: Any) -> Optional[list[str]]:
    return validate_no_forbidden_words(_flatten_response(envelope))


def _v_step3(claim: dict, envelope: Any) -> Optional[list[str]]:
    lesson = _response_as_lesson(envelope)
    return None if lesson is None else validate_step_3_phrases(lesson)


def _v_grade_band_close(claim: dict, envelope: Any) -> Optional[list[str]]:
    lesson = _response_as_lesson(envelope)
    if lesson is None:
        return None
    band = scripted_ml_grade_band(_grade(envelope, claim))
    return validate_grade_band_close(lesson, band)


def _v_details(claim: dict, envelope: Any) -> Optional[list[str]]:
    return validate_details_not_reasons(
        _flatten_response(envelope), _grade(envelope, claim), _mode(envelope, claim)
    )


def _v_story(claim: dict, envelope: Any) -> Optional[list[str]]:
    return validate_story_only_narrative(
        _flatten_response(envelope), _mode(envelope, claim)
    )


# F57 salvage: PK-1/K carry a documented depth carve-out (a shorter monologue
# is CORRECT there). Skip the deterministic ratio floor for young grades and let
# the LLM rubric judge them; enforce the floor for grades 3-12.
_YOUNG_GRADES = {"PK", "PK-1", "K", "1"}


def _v_depth(claim: dict, envelope: Any) -> Optional[list[str]]:
    lesson = _response_as_lesson(envelope)
    if lesson is None:
        return None
    grade = str(_grade(envelope, claim) or "").strip().upper()
    if grade in _YOUNG_GRADES:
        return []  # carve-out: deterministic leg defers to the LLM rubric
    return validate_lesson_depth(lesson) + validate_step_2b_monologue(lesson)


_VALIDATORS: dict[str, Callable[[dict, Any], Optional[list[str]]]] = {
    "validate_no_forbidden_words": _v_forbidden,
    "validate_step_3_phrases": _v_step3,
    "validate_grade_band_close": _v_grade_band_close,
    "validate_details_not_reasons": _v_details,
    "validate_story_only_narrative": _v_story,
    "validate_lesson_depth": _v_depth,
}

# Friendly aliases so a claim may name the rule rather than the function.
_VALIDATOR_ALIASES = {
    "banned-words": "validate_no_forbidden_words",
    "banned_words": "validate_no_forbidden_words",
    "forbidden-words": "validate_no_forbidden_words",
    "forbidden_words": "validate_no_forbidden_words",
    "step-3-phrases": "validate_step_3_phrases",
    "step_3_phrases": "validate_step_3_phrases",
    "grade-band-close": "validate_grade_band_close",
    "e1": "validate_grade_band_close",
    "details-not-reasons": "validate_details_not_reasons",
    "n1": "validate_details_not_reasons",
    "story-only-narrative": "validate_story_only_narrative",
    "n2": "validate_story_only_narrative",
    "lesson-depth": "validate_lesson_depth",
    "depth": "validate_lesson_depth",
    "2a2b": "validate_lesson_depth",
}


def _resolve_validator(
    observable: str,
) -> Optional[Callable[[dict, Any], Optional[list[str]]]]:
    key = (observable or "").strip()
    key = _VALIDATOR_ALIASES.get(key.lower(), key)
    return _VALIDATORS.get(key)


def _run_validator(claim: dict, envelope: Any) -> tuple[Optional[list[str]], bool]:
    """Run the claim's validator. Returns (errors, known):
      * (list, True) — validator ran; ``[]`` means clean.
      * (None, True) — validator known but inapplicable to this response shape.
      * (None, False) — observable is not a known validator (config error).
    """
    fn = _resolve_validator(claim.get("observable", ""))
    if fn is None:
        return None, False
    return fn(claim, envelope), True


# ---------------------------------------------------------------------------
# Independent Launch/PIE provenance classifiers.
#
# Grounded in the corpus source_document naming (every Launch chunk contains
# "Launching the Writers Workshop"; the PLAN_UNIT primary is the Essential
# Skills PIE doc / SKILL n. sheets). Deliberately a SEPARATE copy from
# retrieval/reranker.py: a verifier that reused the production classifier would
# inherit any provenance bug it is meant to catch (spec §7: verify tier vs
# provenance, not raw order).
# ---------------------------------------------------------------------------


def _doc_is_launch(source_document: str) -> bool:
    return "launching the writers workshop" in (source_document or "").lower()


def _doc_is_pie(source_document: str) -> bool:
    s = (source_document or "").lower()
    return (
        "essential skills" in s
        or "pie" in s
        or "skill 1" in s
        or "skill 2" in s
    )


# PLAN_UNIT is the one query_type whose top source is the PIE doc (Launch sits
# just below — CORRECT, not a violation). Every other in-scope type expects
# Launch-book content at the top tier ("always, always, always").
_PLAN_UNIT = "PLAN_UNIT"


# ---------------------------------------------------------------------------
# OpenAI client (lazy) — only built when a real client wasn't injected.
# ---------------------------------------------------------------------------


def _ensure_client(client: Any) -> Any:
    if client is not None:
        return client
    from openai import OpenAI  # local import — tests always inject a stub
    from config import settings

    kwargs: dict[str, Any] = {"api_key": settings.openai_api_key, "timeout": 60.0}
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return OpenAI(**kwargs)


def _render_for_llm_judge(envelope: Any) -> str:
    """What the TEACHER sees — the view the LLM judge must grade.

    Separate from ``_flatten_response`` on purpose. The deterministic legs scan
    the teacher-visible PROSE for banned words / vocabulary, so field labels must
    never enter their text. The LLM judge has the opposite need: without labels
    it cannot tell one field from the next, and two claims proved that produces
    false verdicts in BOTH directions from the SAME root:

      * f7 — the judge was handed 'Grade 5\\n\\n\\n\\nSnapke details\\n\\n5\\n\\nInform'
        and quoted a header "Grade 5 | Inform" that exists nowhere, at high
        confidence. It had STITCHED `header` to `writing_mode` — the LLM-authored
        field Brady's Fm4 decision deliberately keeps OUT of the teacher's header.
        So it graded a header the teacher never sees. (Campaign #31: "judges
        confabulate quoted evidence at 0.98-1.0 conf".)
      * fm2 — its rubric checks for Brady's step labels ("Step 2A — Tell"), which
        a value-join NEVER emits: 0 of 5 found on every sample, so the rubric
        could not PASS however correct the app was. Its 10/10 MISALIGNED was a
        pure harness artifact; the blocks have shipped since the initial commit.

    So the fix is not to invent a third rendering — it is to show the judge the
    real one. ``handlers.scripted_ml._lesson_to_free_text`` is the same renderer
    behind the teacher-facing text, carrying Brady's own display labels, so the
    labels can never drift from what ships. The delivery fields that
    ``_finalize_ml_delivery`` adds around the body (header, one-skill guard,
    citation, follow-up) are placed where the teacher meets them.

    Free-text responses (every non-SCRIPTED_ML handler, and the whole gold set)
    pass through untouched — their prompt must not drift.
    """
    lesson = _response_as_lesson(envelope)
    if lesson is None:
        return _flatten_response(envelope)
    from handlers.scripted_ml import _lesson_to_free_text

    resp = _get(envelope, "response") or {}
    parts = [
        str(resp.get("header", "") or ""),
        str(resp.get("one_skill_guard", "") or ""),
        _lesson_to_free_text(lesson),
        str(resp.get("book_citation", "") or ""),
        str(resp.get("followup", "") or ""),
    ]
    return "\n\n".join(p for p in parts if p.strip())


def _prior_turns_block(envelope: Any) -> str:
    """Render a multi-turn probe's earlier exchange, or "" for a single turn.

    Returns "" (not a header) when there are no prior turns, so the single-turn
    prompt — which every gold item and the overwhelming majority of probes use —
    stays byte-identical and the calibration set keeps measuring what it did.
    """
    prior = _get(envelope, "prior_turns") or []
    if not prior:
        return ""
    lines = []
    for i, t in enumerate(prior, 1):
        if not isinstance(t, dict):
            continue
        resp = t.get("response")
        if not isinstance(resp, str):
            resp = _flatten_response({"response": resp})
        lines.append(f"[turn {i}] teacher: {t.get('message', '')}\n"
                     f"[turn {i}] assistant: {resp}")
    if not lines:
        return ""
    body = "\n\n".join(lines)
    return ("\nEARLIER TURNS (same conversation, context only — the RESPONSE "
            f"below is what you judge):\n{body}\n")


def _call_llm_judge(claim: dict, envelope: Any, client: Any) -> _LLMJudgment:
    """One gpt-4o @ temp 0 structured-output call. Never raises on refusal."""
    rubric = claim.get("rubric") or claim.get("requirement") or ""
    # The judge grades what the TEACHER sees; the validators keep the raw prose.
    text = _render_for_llm_judge(envelope)
    messages = [
        {"role": "system", "content": _LLM_JUDGE_SYSTEM},
        {"role": "user", "content": f"RUBRIC:\n{rubric}\n{_prior_turns_block(envelope)}"
                                    f"\nRESPONSE:\n{text}"},
    ]
    completion = client.chat.completions.parse(
        model=JUDGE_MODEL,
        messages=messages,
        response_format=_LLMJudgment,
        temperature=JUDGE_TEMPERATURE,
    )
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        return _LLMJudgment(
            status="UNCERTAIN", confidence=0.0,
            rationale="LLM returned no parsed verdict (refusal).",
        )
    return parsed


# ---------------------------------------------------------------------------
# Per-method judges (uniform signature so dispatch is a plain table lookup).
# ---------------------------------------------------------------------------


def _judge_deterministic(claim: dict, envelope: Any, client: Any) -> Verdict:
    errors, known = _run_validator(claim, envelope)
    obs = claim.get("observable", "")
    if not known:
        return Verdict(
            "UNCERTAIN", 0.0,
            f"deterministic observable {obs!r} is not a known validator",
            "deterministic", _evidence(envelope),
        )
    if errors is None:
        return Verdict(
            "UNCERTAIN", 0.0,
            f"validator {obs!r} is inapplicable to this response shape "
            f"(no SCRIPTED_ML lesson to check)",
            "deterministic", _evidence(envelope),
        )
    if errors:
        return Verdict(
            "MISALIGNED", 1.0, "; ".join(errors),
            "deterministic", _evidence(envelope, errors),
        )
    return Verdict(
        "ALIGNED", 1.0, f"validator {obs!r} reported no violation",
        "deterministic", _evidence(envelope),
    )


def _judge_llm(claim: dict, envelope: Any, client: Any) -> Verdict:
    client = _ensure_client(client)
    j = _call_llm_judge(claim, envelope, client)
    return Verdict(j.status, float(j.confidence), j.rationale, "llm-judge",
                   _evidence(envelope))


def _judge_hybrid(claim: dict, envelope: Any, client: Any) -> Verdict:
    errors, known = _run_validator(claim, envelope)
    if not known:
        return Verdict(
            "UNCERTAIN", 0.0,
            f"hybrid observable {claim.get('observable')!r} is not a known validator",
            "hybrid", _evidence(envelope),
        )
    if errors:  # a real, exact violation — authoritative, no LLM needed.
        return Verdict(
            "MISALIGNED", 1.0, "deterministic validator failed: " + "; ".join(errors),
            "hybrid", _evidence(envelope, errors),
        )
    if errors is None:  # can't run the deterministic leg → can't confirm.
        return Verdict(
            "UNCERTAIN", 0.0,
            f"hybrid validator {claim.get('observable')!r} inapplicable to this "
            f"response shape; cannot confirm",
            "hybrid", _evidence(envelope),
        )
    # Validator clean → consult the LLM leg; both must agree for ALIGNED.
    client = _ensure_client(client)
    j = _call_llm_judge(claim, envelope, client)
    if j.status == "ALIGNED":
        return Verdict(
            "ALIGNED", float(j.confidence),
            "validator clean AND llm-judge confirms: " + j.rationale,
            "hybrid", _evidence(envelope),
        )
    return Verdict(
        "UNCERTAIN", float(j.confidence),
        f"disagreement — validator passed but llm-judge returned {j.status}: "
        f"{j.rationale}",
        "hybrid", _evidence(envelope),
    )


def _judge_launch_first(claim: dict, envelope: Any, client: Any) -> Verdict:
    sources = _get(envelope, "sources") or []
    if not sources:
        return Verdict("UNCERTAIN", 0.0,
                       "no sources in envelope; cannot verify Launch-first",
                       "launch-first", "")

    tiers = [s.get("source_tier") for s in sources
             if isinstance(s.get("source_tier"), int)]
    if not tiers:
        return Verdict(
            "UNCERTAIN", 0.0,
            "no source_tier on any source; Launch-first needs the /api/chat "
            "source_tier debug field",
            "launch-first", "",
        )

    query_type = _query_type(envelope, claim)
    top_tier = min(tiers)  # lower tier number = higher priority
    top_docs = [s.get("source_document", "") for s in sources
                if s.get("source_tier") == top_tier]
    top_is_launch = any(_doc_is_launch(d) for d in top_docs)
    top_is_pie = any(_doc_is_pie(d) for d in top_docs)
    all_docs = [s.get("source_document", "") for s in sources]
    evidence = f"query_type={query_type}; top_tier={top_tier}; top_docs={top_docs}"

    if query_type == _PLAN_UNIT:
        # PIE-first is CORRECT (Launch sits below). Launch-at-top is also fine.
        if top_is_pie or top_is_launch:
            return Verdict(
                "ALIGNED", 1.0,
                "PLAN_UNIT: the PIE/Launch primary holds the top tier "
                "(PIE-first is correct, not a Launch-first violation)",
                "launch-first", evidence,
            )
        if any(_doc_is_pie(d) or _doc_is_launch(d) for d in all_docs):
            return Verdict(
                "MISALIGNED", 1.0,
                "PLAN_UNIT: a non-primary source outranks the PIE/Launch "
                f"content that should lead ({top_docs})",
                "launch-first", evidence,
            )
        return Verdict(
            "UNCERTAIN", 0.0,
            "PLAN_UNIT: no PIE or Launch source retrieved — a recall gap, not "
            "an ordering fault",
            "launch-first", evidence,
        )

    # Every other in-scope type (skill-seeking, COACHING_GENERAL, MANAGEMENT)
    # expects Launch-book content at the top tier.
    if top_is_launch:
        return Verdict(
            "ALIGNED", 1.0,
            f"{query_type}: Launch-book content holds the top tier "
            "(Brady's always-always-always)",
            "launch-first", evidence,
        )
    if any(_doc_is_launch(d) for d in all_docs):
        return Verdict(
            "MISALIGNED", 1.0,
            f"{query_type}: non-Launch content ({top_docs}) outranks the Launch "
            "chunk that was retrieved — Launch-first inversion",
            "launch-first", evidence,
        )
    return Verdict(
        "UNCERTAIN", 0.0,
        f"{query_type}: no Launch source retrieved — a recall gap, not an "
        "ordering fault",
        "launch-first", evidence,
    )


_DISPATCH: dict[str, Callable[[dict, Any, Any], Verdict]] = {
    "deterministic": _judge_deterministic,
    "llm-judge": _judge_llm,
    "hybrid": _judge_hybrid,
    "launch-first": _judge_launch_first,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def judge_claim(claim: dict, envelope: Any, *, openai_client: Any = None) -> Verdict:
    """Judge one claim against one driven envelope.

    Dispatches on ``claim["judge_method"]`` (deterministic / llm-judge /
    hybrid / launch-first). A NON_VERDICT envelope (upstream error) is never
    scored; an unknown method returns UNCERTAIN rather than crashing a batch
    run. ``openai_client`` is injected for the LLM legs (stubbed in tests);
    when None, a synchronous client is built lazily from ``config.settings``.
    """
    method = (claim.get("judge_method") or "").strip().lower()

    # Never score an upstream non-verdict (spec §6). Plain dicts have no ``ok``
    # attribute → treated as scorable.
    if getattr(envelope, "ok", True) is False:
        return Verdict(
            "UNCERTAIN", 0.0,
            "envelope is a NON_VERDICT (upstream error); not scored",
            method or "unknown", _evidence(envelope),
        )

    fn = _DISPATCH.get(method)
    if fn is None:
        return Verdict(
            "UNCERTAIN", 0.0,
            f"unknown judge_method {claim.get('judge_method')!r}",
            method or "unknown", "",
        )
    return fn(claim, envelope, openai_client)
