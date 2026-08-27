"""SCRIPTED_ML lesson-shape validators — depth, Step-3, Step-2B voice, balance.

Split out of validation/policy.py (Wave 0 Part 2). All operate on a MiniLesson.
Re-exported from validation.policy.
"""
from __future__ import annotations

import re

from generation.lesson import MiniLesson


STEP_2A_MIN_MULTIPLIER = 2.0
# Target vs floor, explained:
# - Prompt still tells the model "Step 2B MUST be ≥4× Step 1, aim for ~5×"
#   so the generator produces appropriately deep think-alouds.
# - Validator accepts ≥3× as the pass/fail floor. GPT-4o lands Step 2B at
#   3.0–5.5× Step 1 across sampling; the cluster near 4.0 means ~35% of
#   short-Step-1 lessons (K-1, young grades) would trip a 4.0 floor and
#   ship as low_quality despite being pedagogically fine. A 3.0 validator
#   floor tolerates that sampling noise without softening the instruction.
# This asymmetry (generate-at-4×, accept-at-3×) is intentional — the model
# aims for Brady's rule, the validator catches truly short Step 2Bs.
STEP_2B_MIN_MULTIPLIER = 3.0


def _word_count(text: str) -> int:
    return len(text.split()) if text else 0


def validate_lesson_depth(lesson: MiniLesson) -> list[str]:
    """Enforce Brady's depth rule: Step 2A ≥ 2× Step 1, Step 2B ≥ 3× Step 1.

    Plan §17.1: "Steps 2A & 2B should be significantly longer than Steps 1, 3, 4."
    We use Step 1 as the reference; callers wanting a stricter bound could
    compare against max(step_1, step_3, step_4) — we pick step_1 because it's
    the most consistent anchor.

    Note: the generation prompt tells the model to hit ≥4× for Step 2B (with
    a target of ~5×). The validator accepts ≥3× as a tolerance floor —
    sampling noise around the 4× target sends ~35% of young-grade lessons
    just under. The asymmetry (generate-at-4×, accept-at-3×) keeps the rule
    strong where it matters (generation aim) without over-penalizing the
    LLM's natural variance.
    """
    errors: list[str] = []
    s1 = _word_count(lesson.step_1_introduce)
    s2a = _word_count(lesson.step_2a_tell)
    s2b = _word_count(lesson.step_2b_show)

    if s1 == 0:
        return errors  # empty step_1 is a structural failure, caught elsewhere.

    if s2a < s1 * STEP_2A_MIN_MULTIPLIER:
        errors.append(
            f"Step 2A is too short ({s2a} words). It must be at least "
            f"{STEP_2A_MIN_MULTIPLIER}× the length of Step 1 ({s1} words) — "
            f"target ≥ {int(s1 * STEP_2A_MIN_MULTIPLIER)} words. Step 2A "
            f"must cover what the skill is, when/where writers use it, why "
            f"it matters, and how to do it."
        )
    if s2b < s1 * STEP_2B_MIN_MULTIPLIER:
        errors.append(
            f"Step 2B is too short ({s2b} words). It must be at least "
            f"{STEP_2B_MIN_MULTIPLIER}× the length of Step 1 ({s1} words) — "
            f"target ≥ {int(s1 * STEP_2B_MIN_MULTIPLIER)} words. Step 2B is "
            f"where the teacher models the skill live — it should be a full "
            f"think-aloud monologue, not a summary."
        )
    return errors


STEP_3_REQUIRED_PHRASES: tuple[str, ...] = (
    "help me with the next",
    "turn and talk",
    "back to me",
    "this is some of what",
)

# Minimum number of alpha characters that must follow the "this is some of
# what" cue (Phase 16.4). Brady's B-G09 requires the cue to OPEN a modeled
# teacher answer: "This is some of what I heard from you... [modeled
# response]". A lesson that ends the step with "...this is some of what."
# and nothing more satisfies the literal substring gate but fails Brady's
# requirement. 40 chars is ~one short sentence and enough to catch the
# dangling-cue pattern without false-flagging legitimate tails.
_STEP_3_CUE_MIN_TAIL_CHARS = 40


def validate_step_3_phrases(lesson: MiniLesson) -> list[str]:
    """All four Smekens interaction phrases must appear in Step 3, AND the
    final cue ("this is some of what") must be followed by a non-trivial
    tail (a modeled teacher response, per Brady B-G09 [SC:35]).

    These aren't style preferences — they cue the specific classroom moves
    Smekens teachers use: help-me-with-the-next (modeling together), turn-
    and-talk (peer practice), back-to-me (reconvene), this-is-some-of-what-
    I-heard-from-you + modeled response (affirm and demonstrate).

    Returns a list of human-readable error strings. Empty list = pass.
    """
    errors: list[str] = []
    text = (lesson.step_3_interact or "").lower()
    missing = [p for p in STEP_3_REQUIRED_PHRASES if p not in text]
    if missing:
        errors.append(
            f"Step 3 is missing the required Smekens phrase(s): "
            f"{', '.join(repr(p) for p in missing)}. These are EXACT "
            f"character-for-character substrings — do NOT paraphrase "
            f"(e.g. 'help with the next' or 'help me with this' do NOT "
            f"satisfy 'help me with the next'). All four must appear as "
            f"literal substrings: "
            f"{', '.join(repr(p) for p in STEP_3_REQUIRED_PHRASES)}."
        )
        # Short-circuit the tail check when the cue itself is missing —
        # the tail requirement only makes sense if the cue is present.
        return errors

    tail_error = _check_step_3_closing_tail(text)
    if tail_error:
        errors.append(tail_error)
    return errors


def _check_step_3_closing_tail(lower_text: str) -> str | None:
    """Ensure a modeled teacher answer follows "this is some of what".

    Locates the LAST occurrence of the cue (Smekens teachers may say the
    phrase only once; we check the last one so a dangling trailing cue is
    caught even if earlier prose happens to use the same words) and
    verifies the tail contains enough alpha content to plausibly be a
    modeled answer. Punctuation and whitespace are ignored so ``...``
    and ``!``-style endings don't satisfy the requirement.

    Returns an error string when the tail is too thin; None when it passes.
    Expected input: already-lowercased Step 3 body.
    """
    cue = "this is some of what"
    idx = lower_text.rfind(cue)
    if idx < 0:
        # Upstream already flagged the missing cue; nothing more to say.
        return None
    tail = lower_text[idx + len(cue):]
    # Count alpha characters only — punctuation and filler don't model a
    # teacher answer.
    alpha_count = sum(1 for ch in tail if ch.isalpha())
    if alpha_count >= _STEP_3_CUE_MIN_TAIL_CHARS:
        return None
    return (
        f"Step 3 contains 'this is some of what' but no modeled teacher "
        f"answer follows it (found only {alpha_count} alpha chars of tail "
        f"content). Brady's B-G09 requirement: the cue opens a full "
        f"sentence — 'This is some of what I heard from you...' followed "
        f"by a teacher-voiced modeled response that applies the skill to "
        f"the Step 3 example. A cue with nothing after it fails the gate."
    )


STEP_2B_MONOLOGUE_PHRASES: tuple[str, ...] = (
    # Original cue set (Brady-sourced via B-G02)
    "i close my eyes",
    "i wonder",
    "i think to myself",
    "let me try",
    "that doesn't work",
    "hmm",
    # Phase 16.8 / LOW-1 expansion — alternative monologue markers that
    # read naturally for topics where "I close my eyes" or similar cues
    # feel forced (e.g. a punctuation think-aloud). The prompt still
    # lists these and asks the model to pick fitting ones; the validator
    # accepts any ≥2 from the combined set.
    "wait, let me reconsider",
    "my first thought is",
    "actually,",
    "on second thought",
)

MIN_MONOLOGUE_PHRASES = 2  # At least 2 of the above must appear.


# Broader first-person deliberation signals — the regex fallback for when
# the LLM writes in natural monologue voice without hitting the canonical
# Brady phrases. Same principle as the trigger-usage stem-prefix fix: the
# rule's intent is "thinking-out-loud voice", not "verbatim phrase match".
# Verbs here are all ACTIVE deliberation (trying / weighing / reconsidering /
# noticing) — not passive modals ("I should", "I would") that merely indicate
# first-person without thinking-out-loud signal.
_MONOLOGUE_VOICE_RE = re.compile(
    r"\b(?:"
    r"i(?:'ll|'m)?\s+(?:"
    r"try(?:ing|ied)?|wonder(?:ing|ed)?|consider(?:ing|ed)?|"
    r"think(?:ing)?|decide(?:d|\s+to)?|pause(?:d|\s+to\s+think)?|"
    r"reconsider(?:ing|ed)?|realize(?:d)?|notice(?:d)?|"
    r"ask\s+myself|tell\s+myself|prefer(?:red)?|"
    r"need\s+to\s+(?:think|decide|figure)"
    r")"
    r"|"
    r"let\s+me\s+(?:try|think|reconsider|test|check|reread|pause|see)"
    r"|"
    r"what\s+if(?:\s+i)?"
    r")\b",
    re.IGNORECASE,
)


MONOLOGUE_ERROR_PREFIX = "Step 2B voice"


def is_monologue_voice_error(error: str) -> bool:
    return error.startswith(MONOLOGUE_ERROR_PREFIX)


def _count_monologue_signals(text: str) -> tuple[int, list[str]]:
    """Return (signal_count, sample_hits) for Step 2B monologue voice.

    Signals = literal Brady phrases + distinct regex-matched voice
    markers. Counted as a single set so a sentence containing both
    'I wonder' (literal) and 'i wonder' (regex) only counts once.
    """
    lowered = text.lower()
    literal_hits = [p for p in STEP_2B_MONOLOGUE_PHRASES if p in lowered]
    regex_hits = {m.group(0).strip().lower() for m in _MONOLOGUE_VOICE_RE.finditer(text)}
    # Deduplicate: remove regex hits whose text is already covered by a literal
    all_signals = set(literal_hits) | regex_hits
    return len(all_signals), sorted(all_signals)[:6]


def validate_step_2b_monologue(lesson: MiniLesson) -> list[str]:
    """Step 2B must sound like a teacher thinking out loud, not narrating.

    Accepts ANY combination of ≥2 first-person deliberation signals:
      - The classic Brady phrases ("I wonder", "let me try", "hmm", …)
      - OR natural first-person-thinking voice ("I try", "I consider",
        "I realize", "Let me reconsider", "What if I try", …)

    The rule's intent is "thinking-out-loud voice", not specific words.
    Narration ("The teacher demonstrates…") has zero first-person
    deliberation signals and still correctly fails. Register-aware error
    phrasing so the LLM knows what "fix" actually means.
    """
    text = lesson.step_2b_show or ""
    signal_count, sample_hits = _count_monologue_signals(text)
    if signal_count >= MIN_MONOLOGUE_PHRASES:
        return []
    return [
        f"{MONOLOGUE_ERROR_PREFIX}: Step 2B must sound like a teacher "
        f"thinking out loud — first-person internal monologue with "
        f"moments of wondering, trying alternatives, reconsidering, "
        f"and noticing. Your Step 2B reads more like narration than "
        f"internal monologue. Found {signal_count} first-person "
        f"deliberation signal(s); need at least {MIN_MONOLOGUE_PHRASES}. "
        f"Natural-voice markers all count — 'I wonder', 'I try', "
        f"'I consider', 'Let me reconsider', 'What if I try', "
        f"'Actually,', 'Hmm', 'That doesn't work'. Add more moments "
        f"of real deliberation: test a candidate, question it, reject "
        f"it, try another, pause to reflect. Do NOT switch to third-"
        f"person narration ('the teacher writes…')."
    ]


# A scripted mini-lesson is delivered in one classroom session (~10-15 min).
# Any single step that grows past this share crowds out the other steps'
# classroom time — the lesson becomes impractical to deliver. This ceiling
# is soft enough to allow Step 2B's 30-45% target share plus normal variance.
_MAX_STEP_SHARE_OF_LESSON = 0.55


def validate_lesson_balance(lesson: MiniLesson) -> list[str]:
    """Enforce classroom-pacing balance — no step may exceed 55% of total.

    Catches the failure mode where an expanded think-aloud gets spliced
    verbatim into a lesson, leaving Step 2B carrying 60-70% of the word
    count and starving Steps 1/2A/3/4 of delivery time. The repair
    instruction tells the LLM to compress while preserving key teacher
    moves — not to delete material wholesale.
    """
    step_texts = {
        "Step 1 Introduce": lesson.step_1_introduce or "",
        "Step 2A Tell":     lesson.step_2a_tell or "",
        "Step 2B Show":     lesson.step_2b_show or "",
        "Step 3 Interact":  lesson.step_3_interact or "",
        "Step 4 Close":     lesson.step_4_close or "",
    }
    counts = {name: len(text.split()) for name, text in step_texts.items()}
    total = sum(counts.values())
    if total == 0:
        return []
    errors: list[str] = []
    for name, words in counts.items():
        share = words / total
        if share > _MAX_STEP_SHARE_OF_LESSON:
            pct = int(share * 100)
            max_pct = int(_MAX_STEP_SHARE_OF_LESSON * 100)
            errors.append(
                f"Lesson balance: {name} is {pct}% of the lesson "
                f"({words}/{total} words); a scripted mini-lesson is a "
                f"single classroom session and no step may exceed "
                f"{max_pct}% without crowding out the other steps' "
                f"delivery time. Compress {name} while preserving the "
                f"key teacher moves (testing alternatives, rejecting "
                f"weak options, reconsidering, rereading) — do not "
                f"delete the teacher thinking, just tighten its prose."
            )
    return errors
