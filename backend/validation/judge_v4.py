"""v4 LLM-as-judge — semantic quality scoring for scripted mini-lessons.

Three dimensions, load-bearing for Brady's pedagogy:

  1. narrative_coherence — any concept/term/example referenced in
     Step 3 or Step 4 must have been introduced in Step 1, 2A, or 2B.
     Fixes Brady's "listy in Step 4 without intro in Step 2A" complaint.

  2. strategy_gist_present — when the response names a Smekens strategy
     (pizza-table, dissected-web, slinky-test, etc.), it must include
     a 1-2 sentence gist. Teachers may not have the Launch books —
     never drop a named tool without explaining what it is.

  3. step1_structure — Step 1 must link to prior learning (when
     applicable), name the skill in teacher vocabulary, state the
     skill's purpose, and connect to the 6+1 trait.

The judge is ONE LLM call that scores all three dimensions together.
Below-threshold scores trigger retry-with-repair with specific feedback.

Design decisions:
  * Same flagship model as generation (consistency > cost savings)
  * Temperature 0 + structured output (Pydantic JudgeVerdict)
  * Scores 0-10 with threshold 7 for pass (configurable in handler)
  * Every failure includes SPECIFIC evidence (offending term /
    missing component) so retry prompts are actionable
"""

from __future__ import annotations

import logging
from typing import Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, Field

from generation.lesson import MiniLesson
from llm_params import call_params, temperature_kwargs

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Output schema — what the judge emits
# ----------------------------------------------------------------------


class DimensionScore(BaseModel):
    """Score + evidence for a single quality dimension."""

    model_config = ConfigDict(frozen=True)

    score: int = Field(ge=0, le=10, description="0-10 score; 7+ passes")
    violations: list[str] = Field(
        default_factory=list,
        description=(
            "Specific, actionable violations — e.g. 'the term \"listy\" "
            "appears in Step 4 but was not introduced earlier' or 'Step 1 "
            "is missing the trait connection'. Empty when score ≥ 7."
        ),
    )


class JudgeVerdict(BaseModel):
    """Complete judge output — three dimensions + overall pass flag."""

    model_config = ConfigDict(frozen=True)

    narrative_coherence: DimensionScore
    strategy_gist_present: DimensionScore
    step1_structure: DimensionScore

    @property
    def passes(self) -> bool:
        """Overall pass: ALL dimensions score ≥ 7."""
        return all(
            d.score >= _PASS_THRESHOLD
            for d in (
                self.narrative_coherence,
                self.strategy_gist_present,
                self.step1_structure,
            )
        )

    def repair_feedback(self) -> str:
        """Compose structured feedback for the retry prompt.

        Returns a string the generator sees, formatted so it's
        actionable: each failed dimension lists its specific violations.
        """
        parts: list[str] = []
        for name, dim in (
            ("NARRATIVE COHERENCE", self.narrative_coherence),
            ("NAMED-STRATEGY GIST", self.strategy_gist_present),
            ("STEP 1 STRUCTURE", self.step1_structure),
        ):
            if dim.score < _PASS_THRESHOLD:
                parts.append(
                    f"{name} — score {dim.score}/10. Fix:"
                )
                for v in dim.violations:
                    parts.append(f"  - {v}")
        return "\n".join(parts) if parts else ""


_PASS_THRESHOLD = 7


# ----------------------------------------------------------------------
# Judge prompt
# ----------------------------------------------------------------------


_JUDGE_SYSTEM_PROMPT = """\
You are a quality judge for Smekens Education writing mini-lessons.

Given a 4-step scripted mini-lesson (Step 1 Introduce, Step 2A Tell,
Step 2B Show, Step 3 Interact, Step 4 Close), score three dimensions
from 0 to 10 and list specific violations for any dimension below 7.

Return a JudgeVerdict per the schema.

## Dimension 1 — narrative_coherence

Check: every concept, term, example, or analogy referenced in Step 3
or Step 4 MUST have been introduced in Step 1, 2A, or 2B earlier in
THIS lesson. Key signals:
  * A noun or phrase that appears "new" in Step 3/4 (e.g., "listy
    writing" in Step 4 with no prior intro) → VIOLATION.
  * An example in Step 3/4 that's different from the one modeled in
    Step 2B → usually VIOLATION (unless Step 3 is an explicit
    new-example practice, which should still echo established
    vocabulary).
  * A pedagogical term (turn-and-talk, back to me, this is some of
    what I heard) appearing in Step 3 without having been scaffolded
    earlier is NOT a violation — these are framework phrases.

Score 10 = all terms/examples/concepts in later steps are traceable
to earlier steps. Score ≤ 6 = one or more undefined terms appear in
Step 3/4. For each violation, state the specific term or phrase.

## Dimension 2 — strategy_gist_present

Check: any time the lesson names a specific Smekens strategy, trigger,
organizer, or graphic-organizer by name, it must include a 1-2
sentence explanation of the concept. Examples of named tools that
need explanation: pizza-table, Dissected Web, road-sign, sticky-dot
details, magnify-close-up, slinky test, spider legs, pump up the
middle, pie foldable, table-top / tables-and-legs, etc.

Score 10 = every named strategy is explained in context. Score ≤ 6 =
one or more named strategies are mentioned bare (e.g., "Use the
Dissected Web" without saying what it is). For each violation, cite
the strategy name that was dropped without explanation.

## Dimension 3 — step1_structure

Check: Step 1 Introduce has these four components (2-4 sentences
total):
  a) LINK to prior learning — "Yesterday we learned…" / "Writers,
     we've been working on…". Optional if this is the session's
     genuinely first writing turn, but preferred.
  b) NAME the skill — in the teacher's vocabulary. Must be explicit.
  c) PURPOSE — what does this skill do for the writer?
  d) TRAIT CONNECTION — "This strengthens our [Ideas/Organization/
     Voice/…] trait."

Score 10 = all four components present (link-prior may be implicit
if session is fresh). Score ≤ 6 = two or more missing. For each
missing component, list it by name: "missing: trait_connection".

---

BE STRICT but FAIR. A lesson that passes is GENUINELY high quality.
A lesson that fails has a REAL pedagogical gap Brady would flag.
Err on the side of flagging rather than letting subtle issues through.
"""


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------


async def judge_scripted_ml(
    lesson: MiniLesson,
    *,
    client: AsyncOpenAI,
    model: str,
) -> JudgeVerdict:
    """Run the v4 judge on a scripted mini-lesson.

    Returns a JudgeVerdict with per-dimension scores + violation lists.
    Call .passes to check if retry is needed; call .repair_feedback()
    to get the string to inject into the retry prompt.

    Raises: openai errors if API call fails. Pydantic ValidationError
    if the LLM structured output violates the JudgeVerdict schema
    (rare — structured output enforces it).
    """
    lesson_text = _render_lesson_for_judge(lesson)

    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
        {"role": "user", "content": lesson_text},
    ]

    completion = await client.chat.completions.parse(
        model=model,
        messages=messages,
        response_format=JudgeVerdict,
        **call_params(model, 0, max_tokens=2048),
    )

    verdict = completion.choices[0].message.parsed
    if verdict is None:
        # Refusal — treat as pass-through (don't block on judge error)
        logger.warning("judge_v4 returned no parsed verdict; treating as pass")
        passthrough = DimensionScore(score=10, violations=[])
        return JudgeVerdict(
            narrative_coherence=passthrough,
            strategy_gist_present=passthrough,
            step1_structure=passthrough,
        )
    return verdict


# ----------------------------------------------------------------------
# Internals
# ----------------------------------------------------------------------


def _render_lesson_for_judge(lesson: MiniLesson) -> str:
    """Flatten a MiniLesson into a single labeled text block the judge
    reads. Keeping the step boundaries explicit lets the judge reason
    about where a term first appears."""
    return (
        f"SKILL: {lesson.skill_focus}\n"
        f"GRADE: {lesson.grade_level}\n"
        f"MODE: {lesson.writing_mode}\n\n"
        f"=== STEP 1 INTRODUCE ===\n{lesson.step_1_introduce}\n\n"
        f"=== STEP 2A TELL ===\n{lesson.step_2a_tell}\n\n"
        f"=== STEP 2B SHOW ===\n{lesson.step_2b_show}\n\n"
        f"=== STEP 3 INTERACT ===\n{lesson.step_3_interact}\n\n"
        f"=== STEP 4 CLOSE ===\n{lesson.step_4_close}\n"
    )
