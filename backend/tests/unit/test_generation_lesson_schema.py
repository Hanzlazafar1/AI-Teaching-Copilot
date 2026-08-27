"""The attribution field's CONTRACT with the OpenAI strict-output schema.

Locked because the whole citation-identity design rests on the model being able
to return this field, and on a failed attempt still being constructible.
"""
from generation.lesson import MiniLesson


def _full(**over):
    base = dict(
        skill_focus="Generate reasons to support an opinion",
        grade_level="3", writing_mode="Persuade",
        step_1_introduce="a", step_2a_tell="b", step_2b_show="c",
        step_3_interact="d", step_4_close="e",
    )
    base.update(over)
    return MiniLesson(**base)


def test_source_chunk_id_defaults_to_none_so_the_abort_stub_still_constructs():
    # scripted_ml.py:475 builds a stub WITHOUT this field when the generator
    # returns nothing. It must not raise.
    assert _full().source_chunk_id is None


def test_source_chunk_id_round_trips():
    assert _full(source_chunk_id="lww312-s8-ml05-table-top-leg-sentences").source_chunk_id == (
        "lww312-s8-ml05-table-top-leg-sentences"
    )


def test_strict_schema_makes_it_nullable_but_REQUIRED():
    """openai strict mode puts every field in `required`; optionality is expressed
    as anyOf[..., null]. So the PROMPT must tell the model to emit an explicit
    null — it cannot omit the key. If this ever flips, the prompt rule is wrong."""
    from openai.lib._pydantic import to_strict_json_schema

    schema = to_strict_json_schema(MiniLesson)
    assert "source_chunk_id" in schema["required"]
    assert {"type": "null"} in schema["properties"]["source_chunk_id"]["anyOf"]


# ---------------------------------------------------------------------------
# lesson_title (Brady C1) — the model-authored VERB-LED display title, distinct
# from skill_focus (the teacher-vocab anchor). A plain `str`, so strict mode
# forces it REQUIRED (the model must always emit a title); the Python default
# keeps code constructions (the abort stub, library-verbatim, test fixtures)
# building without naming it.
# ---------------------------------------------------------------------------


def test_lesson_title_defaults_to_empty_so_code_constructions_still_construct():
    # scripted_ml.py's abort stub + the library-verbatim/test fixtures build a
    # MiniLesson WITHOUT this field; it must not raise, and must default empty so
    # the frontend `lesson_title or skill_focus` fallback kicks in.
    assert _full().lesson_title == ""


def test_lesson_title_round_trips():
    assert _full(lesson_title="Determine the strongest side").lesson_title == (
        "Determine the strongest side"
    )


def test_lesson_title_is_required_but_NOT_nullable_under_strict_mode():
    """A plain `str`: strict mode forces it into `required` (the model cannot
    omit it), but — UNLIKE source_chunk_id — it is NOT nullable, so there is no
    `{"type": "null"}` escape. The prompt must ALWAYS ask for a real title."""
    from openai.lib._pydantic import to_strict_json_schema

    schema = to_strict_json_schema(MiniLesson)
    assert "lesson_title" in schema["required"]
    prop = schema["properties"]["lesson_title"]
    assert prop.get("type") == "string"
    assert "anyOf" not in prop


def test_the_attribution_never_reaches_teacher_text():
    """The id is a POINTER for code — never a word in the lesson.

    ``_lesson_to_free_text`` names its fields explicitly. If someone ever
    switched it to iterating ``model_dump()``, the id would land in
    ``response_text``, and TWO real things break — neither of them delivery:

      1. ``response_text`` is what the structural validators scan
         (``validate_lesson_policy(response_text=...)``, scripted_ml.py:497).
      2. ``response_text`` becomes the assistant ``Turn.text``
         (routes_v4.py:152), which ``_render_conversation_snippet`` replays
         into the NEXT turn's prompt — feeding the model internal vocabulary
         its own rules ban (scripted_ml_prompt.py:209-213) and inviting it to
         echo the id back into a lesson.

    ⚠️ This test does NOT cover delivery. The payload the teacher actually
    receives is ``structured = lesson.model_dump()`` (scripted_ml.py:756) —
    which iterates model_dump() *today* and therefore carries this id the
    moment the field exists. Stripping it there is Task 5's step (the plan
    assigns ``_finalize_ml_delivery``); the current Streamlit frontend renders
    only named keys, so nothing renders it in the meantime.
    """
    from handlers.scripted_ml import _lesson_to_free_text

    text = _lesson_to_free_text(_full(source_chunk_id="lww312-s8-ml05-table-top-leg-sentences"))
    assert "lww312" not in text
    assert "source_chunk_id" not in text
