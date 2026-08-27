"""Unit tests for SCRIPTED_ML prompt builder.

No LLM calls — we verify the prompt contains every rule Brady requires
and that TurnIntent fields thread through correctly.
"""

from __future__ import annotations

import pytest

from handlers._prompt_rules import EARLY_WRITER_STAGE_RULE
from handlers.scripted_ml_prompt import (
    _BASE_PROMPT,
    build_retry_preamble,
    build_scripted_ml_prompt,
)
from schemas import (
    Conversation,
    GradeSpec,
    ModeSpec,
    Quality,
    RequestType,
    Role,
    SkillSpec,
    TraitSpec,
    Turn,
    TurnIntent,
)


# ----------------------------------------------------------------------
# Base-prompt structural expectations
# ----------------------------------------------------------------------


def _simple_intent() -> TurnIntent:
    return TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        grade=GradeSpec(value="3", stated_explicit=True, stated_turn=0),
        mode=ModeSpec(value="Inform", stated_explicit=True),
        trait=TraitSpec(value="Ideas", stated_explicit=False, confidence=0.8),
        skill=SkillSpec(
            canonical="topic sentences",
            as_stated="topic sentence and supporting details",
        ),
    )


def test_prompt_contains_step3_required_phrases() -> None:
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    # All four Brady phrases must appear in the prompt rules
    assert "Help me with the next" in prompt
    assert "Turn and talk" in prompt
    assert "Back to me" in prompt
    assert "This is some of what I heard" in prompt


def test_prompt_step3_models_teacher_voiced_answer_after_cue() -> None:
    """F57 salvage: the final Step-3 cue ("this is some of what") must open
    a full modeled teacher answer, not dangle with nothing after it — Brady's
    requirement, previously present only in the dead generation/prompts.py
    path. Ported into the active _BASE_PROMPT so scripted-ML lessons keep
    getting this instruction."""
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    lowered = prompt.lower()
    assert "model a teacher-voiced answer" in lowered
    assert "do not stop at" in lowered
    assert "one or two modeled sentences" in lowered  # the worked-tail example


def test_prompt_contains_banned_word_rules() -> None:
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    # Every Brady-banned token appears in the forbidden list
    for banned in ("discuss", "activity", "I'll listen in", "professional development"):
        assert banned in prompt, f"prompt must forbid {banned!r}"


def test_prompt_enforces_step2b_depth_and_monologue() -> None:
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    assert "4×" in prompt or "4x" in prompt.lower() or "four times" in prompt.lower()
    for phrase in ("I close my eyes", "I wonder", "hmm"):
        assert phrase in prompt.lower() or phrase.replace("I ", "i ") in prompt.lower()


def test_prompt_step2b_depth_regardless_of_grade() -> None:
    """F57 salvage: Step 2B's ≥4× depth rule is grade-invariant — a K-1
    lesson doesn't get a shorter think-aloud than a 12th-grade one. This
    instruction previously lived only in the dead generation/prompts.py
    path; ported into the active _BASE_PROMPT so young-grade lessons keep
    getting full-depth modeling."""
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    lowered = prompt.lower()
    assert "regardless of grade level" in lowered
    assert "do not shorten step 2b because the grade is young" in lowered


def test_prompt_step1_four_components_documented() -> None:
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    # Step 1 structural rule names the 4 components
    for key in ("LINK", "NAME the skill", "PURPOSE", "TRAIT CONNECTION"):
        assert key in prompt, f"Step 1 rules missing {key!r}"


def test_prompt_named_strategy_gist_rule() -> None:
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    assert "pizza-table" in prompt.lower()
    assert "gist" in prompt.lower()


# ----------------------------------------------------------------------
# Brady C3 — carried organizer / prior approach block
# ----------------------------------------------------------------------


def test_prompt_includes_carried_organizer_block() -> None:
    """When a carried organizer/approach is threaded in, the prompt surfaces it
    as an explicit block AND instructs the generator to incorporate it into the
    lesson (the content must reach the generation input, not just linger in the
    conversation snippet)."""
    organizer = (
        "Use PIE flaps: a three-flap foldable (Point / Information / Explanation)."
    )
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
        carried_context=organizer,
    )
    assert organizer in prompt  # the described organizer reaches generation input
    assert "CARRIED ORGANIZER" in prompt  # distinctive, block-owned marker
    assert "incorporate it into the lesson" in prompt.lower()  # the instruction


def test_prompt_omits_carried_block_when_absent() -> None:
    """Prompt-restraint / no-op: with no carried organizer the block is absent
    entirely — no bloat on the common (non-DEEPEN) generation path."""
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    assert "CARRIED ORGANIZER" not in prompt


# ----------------------------------------------------------------------
# Session-context rendering threads TurnIntent fields into the prompt
# ----------------------------------------------------------------------


def test_session_context_contains_grade_mode_trait() -> None:
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    assert "SESSION CONTEXT" in prompt
    assert "Grade: 3" in prompt
    assert "Inform" in prompt
    assert "Ideas" in prompt


def test_skill_as_stated_preserved_in_session_block() -> None:
    """Teacher's vocabulary must appear verbatim — Brady's 'use my
    words' requirement."""
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    # The teacher phrasing "topic sentence and supporting details" must
    # appear (this is skill.as_stated)
    assert "topic sentence and supporting details" in prompt


def test_required_triggers_listed_in_session_block() -> None:
    intent = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        grade=GradeSpec(value="3", stated_explicit=True),
        skill=SkillSpec(canonical="pizza-table", as_stated="pizza table"),
        required_triggers=["pizza-table"],
    )
    prompt = build_scripted_ml_prompt(
        intent=intent,
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    assert "Required Smekens triggers" in prompt
    assert "pizza-table" in prompt


# ----------------------------------------------------------------------
# Conversation context rendering
# ----------------------------------------------------------------------


def test_conversation_snippet_included_when_turns_exist() -> None:
    conv = Conversation(session_id="s1")
    conv.append(Turn(index=0, role=Role.USER, text="How do I teach paragraph writing?"))
    conv.append(Turn(index=1, role=Role.ASSISTANT, text="Here's the pizza-table strategy..."))

    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=conv,
    )
    assert "CONVERSATION" in prompt
    assert "paragraph writing" in prompt
    assert "pizza-table" in prompt


def test_conversation_block_absent_when_empty() -> None:
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    assert "CONVERSATION (recent turns)" not in prompt


# ----------------------------------------------------------------------
# Retrieved context block
# ----------------------------------------------------------------------


def test_retrieved_context_block_appears_when_present() -> None:
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="[1] Source: lww312-s8-ml05 | Page: 64\nPizza-table content...",
        conversation=Conversation(session_id="s1"),
    )
    assert "RETRIEVED CONTEXT" in prompt
    assert "Page: 64" in prompt


def test_retrieved_context_block_absent_when_empty() -> None:
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    assert "=== RETRIEVED CONTEXT ===" not in prompt


# ----------------------------------------------------------------------
# Repair feedback (retry prompt)
# ----------------------------------------------------------------------


def test_retry_preamble_combines_policy_and_judge_feedback() -> None:
    """The repair preamble aggregates structural + semantic feedback
    so the retry LLM sees everything to fix in one block."""
    from validation.judge_v4 import DimensionScore, JudgeVerdict
    from validation.policy import LessonPolicyResult

    policy = LessonPolicyResult()
    policy.errors.append("Step 3 is missing 'turn and talk'")

    judge = JudgeVerdict(
        narrative_coherence=DimensionScore(
            score=4, violations=["'listy' appears in Step 4 but not introduced"]
        ),
        strategy_gist_present=DimensionScore(score=9, violations=[]),
        step1_structure=DimensionScore(score=10, violations=[]),
    )

    preamble = build_retry_preamble(policy, judge)
    assert "STRUCTURAL POLICY VIOLATIONS" in preamble
    assert "turn and talk" in preamble
    assert "NARRATIVE COHERENCE" in preamble
    assert "listy" in preamble
    # Passing dimensions don't clutter the feedback
    assert "NAMED-STRATEGY GIST" not in preamble
    assert "STEP 1 STRUCTURE" not in preamble


def test_retry_preamble_empty_when_no_violations() -> None:
    """If both policy and judge pass, preamble is empty (no retry
    needed anyway — but called defensively from the handler)."""
    from validation.judge_v4 import DimensionScore, JudgeVerdict
    from validation.policy import LessonPolicyResult

    policy = LessonPolicyResult()  # no errors
    judge = JudgeVerdict(
        narrative_coherence=DimensionScore(score=10, violations=[]),
        strategy_gist_present=DimensionScore(score=10, violations=[]),
        step1_structure=DimensionScore(score=10, violations=[]),
    )

    preamble = build_retry_preamble(policy, judge)
    assert preamble == ""


def test_prompt_includes_repair_feedback_when_retry() -> None:
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
        repair_feedback="STRUCTURAL POLICY VIOLATIONS:\n  - Step 3 missing phrase",
    )
    assert "PREVIOUS ATTEMPT FAILED" in prompt
    assert "Step 3 missing phrase" in prompt


# ----------------------------------------------------------------------
# Step 4 close — grade-band branch (Brady E1 / non-negotiable #10,
# Wave 1a Task 4). K-2 lessons must be told to end "Let's go be
# writers!"; grades 3-12 must be told to end "Now it's your turn!".
# The static base prompt can no longer hardcode a single phrase (or
# claim omitting the close is fine) — build_scripted_ml_prompt injects
# the band-specific instruction from intent.grade.
# ----------------------------------------------------------------------


def _intent_with_grade(grade: str) -> TurnIntent:
    return TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        grade=GradeSpec(value=grade, stated_explicit=True, stated_turn=0),
        mode=ModeSpec(value="Inform", stated_explicit=True),
        skill=SkillSpec(canonical="labeling pictures", as_stated="labeling pictures"),
    )


def test_step4_close_k2_band_gets_lets_go_be_writers() -> None:
    prompt = build_scripted_ml_prompt(
        intent=_intent_with_grade("1"),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    assert "Let's go be writers!" in prompt
    assert "Now it's your turn!" not in prompt
    assert "K-2" in prompt


def test_step4_close_3_12_band_gets_now_its_your_turn() -> None:
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),  # grade "3" -> 3-12 band
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    assert "Now it's your turn!" in prompt
    assert "Let's go be writers!" not in prompt
    assert "3-12" in prompt


def test_step4_close_defaults_to_3_12_band_when_grade_missing() -> None:
    intent = TurnIntent(request_type=RequestType.SCRIPTED_ML)  # no grade at all
    prompt = build_scripted_ml_prompt(
        intent=intent,
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    assert "Now it's your turn!" in prompt
    assert "Let's go be writers!" not in prompt


def test_step4_close_still_bans_pd_plug_and_website_link() -> None:
    # E1 makes the close phrase mandatory — it must NOT relax the existing
    # prohibition on PD plugs / certificates / professional-development
    # references / Smekens-website links in Step 4.
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    assert "certificate" in prompt.lower()
    assert "professional-development reference" in prompt.lower() or "professional development" in prompt.lower()
    assert "smekens-website link" in prompt.lower()


# ----------------------------------------------------------------------
# Cache-friendly ordering
# ----------------------------------------------------------------------


def test_prompt_ordering_system_session_conversation_retrieved_repair() -> None:
    """Prompt-caching requires stable prefix. System rules first,
    then session (stable across turns), then conversation (append-only),
    then retrieved (fresh), then repair (only on retries)."""
    conv = Conversation(session_id="s1")
    conv.append(Turn(index=0, role=Role.USER, text="earlier turn text"))
    conv.append(Turn(index=1, role=Role.ASSISTANT, text="earlier response"))

    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="chunk content",
        conversation=conv,
        repair_feedback="retry me",
    )

    # Indices of each section in the final prompt
    session_idx = prompt.index("SESSION CONTEXT")
    conv_idx = prompt.index("CONVERSATION")
    retrieved_idx = prompt.index("RETRIEVED CONTEXT")
    repair_idx = prompt.index("PREVIOUS ATTEMPT FAILED")

    assert session_idx < conv_idx < retrieved_idx < repair_idx, (
        "prompt sections out of order — caching discipline broken"
    )


# ----------------------------------------------------------------------
# Fm5 — the LLM no longer authors citations (Python appends them)
# ----------------------------------------------------------------------
#
# Brady Fm5 redesign: the reverted prompt-reword had the model reformat raw
# "Book:/Page:" context headers, which leaked header-label words + blank page
# slots. The grounding clause must now tell the model NOT to author a citation
# — a deterministic soft-citation pointer is appended by Python (build_soft_
# citation / _build_outcome footer), so the LLM must be told it's "added for
# you automatically". Guard both directions so a re-inserted "MAY cite"
# authorization is caught.


def test_scripted_ml_prompt_defers_citation_to_python():
    # Fm5: the LLM must NOT author citations anymore; Python appends them.
    assert "MAY cite" not in _BASE_PROMPT
    assert "added for you" in _BASE_PROMPT


# ----------------------------------------------------------------------
# Citation identity — the model POINTS, the code SPEAKS
# ----------------------------------------------------------------------
#
# The page used to be chosen from retrieval RANK before generation ran, so
# "you'll find THIS LESSON on p.N" was decided before "this lesson" existed
# (measured live: cited page == top-ranked chunk's page 30/30; wrong page
# 10/30). The model is the only thing that knows which retrieved block it
# actually taught from — it reads "Source: <chunk_id>" on every block
# (assembler.py:79) — so it names one in MiniLesson.source_chunk_id and
# handlers/citation.py::resolve_attribution turns that into the pointer.
#
# NOTHING here weakens Fm5 above: the prohibition on the model writing a book
# or page of its own is the OTHER half of the same design, not a casualty of
# it. Both halves are asserted together on purpose — an "attribution" rule that
# arrived by re-authorizing the model to cite would be the reverted Fm5 attempt
# (leaked "Book:"/"Page:" label text and blank page slots) wearing a new name.


# ----------------------------------------------------------------------
# C1 — lesson_title is authored as a VERB-LED statement, distinct from
# the teacher-vocab skill_focus.
# ----------------------------------------------------------------------


def test_prompt_instructs_a_verb_led_lesson_title():
    """Brady C1: 'I love that it's a verb. It's a statement.' The model must be
    told to author lesson_title as a verb-led statement — if this rule erodes,
    the title silently reverts to a bare-noun echo of skill_focus with the gate
    still green (the C1 defect)."""
    # The field is named in the enumeration (strict mode requires it) AND the
    # imperative rule is present.
    assert "lesson_title" in _BASE_PROMPT
    lower = _BASE_PROMPT.lower()
    assert "verb" in lower  # the rule speaks of a verb-led title


def test_prompt_keeps_lesson_title_distinct_from_skill_focus():
    """lesson_title is a REPHRASING; skill_focus stays the teacher's exact
    wording. The prompt must keep both jobs — collapsing them back is the bug."""
    assert "skill_focus" in _BASE_PROMPT
    # skill_focus preservation rule is untouched (still asks for verbatim vocab)
    assert "verbatim" in _BASE_PROMPT.lower()


def test_scripted_ml_prompt_asks_the_model_to_NAME_its_source():
    """The generator half of the citation-identity design. If this rule is ever
    dropped, the model returns null forever, resolve_attribution resolves
    nothing, and the footer silently disappears from every lesson — green tests
    and all. This is the only thing that fails when that happens."""
    # The rule's core IMPERATIVE, not just the field name: "source_chunk_id"
    # also appears in the field enumeration (scripted_ml_prompt.py:67), so the
    # bare-name assertion below survives the instruction being reworded away —
    # deleting the rule is caught (via "null"), but degrading it silently is
    # not. This is the assertion that holds the model to being TOLD to name it.
    assert 'Set "source_chunk_id"' in _BASE_PROMPT
    assert "source_chunk_id" in _BASE_PROMPT
    # Nullable-but-REQUIRED under openai strict mode (locked in
    # test_generation_lesson_schema.py): the model cannot omit the key, so the
    # rule has to name the explicit-null case or a not-from-context lesson has
    # no legal answer.
    assert "null" in _BASE_PROMPT


def test_naming_a_source_did_not_re_authorize_the_model_to_cite():
    # Fm5's prohibition is load-bearing for the pointing design and must
    # survive it. Guarded here as well as above because THIS rule is the one
    # with a motive to erode it.
    assert "Do NOT include a book or\npage citation of your own" in _BASE_PROMPT
    assert "Never invent a page number or book title." in _BASE_PROMPT


def test_the_id_is_ordered_out_of_the_lesson_text():
    """scripted_ml_prompt.py:209-213 bans internal vocabulary from every step. A
    rule that hands the model a chunk id without saying where it may NOT go is
    the reason that ban would start losing."""
    assert "Never put this id anywhere in the lesson text" in _BASE_PROMPT


# ======================================================================
# Brady S3 — the deferred-skill EXCLUSION (scope) block
# ======================================================================
# The S3 guard ("Adding in X would come in a second or future mini-lesson") is
# rendered by dispatch AFTER generation, and for a long time that was ALL it
# did: nothing ever told the generator a skill had been deferred, so the LLM —
# reading a Launch source that covers both skills together — taught the deferred
# skill in full. The app shipped a payload that promised to defer a skill and
# then taught it: a self-contradiction.
#
# The fix is a prompt block derived from the SAME `deferred_skills` normalizer
# the guard uses. These tests lock the RULE (any deferred skill is excluded),
# never one instance — and, critically, lock that the block is INERT when
# nothing is deferred, which is what protects the 0/30 false-positive gate S3
# shipped against (see the B03 test below).

from handlers.formatting import deferred_skills, format_one_skill_guard  # noqa: E402
from handlers.scripted_ml_prompt import (  # noqa: E402
    _ONE_SKILL_SCOPE_MARKER,
    _ONE_SKILL_SCOPE_END_MARKER,
    _render_one_skill_scope_block,
)


def _intent_with(extras, *, as_stated="topic sentences") -> TurnIntent:
    """A SCRIPTED_ML intent whose PRIMARY skill is `as_stated` and whose
    scope-creep extras are `extras` (QU's additional_skills)."""
    return TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        grade=GradeSpec(value="3", stated_explicit=True, stated_turn=0),
        mode=ModeSpec(value="Inform", stated_explicit=True),
        skill=SkillSpec(canonical="topic sentences", as_stated=as_stated),
        additional_skills=extras,
    )


def _build(intent: TurnIntent, retrieved_context: str = "") -> str:
    return build_scripted_ml_prompt(
        intent=intent,
        retrieved_context=retrieved_context,
        conversation=Conversation(session_id="s1"),
    )


def _scope_block(prompt: str) -> str:
    """The scope block ONLY — so 'is the skill named as deferred?' can never be
    satisfied by the skill merely appearing in session/retrieved context."""
    if _ONE_SKILL_SCOPE_MARKER not in prompt:
        return ""
    start = prompt.index(_ONE_SKILL_SCOPE_MARKER)
    end = prompt.index(_ONE_SKILL_SCOPE_END_MARKER) + len(_ONE_SKILL_SCOPE_END_MARKER)
    return prompt[start:end]


# --- (a) the RULE: every deferred skill is excluded, whatever it is ----------


@pytest.mark.parametrize(
    "extras",
    [
        ["transitions"],
        ["conclusions"],
        ["strong verbs"],
        ["adding a hook"],
        ["introductions", "conclusions"],
        ["transitions", "introductions", "conclusions"],
        ["  transitions  "],  # normalized, still excluded
    ],
)
def test_prompt_excludes_every_deferred_skill(extras) -> None:
    """Parametrized over skill sets, not one hard-coded pair: whatever QU
    defers, the generator is told not to teach it. Catches a future fix that
    only handles the 'topic sentences + transitions' instance."""
    block = _scope_block(_build(_intent_with(extras)))
    assert block, "a populated additional_skills must produce a scope block"
    for skill in deferred_skills(extras):
        assert skill in block, f"{skill!r} must be named as deferred in the block"


def test_scope_block_names_the_primary_skill_to_teach() -> None:
    """The block must say what to teach, not only what to skip — an exclusion
    with no positive target invites the model to drop the lesson's focus."""
    block = _scope_block(_build(_intent_with(["transitions"])))
    assert "topic sentences" in block


def test_scope_block_carries_an_explicit_exclusion_instruction() -> None:
    """Naming the skill is not enough — the block must actually instruct the
    model not to teach it. Catches a block that degrades into a bare mention."""
    lowered = _scope_block(_build(_intent_with(["transitions"]))).lower()
    assert "do not" in lowered
    assert "deferred" in lowered


def test_scope_block_neutralizes_the_retrieved_source() -> None:
    """The ROOT CAUSE of the shipped defect: the retrieved Launch chunk covers
    both skills together, so the model pulled the deferred one in 'naturally'.
    The block must explicitly say the source covering it is not a licence to
    teach it."""
    lowered = _scope_block(_build(_intent_with(["transitions"]))).lower()
    assert "retrieved context" in lowered


def test_scope_block_tells_model_not_to_restate_the_guard() -> None:
    """dispatch already prepends the teacher-facing guard. Without this line the
    lesson re-explains the deferral in its own words — which is exactly the
    LLM-authored guard text the anti-Fm5 rule forbids."""
    lowered = _scope_block(_build(_intent_with(["transitions"]))).lower()
    assert "already been told" in lowered


def test_scope_block_survives_a_retrieved_context(  # noqa: D103
) -> None:
    prompt = _build(
        _intent_with(["transitions"]),
        retrieved_context="Launch p.42 — topic sentences and transitions ...",
    )
    assert _scope_block(prompt), "block must be present alongside retrieved context"


# --- (b) INERT when nothing is deferred — the B03 / false-positive gate ------


@pytest.mark.parametrize("empty", [[], [""], ["   "], ["", "  "]])
def test_prompt_byte_identical_when_nothing_deferred(empty) -> None:
    """No drift: with nothing deferred (or only blanks), the prompt is
    byte-for-byte the prompt we shipped before this feature existed. This is
    what keeps the S3 false-positive gate (0/30 live probes) valid — an
    always-on scope rule would make the generator start excluding legitimate
    sub-facets. `_intent_with([])` is the reference because [] is the field's
    default."""
    reference = _build(_intent_with([]))
    assert _build(_intent_with(empty)) == reference


def test_b03_golden_gets_no_exclusion() -> None:
    """Brady's golden B03: 'topic sentences and supporting details' is ONE
    skill — supporting details are PART of the topic-sentence lesson. QU
    correctly leaves additional_skills EMPTY, so NOTHING may tell the
    generator to exclude anything. If this fails, the app has started
    refusing to teach a legitimate sub-facet."""
    prompt = _build(
        _intent_with([], as_stated="topic sentence and supporting details")
    )
    assert _ONE_SKILL_SCOPE_MARKER not in prompt
    assert "deferred" not in prompt.lower()
    # The primary skill phrase is of course still present (session context) —
    # it just must never be framed as something to leave out.
    assert "supporting details" in prompt


def test_no_scope_language_leaks_into_the_base_prompt() -> None:
    """Guards the seam itself: the exclusion must stay CONDITIONAL. Catches a
    future 'simplification' that hoists the one-skill rule into _BASE_PROMPT,
    which would silently apply it to every lesson — B03 included."""
    assert "deferred" not in _BASE_PROMPT.lower()
    assert _ONE_SKILL_SCOPE_MARKER not in _BASE_PROMPT


def test_render_scope_block_empty_is_inert() -> None:
    for empty in ([], [""], ["  "], ["", "   "]):
        assert _render_one_skill_scope_block(_intent_with(empty)) == ""


# --- (d) guard and lesson can NEVER contradict ------------------------------


@pytest.mark.parametrize(
    "extras",
    [[], [""], ["  "], ["transitions"], ["  transitions "], ["", "conclusions"],
     ["introductions", "conclusions"]],
)
def test_guard_fires_iff_generator_is_constrained(extras) -> None:
    """THE anti-contradiction invariant, at the unit seam: the teacher-facing
    guard is emitted for exactly the inputs that constrain the generator.
    Both read the same `deferred_skills` normalizer, so neither can drift
    without this failing. A guard without the constraint is the shipped
    defect (promise to defer, then teach it); a constraint without the guard
    is its mirror (silently drop a skill the teacher asked for, unexplained)."""
    guard_fires = bool(format_one_skill_guard(extras))
    generator_constrained = bool(_render_one_skill_scope_block(_intent_with(extras)))
    assert guard_fires == generator_constrained


def test_scope_block_handles_missing_primary_skill() -> None:
    """Defensive: dispatch gates SCRIPTED_ML on a resolved skill, so this
    should be unreachable — but the renderer must not crash if it ever is."""
    intent = TurnIntent(
        request_type=RequestType.SCRIPTED_ML, additional_skills=["transitions"]
    )
    block = _render_one_skill_scope_block(intent)
    assert "transitions" in block


# ----------------------------------------------------------------------
# Brady SG2 / §F — the developmental writing stage reaches the composer
#
# THE SECOND SEAM. Once the gate stops demanding a grade on a subgroup+stage
# turn (handlers/clarify.py::effective_missing_required), SCRIPTED_ML composes
# a lesson with NO grade. If the stage never reaches the prompt, that lesson is
# pitched at nothing — a generic on-grade lesson that ignores the very
# picture-drawing stage the teacher supplied. Fixing the gate alone would trade
# a wrong QUESTION for a wrong LESSON.
#
# HOW_TO_TEACH already threads it (test_how_to_teach_prompt.py); these lock the
# same guarantee for the 4-step mini-lesson.
# ----------------------------------------------------------------------


def _stage_intent(**kw) -> TurnIntent:
    """A subgroup+stage lesson ask with NO grade — the defect's shape."""
    base = dict(
        request_type=RequestType.SCRIPTED_ML,
        skill=SkillSpec(canonical="leads", as_stated="strong leads"),
    )
    base.update(kw)
    return TurnIntent(**base)


@pytest.mark.parametrize("stage", ["picture", "label", "word", "sentence"])
def test_writing_level_threads_into_scripted_ml_prompt(stage: str) -> None:
    """SG2 threading (deterministic, no LLM): the stage value reaches SESSION
    CONTEXT and the early-writer stage rule is spliced in — for every stage."""
    prompt = build_scripted_ml_prompt(
        intent=_stage_intent(writing_level=stage, subgroup="SPED"),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    assert EARLY_WRITER_STAGE_RULE in prompt, "the SG2 stage rule must be spliced in"
    assert stage in prompt, "the stage value must reach SESSION CONTEXT"


def test_subgroup_threads_into_scripted_ml_prompt() -> None:
    """The subgroup is context the lesson is written FOR — it must reach the
    prompt alongside the stage (parity with the HOW_TO_TEACH builder)."""
    prompt = build_scripted_ml_prompt(
        intent=_stage_intent(writing_level="picture", subgroup="MLL"),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    assert "MLL" in prompt


def test_no_writing_level_is_noop_in_scripted_ml_prompt() -> None:
    """No-op for a normal on-grade lesson: the stage rule must NOT be injected,
    so the overwhelming-majority path is byte-for-byte unchanged (no bloat)."""
    prompt = build_scripted_ml_prompt(
        intent=_simple_intent(),
        retrieved_context="",
        conversation=Conversation(session_id="s1"),
    )
    assert EARLY_WRITER_STAGE_RULE not in prompt


def test_stage_rule_is_shared_verbatim_with_how_to_teach() -> None:
    """One source of truth for the SG2 principle: the SCRIPTED_ML builder must
    splice the SAME shared constant the HOW_TO_TEACH builder uses, so a future
    wording change can't drift out of one handler while staying in the other.
    """
    from handlers import _prompt_rules

    assert EARLY_WRITER_STAGE_RULE is _prompt_rules.EARLY_WRITER_STAGE_RULE
    lowered = EARLY_WRITER_STAGE_RULE.lower()
    assert "stage" in lowered and "grade" in lowered


def test_stage_rule_omits_outline_only_per_bullet_clause() -> None:
    """The shared SG2 core must NOT carry HOW_TO_TEACH's 'restate the stage in
    each BULLETED skill' (SG3) instruction: a 4-step mini-lesson has no
    bulleted skill list, so that clause would be an instruction to do something
    the output shape doesn't contain. SG3 stays spliced on the outline path
    only (locked by test_how_to_teach_prompt.py).
    """
    assert "bullet" not in EARLY_WRITER_STAGE_RULE.lower()
