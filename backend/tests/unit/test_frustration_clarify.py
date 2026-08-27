"""Fix ④ — frustration validation on the first-contact CLARIFY path (dogfood).

Brady C10: validate the emotion FIRST, then the practical guidance. The prompt
instruction ``FRUSTRATION_VALIDATION_RULE`` (handlers/_prompt_rules.py) only runs
when a handler actually calls the LLM. But a frustrated FIRST-contact turn whose
grade/skill is missing short-circuits in ``dispatch()`` to ``_clarify_outcome`` —
a PURE CONSTRUCTOR, no LLM — so that instruction never runs and the teacher gets
a bare "Which grade level are you teaching?" with NO acknowledgment of the
frustration they just voiced.

The fix threads ``intent`` into ``_clarify_outcome`` and, gated on the same
deterministic ``expressed_frustration`` signal, PREPENDS a short, topic-agnostic,
warm sentence (``FRUSTRATION_VALIDATION_CLARIFY``) before the clarifying
question. It is ONE shared seam, so it covers EVERY clarify short-circuit
(grade / skill / mode / mgmt / SG1 acronym / SG2 writing-level / pick-list /
fallback), not just the grade case. A calm turn (the overwhelming default) is
byte-identical to before.
"""

import pytest

from api.models import ModelSet
from handlers import _CLARIFY_QUESTIONS, dispatch
from handlers._prompt_rules import FRUSTRATION_VALIDATION_CLARIFY
from handlers.clarify import UNKNOWN_SUBGROUP_ACRONYM_Q
from schemas import (
    Conversation,
    RequestType,
    SessionHandshakes,
    TurnIntent,
)


def _models() -> ModelSet:
    return ModelSet("GEN", "QRY", "JDG")


async def _dispatch(intent: TurnIntent, message: str):
    # client=None + canonicalizer=None: the clarify short-circuit runs BEFORE any
    # handler, so no LLM is called — a handler reaching an LLM would blow up on
    # client=None, which PROVES the clarify path (not a real handler) produced it.
    return await dispatch(
        intent,
        Conversation(session_id="s"),
        SessionHandshakes(),
        message,
        client=None,
        models=_models(),
        canonicalizer=None,
        retrieval_fn=None,
        library=None,
    )


# ---------------------------------------------------------------------------
# The constant itself: short, ONE sentence, topic-agnostic (fires when the
# skill/grade are still UNKNOWN, so it must carry no such specifics), warm.
# ---------------------------------------------------------------------------


def test_frustration_clarify_constant_is_one_topic_agnostic_sentence() -> None:
    c = FRUSTRATION_VALIDATION_CLARIFY
    assert c.strip(), "the constant must be non-empty"
    # ONE sentence: exactly one terminal period, and no question/exclamation.
    assert c.count(".") == 1 and c.rstrip().endswith(".")
    assert "?" not in c and "!" not in c
    # Topic-agnostic — it renders when grade/skill are still unknown, so it must
    # never name either (that would be a wrong-specifics answer, the exact thing
    # Brady objects to).
    low = c.lower()
    assert "grade" not in low
    assert "skill" not in low
    # It actually validates the frustration (the emotion-first nut).
    assert "frustrat" in low


# ---------------------------------------------------------------------------
# (a) frustration + missing-grade HOW_TO_TEACH -> validation THEN grade question
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_frustration_prefixes_grade_clarify() -> None:
    intent = TurnIntent(
        request_type=RequestType.HOW_TO_TEACH,
        missing_required=["grade"],
        expressed_frustration=True,
    )
    outcome = await _dispatch(intent, "I'm so frustrated — how do I even teach leads?")
    # Opens with Brady's validation sentence...
    assert outcome.response_text.startswith(FRUSTRATION_VALIDATION_CLARIFY)
    # ...THEN still asks the grade question (the clarify's actual job).
    assert "Which grade level are you teaching?" in outcome.response_text
    # Validation leads, the question follows it (order is the whole point).
    assert outcome.response_text.index(FRUSTRATION_VALIDATION_CLARIFY) < (
        outcome.response_text.index("Which grade level are you teaching?")
    )
    assert outcome.structured is None


# ---------------------------------------------------------------------------
# (b) calm turn -> byte-identical to today's bare grade question (back-compat)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calm_grade_clarify_is_byte_identical() -> None:
    intent = TurnIntent(
        request_type=RequestType.HOW_TO_TEACH,
        missing_required=["grade"],
        expressed_frustration=False,  # the overwhelming default
    )
    outcome = await _dispatch(intent, "how do I teach leads?")
    # EXACTLY today's bare grade question — no prefix, no change whatsoever.
    assert outcome.response_text == _CLARIFY_QUESTIONS["grade"]
    assert not outcome.response_text.startswith(FRUSTRATION_VALIDATION_CLARIFY)
    assert FRUSTRATION_VALIDATION_CLARIFY not in outcome.response_text
    assert outcome.structured is None


# ---------------------------------------------------------------------------
# (c) the seam is GENERIC — a DIFFERENT clarify category (SG1 unknown-acronym)
#     with frustration also gets the prefix. This exercises a distinct
#     _clarify_outcome call site than the grade case, proving the fix is at the
#     shared seam and not grade-only.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_frustration_prefixes_acronym_clarify_generic_seam() -> None:
    intent = TurnIntent(
        request_type=RequestType.COACHING,  # not grade-gated; diverted purely by SG1
        unknown_subgroup_acronym="TAG",
        expressed_frustration=True,
    )
    outcome = await _dispatch(intent, "I'm at my wit's end with my TAG kids")
    assert outcome.response_text.startswith(FRUSTRATION_VALIDATION_CLARIFY)
    # The category's own question still follows (Brady's acronym clarify).
    assert UNKNOWN_SUBGROUP_ACRONYM_Q in outcome.response_text
    assert outcome.structured is None


@pytest.mark.asyncio
async def test_calm_acronym_clarify_is_byte_identical() -> None:
    # Back-compat on the generic seam too: a calm acronym clarify is unchanged.
    intent = TurnIntent(
        request_type=RequestType.COACHING,
        unknown_subgroup_acronym="TAG",
        expressed_frustration=False,
    )
    outcome = await _dispatch(intent, "how do I support my TAG kids?")
    assert outcome.response_text == UNKNOWN_SUBGROUP_ACRONYM_Q
    assert FRUSTRATION_VALIDATION_CLARIFY not in outcome.response_text
    assert outcome.structured is None
