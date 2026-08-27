"""The GENERATOR half of per-claim citation — HOW_TO_TEACH + COACHING.

The design is "the model POINTS, the code SPEAKS": the model appends an opaque
`[[src:<chunk_id>]]` marker to each claim it built from a retrieved block, and
handlers/citation.py::resolve_markers renders Brady's sentence from that chunk's
typed metadata. Task 3 shipped the resolver. These tests lock the prompt rule
that makes the model emit anything for it to resolve.

WHY THESE ARE WRITTEN THE WAY THEY ARE — the hole plan (1) left here.

Plan (1)'s prompt tests all passed with its attribution rule DELETED. With no
rule, the model nulls the field forever, the citation silently vanishes from
every response, and the gate stays green. The same trap is live on this path,
one step worse: no rule -> no markers -> resolve_markers is handed clean text,
returns it byte-identical (its guarantee #2), and every one of Task 3's eleven
mutation-tested resolver tests still passes. NOTHING downstream fails.

So every rule assertion below is a VERBATIM literal asserted against the BUILT
prompt of EACH handler. Not the constant (a shared constant on both sides of an
`in` is unfailable against a reword — it moves with the assertion), and not a
keyword ("append", "source") that survives the imperative being reworded away.
Deleting the rule AND degrading it both have to go red. House style:
test_scripted_ml_prompt.py:477 and its sibling at :490, added by 9251403 for
exactly this reason.
"""

from __future__ import annotations

import re

from handlers import (
    coaching,
    how_to_teach,
    management,
    plan_unit,
    think_aloud,
)
from handlers._prompt_rules import PER_CLAIM_SOURCE_MARKER_RULE
from handlers.citation import _MARKER_RE
from schemas import (
    Conversation,
    GradeSpec,
    ModeSpec,
    RequestType,
    SkillSpec,
    TurnIntent,
)

#: A real corpus chunk id (chunks/*.json). Used to prove the shape the prompt
#: promises is the shape the resolver recognises, on data rather than on a
#: hand-invented id that might not look like the real thing — the near-miss the
#: spec records as instance ~17 (a fixture written from a belief about a format
#: tests the belief, not the format).
_REAL_CHUNK_ID = "ep8-elem-skill1-describe-problem"


def _intent(rt: RequestType) -> TurnIntent:
    return TurnIntent(
        request_type=rt,
        grade=GradeSpec(value="3", stated_explicit=True),
        mode=ModeSpec(value="Inform", stated_explicit=True),
        skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
    )


def _htt_prompt() -> str:
    return how_to_teach._build_prompt(
        _intent(RequestType.HOW_TO_TEACH), "", Conversation(session_id="s"), None
    )


def _coaching_prompt() -> str:
    return coaching._build_prompt(
        _intent(RequestType.COACHING), "", Conversation(session_id="s"), None
    )


def _cited_prompts() -> list[tuple[str, str]]:
    """The two handlers that cite. _base_text.py:371-373 is the authority on
    this list: the footer is the default for every text handler EXCEPT
    HOW_TO_TEACH and COACHING, so those two are the per-claim producers."""
    return [("how_to_teach", _htt_prompt()), ("coaching", _coaching_prompt())]


def _assert_rule_is_substantive() -> None:
    """Guard against the vacuous form of every `CONST in prompt` assertion.

    FOUND BY MUTATION, in this file's own tests: gutting the constant to "" left
    the splice test below GREEN, because `"" in prompt` is True for every
    prompt. Seven other tests caught that mutant, so the suite as a whole held —
    but the one test whose entire job is "the rule reaches the prompt" was
    unfailable against a rule that had ceased to exist. A shared constant is
    exactly where that hides: the assertion moves with the thing it asserts.
    Pinning the constant to a real rule first is what makes the splice
    assertions mean something."""
    rule = PER_CLAIM_SOURCE_MARKER_RULE.strip()
    assert len(rule) > 200, "the rule has been gutted; the splice checks below would pass vacuously"
    assert "[[src:<id>]]" in rule


# ----------------------------------------------------------------------
# The rule reaches both prompts, from ONE shared source
# ----------------------------------------------------------------------


def test_the_marker_rule_reaches_BOTH_handler_prompts():
    """Un-splicing the rule from either builder = no markers from that handler
    = its citations silently vanish. Nothing else in the suite notices."""
    _assert_rule_is_substantive()
    for name, prompt in _cited_prompts():
        assert PER_CLAIM_SOURCE_MARKER_RULE.strip() in prompt, name


def test_both_handlers_use_the_SAME_rule_object_not_a_copy():
    """Mirrors test_prompt_rules.py:104. Two handlers must not carry forked
    copies of one rule — that is what _prompt_rules.py exists to prevent, and
    the SG2 comment there records it happening for real (SCRIPTED_ML shipped
    without a rule the outline builder had)."""
    assert how_to_teach.PER_CLAIM_SOURCE_MARKER_RULE is PER_CLAIM_SOURCE_MARKER_RULE
    assert coaching.PER_CLAIM_SOURCE_MARKER_RULE is PER_CLAIM_SOURCE_MARKER_RULE


# ----------------------------------------------------------------------
# The core imperatives — VERBATIM, so a REWORD goes red, not just a delete
# ----------------------------------------------------------------------


def test_the_EMISSION_and_PLACEMENT_imperative_is_verbatim_in_both_prompts():
    """THE load-bearing sentence. Without it the model emits nothing, the
    resolver resolves nothing, and every citation on these two paths disappears
    while the whole gate stays green — plan (1)'s hole, exactly.

    Asserted verbatim rather than by keyword: "append" and "Source" both survive
    the instruction being softened to something the model can decline."""
    for name, prompt in _cited_prompts():
        assert (
            "Append that block's `Source:` id at the END of that claim's own line,"
            in prompt
        ), name


def test_the_marker_may_NEVER_sit_on_a_line_of_its_own():
    """Load-bearing, NOT cosmetic — the sharpest failure this rule can cause.

    picklist.py:73 is `elif in_list: break` ("prose after the list does end
    it"), and _base_text.py:596 extracts offered_skills from the text a citation
    has already entered at :586. A citation on its OWN line mid-list truncates
    the pick-list; "number 4" then falls out of range, resolve_ordinal_pick
    returns None, and the model's guess stands — silently reverting the nn4 fix
    (a teacher asks for 4 and gets 3), the campaign's worst-defect class.
    Today's footer sits after the list and cannot do this. Markers put a
    citation mid-list for the first time."""
    for name, prompt in _cited_prompts():
        assert "Never put a marker on a line of its own." in prompt, name


def test_a_claim_with_NO_marker_is_expected_and_correct():
    """Brady decision #2 — a claim is ELIGIBLE for a citation, never obliged.
    His own approved artifacts prove both halves: image39 cites its lead
    paragraph and points 2-5 and is SILENT on point 1; image3 cites points 1
    and 4 and leaves its lead paragraph UNCITED. He praised both.

    A rule that dropped this clause would read as "mark every line", and the
    model would stretch to attribute claims it did not build from a block —
    manufacturing exactly the confident-wrong-page defect this slice exists to
    close. The permission has to be explicit, or silence looks like failure."""
    for name, prompt in _cited_prompts():
        assert (
            "Append nothing when a claim was not built from a retrieved block."
            in prompt
        ), name
        assert "A claim with no marker is expected and correct." in prompt, name


def test_the_rule_licenses_MULTIPLE_sources_on_ONE_claim():
    """Spec decision #5 / §3.5, and Brady's own artifact: image39 point 3 cites
    "pages 97, 111" on ONE claim, in the response he called "all great".

    The resolver already implements this (citation.py groups markers by title
    and joins pages; test_citation_markers.py:76 locks it). If the prompt only
    ever licensed one id per claim, that branch would be unreachable by
    construction — the same shape as the p.124 finding this task exists to fix,
    where retrieval had the page all along and the response shape threw it
    away."""
    for name, prompt in _cited_prompts():
        assert (
            "If one claim came from several blocks, append one marker per block."
            in prompt
        ), name


def test_the_id_is_ordered_OUT_of_teacher_visible_prose():
    """Both handlers ban internal vocabulary from teacher-facing output
    (how_to_teach.py:86-93, coaching.py:118-141). A rule that hands the model a
    chunk id without saying where it may NOT go is the reason that ban starts
    losing. Mirrors test_scripted_ml_prompt.py:494."""
    for name, prompt in _cited_prompts():
        assert "Never write the id anywhere else in your answer." in prompt, name


# ----------------------------------------------------------------------
# The Fm5 prohibition SURVIVES the new rule
# ----------------------------------------------------------------------


def test_pointing_did_NOT_re_authorize_the_model_to_cite():
    """The other half of the same design, and the half with a motive to erode:
    a rule that asked the model to attribute could very easily arrive by
    re-authorizing it to write the citation itself. That is the REVERTED Fm5
    attempt (it leaked `Book:`/`Page:` header label text and blank page slots to
    teachers) wearing a new name. The model points; the code speaks."""
    for name, prompt in _cited_prompts():
        assert "Do NOT include a book or page citation" in prompt, name
        assert "added for you" in prompt, name
        assert "Never invent a page number or book title." in prompt, name
        assert "MAY cite" not in prompt, name
    # And the new rule states the prohibition itself, so the two cannot be read
    # as being in tension across prompt sections.
    assert (
        "Never write a book title or a page number of your own."
        in PER_CLAIM_SOURCE_MARKER_RULE
    )


def test_the_rule_hands_the_model_NO_book_or_page_PHRASING_to_echo():
    """The prompt is not a scratchpad. A prior fix in this repo put its own
    explanation inside a prompt string and fed the model the exact phrasing it
    was removing. An "example" citation here would do the same, in the one area
    where a prompt reword was already reverted once for leaking."""
    assert "Launching the Writers Workshop" not in PER_CLAIM_SOURCE_MARKER_RULE
    # No page-shaped exemplar. The words "page number" are the PROHIBITION and
    # must stay; a page with a NUMBER on it would be a template to copy.
    assert not re.search(r"p\.\s*\d|pages?\s+\d", PER_CLAIM_SOURCE_MARKER_RULE)


# ----------------------------------------------------------------------
# The prompt's grammar IS the resolver's grammar
# ----------------------------------------------------------------------


def test_the_promised_marker_shape_is_the_shape_the_resolver_RECOGNISES():
    """If these two drift, every marker the model emits resolves to nothing and
    the citation vanishes — silently, and green: resolve_markers sweeps what it
    cannot resolve (its invariant #1), so a drifted grammar produces clean,
    plausible, uncited responses. The prompt promises a shape; _MARKER_RE
    recognises a shape; nothing else binds them together.

    The template flows from the prompt INTO the match, so this cannot pass by
    agreeing with itself."""
    template = "[[src:<id>]]"
    assert template in PER_CLAIM_SOURCE_MARKER_RULE
    instance = template.replace("<id>", _REAL_CHUNK_ID)
    m = _MARKER_RE.fullmatch(instance)
    assert m is not None
    assert m.group("cid") == _REAL_CHUNK_ID


# ----------------------------------------------------------------------
# The rule stays OFF the handlers that must not cite
# ----------------------------------------------------------------------


def test_the_marker_rule_does_NOT_reach_the_UNCITED_builders():
    """MANAGEMENT / PLAN_UNIT / THINK_ALOUD emit ZERO citations
    (_base_text.py:371-373; locked at test_fm5_citation_wiring.py:442). The
    resolver is generic and runs on the shared text loop, so a marker rule that
    leaked into one of these builders would hand it working citations Brady
    never asked it for — a behaviour change nothing else here would catch,
    because the leak would look like a passing citation, not a crash."""
    _assert_rule_is_substantive()  # else `"" not in prompt` fails for the wrong reason
    conv = Conversation(session_id="s")
    uncited = [
        ("management", management._build_prompt(
            _intent(RequestType.MANAGEMENT), "", conv, None)),
        ("plan_unit", plan_unit._build_prompt(
            _intent(RequestType.PLAN_UNIT), "", conv, None)),
        ("think_aloud", think_aloud._build_prompt(
            _intent(RequestType.THINK_ALOUD), "", conv, None)),
    ]
    for name, prompt in uncited:
        assert PER_CLAIM_SOURCE_MARKER_RULE.strip() not in prompt, name
        assert "[[src:" not in prompt, name
