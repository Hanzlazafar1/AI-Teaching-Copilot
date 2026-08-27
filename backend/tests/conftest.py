"""Shared fixtures for the backend test suite."""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# MUST run before any project import.
#
# `config` validates required secrets AT IMPORT TIME and raises if the OpenAI
# key is absent. The unit suite makes no network calls and needs no key, so
# without this the whole suite fails to collect on any machine that does not
# happen to have a real `.env` in the working directory — which is exactly
# what a fresh clone looks like.
#
# `config` already documented this flag as being set "automatically by pytest".
# Nothing actually set it. This makes that true.
#
# The flag is set ONLY for the duration of that first import and then restored.
# Leaving it set would neuter `test_config_secrets.py`, whose whole job is to
# assert that validation DOES raise when a required secret is missing — the
# flag would make those checks unable to fail.
# ---------------------------------------------------------------------------
_PRIOR_SKIP = os.environ.get("COPILOT_SKIP_SECRET_VALIDATION")
os.environ["COPILOT_SKIP_SECRET_VALIDATION"] = "1"
try:
    import config  # noqa: F401  — triggers the import-time validation under the flag
finally:
    if _PRIOR_SKIP is None:
        os.environ.pop("COPILOT_SKIP_SECRET_VALIDATION", None)
    else:
        os.environ["COPILOT_SKIP_SECRET_VALIDATION"] = _PRIOR_SKIP

import json  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from generation.lesson import MiniLesson  # noqa: E402
from retrieval.search import RetrievedChunk  # noqa: E402


@pytest.fixture
def sample_chunks() -> list[dict]:
    """Load a small set of real chunks for testing."""
    chunks_dir = Path("chunks")
    # Use the smallest file
    path = chunks_dir / "02-ai-coaching-language.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


@pytest.fixture
def sample_retrieved_chunks() -> list[RetrievedChunk]:
    """Fake retrieved chunks for testing assembler/generation."""
    return [
        RetrievedChunk(
            chunk_id="skill1-day1-k5-step2a-tell",
            source_document="SKILL 1. Day 1.pdf",
            content_type="lesson_script",
            content=(
                "Step 2A — Tell. Today we're going to learn about collecting "
                "facts and details from a text. WHAT: When you read informational "
                "text, you collect facts and details. WHEN: You do this whenever "
                "you read nonfiction. WHERE: In your reading notebook. WHY: Because "
                "writers need facts to write informational reports. HOW: Read, think, "
                "and jot down important facts."
            ),
            grade_level="K-5",
            writing_trait="Ideas",
            writing_mode="Inform",
            strategy_name="collect-facts-details",
            tier=1,
            step="step_2a_tell",
            score=0.85,
        ),
        RetrievedChunk(
            chunk_id="ep3-elem-intro",
            source_document="Episode 3 Elementary",
            content_type="episode_explanation",
            content=(
                "Informational writing requires students to collect facts and "
                "details from texts, organize them logically, and present them "
                "clearly for a reader. The four essential skills are: introduce "
                "the topic, develop the topic, organize the body, and conclude."
            ),
            grade_level="K-5",
            writing_trait="Organization",
            writing_mode="Inform",
            strategy_name="",
            tier=2,
            step="",
            score=0.72,
        ),
        RetrievedChunk(
            chunk_id="think-aloud-ideas-k2",
            source_document="Think-Aloud Scripts",
            content_type="think_aloud_guide",
            content=(
                "Think-aloud for Ideas (K-2): 'Let me show you how I collect "
                "facts from this book about bears. I'm going to read this page "
                "and think about what facts are important. Hmm, it says bears "
                "hibernate in winter. That's an important fact! I'll write that "
                "in my notebook.'"
            ),
            grade_level="K-2",
            writing_trait="Ideas",
            writing_mode="Inform",
            strategy_name="think-aloud",
            tier=1,
            step="step_2b_show",
            score=0.68,
        ),
    ]


@pytest.fixture
def good_lesson() -> MiniLesson:
    """A well-formed mini-lesson that should pass all checks."""
    return MiniLesson(
        skill_focus="Collecting facts and details from informational text",
        grade_level="3",
        writing_mode="Inform",
        step_1_introduce=(
            "Today, we're going to learn how to collect facts and details "
            "from informational text. This is an important skill that will "
            "help you become a better informational writer."
        ),
        step_2a_tell=(
            "When we read informational text, we need to pay attention to "
            "the facts and details the author shares. WHAT: Collecting facts "
            "means finding important information in what you read. WHEN: You "
            "do this whenever you're reading nonfiction or informational text. "
            "WHERE: You'll jot down facts in your writer's notebook. WHY: "
            "Because good informational writers need real facts to make their "
            "writing accurate and interesting. HOW: Read carefully, stop and "
            "think about what's important, then write it down."
        ),
        step_2b_show=(
            "Let me show you how I do this. I'm going to read this article "
            "about dolphins. 'Dolphins are mammals that live in the ocean.' "
            "Hmm, I think that's an important fact — dolphins are mammals, "
            "not fish. I'm going to write that in my notebook. Now I'll keep "
            "reading. 'Dolphins use echolocation to find food.' That's another "
            "great fact! I didn't know that. I'm adding it to my list. See how "
            "I'm stopping after each section to think about what facts matter?"
        ),
        step_3_interact=(
            "Now it's your turn! Turn and talk to your partner. I want you to "
            "read this short paragraph about penguins and collect at least two "
            "facts. Share the facts you found with your partner and explain why "
            "you think they're important. Remember, we're looking for real facts, "
            "not opinions."
        ),
        step_4_close=(
            "Today we learned how to collect facts and details from informational "
            "text by reading carefully and jotting down important information. "
            "During writer's workshop today, I want you to practice this skill "
            "with the article at your desk. Collect at least three facts to use "
            "in your informational writing piece."
        ),
    )


@pytest.fixture
def bad_lesson_empty_step() -> MiniLesson:
    """A lesson with an empty step — should hard-fail."""
    return MiniLesson(
        skill_focus="Topic sentences",
        grade_level="4",
        writing_mode="Inform",
        step_1_introduce="Today we will learn about topic sentences. This is important.",
        step_2a_tell="Topic sentences tell the reader what the paragraph is about.",
        step_2b_show="",  # EMPTY — hard fail
        step_3_interact="Talk to your partner about topic sentences.",
        step_4_close="Today we learned about topic sentences. Practice writing them.",
    )


@pytest.fixture
def bad_lesson_no_think_aloud() -> MiniLesson:
    """A lesson where step 2B lacks first-person think-aloud — soft issue."""
    return MiniLesson(
        skill_focus="Organization with transitions",
        grade_level="5",
        writing_mode="Inform",
        step_1_introduce=(
            "Today we will learn about using transitions to organize writing. "
            "Transitions help your reader follow your ideas."
        ),
        step_2a_tell=(
            "Transitions are words or phrases that connect ideas. WHAT: They "
            "show how ideas relate. WHEN: Use them between paragraphs and "
            "sentences. HOW: Choose words like 'first', 'next', 'finally'."
        ),
        step_2b_show=(
            "The teacher demonstrates writing a paragraph about seasons. "  # No I/me/my
            "The paragraph starts with 'First, spring brings warm weather.' "
            "Then the teacher adds 'Next, summer is the hottest season.' "
            "The teacher explains the transitions connect the ideas."
        ),
        step_3_interact=(
            "Turn and talk with your partner. Read this paragraph about "
            "animals and identify the transitions. Discuss why the author "
            "chose those transition words."
        ),
        step_4_close=(
            "Today we practiced using transitions in our writing. During "
            "writer's workshop, add at least two transitions to your current "
            "piece to help organize your ideas."
        ),
    )
