"""Tests for the shared retry-with-repair loop used by text handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from handlers._base_text import (
    _blockify_steps,
    _build_text_outcome,
    _format_repair_feedback,
    _isolate_closing_question,
    _swap_multi_skill_closer,
    run_text_handler_with_retry,
)
from handlers.formatting import format_lesson_header
from handlers.picklist import extract_offered_skills
from validation.endings import HOW_TO_TEACH_MULTI_SKILL_CLOSER
from schemas import (
    ChunkRef,
    Conversation,
    GradeSpec,
    ModeSpec,
    Quality,
    RequestType,
    SessionHandshakes,
    SkillSpec,
    TurnIntent,
)


# ----------------------------------------------------------------------
# Fake OpenAI client so tests stay offline
# ----------------------------------------------------------------------


@dataclass
class _FakeMessage:
    content: str


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeCompletion:
    choices: list[_FakeChoice]


@dataclass
class _FakeCompletions:
    responses: list[str]
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def create(self, **kwargs: Any) -> _FakeCompletion:
        self.calls.append(kwargs)
        if not self.responses:
            raise RuntimeError("fake client ran out of responses")
        body = self.responses.pop(0)
        return _FakeCompletion(choices=[_FakeChoice(message=_FakeMessage(content=body))])


@dataclass
class _FakeChat:
    completions: _FakeCompletions


@dataclass
class _FakeClient:
    chat: _FakeChat


def _make_client(responses: list[str]) -> _FakeClient:
    return _FakeClient(chat=_FakeChat(completions=_FakeCompletions(responses=responses)))


def _simple_intent() -> TurnIntent:
    return TurnIntent(
        request_type=RequestType.COACHING,
        skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
    )


def _prompt_builder(intent: TurnIntent, ctx: str, conv: Conversation, repair) -> str:  # noqa: ARG001
    return "system rules\n" + (f"REPAIR: {repair}" if repair else "")


# ----------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_attempt_pass_returns_valid_outcome() -> None:
    client = _make_client(["good response"])
    outcome = await run_text_handler_with_retry(
        intent=_simple_intent(),
        conversation=Conversation(session_id="s1"),
        new_user_message="hi",
        retrieved_context="",
        grounding=[],
        prompt_builder=_prompt_builder,
        validators=[lambda _t: []],  # always passes
        client=client,  # type: ignore[arg-type]
        model="gpt-4o",
        log_label="test",
    )
    assert outcome.quality is Quality.VALID
    assert outcome.response_text == "good response"
    assert outcome.retry_count == 0
    assert outcome.validation_errors == []
    assert len(client.chat.completions.calls) == 1


@pytest.mark.asyncio
async def test_retry_until_pass_counts_attempts() -> None:
    client = _make_client(["bad1", "bad2", "good3"])

    state = {"i": 0}

    def _validator(_text: str) -> list[str]:
        state["i"] += 1
        # Fail on first two calls, pass on third
        return [] if state["i"] >= 3 else ["missing phrase"]

    outcome = await run_text_handler_with_retry(
        intent=_simple_intent(),
        conversation=Conversation(session_id="s1"),
        new_user_message="hi",
        retrieved_context="",
        grounding=[],
        prompt_builder=_prompt_builder,
        validators=[_validator],
        client=client,  # type: ignore[arg-type]
        model="gpt-4o",
        log_label="test",
    )
    assert outcome.quality is Quality.VALID
    assert outcome.response_text == "good3"
    assert outcome.retry_count == 2
    assert len(client.chat.completions.calls) == 3


@pytest.mark.asyncio
async def test_all_three_attempts_fail_yields_best_of_three_low() -> None:
    # Each attempt has a different number of errors; the second has
    # the fewest and should win.
    client = _make_client(["a", "b", "c"])
    counter = {"n": 0}

    def _validator(_text: str) -> list[str]:
        counter["n"] += 1
        return {
            1: ["e1", "e2", "e3"],
            2: ["e1"],
            3: ["e1", "e2"],
        }[counter["n"]]

    outcome = await run_text_handler_with_retry(
        intent=_simple_intent(),
        conversation=Conversation(session_id="s1"),
        new_user_message="hi",
        retrieved_context="",
        grounding=[],
        prompt_builder=_prompt_builder,
        validators=[_validator],
        client=client,  # type: ignore[arg-type]
        model="gpt-4o",
        log_label="test",
    )
    assert outcome.quality is Quality.LOW
    assert outcome.response_text == "b"  # best-of-three (1 error)
    assert outcome.retry_count == 2
    assert outcome.validation_errors == ["e1"]


@pytest.mark.asyncio
async def test_repair_feedback_injected_into_second_prompt() -> None:
    client = _make_client(["fail1", "good2"])
    calls_seen: list[str] = []

    def _builder(intent: TurnIntent, ctx: str, conv: Conversation, repair) -> str:  # noqa: ARG001
        rendered = "system\n" + (f"REPAIR={repair}" if repair else "no-repair")
        calls_seen.append(rendered)
        return rendered

    counter = {"n": 0}

    def _validator(_text: str) -> list[str]:
        counter["n"] += 1
        return ["forbidden word 'discuss'"] if counter["n"] == 1 else []

    await run_text_handler_with_retry(
        intent=_simple_intent(),
        conversation=Conversation(session_id="s1"),
        new_user_message="hi",
        retrieved_context="",
        grounding=[],
        prompt_builder=_builder,
        validators=[_validator],
        client=client,  # type: ignore[arg-type]
        model="gpt-4o",
        log_label="test",
    )
    assert "no-repair" in calls_seen[0]
    assert "REPAIR=" in calls_seen[1]
    assert "discuss" in calls_seen[1]


@pytest.mark.asyncio
async def test_grounding_is_preserved_on_both_outcomes() -> None:
    grounding = [ChunkRef(chunk_id="c1", source_document="lww312")]
    client = _make_client(["fail", "fail", "fail"])
    outcome = await run_text_handler_with_retry(
        intent=_simple_intent(),
        conversation=Conversation(session_id="s1"),
        new_user_message="hi",
        retrieved_context="",
        grounding=grounding,
        prompt_builder=_prompt_builder,
        validators=[lambda _t: ["x"]],
        client=client,  # type: ignore[arg-type]
        model="gpt-4o",
        log_label="test",
    )
    assert outcome.grounding == grounding


def test_format_repair_feedback_is_empty_for_empty_errors() -> None:
    assert _format_repair_feedback([]) == ""


def test_format_repair_feedback_bullets_errors() -> None:
    out = _format_repair_feedback(["missing X", "forbidden Y"])
    assert "POLICY VIOLATIONS" in out
    assert "- missing X" in out
    assert "- forbidden Y" in out
    assert "Fix ONLY the issues above" in out


# ----------------------------------------------------------------------
# Forbidden-word scrub backstop (Wave 1a Task 8 — F31/F32, Brady April #5)
# ----------------------------------------------------------------------
#
# Brady's non-negotiable #5: NEVER emit "discuss"/"activity"/"I'll listen
# in"/PD-plug language. The generation-time validator + retry loop usually
# catches these, but if a forbidden word survives all retries, it must
# still never reach the teacher. _build_text_outcome is the markdown
# delivery seam's final deterministic backstop — it must scrub forbidden
# words the same way it already scrubs unverifiable citations.


def test_build_text_outcome_scrubs_forbidden_words() -> None:
    # retrieved_context="" makes the citation scrubber a no-op, isolating
    # the forbidden-word scrub as the thing doing the work here.
    outcome = _build_text_outcome(
        response_text="Let's discuss this activity with your students.",
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
        retrieved_context="",
        log_label="test",
    )
    lowered = outcome.response_text.lower()
    assert "discuss" not in lowered
    assert "activity" not in lowered
    # The scrubber's safe substitutes must actually be present, not just
    # the banned words absent (guards against e.g. deleting the word).
    assert "turn-and-talk" in outcome.response_text
    assert "mini-lesson" in outcome.response_text


def test_build_text_outcome_forbidden_word_scrub_is_noop_on_clean_text() -> None:
    # Behavior-preserving: no forbidden word present -> untouched text.
    outcome = _build_text_outcome(
        response_text="Let's turn and talk about your topic sentence.",
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
        retrieved_context="",
        log_label="test",
    )
    assert outcome.response_text == "Let's turn and talk about your topic sentence."


def test_build_text_outcome_preserves_paragraph_breaks_while_scrubbing() -> None:
    # Seam-level regression guard (Brady non-negotiable #11: paragraph
    # blocks, never one giant paragraph). A MULTI-paragraph response that
    # also contains a forbidden word must ship with BOTH the word scrubbed
    # AND its "\n\n" paragraph breaks intact. The old unconditional
    # whitespace cleanup inside scrub_forbidden_words collapsed "\n\n" into a
    # single space (\s matches newlines), flattening every multi-paragraph
    # response the moment Task 8 wired the scrubber onto this seam.
    multi = (
        "First, let's discuss the topic.\n\n"
        "Second, model the activity for your students.\n\n"
        "Finally, send them off to write."
    )
    outcome = _build_text_outcome(
        response_text=multi,
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
        retrieved_context="",
        log_label="test",
    )
    text = outcome.response_text
    # Paragraph structure survived: two blank-line separators still present.
    assert text.count("\n\n") == 2
    # And the forbidden words were still scrubbed.
    assert "discuss" not in text.lower()
    assert "activity" not in text.lower()
    assert "turn-and-talk" in text
    assert "mini-lesson" in text


def test_build_text_outcome_preserves_paragraph_breaks_on_citation_removal() -> None:
    # Companion to the forbidden-word guard above, but exercising the OTHER
    # seam scrubber: scrub_unverifiable_citations. The earlier test used
    # retrieved_context="", so no citation removal ever fired and the
    # citation scrubber's own newline-eating (its match regexes padded with
    # raw \s) went untested at the seam. Here a real removal fires — an
    # invented "page 99" (retrieved_context declares only Page: 12) sitting
    # at a paragraph end — and the delivered text must keep BOTH "\n\n"
    # breaks and strip the invented page.
    multi = (
        "Teach the table-top strategy on page 99\n\n"
        "Then let students try it in pairs.\n\n"
        "Finally, share out as a class."
    )
    ctx = "[1] Source: lww312-s8-ml05 | Book: Launching the Writers Workshop 3-12 | Page: 12"
    outcome = _build_text_outcome(
        response_text=multi,
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
        retrieved_context=ctx,
        log_label="test",
    )
    text = outcome.response_text
    assert text.count("\n\n") == 2               # both paragraph breaks survived
    assert "99" not in text                       # invented page removed
    assert "Then let students try it in pairs." in text
    assert "Finally, share out as a class." in text


# ----------------------------------------------------------------------
# Grade|Mode header on markdown responses (Wave 1a Task 11 — Brady Fm4)
# ----------------------------------------------------------------------
#
# Brady Fm4: markdown responses (how_to_teach, plan_unit, management, and
# coaching/think_aloud when a grade is known) must BEGIN with a
# "Grade X | <Mode adjective>" header, mirroring the header SCRIPTED_ML
# already carries on its own separate path (untouched here). grade/mode
# come from TurnIntent and are threaded through
# run_text_handler_with_retry -> _build_text_outcome once, reaching all
# three delivery call sites (first-attempt pass, LLM-trustable fallback,
# best-of-three LOW).


def test_format_lesson_header_both_present_formats_inform() -> None:
    assert format_lesson_header("3", "Inform") == "Grade 3 | Informative"


def test_format_lesson_header_both_present_formats_persuade() -> None:
    assert format_lesson_header("1", "Persuade") == "Grade 1 | Persuasive"


def test_format_lesson_header_both_present_formats_entertain() -> None:
    assert format_lesson_header("2", "Entertain") == "Grade 2 | Narrative"


def test_format_lesson_header_mode_all_omits_mode_segment() -> None:
    assert format_lesson_header("4", "all") == "Grade 4"


def test_format_lesson_header_mode_none_omits_mode_segment() -> None:
    assert format_lesson_header("4", None) == "Grade 4"


def test_format_lesson_header_mode_unrecognized_omits_mode_segment() -> None:
    # Defensive: any mode string outside the 3-key adjective map falls
    # back to grade-only, same as "all" -- the helper never raises on an
    # unexpected mode value.
    assert format_lesson_header("4", "Narrative") == "Grade 4"


def test_format_lesson_header_grade_none_returns_empty() -> None:
    assert format_lesson_header(None, "Inform") == ""


def test_format_lesson_header_grade_empty_string_returns_empty() -> None:
    assert format_lesson_header("", "Inform") == ""


def test_format_lesson_header_grade_band_value_passthrough() -> None:
    # Grade bands ("K-2", "3-5", ...) and single grades are both valid
    # GradeValue members -- the header renders whatever string it is
    # given verbatim, no band-specific formatting.
    assert format_lesson_header("K-2", "Persuade") == "Grade K-2 | Persuasive"


def test_build_text_outcome_prepends_header_when_grade_and_mode_present() -> None:
    outcome = _build_text_outcome(
        response_text="Start with the hook sentence.",
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
        retrieved_context="",
        log_label="test",
        grade="3",
        mode="Inform",
    )
    assert outcome.response_text == (
        "Grade 3 | Informative\n\nStart with the hook sentence."
    )


def test_build_text_outcome_header_grade_only_when_mode_all() -> None:
    outcome = _build_text_outcome(
        response_text="Body text.",
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
        retrieved_context="",
        log_label="test",
        grade="4",
        mode="all",
    )
    assert outcome.response_text.startswith("Grade 4\n\n")
    assert " | " not in outcome.response_text.splitlines()[0]


def test_build_text_outcome_no_header_when_grade_and_mode_unset() -> None:
    # Default grade=None, mode=None (kwargs omitted) -- behavior-preserving
    # for every pre-Fm4 direct call in this file (below) that doesn't pass
    # them.
    outcome = _build_text_outcome(
        response_text="Body text.",
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
        retrieved_context="",
        log_label="test",
    )
    assert outcome.response_text == "Body text."
    assert not outcome.response_text.startswith("Grade")


def test_build_text_outcome_header_survives_scrub_and_preserves_paragraphs() -> None:
    # The header is added AFTER the forbidden-word/citation scrub runs on
    # the body, so it is never itself a scrub target, and the body's own
    # paragraph breaks survive with exactly one more "\n\n" for the
    # header separator.
    outcome = _build_text_outcome(
        response_text="Let's discuss this.\n\nThen model the activity.",
        grounding=[],
        quality=Quality.VALID,
        retry_count=0,
        validation_errors=[],
        retrieved_context="",
        log_label="test",
        grade="5",
        mode="Persuade",
    )
    text = outcome.response_text
    assert text.startswith("Grade 5 | Persuasive\n\n")
    assert "discuss" not in text.lower()
    assert "activity" not in text.lower()
    # 1 header separator + 1 original paragraph break preserved = 2
    assert text.count("\n\n") == 2


# ----------------------------------------------------------------------
# MANAGEMENT header uses the "Management" label, not a writing mode
# (Wave 2c — Brady Fm4, 36:30/image27)
# ----------------------------------------------------------------------
#
# Brady's rule: a management/procedure response must be headed
# "Grade X | Management", NOT a writing-mode adjective. The MANAGEMENT
# handler threads query_type="MANAGEMENT" through _build_text_outcome, which
# swaps the mode adjective for the "Management" label. Every OTHER text
# handler (query_type != "MANAGEMENT") keeps its mode adjective.


def test_management_header_uses_management_label():
    out = _build_text_outcome(response_text="Set up your Help Desk...", grounding=[], quality=Quality.VALID,
        retry_count=0, validation_errors=[], retrieved_context="", log_label="t",
        grade="1", mode="Inform", query_type="MANAGEMENT")
    assert out.response_text.startswith("Grade 1 | Management")


def test_skill_handler_header_uses_mode_adjective():
    out = _build_text_outcome(response_text="Here's an outline...", grounding=[], quality=Quality.VALID,
        retry_count=0, validation_errors=[], retrieved_context="", log_label="t",
        grade="3", mode="Inform", query_type="HOW_TO_TEACH")
    assert out.response_text.startswith("Grade 3 | Informative")


@pytest.mark.asyncio
async def test_run_text_handler_threads_intent_grade_mode_into_header() -> None:
    # End-to-end: TurnIntent carries grade/mode -> run_text_handler_with_retry
    # extracts .value once and threads it to _build_text_outcome on the
    # first-attempt-pass call site.
    client = _make_client(["Body of the lesson overview."])
    intent = TurnIntent(
        request_type=RequestType.HOW_TO_TEACH,
        grade=GradeSpec(value="3", stated_explicit=True),
        mode=ModeSpec(value="Inform", stated_explicit=True),
        skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
    )
    outcome = await run_text_handler_with_retry(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        new_user_message="hi",
        retrieved_context="",
        grounding=[],
        prompt_builder=_prompt_builder,
        validators=[lambda _t: []],
        client=client,  # type: ignore[arg-type]
        model="gpt-4o",
        log_label="test",
    )
    assert outcome.response_text == (
        "Grade 3 | Informative\n\nBody of the lesson overview."
    )


@pytest.mark.asyncio
async def test_run_text_handler_no_header_when_intent_grade_unset() -> None:
    client = _make_client(["Body with no grade known."])
    outcome = await run_text_handler_with_retry(
        intent=_simple_intent(),  # no grade/mode set
        conversation=Conversation(session_id="s1"),
        new_user_message="hi",
        retrieved_context="",
        grounding=[],
        prompt_builder=_prompt_builder,
        validators=[lambda _t: []],
        client=client,  # type: ignore[arg-type]
        model="gpt-4o",
        log_label="test",
    )
    assert outcome.response_text == "Body with no grade known."


@pytest.mark.asyncio
async def test_run_text_handler_threads_header_on_best_of_three_low_path() -> None:
    # Covers the OTHER _build_text_outcome call site (best-of-three LOW):
    # all three attempts fail, and the header must still be prepended to
    # whichever attempt wins best-of-three.
    client = _make_client(["a", "b", "c"])
    counter = {"n": 0}

    def _validator(_text: str) -> list[str]:
        counter["n"] += 1
        return {1: ["e1", "e2"], 2: ["e1"], 3: ["e1", "e2", "e3"]}[counter["n"]]

    intent = TurnIntent(
        request_type=RequestType.MANAGEMENT,
        grade=GradeSpec(value="1", stated_explicit=True),
        mode=ModeSpec(value="Persuade", stated_explicit=True),
    )
    outcome = await run_text_handler_with_retry(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        new_user_message="hi",
        retrieved_context="",
        grounding=[],
        prompt_builder=_prompt_builder,
        validators=[_validator],
        client=client,  # type: ignore[arg-type]
        model="gpt-4o",
        log_label="test",
    )
    assert outcome.quality is Quality.LOW
    assert outcome.response_text == "Grade 1 | Persuasive\n\nb"  # best-of-three (1 error)


@pytest.mark.asyncio
async def test_run_text_handler_threads_header_on_llm_trustable_path() -> None:
    # Covers the THIRD _build_text_outcome call site (LLM-trustable
    # fallback): after >=1 retry, only LLM-trustable errors remain, so the
    # loop trusts the LLM and ships VALID -- the header must reach this
    # path too.
    client = _make_client(["fail1", "trustable-fail"])
    counter = {"n": 0}

    def _validator(_text: str) -> list[str]:
        counter["n"] += 1
        if counter["n"] == 1:
            return ["missing closing phrase"]
        return ["Forbidden word 'discuss' used in a coaching tip."]

    intent = TurnIntent(
        request_type=RequestType.COACHING,
        grade=GradeSpec(value="6", stated_explicit=True),
        mode=ModeSpec(value="Entertain", stated_explicit=True),
    )
    outcome = await run_text_handler_with_retry(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        new_user_message="hi",
        retrieved_context="",
        grounding=[],
        prompt_builder=_prompt_builder,
        validators=[_validator],
        client=client,  # type: ignore[arg-type]
        model="gpt-4o",
        log_label="test",
    )
    assert outcome.quality is Quality.VALID
    assert outcome.retry_count == 1
    assert outcome.response_text.startswith("Grade 6 | Narrative\n\n")


# ----------------------------------------------------------------------
# Closing question isolated onto its own paragraph (Wave 1b Task 3 — E5(a))
# ----------------------------------------------------------------------
#
# Brady E5(a): a closing question glued to the last list item (no blank
# line before it) must render on its own paragraph. _isolate_closing_question
# is anchored to the SAME closing phrases the ending validator requires
# (validation.endings.required_closing_phrases) so the delivery-seam
# normalizer and the policy validator can never drift apart. Cosmetic —
# runs post-validation; query_type=None (or no registered closer) is a
# strict no-op.


def test_isolate_closing_question_peels_glued_closer() -> None:
    # HOW_TO_TEACH closer glued to the last list item must move to its own block.
    glued = "Here are focus skills.\n\n- Topic sentences\n- Transitions Are you ready for a scripted mini-lesson on this skill?"
    out = _isolate_closing_question(glued, "HOW_TO_TEACH")
    assert "\n\nAre you ready for a scripted mini-lesson on this skill?" in out


def test_isolate_closing_question_noop_when_already_separated() -> None:
    ok = "Here are focus skills.\n\n- Topic sentences\n\nAre you ready for a scripted mini-lesson on this skill?"
    assert _isolate_closing_question(ok, "HOW_TO_TEACH") == ok


def test_isolate_closing_question_never_splits_the_plan_unit_closer() -> None:
    """Brady x1: PLAN_UNIT's closer is TWO sentences — "Is this helpful?
    Would you like a general outline of this unit?" — and the REQUIRED phrase
    ("general outline of this unit") sits MID-SENTENCE.

    Anchoring the isolator on the required phrase splits Brady's sentence in
    half. Observed live before the fix:

        Is this helpful? Would you like a
        <blank>
        general outline of this unit?

    The anchor must be the closer's START ("is this helpful"), which cannot be
    a REQUIRED phrase for PLAN_UNIT because COACHING_GENERAL owns that fragment
    — hence closer_anchor_phrases() is registered separately from
    _ENDING_REQUIRED. This test locks the two apart.
    """
    closer = "Is this helpful? Would you like a general outline of this unit?"

    # Already its own paragraph -> strict no-op (never split).
    ok = f"Here are the priority skills.\n\n1. Recognize opinion topics\n\n{closer}"
    assert _isolate_closing_question(ok, "PLAN_UNIT") == ok

    # Glued to the last list item -> the break lands BEFORE the closer's first
    # sentence, keeping BOTH sentences intact on one block.
    glued = f"Here are the priority skills.\n\n1. Recognize opinion topics {closer}"
    out = _isolate_closing_question(glued, "PLAN_UNIT")
    assert f"\n\n{closer}" in out
    assert "Would you like a\n\ngeneral outline" not in out


def test_isolate_closing_question_noop_when_no_closer_or_no_type() -> None:
    assert _isolate_closing_question("No closer here at all.", "HOW_TO_TEACH") == "No closer here at all."
    assert _isolate_closing_question("Are you ready for a scripted mini-lesson?", None) == "Are you ready for a scripted mini-lesson?"


def test_isolate_closing_question_is_idempotent() -> None:
    glued = "Skills.\n\n- A\n- B Are you ready for a scripted mini-lesson on this skill?"
    once = _isolate_closing_question(glued, "HOW_TO_TEACH")
    twice = _isolate_closing_question(once, "HOW_TO_TEACH")
    assert once == twice


def test_isolate_closing_question_moves_compound_closer_as_one_block() -> None:
    # COACHING_GENERAL/MANAGEMENT closer is two registered phrases
    # ("does this make sense" + "is this helpful"). When glued, the WHOLE
    # compound must move to its own block, not split between the sentences.
    glued = "Here is advice.\n\n- Point A\n- Point B Does this make sense? Is this helpful?"
    out = _isolate_closing_question(glued, "COACHING_GENERAL")
    assert "- Point B\n\nDoes this make sense? Is this helpful?" in out
    # and the first closer sentence is NOT left glued to the list item
    assert "- Point B Does this make sense?" not in out


def test_isolate_closing_question_moves_e3_management_closer_as_one_block() -> None:
    # Brady E3: the MANAGEMENT overview closer renders on its own paragraph.
    # required_closing_phrases("MANAGEMENT") now returns the E3 keys (earliest
    # match = "this was an overview"), so _isolate_closing_question moves the
    # WHOLE closer onto its own block rather than leaving it glued to the last
    # list item — proving the validator change flows through the delivery seam.
    closer = ("This was an overview. Which ONE area or SINGLE routine would "
              "you like to start with?")
    glued = f"Here are the routines.\n\n- Set up folders\n- Post the schedule {closer}"
    out = _isolate_closing_question(glued, "MANAGEMENT")
    assert f"\n\n{closer}" in out
    assert "- Post the schedule This was an overview." not in out


@pytest.mark.asyncio
async def test_run_text_handler_threads_query_type_isolates_closer() -> None:
    # Brady C8: a 2-skill outline's single-skill closer is swapped for the
    # multi-skill pick-list closer at the seam, then E5a isolates it onto its
    # own paragraph — both driven by the query_type threaded through
    # run_text_handler_with_retry -> _build_text_outcome.
    glued = "Here are strategies.\n\n- Focus A\n- Focus B Are you ready for a scripted mini-lesson on this skill?"
    client = _make_client([glued])
    intent = TurnIntent(
        request_type=RequestType.HOW_TO_TEACH,
        skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
    )
    outcome = await run_text_handler_with_retry(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        new_user_message="hi",
        retrieved_context="",
        grounding=[],
        prompt_builder=_prompt_builder,
        validators=[lambda _t: []],
        client=client,  # type: ignore[arg-type]
        model="gpt-4o",
        log_label="how_to_teach",
        query_type="HOW_TO_TEACH",
    )
    assert f"\n\n{HOW_TO_TEACH_MULTI_SKILL_CLOSER}" in outcome.response_text
    assert "are you ready for a scripted mini-lesson" not in outcome.response_text.lower()


# ----------------------------------------------------------------------
# HOW_TO_TEACH bullet normalizer (Wave 1b Task 4 — Fm1)
# ----------------------------------------------------------------------
#
# Brady Fm1: a HOW_TO_TEACH outline lists discrete sub-skill OPTIONS
# (not an ordered sequence), so it must render as bullets, never numbers.
# The prompt asks for bullets, but this seam backstop deterministically
# converts any stray line-leading "N. " markers to "- " for HOW_TO_TEACH
# only. No-op for every other query_type (PLAN_UNIT's numbered
# scope-and-sequence is intentional and must be preserved).


def test_bulletize_how_to_teach_converts_numbered_to_bullets() -> None:
    out = _build_text_outcome(
        response_text="Focus on these skills:\n\n1. Topic sentences\n2. Transitions\n3. Elaboration",
        grounding=[], quality=Quality.VALID, retry_count=0, validation_errors=[],
        retrieved_context="", log_label="how_to_teach", query_type="HOW_TO_TEACH",
    )
    text = out.response_text
    assert "- Topic sentences" in text
    assert "- Transitions" in text
    assert "1. Topic sentences" not in text


def test_bulletize_noop_for_plan_unit() -> None:
    # PLAN_UNIT's numbered scope-and-sequence is intentional — untouched.
    out = _build_text_outcome(
        response_text="Priority skills in order:\n\n1. A\n2. B\n3. C",
        grounding=[], quality=Quality.VALID, retry_count=0, validation_errors=[],
        retrieved_context="", log_label="plan_unit", query_type="PLAN_UNIT",
    )
    assert "1. A" in out.response_text


# ----------------------------------------------------------------------
# 4-step paragraph-block guarantee + unified-pass idempotency
# (Wave 1b Task 5 — Fm2(a))
# ----------------------------------------------------------------------
#
# Brady Fm2: any 4-step mini-lesson content that reaches the TEXT path
# must render in paragraph blocks, never one giant paragraph.
# _blockify_steps is query_type-INDEPENDENT — it inserts a blank line
# before a capitalized Smekens step header ("Step 1", "Step 2A", "Step
# 2B") that is glued mid-line. It sits in the pipeline after
# _bulletize_how_to_teach and before _isolate_closing_question. The
# structured SCRIPTED_ML path renders its own blocks on a separate seam
# (scripted_ml.py::_build_outcome) and is untouched by this normalizer.


def test_blockify_steps_splits_glued_step_headers() -> None:
    out = _build_text_outcome(
        response_text="Here is the lesson. Step 1 Introduce the hook. Step 2A Tell them why. Step 2B Show the think-aloud.",
        grounding=[], quality=Quality.VALID, retry_count=0, validation_errors=[],
        retrieved_context="", log_label="coaching", query_type="COACHING_GENERAL",
    )
    text = out.response_text
    assert "\n\nStep 1" in text
    assert "\n\nStep 2A" in text
    assert "\n\nStep 2B" in text


def test_blockify_steps_ignores_midsentence_lowercase_step() -> None:
    out = _build_text_outcome(
        response_text="The first step 1 kids take is drawing a picture.",
        grounding=[], quality=Quality.VALID, retry_count=0, validation_errors=[],
        retrieved_context="", log_label="coaching", query_type="COACHING_GENERAL",
    )
    assert "\n\n" not in out.response_text  # lowercase "step 1" left alone


def test_unified_normalizer_pass_is_idempotent() -> None:
    raw = (
        "Here are the focus skills.\n\n"
        "1. Topic sentences\n2. Transitions\n3. Elaboration Are you ready for a scripted mini-lesson on this skill?"
    )
    kwargs = dict(
        grounding=[], quality=Quality.VALID, retry_count=0, validation_errors=[],
        retrieved_context="", log_label="how_to_teach", query_type="HOW_TO_TEACH",
    )
    first = _build_text_outcome(response_text=raw, **kwargs).response_text
    second = _build_text_outcome(response_text=first, **kwargs).response_text
    assert first == second                                   # idempotent
    assert "- Topic sentences" in first                      # Fm1 bulletized
    # Brady C8: a 3-skill outline closes with the multi-skill pick-list closer
    # (swapped at the seam), isolated onto its own paragraph by E5(a) — not the
    # single-skill "...on this skill?" closer.
    assert f"\n\n{HOW_TO_TEACH_MULTI_SKILL_CLOSER}" in first
    assert "are you ready for a scripted mini-lesson" not in first.lower()


# Direct tests on _blockify_steps itself. The three tests above exercise it
# through _build_text_outcome, where the other pipeline stages no-op
# independently — so they'd still pass if _blockify_steps were deleted or made
# case-insensitive. These pin the function's contract directly: a HEADER splits
# but a mid-sentence back-reference does not, case-sensitivity holds, and the
# pass is idempotent / no-op at a string start.


def test_blockify_steps_leaves_midsentence_step_reference_intact() -> None:
    # Brady §0: coaching that digs into a prior lesson legitimately says
    # "As discussed in Step 2, ...". That is a back-reference, not a header —
    # splitting it would corrupt the sentence.
    prose = "As discussed in Step 2, revise your draft."
    assert _blockify_steps(prose) == prose
    prose2 = "In Step 2 you modeled the think-aloud."
    assert _blockify_steps(prose2) == prose2


def test_blockify_steps_is_case_sensitive_directly() -> None:
    # Pins case-sensitivity on the function itself, so adding re.IGNORECASE fails here.
    prose = "The first step 1 kids take is drawing."
    assert _blockify_steps(prose) == prose


def test_blockify_steps_splits_header_forms_directly() -> None:
    assert _blockify_steps("Intro. Step 1 Introduce") == "Intro.\n\nStep 1 Introduce"
    assert _blockify_steps("Intro. Step 2A — Tell") == "Intro.\n\nStep 2A — Tell"
    assert _blockify_steps("Intro. Step 3: Interact") == "Intro.\n\nStep 3: Interact"
    assert _blockify_steps("Intro. Step 10 Close") == "Intro.\n\nStep 10 Close"


def test_blockify_steps_direct_idempotent_and_noop() -> None:
    glued = "Intro. Step 1 Introduce the hook."
    once = _blockify_steps(glued)
    assert _blockify_steps(once) == once                                # idempotent
    assert _blockify_steps("") == ""                                    # empty
    assert _blockify_steps("Step 1 Introduce") == "Step 1 Introduce"    # at string start


# ----------------------------------------------------------------------
# Shared make_markdown_validators helper + per-handler wiring
# (Wave 2c — Brady N1/N2 threaded into the 5 markdown handlers)
# ----------------------------------------------------------------------
#
# Brady N1 ("details", never "reasons" in K-1 persuasive) and N2 ("story" is
# narrative-only) were enforced for SCRIPTED_ML but not on the markdown path.
# make_markdown_validators is the ONE validation-assembly point all five text
# handlers now share: it reads the intent's grade + writing mode and threads
# them into validate_markdown_response so the two rules fire on the text path
# too. Centralizing it means the five handlers can't drift apart. These tests
# pin (1) the helper threads mode so N2 fires, (2) it stays inert without
# grade/mode (back-compat for unthreaded callers), and (3) each of the five
# handlers actually calls it with its OWN query_type + the live intent (spied
# via monkeypatch — no live LLM needed; retrieval_fn=None -> empty retrieval).

import importlib

from handlers._base_text import make_markdown_validators


def _md_intent(grade=None, mode=None) -> TurnIntent:
    """Build a minimal COACHING intent carrying only the grade/mode a test
    needs. Reuses the required GradeSpec/ModeSpec(..., stated_explicit=True)
    construction (both fields are mandatory — no default)."""
    return TurnIntent(
        request_type=RequestType.COACHING,
        grade=GradeSpec(value=grade, stated_explicit=True) if grade else None,
        mode=ModeSpec(value=mode, stated_explicit=True) if mode else None,
    )


def test_markdown_validators_thread_mode_for_n2() -> None:
    vs = make_markdown_validators(
        intent=_md_intent(mode="Inform"),
        query_type="COACHING_GENERAL",
        retrieved_context="",
        required_triggers=[],
    )
    assert any("N2" in e for v in vs for e in v("Tell a story about the facts."))


def test_markdown_validators_inert_without_mode() -> None:
    vs = make_markdown_validators(
        intent=_md_intent(),
        query_type="COACHING_GENERAL",
        retrieved_context="",
        required_triggers=[],
    )
    assert not any(
        "N2" in e for v in vs for e in v("Tell a story about the facts.")
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "module,func,qt",
    [
        ("handlers.coaching", "handle_coaching", "COACHING_GENERAL"),
        ("handlers.how_to_teach", "handle_how_to_teach", "HOW_TO_TEACH"),
        ("handlers.think_aloud", "handle_think_aloud", "THINK_ALOUD"),
        ("handlers.plan_unit", "handle_plan_unit", "PLAN_UNIT"),
        ("handlers.management", "handle_management", "MANAGEMENT"),
    ],
)
async def test_handler_wires_make_markdown_validators(
    module, func, qt, monkeypatch
) -> None:
    # Each handler must call make_markdown_validators with its own query_type
    # literal and the live intent. Spy on the name in the handler's namespace
    # (it imports the helper by name, so patching mod.make_markdown_validators
    # intercepts the real call). raising=True asserts the handler imported it.
    mod = importlib.import_module(module)
    seen: dict[str, Any] = {}

    def _spy(*, intent, query_type, retrieved_context, required_triggers):
        seen["qt"] = query_type
        seen["intent"] = intent
        return []  # no validators -> first attempt passes, no live LLM needed

    monkeypatch.setattr(mod, "make_markdown_validators", _spy, raising=True)

    intent = _md_intent(grade="3", mode="Inform")
    handler = getattr(mod, func)
    await handler(
        intent,
        Conversation(session_id="s1"),
        SessionHandshakes(),
        "How do I teach this?",
        client=_make_client(["ok response"]),  # type: ignore[arg-type]
        model="gpt-4o",
        canonicalizer=None,  # type: ignore[arg-type]
    )
    assert seen["qt"] == qt
    assert seen["intent"] is intent


# ----------------------------------------------------------------------
# N2 is LLM-trustable on the markdown path (Wave 2c — Brady N2)
# ----------------------------------------------------------------------
#
# On free-form prose, "story" has legitimate non-narrative uses ("the data
# tells a story", "the whole story"), so N2 has a large false-positive
# surface. Brady bans mislabeling the PIECE a story, not the word itself.
# The markdown retry loop therefore treats N2 as LLM-trustable: after >=1
# retry, if the ONLY remaining class of error is N2, the loop trusts the
# LLM's kept wording and ships VALID (the flag is retained in
# validation_errors for audit). N2 stays NON-trustable in the GLOBAL
# is_llm_trustable_error predicate, so SCRIPTED_ML's structured path is
# unaffected. N1 is deliberately NOT trustable here (its K-1 "reasons" gate
# is reliable).

from validation.policy import is_llm_trustable_error, is_story_narrative_error
from validation.vocabulary import validate_story_only_narrative


def test_n2_error_is_recognized() -> None:
    # The stable "Brady N2:" prefix the markdown loop keys on is exactly what
    # validate_story_only_narrative emits.
    err = validate_story_only_narrative("Write a story.", "Inform")[0]
    assert is_story_narrative_error(err)


def test_n2_not_globally_trustable() -> None:
    # N2 stays NON-trustable in the global predicate (SCRIPTED_ML unaffected).
    err = validate_story_only_narrative("Write a story.", "Inform")[0]
    assert not is_llm_trustable_error(err)


@pytest.mark.asyncio
async def test_markdown_loop_ships_valid_when_only_n2_remains_after_retry() -> None:
    # Loop-level proof: after a retry, when the SOLE surviving error is N2,
    # the markdown loop ships VALID (not LOW) and keeps the N2 flag in
    # validation_errors. Under the OLD global trust set (is_llm_trustable_error)
    # N2 would NOT be trustable -> all three attempts fail -> LOW, so this test
    # pins the new markdown-scoped behavior specifically.
    n2_err = validate_story_only_narrative("Tell a story.", "Inform")[0]
    client = _make_client(
        [
            "Attempt one is off-topic.",
            "The data tells a story about the weather.",
            "Third attempt still mentions a story.",
        ]
    )
    counter = {"n": 0}

    def _validator(_text: str) -> list[str]:
        counter["n"] += 1
        # Attempt 1: a non-trustable error forces at least one retry.
        # Attempts 2+: only the N2 error remains.
        return ["missing closing phrase"] if counter["n"] == 1 else [n2_err]

    intent = TurnIntent(
        request_type=RequestType.COACHING,
        grade=GradeSpec(value="3", stated_explicit=True),
        mode=ModeSpec(value="Inform", stated_explicit=True),
    )
    outcome = await run_text_handler_with_retry(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        new_user_message="hi",
        retrieved_context="",
        grounding=[],
        prompt_builder=_prompt_builder,
        validators=[_validator],
        client=client,  # type: ignore[arg-type]
        model="gpt-4o",
        log_label="test",
    )
    assert outcome.quality is Quality.VALID
    assert outcome.retry_count == 1  # trusted on the 2nd attempt, no 3rd call
    assert any(is_story_narrative_error(e) for e in outcome.validation_errors)


@pytest.mark.asyncio
async def test_markdown_loop_still_low_when_non_n2_error_accompanies_n2() -> None:
    # Boundary: N2 is trusted ONLY when it is the lone remaining class. If a
    # non-trustable error (e.g. a missing closing phrase) survives alongside
    # N2 on every retry, the loop must NOT trust -> ships LOW best-of-three.
    n2_err = validate_story_only_narrative("Tell a story.", "Inform")[0]
    client = _make_client(["a", "b", "c"])

    def _validator(_text: str) -> list[str]:
        return [n2_err, "missing closing phrase"]

    intent = TurnIntent(
        request_type=RequestType.COACHING,
        grade=GradeSpec(value="3", stated_explicit=True),
        mode=ModeSpec(value="Inform", stated_explicit=True),
    )
    outcome = await run_text_handler_with_retry(
        intent=intent,
        conversation=Conversation(session_id="s1"),
        new_user_message="hi",
        retrieved_context="",
        grounding=[],
        prompt_builder=_prompt_builder,
        validators=[_validator],
        client=client,  # type: ignore[arg-type]
        model="gpt-4o",
        log_label="test",
    )
    assert outcome.quality is Quality.LOW


# ----------------------------------------------------------------------
# Offer-anchored dedupe of the generic closer (Wave 2c — Brady E4)
# ----------------------------------------------------------------------
#
# Brady E4: a COACHING_GENERAL/MANAGEMENT response closes with a SINGLE
# question. When the generator stacks the generic "Does this make sense? Is
# this helpful?" closer AFTER a concrete offer question,
# _dedupe_closing_question drops the redundant generic closer so only the
# offer question remains. It is PROVABLY BOUNDED: it commits the strip only
# when what would be removed is the BARE generic closer AND the remaining
# candidate STILL ENDS WITH a valid offer question — so it can only turn
# "valid (two questions)" into "valid (one offer question)", never into an
# invalid/no-closer ending. No-op for non-eligible types, no generic closer
# in the tail, a non-final offer, a substantive trailing question, or a stray
# mid-body "does this make sense" mention. Idempotent; runs before
# _isolate_closing_question in _build_text_outcome.

from handlers._base_text import _dedupe_closing_question

_OFFER = "Want me to map out a week of lessons?"
_GENERIC = "Does this make sense? Is this helpful?"


def test_dedupe_strips_generic_after_offer() -> None:
    out = _dedupe_closing_question(
        f"Coaching.\n\n{_OFFER} {_GENERIC}", "COACHING_GENERAL"
    )
    assert "does this make sense" not in out.lower()
    assert "want me to map out a week" in out.lower()


def test_dedupe_widened_offer_stem() -> None:
    # A widened offer stem ("Can I ...?") is still recognized as the surviving
    # valid close, so the generic closer stacked after it is stripped.
    out = _dedupe_closing_question(
        f"Coaching.\n\nCan I map out a week? {_GENERIC}", "COACHING_GENERAL"
    )
    assert "does this make sense" not in out.lower()
    assert out.lower().rstrip().endswith("week?")


def test_dedupe_keeps_generic_when_no_offer() -> None:
    # No offer question precedes the generic closer -> stripping it would leave
    # a declarative ending, so the offer-anchor gate refuses the strip.
    text = f"Coaching.\n\n{_GENERIC}"
    assert _dedupe_closing_question(text, "COACHING_GENERAL") == text


def test_dedupe_noop_offer_only() -> None:
    text = f"Coaching.\n\n{_OFFER}"
    assert _dedupe_closing_question(text, "COACHING_GENERAL") == text


def test_dedupe_noop_wrong_type() -> None:
    text = f"Outline.\n\n{_OFFER} {_GENERIC}"
    assert _dedupe_closing_question(text, "HOW_TO_TEACH") == text


def test_dedupe_noop_empty() -> None:
    assert _dedupe_closing_question("", "COACHING_GENERAL") == ""


def test_dedupe_idempotent() -> None:
    # COACHING_GENERAL (not MANAGEMENT): Brady E3 moved MANAGEMENT onto its own
    # overview closer, so the generic-closer dedup is now exercised against the
    # one type that still registers the generic closer.
    once = _dedupe_closing_question(f"C.\n\n{_OFFER} {_GENERIC}", "COACHING_GENERAL")
    assert _dedupe_closing_question(once, "COACHING_GENERAL") == once


def test_dedupe_keeps_original_when_offer_not_final() -> None:
    # The offer question is not the last sentence before the generic closer,
    # so cutting the closer would leave a declarative ending -> refuse.
    text = f"C.\n\n{_OFFER} Then model it once. {_GENERIC}"
    assert _dedupe_closing_question(text, "COACHING_GENERAL") == text


def test_dedupe_BLOCKING_midbody_generic_does_not_delete_real_closer() -> None:
    # A mid-body "Does this make sense?" self-check well before the end, plus
    # the real generic closer. The candidate after cutting the closer ends
    # declaratively ("...revise once."), so the offer-anchor gate must REFUSE
    # the strip and keep the closer intact — proving the strip can never
    # produce an invalid/no-closer ending.
    body = (
        "When students reread, have them ask, 'Does this make sense?' "
        + ("x " * 130)
        + "and then revise once."
    )
    text = f"{body} {_GENERIC}"
    out = _dedupe_closing_question(text, "COACHING_GENERAL")
    assert out == text  # unchanged — no valid offer close, so must not strip


def test_dedupe_does_not_eat_substantive_trailing_question() -> None:
    # "Does this make sense for how you pace things?" is a SUBSTANTIVE
    # question, not the bare generic closer -> must not be stripped.
    text = f"C.\n\n{_OFFER} Does this make sense for how you pace things?"
    assert _dedupe_closing_question(text, "COACHING_GENERAL") == text


# ----------------------------------------------------------------------
# Deterministic soft book-citation placement (Fm5 — Brady)
# ----------------------------------------------------------------------
#
# REMOVED (2026-07-17): the six `_insert_book_citation` tests.
#
# NOT re-pointed — the behaviour they locked no longer exists. Every one of them
# asserted where a FOOTER lands relative to the closing question (registered
# closer first, E4 offer question as anchor 2, top-frame fallback). Per-claim
# citations sit where the model put the marker, on the claim's own line, so
# there is no placement problem left to solve and no anchor ladder to test.
# `_insert_book_citation` was deleted with its last caller; the placement rule
# that replaced it is locked in handlers/citation.py::_resolve_one_line's tests
# (test_citation_markers.py) and end-to-end in test_fm5_citation_wiring.py.


# ----------------------------------------------------------------------
# Multi-skill HOW_TO_TEACH closer swap (Brady C8)
# ----------------------------------------------------------------------
#
# Brady C8: a HOW_TO_TEACH outline that enumerates MORE THAN ONE sub-skill
# closes with Brady's pick-list closer ("Which of these skills do you want to
# start with? You can't teach them all in a single lesson."), NOT the
# single-skill "...on this skill?" closer — "this skill" has no referent once
# 3-5 skills were listed. The count is arithmetic, not the model's job
# (handlers/picklist.py): extract_offered_skills enumerates the rendered
# outline; _swap_multi_skill_closer swaps the closer when it lists >1 skill and
# leaves a lone-skill outline untouched. It runs at the delivery seam AFTER
# _blockify_steps and BEFORE _isolate_closing_question, which then moves the new
# closer onto its own paragraph. Bounded + fail-safe + idempotent like the E4
# dedup: it can only swap the trailing single-skill closer or leave the text
# unchanged, never a mangled tail.

_FIVE_SKILL_OUTLINE = (
    "Here are the priority sub-skills for teaching paragraphing:\n\n"
    "- Identify the main idea\n"
    "- Write a topic sentence\n"
    "- Add supporting details\n"
    "- Use transitions\n"
    "- Write a closing sentence\n\n"
    "Are you ready for a scripted mini-lesson on this skill?"
)


def test_swap_multi_skill_closer_end_to_end_5_skills() -> None:
    # A 5-skill outline: the single-skill closer is swapped for the multi-skill
    # pick-list closer, isolated onto its own paragraph (E5a ran after the swap).
    out = _build_text_outcome(
        response_text=_FIVE_SKILL_OUTLINE, grounding=[], quality=Quality.VALID,
        retry_count=0, validation_errors=[], retrieved_context="",
        log_label="how_to_teach", query_type="HOW_TO_TEACH",
    ).response_text
    assert "are you ready for a scripted mini-lesson" not in out.lower()
    assert out.rstrip().endswith(HOW_TO_TEACH_MULTI_SKILL_CLOSER)
    assert f"\n\n{HOW_TO_TEACH_MULTI_SKILL_CLOSER}" in out  # own paragraph
    # All five skills are still offered (the closer is prose, not a list item).
    assert len(extract_offered_skills(out)) == 5


def test_swap_multi_skill_closer_noop_for_single_skill_outline() -> None:
    # A lone-skill outline keeps the single-skill closer — "this skill" has a
    # referent, so no swap.
    outline = (
        "Here is the focus sub-skill for teaching paragraphing:\n\n"
        "- Write a topic sentence\n\n"
        "Are you ready for a scripted mini-lesson on this skill?"
    )
    out = _build_text_outcome(
        response_text=outline, grounding=[], quality=Quality.VALID,
        retry_count=0, validation_errors=[], retrieved_context="",
        log_label="how_to_teach", query_type="HOW_TO_TEACH",
    ).response_text
    assert out.rstrip().endswith(
        "Are you ready for a scripted mini-lesson on this skill?"
    )
    assert "which of these skills" not in out.lower()


def test_swap_multi_skill_closer_idempotent_through_seam() -> None:
    kwargs = dict(
        grounding=[], quality=Quality.VALID, retry_count=0, validation_errors=[],
        retrieved_context="", log_label="how_to_teach", query_type="HOW_TO_TEACH",
    )
    first = _build_text_outcome(response_text=_FIVE_SKILL_OUTLINE, **kwargs).response_text
    second = _build_text_outcome(response_text=first, **kwargs).response_text
    assert first == second  # a second pass is a no-op
    # exactly one closer — the swap never stacks a second one
    assert first.lower().count("which of these skills do you want to start with") == 1


def test_swap_multi_skill_closer_noop_for_non_how_to_teach() -> None:
    # Any non-HOW_TO_TEACH type is untouched, even if it contains the fragment.
    text = (
        "Priority skills:\n\n1. A\n2. B\n\n"
        "Are you ready for a scripted mini-lesson on this skill?"
    )
    assert _swap_multi_skill_closer(text, "PLAN_UNIT") == text
    assert _swap_multi_skill_closer(text, "COACHING_GENERAL") == text
    assert _swap_multi_skill_closer(text, None) == text


# Direct tests on _swap_multi_skill_closer itself — the seam pipeline tests
# above exercise it through _build_text_outcome (where isolation adds the
# paragraph break afterward), so these pin the function's own contract: it
# replaces from the single-skill fragment through end-of-text and does NOT
# add a paragraph break itself (that is _isolate_closing_question's job).


def test_swap_multi_skill_closer_glued_case_direct() -> None:
    glued = "Skills.\n\n- A\n- B Are you ready for a scripted mini-lesson on this skill?"
    out = _swap_multi_skill_closer(glued, "HOW_TO_TEACH")
    assert out == f"Skills.\n\n- A\n- B {HOW_TO_TEACH_MULTI_SKILL_CLOSER}"


def test_swap_multi_skill_closer_own_paragraph_direct() -> None:
    sep = "Skills.\n\n- A\n- B\n\nAre you ready for a scripted mini-lesson on this skill?"
    out = _swap_multi_skill_closer(sep, "HOW_TO_TEACH")
    assert out == f"Skills.\n\n- A\n- B\n\n{HOW_TO_TEACH_MULTI_SKILL_CLOSER}"


def test_swap_multi_skill_closer_noop_when_no_single_skill_closer() -> None:
    # >1 skill but the single-skill closer is absent -> nothing to swap.
    text = "Skills.\n\n- A\n- B\n\nSome other ending entirely."
    assert _swap_multi_skill_closer(text, "HOW_TO_TEACH") == text


def test_swap_multi_skill_closer_noop_when_one_item() -> None:
    # A single list item glued to the closer: count == 1 -> no swap.
    text = "Skills.\n\n- A Are you ready for a scripted mini-lesson on this skill?"
    assert _swap_multi_skill_closer(text, "HOW_TO_TEACH") == text


def test_swap_multi_skill_closer_direct_idempotent() -> None:
    glued = "Skills.\n\n- A\n- B Are you ready for a scripted mini-lesson on this skill?"
    once = _swap_multi_skill_closer(glued, "HOW_TO_TEACH")
    assert _swap_multi_skill_closer(once, "HOW_TO_TEACH") == once


def test_swap_multi_skill_closer_empty_is_noop() -> None:
    assert _swap_multi_skill_closer("", "HOW_TO_TEACH") == ""
