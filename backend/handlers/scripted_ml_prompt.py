"""Prompt builder for SCRIPTED_ML handler.

Consumes TurnIntent directly — no ledger lookups, no scattered kwargs.
The prompt encodes every Brady requirement as a first-class rule so
the handler doesn't have to patch around drift:

  * Step 1 structure (link-prior, skill-named, purpose, trait
    connection) — semantic rule enforced by judge_v4
  * Step 2A/2B depth — structural rule enforced by validate_lesson_depth
  * Step 2B monologue phrases — structural rule, validate_step_2b_monologue
  * Step 3 Smekens phrases (4 required) — structural, validate_step_3_phrases
  * Never "discuss", "activity", "I'll listen in", PD plug —
    validate_no_forbidden_words
  * Skill vocabulary preservation — validate_skill_focus_vocab
  * Trigger adherence — validate_trigger_usage
  * Citation honesty — validate_book_citation
  * Narrative coherence — judge_v4
  * Named-strategy-gist — judge_v4
  * Source attribution (source_chunk_id) — handlers/citation.py::
    resolve_attribution

Every rule is stated EXPLICITLY in the prompt. The validators/judge
are the safety net; the prompt tries hard enough that retries are rare.

On the attribution rule (the "## Grounding" block): the model POINTS, the
code SPEAKS. It names the ONE retrieved block it built from — it reads
"Source: <chunk_id>" on each block's header (retrieval/assembler.py:79) and
is the only thing that knows which one it taught — and Python renders the
citation from that chunk's typed metadata. The neighbouring Fm5 prohibition
(no book/page of the model's own) is the other half of the SAME design, not
a leftover: a previous attempt that let the model format citations itself
leaked "Book:"/"Page:" label text and blank page slots to teachers and was
reverted. The rule lives in the prompt; this rationale lives here, because
a prompt is not a scratchpad — an s4 fix once fed the model the exact
phrasing it was trying to remove (logs.md).

``source_chunk_id`` is also named in the field enumeration below: under
openai strict mode it is nullable but NOT omittable (see generation/lesson.py),
so the model must answer it on every lesson. An enumeration that still listed
only the eight lesson fields would contradict the schema it points at and
invite the model to null the ninth reflexively — which would delete the
footer from every lesson with the whole gate still green.
"""

from __future__ import annotations

from typing import Optional

from handlers._prompt_rules import EARLY_WRITER_STAGE_RULE, GLOBAL_VOCAB_RULES
from handlers.formatting import deferred_skills
from schemas import Conversation, TurnIntent
from validation.endings import REQUIRED_CLOSE_PHRASE, scripted_ml_grade_band


# ----------------------------------------------------------------------
# The stable system-prompt prefix (cache-friendly)
# ----------------------------------------------------------------------


_BASE_PROMPT = """\
You are Brady's AI Writing Co-Pilot. Generate a scripted 4-step Smekens
mini-lesson based on the teacher's query, retrieved Launch-book /
scripted-ML content, and the conversation history.

Return a MiniLesson object per the structured output schema, with fields:
skill_focus, lesson_title, grade_level, writing_mode, step_1_introduce,
step_2a_tell, step_2b_show, step_3_interact, step_4_close, source_chunk_id.

## Lesson title

Author "lesson_title" as a VERB-LED STATEMENT of what this lesson teaches —
it BEGINS with a verb and reads like an instruction to the writer:

  * "Determine the strongest side"
  * "Write a clear topic sentence"
  * "Organize reasons from strongest to weakest"

NEVER a bare noun or noun phrase — "the strongest side", "topic sentences",
"transitions" are all WRONG. It is a statement, not a label.

"lesson_title" is DISTINCT from "skill_focus". skill_focus stays the
teacher's exact wording (see the vocabulary rule below); lesson_title is your
verb-led rephrasing of it for the display title. Always include lesson_title.

## Step 1 — Introduce (2-4 sentences, ~30 seconds)

Every Step 1 MUST have these four components:

  1. LINK to prior learning — a brief connection like "Yesterday we
     learned…" or "Writers, we've been working on…". (If this is the
     teacher's first message about this topic, you can skip this line,
     but prefer to include it when any prior context exists.)
  2. NAME the skill — in the teacher's vocabulary. Use skill_focus
     verbatim from `skill_focus` (preserve the teacher's wording).
  3. PURPOSE — one sentence: what does this skill DO for the writer?
     "This helps writers…" / "This makes writing clearer by…".
  4. TRAIT CONNECTION — explicitly name the 6+1 writing trait:
     "This strengthens our Ideas/Organization/Voice/Word Choice/Sentence
     Fluency/Conventions trait."

Step 1 is short. Pack the four components tightly.

## Step 2A — Tell (1-5 minutes, 80-250 words)

Explain the skill: WHAT it is (definition), WHY writers use it, HOW it
works (the steps or approach). Introduce ALL terms, analogies, examples
that you'll reference later in the lesson. If Step 4 will mention
"listy writing" or "pump up the middle" or any Smekens concept, it must
be introduced HERE.

Step 2A should be at LEAST 2× longer than Step 1.

## Step 2B — Show / Think-Aloud (1-5 minutes, 150-500 words)

Model the skill live. Use the teacher's internal monologue voice:

  * "I close my eyes and think…"
  * "I wonder…"
  * "Hmm, let me try…"
  * "Actually, that doesn't work because…"
  * "I think to myself…"
  * "Let me reconsider…"

Use the FIRST person. Narrate every choice — what you're considering,
what you're rejecting, why. This must include AT LEAST TWO monologue
phrases from the list above.

If the retrieved context contains a specific example (e.g., "My mom is
having surgery. She is very anxious." for a transitions think-aloud),
PRESERVE THAT EXAMPLE. Do not invent a different one when a grounded
example is available.

Step 2B MUST be AT LEAST 4× as long as Step 1 (this is Brady's hard rule).

Depth ratios apply REGARDLESS of grade level. A K-1 Step 2B needs the
same ≥4× depth as a 12th-grade Step 2B — the think-aloud is how modeling
actually teaches, and a short one shortchanges young writers as much as
older ones. Do NOT shorten Step 2B because the grade is young.

## Step 3 — Interact (1-3 minutes)

Gradual-release practice with students. Step 3 MUST contain ALL FOUR
of these exact Smekens phrases (case-insensitive matches are fine):

  * "Help me with the next" (continuing the modeling)
  * "Turn and talk" (the student-to-partner cue)
  * "Back to me" (returning the class focus)
  * "This is some of what I heard" (summarizing what students offered)

The flow: pose a new challenge → "Help me with the next one" → model
a partial example → "Turn and talk" → pause → "Back to me. This is
some of what I heard from you: [echo student contribution]" → apply it.

The final Smekens cue ("this is some of what") is the OPENING of a full
closing sentence, not the whole sentence. After "Back to me", write
"This is some of what I heard from you..." and then
MODEL A TEACHER-VOICED ANSWER demonstrating the skill on the Step 3
example — the same way you did in Step 2B. Do NOT stop at "this is
some of what." with nothing following; that fails the requirement.

A correct tail of Step 3 looks like:

    "...Let's turn and talk about this. [pause] Back to me. This is
    some of what I heard from you: [one or two modeled sentences that
    apply the skill to the Step 3 example using the teacher's voice]."

FORBIDDEN in Step 3 (and everywhere):
  * "discuss" / "discussion"  — NEVER use this word
  * "I'll listen in"          — NEVER use this phrase
  * "activities" / "activity" — NEVER use this word (use "practice",
                                "writing time", "try")

## Step 4 — Close (3-4 sentences, ~30 seconds)

Close by:
  1. Naming what was taught (using the same vocabulary as Step 1).
  2. Assigning independent writing time.
  3. Referencing a concept ALREADY INTRODUCED in Steps 1-2B (no new
     terms appear here — every concept must have been introduced
     earlier).

End Step 4 with the EXACT grade-band closing phrase given in the
"STEP 4 CLOSE REQUIREMENT" section below — it is mandatory, never
omitted, and never the other grade band's phrase. Do NOT end with a
PD plug, a certificate mention, a professional-development reference,
or a Smekens-website link.

## Naming Smekens strategies

When the response names a specific Smekens strategy or organizer by
name (pizza-table, road-sign, slinky test, Dissected Web, magnify
close-up, sticky-dot details, etc.), include a 1-2 sentence GIST of
what the strategy is IN CONTEXT. Teachers may not have the Launch
books — never drop a named tool without explaining what it is.

Good: "Use the pizza-table strategy: imagine each main idea as a
table-top that needs supporting 'leg' sentences to hold it up."

Bad: "Use the pizza-table strategy. [no explanation]"

## Grounding

The retrieved context contains Launch-book chunks (when available) and
scripted-ML content. Use it as authoritative source material — paraphrase
or quote examples from it rather than inventing. Do NOT include a book or
page citation of your own — a pointer to the Launch book is added for you
automatically. Never invent a page number or book title.

Set "source_chunk_id" to the exact `Source:` id from the header of the ONE
retrieved block you built this lesson from, copied character-for-character.
If you did not build it from a retrieved block, set it to null. Always
include the key. Never put this id anywhere in the lesson text itself.

## Forbidden in ANY step

  * "discuss" (verb or noun)
  * "activities" / "activity"
  * "I'll listen in"
  * "professional development" / "certificate" — no PD plug

These are policy violations that will trigger an automatic retry.

## Teacher-facing language

The teacher is a classroom educator, not a developer. Never expose
internal system vocabulary in ANY step — BANNED: "chunks", "retrieved
context", "retrieved chunks", "indexed", "corpus", "retrieval",
"retrieved material", "trigger" (in the system sense — the Smekens
metaphor-name sense is fine), "embedding".

## Classroom pacing (critical)

A scripted mini-lesson is a SINGLE classroom delivery. At ~150 words
per minute of teacher speaking time, target the whole lesson at
~1,200–2,200 words total (about 10–15 minutes). Proportional balance:

  * Step 1 Introduce:  5–10% of the lesson
  * Step 2A Tell:      15–25%
  * Step 2B Show:      30–45%   (longest by design — but not dominant)
  * Step 3 Interact:   20–30%
  * Step 4 Close:      5–10%

NO SINGLE STEP MAY EXCEED 55% OF THE TOTAL LESSON. If prior-turn
content (an expanded think-aloud, a long example) would push a step
past that ceiling when incorporated, compress it — preserve the key
teacher moves (testing alternatives, rejecting weak options,
reconsidering, rereading) but in classroom-paced prose. The teacher
can always ask for a deeper "prep version" separately; the lesson
itself must be deliverable in one session.

## Final instruction

Produce the MiniLesson object. Use skill_focus in the teacher's exact
vocabulary (from the SESSION CONTEXT below). Obey every rule above.
"""


# ----------------------------------------------------------------------
# Session-context + retrieved-context renderer
# ----------------------------------------------------------------------


def _render_session_context(intent: TurnIntent) -> str:
    """Render the structured TurnIntent fields into human-readable
    block for the prompt. Canonical names in retrieval context; teacher
    vocabulary preserved in skill_focus via `skill.as_stated`."""
    lines: list[str] = ["=== SESSION CONTEXT ==="]
    if intent.grade is not None:
        lines.append(f"Grade: {intent.grade.value}")
    # Brady SG2 / §F — the developmental stage and who the lesson is FOR. On a
    # subgroup/early-writer turn the grade is legitimately ABSENT (a stated
    # writing level supplants it — handlers/clarify.py::effective_missing_required),
    # so without these lines the lesson would be pitched at nothing: the model
    # would never learn the students are at the picture stage. Rendered only
    # when set, so normal on-grade lessons are unchanged. Wording mirrors the
    # HOW_TO_TEACH builder's session block (same facts, same names).
    if (intent.writing_level or "").strip():
        lines.append(
            f"Current writing level (developmental stage): {intent.writing_level}"
        )
    if (intent.subgroup or "").strip():
        lines.append(f"Subgroup: {intent.subgroup}")
    if intent.mode is not None:
        lines.append(f"Writing mode: {intent.mode.value}")
    if intent.trait is not None:
        lines.append(f"Writing trait: {intent.trait.value}")
    if intent.skill is not None:
        lines.append(
            f"Active skill (teacher vocabulary): {intent.skill.as_stated!r}"
        )
        lines.append(
            f"Canonical form (for retrieval): {intent.skill.canonical!r}"
        )
        lines.append(
            "Use the teacher vocabulary in skill_focus verbatim — preserve "
            "exact wording."
        )
    if intent.required_triggers:
        trig_list = ", ".join(intent.required_triggers)
        lines.append(
            f"Required Smekens triggers to name AND explain: {trig_list}"
        )
    lines.append("=== END SESSION CONTEXT ===")
    return "\n".join(lines)


def _render_step4_close_block(band: str) -> str:
    """Brady E1 (Smekens non-negotiable #10): the grade-band-specific Step 4
    closing phrase, injected explicitly since the static base prompt can't
    hardcode one phrase that's correct for both K-2 and 3-12 lessons.

    `band` is "K-2" or "3-12" (see validation.endings.scripted_ml_grade_band).
    The phrase comes from REQUIRED_CLOSE_PHRASE — the SAME dict the
    post-generation validator (validate_grade_band_close) checks against —
    so the prompt always asks for exactly what the policy check requires,
    with zero drift risk.
    """
    phrase = REQUIRED_CLOSE_PHRASE.get(band, REQUIRED_CLOSE_PHRASE["3-12"])
    return (
        "=== STEP 4 CLOSE REQUIREMENT ===\n"
        f"Grade band for this lesson: {band}.\n"
        f'Step 4 MUST end with the exact phrase "{phrase}" as its final '
        "sentence. Do not paraphrase it, do not omit it, and do not use "
        "the other grade band's phrase.\n"
        "=== END STEP 4 CLOSE REQUIREMENT ==="
    )


_ONE_SKILL_SCOPE_MARKER = "=== ONE SKILL ONLY ==="
_ONE_SKILL_SCOPE_END_MARKER = "=== END ONE SKILL ONLY ==="


def _render_one_skill_scope_block(intent: TurnIntent) -> str:
    """Brady S3 (generator half): tell the model which skill was DEFERRED and
    that it must not teach it.

    The dispatch gate renders Brady's teacher-facing guard ("Adding in X would
    come in a second or future mini-lesson") AFTER generation. For a long time
    that was the whole of S3 — nothing on the generation side ever saw
    ``additional_skills``, so the model, handed a Launch chunk that covers both
    skills together, taught the deferred one anyway. The delivered payload then
    promised to defer a skill while teaching it in full. This block closes that
    loop; the guard's wording is untouched (the anti-Fm5 rule constrains the
    guard's TEXT, not what the generator is told to write).

    Derived from ``deferred_skills`` — the SAME normalizer ``format_one_skill_guard``
    reads — so the guard fires for exactly the inputs that produce this block.
    Returns ``''`` when nothing is deferred (the overwhelming default), which
    keeps the prompt byte-identical on the ordinary single-skill path. That
    inertness is load-bearing: S3 shipped only after a live probe showed 0/30
    false positives, including Brady's golden B03 ("topic sentences and
    supporting details" is ONE skill), and an always-on scope rule would make
    the generator start excluding legitimate sub-facets. Nothing here may become
    unconditional — see tests/unit/test_scripted_ml_prompt.py.
    """
    extras = deferred_skills(intent.additional_skills)
    if not extras:
        return ""
    named = ", ".join(repr(s) for s in extras)
    primary = (
        repr(intent.skill.as_stated)
        if intent.skill is not None
        else "the skill in the session context above"
    )
    return "\n".join([
        _ONE_SKILL_SCOPE_MARKER,
        f"This mini-lesson teaches exactly ONE skill: {primary}.",
        f"DEFERRED to a second, future mini-lesson: {named}.",
        "The teacher has ALREADY been told this in a preface written for them, "
        "so do not restate, explain, or apologize for the deferral anywhere in "
        "the lesson.",
        "Do NOT define, model in the think-aloud, have students practise, or "
        "close on anything in the DEFERRED list. The retrieved context may "
        f"cover it alongside {primary} — that is not a reason to teach it here. "
        f"Name a deferred skill only where it is unavoidable to frame {primary}, "
        "and then only in passing.",
        _ONE_SKILL_SCOPE_END_MARKER,
    ])


def _render_conversation_snippet(conversation: Conversation) -> str:
    """Brief summary of prior turns so the model has continuity context
    (without bloating the prompt). We include last 4 turns' text only;
    detailed structured fields are stored in the ledger per Layer 1
    but aren't needed at generation time for SCRIPTED_ML — QU has
    already digested them into the intent."""
    if not conversation.turns:
        return ""
    lines: list[str] = ["=== CONVERSATION (recent turns) ==="]
    for turn in conversation.turns:
        role = turn.role.value.upper()
        body = (turn.text or "").strip()
        lines.append(f"[Turn {turn.index}] {role}: {body}")
    lines.append("=== END CONVERSATION ===")
    return "\n".join(lines)


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------


def build_scripted_ml_prompt(
    *,
    intent: TurnIntent,
    retrieved_context: str,
    conversation: Conversation,
    repair_feedback: Optional[str] = None,
    carried_context: Optional[str] = None,
) -> str:
    """Build the full system prompt.

    Order (cache-friendly):
      1. Stable base prompt (rules)       [cached]
      2. Session context (from intent)    [cached after first turn on session]
      3. Step 4 close requirement          [cached — derived from intent.grade]
      4. Conversation snippet              [cached after each turn]
      5. Retrieved context                 [fresh per query]
      6. Carried organizer                 [fresh; only on DEEPEN_PRIOR-from-
                                            a-description turns — Brady C3]
      7. One-skill scope block             [only when QU flagged scope-creep —
                                            Brady S3]
      8. Repair feedback                   [only on retries]

    ``carried_context`` (Brady C3) is the prior turn's described
    organizer/approach, threaded by DEEPEN_PRIOR when the teacher asks to turn
    a description into a lesson. When present it is rendered as an explicit
    must-incorporate block AFTER the retrieved context (so it lands in the
    non-cached tail) and BEFORE repair feedback. Absent (the default) it adds
    nothing — no bloat on the common generation path.

    Brady S3's deferred-skill exclusion (step 7) needs no new parameter: this
    builder already consumes the whole ``TurnIntent``, so ``additional_skills``
    — the scope-creep signal dispatch renders the teacher-facing guard from — is
    already in scope here. It, too, adds nothing when empty.
    """
    parts: list[str] = [_BASE_PROMPT, GLOBAL_VOCAB_RULES]

    # Brady SG2 / §F — only when the teacher gave a developmental writing level
    # (subgroup / early writer): teach the grade-level skill AT that stage
    # rather than the full on-grade written form. Shares the constant with the
    # HOW_TO_TEACH builder so the principle can't drift between them. SG3's
    # restate-per-bullet clause is deliberately NOT spliced here — a 4-step
    # lesson has no bulleted skill list. Conditional, so the common on-grade
    # path is unchanged and the prompt stays lean.
    if (intent.writing_level or "").strip():
        parts.append(EARLY_WRITER_STAGE_RULE)

    session_block = _render_session_context(intent)
    if session_block:
        parts.append(session_block)

    # Brady E1 (non-negotiable #10): grade-band-specific Step 4 close.
    # Computed from intent.grade the same way validate_grade_band_close's
    # caller does, so the prompt asks for exactly what the post-generation
    # policy check will enforce. Always appended (never conditional) —
    # scripted_ml_grade_band never returns empty, it defaults to "3-12".
    band = scripted_ml_grade_band(intent.grade.value if intent.grade else None)
    parts.append(_render_step4_close_block(band))

    conv_block = _render_conversation_snippet(conversation)
    if conv_block:
        parts.append(conv_block)

    if retrieved_context:
        parts.append("=== RETRIEVED CONTEXT ===")
        parts.append(retrieved_context)
        parts.append("=== END RETRIEVED CONTEXT ===")

    # Brady C3: a specific organizer/anchor-chart the PRIOR turn described, which
    # the teacher then asked to build a lesson around. Surface it explicitly and
    # tell the model to teach THAT tool — otherwise the description survives only
    # as generic conversation history and the lesson drifts to a different one.
    if carried_context:
        parts.append("=== CARRIED ORGANIZER / PRIOR APPROACH ===")
        parts.append(
            "The previous turn described this specific organizer / anchor-chart "
            "/ approach to the teacher, and the teacher then asked for a lesson "
            "built on it. Incorporate it into the lesson: teach the SAME "
            "organizer/approach and weave in its concrete details (its flaps, "
            "columns, dots, steps, or labels) rather than inventing a different "
            "tool."
        )
        parts.append(carried_context)
        parts.append("=== END CARRIED ORGANIZER ===")

    # Brady S3: when QU flagged scope-creep, tell the generator which skill was
    # DEFERRED so the lesson it writes actually matches the guard dispatch will
    # prepend. Placed AFTER the retrieved + carried context on purpose: those
    # blocks are where the deferred skill leaks in from (a Launch chunk covering
    # both skills is what made the model teach it), so the constraint reads last
    # and speaks to what precedes it. Empty additional_skills — the overwhelming
    # default — renders '' and is not appended at all, leaving the prompt on the
    # ordinary single-skill path byte-identical (the B03 / false-positive gate).
    scope_block = _render_one_skill_scope_block(intent)
    if scope_block:
        parts.append(scope_block)

    if repair_feedback:
        parts.append("=== YOUR PREVIOUS ATTEMPT FAILED — FIX THESE ISSUES ===")
        parts.append(repair_feedback)
        parts.append(
            "Fix ONLY the issues above. Do not break anything that was "
            "working. Keep skill_focus and the example you had if they "
            "were good — adjust only what the feedback calls out."
        )
        parts.append("=== END REPAIR FEEDBACK ===")

    return "\n\n".join(parts)


def build_retry_preamble(
    policy_result,  # LessonPolicyResult — avoid circular import
    judge_verdict,  # Optional[JudgeVerdict]
) -> str:
    """Compose the repair feedback string for a retry attempt.

    Concatenates structural policy errors (strings from
    validate_lesson_policy) and judge semantic feedback (from
    JudgeVerdict.repair_feedback()).
    """
    sections: list[str] = []
    if getattr(policy_result, "errors", None):
        sections.append("STRUCTURAL POLICY VIOLATIONS:")
        for err in policy_result.errors:
            sections.append(f"  - {err}")
    if judge_verdict is not None and not judge_verdict.passes:
        sections.append(judge_verdict.repair_feedback())
    return "\n".join(sections)
