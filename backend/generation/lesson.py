"""MiniLesson: structured-output schema for a 4-step Smekens mini-lesson.

Generation itself lives in handlers/scripted_ml.py (its own
``client.chat.completions.parse`` call, prompted via
handlers/scripted_ml_prompt.py). This module only defines the shared
Pydantic schema consumed by that generator and by validation/*.py.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class MiniLesson(BaseModel):
    """Structured output schema for a 4-step mini-lesson."""

    skill_focus: str = Field(description="The specific writing skill being taught")

    # Brady C1 ("I love that it's a verb. It's a statement."): the DISPLAYED
    # lesson title is a VERB-LED statement of the skill — deliberately DISTINCT
    # from skill_focus, which is pinned to the teacher's exact wording (the
    # step-body anchor + validate_skill_focus_vocab). Titling from skill_focus
    # alone gave the bare-noun echo Brady rejected ("Topic sentences"); this
    # field lets the model rephrase the DISPLAY title ("Write a clear topic
    # sentence") WITHOUT relaxing the vocab invariant on skill_focus.
    #
    # A plain `str` (not Optional): under openai strict mode every field is
    # forced into `required`, so — like source_chunk_id below, but with NO
    # nullable escape — the model MUST author it on every lesson (the prompt's
    # "Always include lesson_title" rule). The Python default keeps CODE
    # constructions (the abort stub at scripted_ml.py, library-verbatim, test
    # fixtures) constructible without naming it; when it is empty the frontend's
    # `lesson_title or skill_focus` fallback renders skill_focus.
    lesson_title: str = Field(
        default="",
        description=(
            "A VERB-LED statement of the skill, for the lesson's display title "
            "(e.g. 'Determine the strongest side', 'Write a clear topic "
            "sentence'). Begin with a verb — NEVER a bare noun ('the strongest "
            "side', 'topic sentences'). DISTINCT from skill_focus, which "
            "preserves the teacher's exact wording verbatim."
        ),
    )

    grade_level: str = Field(description="Target grade level")
    writing_mode: str = Field(description="Inform, Persuade, or Entertain")
    step_1_introduce: str = Field(description="2-3 sentences, ~30 sec intro")
    step_2a_tell: str = Field(description="<5 min explanation of the skill")
    step_2b_show: str = Field(description="~5 min think-aloud demonstration")
    step_3_interact: str = Field(description="~5 min student interaction")
    step_4_close: str = Field(description="3-4 sentences, ~30 sec closing")

    # The ONE field the teacher never sees. It is a POINTER, not prose: the
    # model names which retrieved block it taught from, and code turns that into
    # the "you'll find this lesson on p.N" footer (handlers/citation.py::
    # resolve_attribution). Before this, the page was chosen from retrieval RANK
    # *before* generation ran — so "this lesson" was cited before it existed
    # (measured live: cited page == top-ranked chunk's page 30/30, wrong page
    # 10/30). The model reads "Source: <chunk_id>" on every block
    # (retrieval/assembler.py:79) and is the only thing that knows which one it
    # used, so it points and we speak.
    #
    # Under openai strict mode this is nullable but NOT omittable: Optional[str]
    # emits anyOf[string, null] AND the field is forced into `required`
    # (verified against openai 2.30.0 / pydantic 2.12.5; locked by
    # tests/unit/test_generation_lesson_schema.py). Hence the prompt rule says
    # "Always include the key" — a lesson built from nothing must answer null,
    # it cannot stay silent. The Python default keeps the abort stub at
    # scripted_ml.py:475 constructible without naming the field.
    source_chunk_id: Optional[str] = Field(
        default=None,
        description=(
            "The exact `Source:` id shown in the header of the ONE retrieved "
            "block this lesson was built from, copied verbatim. Use null if the "
            "lesson was not built from a retrieved block."
        ),
    )
