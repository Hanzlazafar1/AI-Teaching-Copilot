"""Deictic title-garble fix (recert Fix ⑤, target 18c follow-up).

On a DEEPEN_PRIOR follow-up ("give me more on that") QU (gpt-5.4-mini)
writes the bare deictic "that" / "those paragraphs" into
``intent.skill.as_stated`` while ``canonical`` and ``lesson_title`` stay
resolved. ``scripted_ml_prompt`` renders ``as_stated`` verbatim into
``skill_focus`` and Step 1 ("Today we're going to focus on that."), and the
safety net certifies it (`"that" in "that"`). A deictic is a *pointer*, not
vocabulary — these tests pin the intent-layer resolution that swaps the
pointer for the skill it points at BEFORE generation.

The resolution logic is deterministic and lives in ``query.qu_v4``
(``resolve_deictic_skill`` + ``_is_deictic_pointer``). The end-to-end live
behaviour (that QU actually emits "that" on that turn) is gated by the
controller — here we test the RESOLUTION LOGIC only, given a deictic
``as_stated`` + a prior skill.
"""

from __future__ import annotations

import pytest

from canonicalizer import (
    CanonicalResolution,
    ResolutionKind,
    get_canonicalizer,
)
from handlers.deepen_prior import _merge_intent
from query.qu_v4 import _is_deictic_pointer, resolve_deictic_skill, understand
from schemas import (
    Conversation,
    GradeSpec,
    ModeSpec,
    Quality,
    RequestType,
    Role,
    SkillSpec,
    Turn,
    TurnIntent,
)

CANON = get_canonicalizer()


# ----------------------------------------------------------------------
# Builders
# ----------------------------------------------------------------------


def _deictic_intent(as_stated: str, canonical: str = "transitions") -> TurnIntent:
    """A follow-up intent whose skill.as_stated degraded to a deictic while
    canonical stayed resolved (the exact live shape of the bug)."""
    return TurnIntent(
        request_type=RequestType.DEEPEN_PRIOR,
        refers_to_prior=True,
        skill=SkillSpec(canonical=canonical, as_stated=as_stated),
    )


def _convo_with_prior_ml(skill_focus: str, prior_intent: TurnIntent | None = None):
    """A conversation whose most recent VALID assistant turn was a scripted ML
    (its structured body carries skill_focus)."""
    conv = Conversation(session_id="s")
    conv.append(
        Turn(
            index=0,
            role=Role.USER,
            text="teach transitions between paragraphs",
            intent=prior_intent,
        )
    )
    conv.append(
        Turn(
            index=1,
            role=Role.ASSISTANT,
            text="[a full transitions lesson]",
            quality=Quality.VALID,
            structured={"skill_focus": skill_focus},
        )
    )
    return conv


def _prior_user_intent(as_stated: str) -> TurnIntent:
    return TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        grade=GradeSpec(value="4", stated_explicit=True),
        mode=ModeSpec(value="Inform", stated_explicit=True),
        skill=SkillSpec(canonical=as_stated, as_stated=as_stated),
    )


class _StubCanon:
    """A canonicalizer whose resolve() I control, so I can prove a leading-
    deictic phrase that DOES name a real skill is left alone. No real Smekens
    skill/trigger starts with that/this/these/those, so this boundary can only
    be exercised with a stub."""

    def __init__(self, known_skill_phrases: set[str]):
        self._known = {p.lower() for p in known_skill_phrases}

    def resolve(self, raw: str) -> CanonicalResolution:
        if (raw or "").lower() in self._known:
            return CanonicalResolution(ResolutionKind.SKILL, (raw or "").lower())
        return CanonicalResolution(ResolutionKind.UNKNOWN, (raw or "").lower())

    def canonicalize_skill(self, raw: str) -> str:
        return (raw or "").lower()


# ----------------------------------------------------------------------
# Detection helper — the tight deictic set
# ----------------------------------------------------------------------


class TestDeicticDetection:
    def test_bare_deictics_are_pointers(self):
        for word in ("that", "this", "these", "those", "it"):
            assert _is_deictic_pointer(word, CANON) is True

    def test_detection_is_case_and_punctuation_insensitive(self):
        assert _is_deictic_pointer("That", CANON) is True
        assert _is_deictic_pointer("Those.", CANON) is True

    def test_a_real_skill_phrase_is_not_a_pointer(self):
        assert _is_deictic_pointer("topic sentences", CANON) is False
        assert _is_deictic_pointer("supporting details", CANON) is False

    def test_a_phrase_that_merely_contains_a_deictic_is_not_a_pointer(self):
        # "Transitions between those paragraphs" does NOT START with a deictic
        # determiner — it names a real skill and must be preserved verbatim.
        assert (
            _is_deictic_pointer("Transitions between those paragraphs", CANON)
            is False
        )

    def test_leading_deictic_phrase_that_names_no_skill_is_a_pointer(self):
        # "those paragraphs" / "that skill" don't canonicalize to any known
        # skill/trigger, so they read as pointers.
        assert _is_deictic_pointer("those paragraphs", CANON) is True
        assert _is_deictic_pointer("that skill", CANON) is True

    def test_leading_deictic_phrase_that_names_a_real_skill_is_not_a_pointer(self):
        stub = _StubCanon({"those special sentences"})
        assert _is_deictic_pointer("those special sentences", stub) is False
        # but an unknown leading-deictic phrase still reads as a pointer
        assert _is_deictic_pointer("those random words", stub) is True

    def test_empty_or_blank_is_not_a_pointer(self):
        assert _is_deictic_pointer("", CANON) is False
        assert _is_deictic_pointer("   ", CANON) is False
        assert _is_deictic_pointer(None, CANON) is False  # type: ignore[arg-type]

    def test_a_long_determiner_led_clause_is_a_skill_not_a_pointer(self):
        """A determiner-led PHRASE is a pointer; a determiner-led CLAUSE is a
        skill objective. Bound guards the one place the resolver could clobber a
        real skill — e.g. a determiner-led item picked by ordinal off a list."""
        assert (
            _is_deictic_pointer("Those transition words matter for readers", CANON)
            is False
        )
        assert _is_deictic_pointer("This strategy helps students organize", CANON) is False
        # short deictic NPs (determiner + a modifier or two) still count
        assert _is_deictic_pointer("those two short paragraphs", CANON) is True


# ----------------------------------------------------------------------
# Resolution — swap the pointer for the referent (required TDD cases)
# ----------------------------------------------------------------------


class TestResolveDeicticSkill:
    def test_a_bare_deictic_resolves_to_the_prior_lessons_skill(self):
        """(a) as_stated="that" + prior scripted-ML skill_focus="Transitions
        between those paragraphs" → as_stated becomes the real skill, NOT
        "that"."""
        convo = _convo_with_prior_ml("Transitions between those paragraphs")
        out = resolve_deictic_skill(_deictic_intent("that"), convo, CANON)
        assert out.skill.as_stated == "Transitions between those paragraphs"
        assert out.skill.as_stated != "that"
        # canonical is recomputed off the referent — never left as the deictic
        assert not _is_deictic_pointer(out.skill.canonical, CANON)

    def test_a_real_skill_phrase_is_left_untouched(self):
        """(b) as_stated="topic sentences" (a real phrase) must not be
        rewritten — legitimate vocabulary is preserved even with a prior ML
        on screen."""
        convo = _convo_with_prior_ml("Transitions between those paragraphs")
        intent = _deictic_intent("topic sentences", canonical="topic sentences")
        out = resolve_deictic_skill(intent, convo, CANON)
        assert out.skill.as_stated == "topic sentences"

    def test_deictic_with_no_referent_falls_back_to_canonical(self):
        """(c) part 1 — no prior skill on screen, but canonical is still
        resolved: fall back to canonical rather than shipping "that"."""
        empty = Conversation(session_id="s")
        intent = _deictic_intent("that", canonical="topic sentences")
        out = resolve_deictic_skill(intent, empty, CANON)
        assert out.skill.as_stated == "topic sentences"

    def test_deictic_with_no_referent_at_all_is_left_never_invented(self):
        """(c) part 2 — canonical is ALSO a deictic and there is nothing to
        inherit: leave the pointer, never invent a skill."""
        empty = Conversation(session_id="s")
        intent = _deictic_intent("that", canonical="that")
        out = resolve_deictic_skill(intent, empty, CANON)
        assert out.skill.as_stated == "that"  # unchanged — no invention

    def test_leading_deictic_phrase_inherits_when_it_names_no_skill(self):
        """(d) "those paragraphs" doesn't canonicalize to a real skill → it is
        a pointer and inherits the prior lesson's skill."""
        convo = _convo_with_prior_ml("Transitions between those paragraphs")
        intent = _deictic_intent("those paragraphs", canonical="those paragraphs")
        out = resolve_deictic_skill(intent, convo, CANON)
        assert out.skill.as_stated == "Transitions between those paragraphs"

    def test_leading_deictic_phrase_that_is_a_real_skill_stays(self):
        """(d) boundary — a leading-deictic phrase that DOES name a real skill
        is preserved (stub canon, since no real Smekens skill starts with a
        deictic)."""
        stub = _StubCanon({"those special sentences"})
        convo = _convo_with_prior_ml("Transitions between those paragraphs")
        intent = _deictic_intent(
            "those special sentences", canonical="those special sentences"
        )
        out = resolve_deictic_skill(intent, convo, stub)
        assert out.skill.as_stated == "those special sentences"

    def test_no_skill_on_intent_is_a_noop(self):
        convo = _convo_with_prior_ml("Transitions between those paragraphs")
        intent = TurnIntent(request_type=RequestType.DEEPEN_PRIOR)
        out = resolve_deictic_skill(intent, convo, CANON)
        assert out.skill is None


class TestReferentPriority:
    def test_prior_scripted_ml_skill_focus_wins_over_prior_intent(self):
        """Priority order: prior scripted-ML skill_focus beats the prior user
        turn's as_stated."""
        prior_intent = _prior_user_intent("supporting details")
        convo = _convo_with_prior_ml(
            "Transitions between those paragraphs", prior_intent=prior_intent
        )
        out = resolve_deictic_skill(
            _deictic_intent("that"), convo, CANON, prior_intent=prior_intent
        )
        assert out.skill.as_stated == "Transitions between those paragraphs"

    def test_prior_intent_used_when_no_scripted_ml_turn(self):
        """No scripted-ML turn on screen, but the prior user turn named a real
        skill → inherit that (before falling back to canonical)."""
        conv = Conversation(session_id="s")
        conv.append(
            Turn(index=0, role=Role.USER, text="coach me on organization",
                 intent=_prior_user_intent("paragraph organization")),
        )
        conv.append(
            Turn(index=1, role=Role.ASSISTANT, text="some coaching prose",
                 quality=Quality.VALID),  # NOT a scripted ML (no skill_focus)
        )
        # canonical is a deictic here so only prior-intent can rescue it
        out = resolve_deictic_skill(_deictic_intent("that", canonical="that"), conv, CANON)
        assert out.skill.as_stated == "paragraph organization"


# ----------------------------------------------------------------------
# _merge_intent integration — the DEEPEN_PRIOR routing path
# ----------------------------------------------------------------------


class TestMergeIntentResolvesDeictic:
    def test_merge_resolves_a_deictic_that_survived_inheritance(self):
        """The bug's exact path: DEEPEN_PRIOR merges, skill is NOT None (it's a
        deictic) so the None-gated inheritance leaves it, and it would reach the
        prompt as the title. _merge_intent now resolves it against the prior
        scripted-ML turn."""
        prior_intent = _prior_user_intent("transitions between paragraphs")
        convo = _convo_with_prior_ml(
            "Transitions between those paragraphs", prior_intent=prior_intent
        )
        current = _deictic_intent("that")
        merged = _merge_intent(
            current,
            prior_intent,
            RequestType.SCRIPTED_ML,
            conversation=convo,
            canon=CANON,
        )
        assert merged.skill.as_stated == "Transitions between those paragraphs"
        assert merged.request_type is RequestType.SCRIPTED_ML

    def test_merge_leaves_a_real_skill_alone(self):
        prior_intent = _prior_user_intent("topic sentences")
        convo = _convo_with_prior_ml("topic sentences", prior_intent=prior_intent)
        current = _deictic_intent("supporting details", canonical="supporting details")
        merged = _merge_intent(
            current, prior_intent, RequestType.SCRIPTED_ML,
            conversation=convo, canon=CANON,
        )
        assert merged.skill.as_stated == "supporting details"

    def test_merge_is_backward_compatible_without_conversation(self):
        """The legacy 3-arg call (no conversation/canon) still works — a real
        skill is untouched and inheritance still fires."""
        prior_intent = _prior_user_intent("topic sentences")
        current = TurnIntent(request_type=RequestType.DEEPEN_PRIOR, refers_to_prior=True)
        merged = _merge_intent(current, prior_intent, RequestType.SCRIPTED_ML)
        assert merged.skill is not None
        assert merged.skill.as_stated == "topic sentences"


# ----------------------------------------------------------------------
# understand() wiring — the sibling call actually runs (deterministic, no net)
# ----------------------------------------------------------------------


class _FakeMessage:
    def __init__(self, parsed):
        self.parsed = parsed
        self.refusal = None


class _FakeChoice:
    def __init__(self, parsed):
        self.message = _FakeMessage(parsed)


class _FakeCompletion:
    def __init__(self, parsed):
        self.choices = [_FakeChoice(parsed)]


class _FakeCompletions:
    def __init__(self, parsed):
        self._parsed = parsed

    async def parse(self, **kwargs):
        return _FakeCompletion(self._parsed)


class _FakeChat:
    def __init__(self, parsed):
        self.completions = _FakeCompletions(parsed)


class _FakeQUClient:
    """Stand-in for AsyncOpenAI whose chat.completions.parse() returns a fixed
    TurnIntent — lets us drive understand() end-to-end with no network."""

    def __init__(self, parsed):
        self.chat = _FakeChat(parsed)


class TestUnderstandResolvesDeicticEndToEnd:
    @pytest.mark.asyncio
    async def test_understand_resolves_a_deictic_qu_emitted(self):
        """The live shape: QU emits skill.as_stated="that" while canonical stays
        resolved. understand()'s sibling call must swap it for the prior lesson's
        skill BEFORE the intent leaves QU — proving the wiring, not just the
        isolated helper."""
        qu_output = TurnIntent(
            request_type=RequestType.DEEPEN_PRIOR,
            refers_to_prior=True,
            skill=SkillSpec(canonical="transitions between paragraphs", as_stated="that"),
        )
        convo = _convo_with_prior_ml("Transitions between those paragraphs")
        out = await understand(
            convo, "Give me more on that.",
            client=_FakeQUClient(qu_output), model="fake", canonicalizer=CANON,
        )
        assert out.skill.as_stated == "Transitions between those paragraphs"
        assert not _is_deictic_pointer(out.skill.as_stated, CANON)

    @pytest.mark.asyncio
    async def test_understand_leaves_a_real_skill_untouched(self):
        """A legitimate new-skill turn must pass through unchanged — the sibling
        call is a no-op on non-deictic vocabulary."""
        qu_output = TurnIntent(
            request_type=RequestType.SCRIPTED_ML,
            skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
        )
        convo = _convo_with_prior_ml("Transitions between those paragraphs")
        out = await understand(
            convo, "Now do topic sentences.",
            client=_FakeQUClient(qu_output), model="fake", canonicalizer=CANON,
        )
        assert out.skill.as_stated == "topic sentences"

    @pytest.mark.asyncio
    async def test_an_ordinal_pick_of_a_determiner_led_item_is_not_clobbered(self):
        """The regression the bound + ordering guard against: the teacher picks
        "number 2" and item 2 opens with a determiner. The deterministic ordinal
        pick must be final — NOT re-read as a deictic and silently rewritten to
        the prior lesson's skill (measured: it was, 'Those transition words…' →
        'Transitions between paragraphs')."""
        convo = Conversation(session_id="s")
        convo.append(Turn(index=0, role=Role.USER, text="teach transitions"))
        convo.append(Turn(
            index=1, role=Role.ASSISTANT, text="a transitions lesson",
            quality=Quality.VALID,
            structured={"skill_focus": "Transitions between paragraphs"},
        ))
        convo.append(Turn(index=2, role=Role.USER, text="now plan a persuasive unit"))
        convo.append(Turn(
            index=3, role=Role.ASSISTANT, text="here is the unit list",
            quality=Quality.VALID,
            offered_skills=[
                "Recognize opinionated topics",
                "Those transition words matter for readers",
                "State an opinion to a particular audience",
            ],
        ))
        qu_output = TurnIntent(
            request_type=RequestType.DEEPEN_PRIOR,
            skill=SkillSpec(canonical="number 2", as_stated="number 2"),
        )
        out = await understand(
            convo, "Give me a lesson on number 2.",
            client=_FakeQUClient(qu_output), model="fake", canonicalizer=CANON,
        )
        assert out.skill.as_stated == "Those transition words matter for readers"
