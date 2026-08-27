"""U2: 'How can I help?' header + 6 generic question-buttons (Brady doc 452-456).

Also covers U1: the frontend forces GPT-5.4 with no model choice (Brady:
"I stopped using 4.0 ... don't even give them the choice of 4.0")."""

import ast
import re
from pathlib import Path

from ui_content import (
    EXAMPLE_QUERIES,
    HELP_HEADER,
    HELP_QUESTIONS,
    format_lesson_header_display,
    lesson_display_title,
)

# app.py is a Streamlit script: importing it runs the password gate and
# st.stop() at module scope, which needs a live Streamlit ScriptRunContext
# and configured secrets — not available under pytest (this is exactly why
# ui_content.py above was extracted as an importable module). So the model
# assertions below read app.py's source statically instead of importing it.
_APP_PY = Path(__file__).resolve().parent.parent / "app.py"
_APP_SOURCE = _APP_PY.read_text()


def _model_profiles() -> dict[str, str]:
    """Statically extract the MODEL_PROFILES dict literal from app.py."""
    tree = ast.parse(_APP_SOURCE, filename=str(_APP_PY))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "MODEL_PROFILES"
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("MODEL_PROFILES assignment not found in app.py")


def test_header_is_how_can_i_help() -> None:
    assert HELP_HEADER == "How can I help?"


def test_six_generic_questions_verbatim() -> None:
    assert HELP_QUESTIONS == [
        "Do you need a scripted mini-lesson for a grade-level writing skill?",
        "What writing unit are you planning for?",
        "Are your students writing in pictures and letters?",
        "Do you want a suggested prop or trigger to teach a writing skill?",
        "Are you looking for different ideas to teach the same writing skill?",
        "Would you like to sharpen routines & expectations during writing time?",
    ]


def test_example_queries_send_the_question_verbatim() -> None:
    assert EXAMPLE_QUERIES == [(q, q) for q in HELP_QUESTIONS]


def test_no_grade_or_skill_baked_into_messages() -> None:
    # Brady's complaint: the old buttons baked in "5th grade persuasive".
    for _label, msg in EXAMPLE_QUERIES:
        assert not re.search(r"\b\d+(st|nd|rd|th)?\s+grade\b", msg.lower())


def test_turn_and_talk_button_removed() -> None:
    joined = " ".join(q.lower() for q in HELP_QUESTIONS)
    assert "turn and talk" not in joined


def test_model_is_forced_to_gpt_5_4_with_no_choice() -> None:
    # U1 (Brady): "I stopped using 4.0 ... make it the default/automatic,
    # don't even give them the choice of 4.0."
    profiles = _model_profiles()
    assert set(profiles.values()) == {"gpt-5.4"}
    assert not any("4o" in label.lower() for label in profiles)


def test_model_selectbox_removed() -> None:
    # There is no model choice left to render as a selectbox.
    assert "st.selectbox" not in _APP_SOURCE


# ---------------------------------------------------------------------------
# Fm4: render the backend-computed `header` field (with legacy fallback)
# ---------------------------------------------------------------------------


def test_prefers_backend_header() -> None:
    assert format_lesson_header_display(
        {"header": "Grade 3 | Informative", "grade_level": "3", "writing_mode": "Inform"}
    ) == "Grade 3 | Informative"


def test_fallback_grade_only_never_fabricates_mode() -> None:
    # No backend `header`: fall back to grade-only. The LLM-authored writing_mode
    # must NOT be synthesized into a header (upholds the backend "no fabricated
    # mode" rule end-to-end) — final whole-branch review finding.
    out = format_lesson_header_display({"grade_level": "3", "writing_mode": "Inform"})
    assert out == "Grade: 3"
    assert "Mode" not in out and "Inform" not in out


def test_empty_when_nothing() -> None:
    assert format_lesson_header_display({}) == ""


# ---------------------------------------------------------------------------
# Fm5: render the backend-computed soft `book_citation` footer on the
# structured-lesson path (mirrors the S3 one-skill guard). The copy-to-clipboard
# text must keep the citation so it isn't dropped from the copy path.
# ---------------------------------------------------------------------------


def test_lesson_as_text_includes_book_citation() -> None:
    from app import _lesson_as_text
    text = _lesson_as_text({
        "skill_focus": "Topic sentences",
        "step_1_introduce": "a", "step_2a_tell": "b", "step_2b_show": "c",
        "step_3_interact": "d", "step_4_close": "e",
        "book_citation": "If you have the 'Launching the Writers Workshop 3-12' book, you'll find this lesson on p.64.",
    })
    assert "If you have the 'Launching the Writers Workshop 3-12' book" in text


# ---------------------------------------------------------------------------
# E2: the backend delivers the teacher-facing customization follow-up as a
# `followup` field on the structured lesson (like `book_citation` above). The
# frontend is the ONLY thing that renders the structured path, so a field the
# backend delivers but app.py never reads is the same delivery gap one layer up.
# ---------------------------------------------------------------------------

_E2 = (
    "Does this script seem appropriate for your student-writers? "
    "Do I need to make anything more rigorous or simpler?"
)


def _lesson_with_followup() -> dict:
    return {
        "skill_focus": "Topic sentences",
        "step_1_introduce": "a", "step_2a_tell": "b", "step_2b_show": "c",
        "step_3_interact": "d", "step_4_close": "e",
        "followup": _E2,
    }


def test_lesson_as_text_includes_e2_followup() -> None:
    from app import _lesson_as_text
    assert _E2 in _lesson_as_text(_lesson_with_followup())


def test_lesson_as_text_puts_e2_followup_last() -> None:
    """E2 addresses the TEACHER and must close the lesson — after Step 4's
    student-facing close, never glued to it."""
    from app import _lesson_as_text
    text = _lesson_as_text(_lesson_with_followup())
    assert text.index(_E2) > text.index("Step 4")


def test_lesson_as_text_omits_e2_when_absent() -> None:
    """Back-compat: a payload with no `followup` renders nothing extra (the
    field is additive — older/other producers must not break)."""
    from app import _lesson_as_text
    lesson = _lesson_with_followup()
    del lesson["followup"]
    assert "rigorous or simpler" not in _lesson_as_text(lesson)


# ---------------------------------------------------------------------------
# C1: the DISPLAYED lesson title prefers the backend's model-authored, verb-led
# `lesson_title` and falls back to `skill_focus` (old stored history / the
# library-verbatim path carry no lesson_title). Brady: "I love that it's a
# verb. It's a statement." skill_focus stays the teacher-vocab anchor.
# ---------------------------------------------------------------------------


def test_lesson_display_title_prefers_lesson_title() -> None:
    assert lesson_display_title(
        {"lesson_title": "Determine the strongest side",
         "skill_focus": "the strongest side"}
    ) == "Determine the strongest side"


def test_lesson_display_title_falls_back_to_skill_focus() -> None:
    # Old stored history / library-verbatim payloads have no lesson_title.
    assert lesson_display_title({"skill_focus": "Topic sentences"}) == "Topic sentences"


def test_lesson_display_title_falls_back_when_lesson_title_empty() -> None:
    # An empty-string lesson_title (the abort-stub default) must not win over
    # a real skill_focus — `or` semantics, not `get`-with-default.
    assert lesson_display_title(
        {"lesson_title": "", "skill_focus": "Topic sentences"}
    ) == "Topic sentences"


def test_lesson_display_title_defaults_when_both_absent() -> None:
    assert lesson_display_title({}) == "Mini-Lesson"


def test_lesson_as_text_uses_lesson_title_as_h1_when_present() -> None:
    from app import _lesson_as_text
    text = _lesson_as_text({
        "lesson_title": "Determine the strongest side",
        "skill_focus": "the strongest side",
        "step_1_introduce": "a", "step_2a_tell": "b", "step_2b_show": "c",
        "step_3_interact": "d", "step_4_close": "e",
    })
    assert "# Determine the strongest side" in text
    # skill_focus is NOT used as the H1 when a lesson_title is present
    assert "# the strongest side" not in text


def test_lesson_as_text_h1_falls_back_to_skill_focus() -> None:
    from app import _lesson_as_text
    text = _lesson_as_text({
        "skill_focus": "Topic sentences",
        "step_1_introduce": "a", "step_2a_tell": "b", "step_2b_show": "c",
        "step_3_interact": "d", "step_4_close": "e",
    })
    assert "# Topic sentences" in text
