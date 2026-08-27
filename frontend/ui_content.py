"""Frontend copy extracted so it is importable + testable without running
Streamlit. Brady U2: 'How can I help?' + 6 generic question-buttons."""

from __future__ import annotations

HELP_HEADER = "How can I help?"

# Brady U2 (doc 452-456), verbatim. No grade or skill is baked in — clicking
# sends the question as-is so the backend asks the open follow-up instead of
# assuming specifics. "Coaching — turn and talk" is dropped (folded into #6).
HELP_QUESTIONS: list[str] = [
    "Do you need a scripted mini-lesson for a grade-level writing skill?",
    "What writing unit are you planning for?",
    "Are your students writing in pictures and letters?",
    "Do you want a suggested prop or trigger to teach a writing skill?",
    "Are you looking for different ideas to teach the same writing skill?",
    "Would you like to sharpen routines & expectations during writing time?",
]

# (label, message): label is the button text, message is sent as the user's
# chat message. For U2 they are identical — the question IS the button.
EXAMPLE_QUERIES: list[tuple[str, str]] = [(q, q) for q in HELP_QUESTIONS]


def lesson_display_title(lesson: dict) -> str:
    """Brady C1: the DISPLAYED lesson title prefers the backend's model-authored,
    verb-led ``lesson_title`` ("Determine the strongest side"), falling back to
    ``skill_focus`` (the teacher-vocab anchor) for old stored history and the
    library-verbatim path, which carry no lesson_title. ``or`` (not ``get`` with
    a default) so an empty-string lesson_title — the abort-stub default — still
    falls through to skill_focus."""
    return lesson.get("lesson_title") or lesson.get("skill_focus", "Mini-Lesson")


def format_lesson_header_display(lesson: dict) -> str:
    """Prefer the backend-computed 'header'; else fall back to GRADE-ONLY.
    Never synthesize a mode from the LLM-authored writing_mode — the backend
    rule is 'no fabricated mode', and the frontend fallback must uphold it too."""
    hdr = lesson.get("header")
    if hdr:
        return hdr
    # No backend `header` (old stored history, or a rare gradeless lesson):
    # grade-only — never a fabricated mode (final whole-branch review finding).
    g = lesson.get("grade_level")
    return f"Grade: {g}" if g else ""
