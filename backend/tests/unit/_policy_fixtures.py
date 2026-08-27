"""Shared policy-test fixture (extracted from test_policy.py, Wave 0 Part 2).

A MiniLesson that passes every policy check by default; override fields per test.
"""
from __future__ import annotations

from generation.lesson import MiniLesson


def _good_lesson(**overrides) -> MiniLesson:
    """A lesson that passes every policy check by default. Override fields
    per-test to verify specific violations.

    Note: the default ``step_4_close`` is the 3-12 grade-band phrase ("Now
    it's your turn!"), matching the default ``grade_level="4"`` — so the
    Brady E1 close check passes by default. A test that validates this
    lesson under a K-2 grade MUST also override ``step_4_close`` to a K-2
    close ("Let's go be writers!"), or E1 will flag a grade-band mismatch."""
    # Step 1 is 20 words, Step 2A is 50 (≥ 2×), Step 2B is 120 (≥ 4×), etc.
    step_3 = (
        "Now let's help me with the next sentence together. "
        "Turn and talk with your partner about where a transition would go. "
        "When you come back to me, share what you decided. "
        "This is some of what you might say: 'However, my favorite flavor is chocolate.'"
    )
    step_2b = (
        "I close my eyes and picture my topic clearly. "
        "I wonder — what's the most important detail to add first? "
        "Hmm, let me try writing it this way. "
        "I think to myself, does this sound right? "
        "That doesn't work — let me revise. "
        "Let me try one more version with a transition word upfront, making sure "
        "the idea flows from the previous sentence. "
        "Now I read it aloud to check the rhythm and see if it's clear. "
        "I wonder if a reader would follow this — yes, I think they would. "
        "I close my eyes again and check the whole paragraph in my mind, adding "
        "one more supporting detail to make the argument stronger and more "
        "convincing to my audience. "
        "Hmm, that's better. I think to myself: the transition now clearly links "
        "the opening claim to the specific evidence I just provided."
    )
    step_2a = (
        "Writers use transitions to connect ideas between sentences and paragraphs. "
        "You use them when you want the reader to follow your thinking smoothly. "
        "You add them where ideas shift from one focus to another. "
        "Why? Because transitions make writing feel organized and intentional. "
        "How do you write one? Pick a word or phrase that signals the relationship "
        "between the two ideas — words like 'however', 'in addition', or 'because'."
    )
    defaults = dict(
        skill_focus="transitions between paragraphs",
        grade_level="4",
        writing_mode="Inform",
        step_1_introduce=(
            "Today we will learn how to use transitions in your writing. "
            "Transitions help the reader follow your thinking."
        ),
        step_2a_tell=step_2a,
        step_2b_show=step_2b,
        step_3_interact=step_3,
        step_4_close=(
            "Today you practiced using transitions to link your ideas. "
            "Now it's your turn! Try writing three sentences with a "
            "transition in your notebook."
        ),
    )
    defaults.update(overrides)
    return MiniLesson(**defaults)
