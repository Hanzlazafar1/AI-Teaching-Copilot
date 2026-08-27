"""Wave 2c S3 — live scenarios for the one-skill-per-mini-lesson guard.

Brady S3: when a teacher tries to cram a SECOND distinct skill into ONE mini-
lesson, QU populates ``additional_skills`` and the dispatch gate prepends a
deterministic guard ("Mini-lessons are focused on one skill at a time. Adding
in {extra} would come in a second or future mini-lesson.") to a lesson generated
on the PRIMARY skill — but ONLY for the two lesson-shaped request types
(SCRIPTED_ML / DEEPEN_PRIOR). It must NEVER fire on a legitimate single-skill
request (esp. "topic sentences and supporting details", which is ONE skill).

These property-based scenarios lock the END-TO-END delivered behavior. The guard
sentence is deterministic (a code template, not LLM prose), so exact-substring
checks are appropriate. Skips automatically when no backend is up — it carries
its OWN skip guard (a conftest-level ``pytestmark`` does not propagate to sibling
test modules) and mirrors tests/acceptance/test_wave2c_conformance.py. ``API_BASE``
is imported from the acceptance conftest so this guard checks the exact base URL
the shared ``chat`` fixture connects to.

DELIVERY-PATH NOTE (previously-fixed gap): the guard fires only on lesson-shaped
requests (SCRIPTED_ML always; DEEPEN_PRIOR when it delegates to
handle_scripted_ml). Those deliver ``outcome.structured`` (the MiniLesson dict)
as the API ``response`` — ``api.routes_v4._build_response`` returns ``structured``
whenever it is non-None and drops ``response_text``. Originally the dispatch gate
prepended the guard to ``response_text`` ONLY, so it was computed then dropped at
the API boundary and never reached ``resp.text`` (= json.dumps(structured)). The
fix mirrors the Fm4 header: the dispatch gate now ALSO injects the guard into
``outcome.structured["one_skill_guard"]`` (see handlers/__init__.py), so it rides
inside the delivered ``response`` payload and lands in ``resp.text``. Both "fires"
scenarios below are therefore now PLAIN assertions (no longer xfail). The
single-skill "must-not-fire" scenario passes regardless (the guard genuinely
never fires there).

Run:  (backend up)  python3 -m pytest tests/acceptance/test_wave2c_s3_guard.py -q
"""
from __future__ import annotations

import pytest
import requests

from handlers.formatting import ONE_SKILL_GUARD_TEMPLATE  # SoT for the guard wording
from tests.acceptance.conftest import API_BASE  # same base the `chat` fixture connects to


def _server_up() -> bool:
    try:
        return requests.get(f"{API_BASE}/health", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.skipif(not _server_up(), reason=f"backend not reachable at {API_BASE}"),
]


# Two stable, case-insensitive fragments of Brady's verbatim guard template.
# Drift guard (below) asserts they really are part of the SoT template, so a
# future reword of ONE_SKILL_GUARD_TEMPLATE surfaces here rather than silently
# neutering these checks.
_FRAG_HEAD = "focused on one skill at a time"
_FRAG_TAIL = "second or future mini-lesson"
assert _FRAG_HEAD in ONE_SKILL_GUARD_TEMPLATE.lower()
assert _FRAG_TAIL in ONE_SKILL_GUARD_TEMPLATE.lower()


def _guard_fired(text: str) -> bool:
    """The deterministic guard's two constant fragments both present."""
    t = text.lower()
    return _FRAG_HEAD in t and _FRAG_TAIL in t


class TestScopeCreepGuardFires:
    """The guard MUST fire when a second distinct skill is crammed into one lesson."""

    def test_scope_creep_single_turn(self, chat):
        # Two distinct skills in one scripted-mini-lesson ask -> QU flags
        # additional_skills=['transitions'], dispatch prepends the guard while
        # still generating the lesson on the PRIMARY skill (topic sentences).
        resp = chat.send(
            "Give me one 3rd-grade scripted mini-lesson on topic sentences "
            "and transitions."
        )
        text = resp.text
        assert _guard_fired(text), f"guard absent; got: {text[:500]!r}"
        assert "transitions" in text.lower(), (
            f"guard must NAME the deferred skill 'transitions'; got: {text[:500]!r}"
        )
        # ...and it is still a lesson delivered on the PRIMARY skill.
        assert resp.is_lesson, f"expected a MiniLesson on the primary skill; got: {text[:300]!r}"
        assert "topic sentence" in text.lower(), (
            f"primary-skill lesson (topic sentences) must still be delivered; got: {text[:500]!r}"
        )

    def test_multiturn_add_followup(self, chat):
        # Turn 1: a clean single-skill scripted lesson (no guard).
        chat.send("Give me a scripted mini-lesson on transitions for 3rd grade.")
        # Turn 2 (same chat -> same session_id): "also add conclusions to THIS
        # same lesson" is scope-creep on the prior lesson -> DEEPEN_PRIOR +
        # additional_skills=['conclusions']; the guard fires on turn 2.
        resp = chat.send(
            "Can you also add a section on conclusions to this same lesson?"
        )
        text = resp.text
        assert _guard_fired(text), f"turn-2 guard absent; got: {text[:500]!r}"
        assert "conclusions" in text.lower(), (
            f"turn-2 guard must NAME the deferred skill 'conclusions'; got: {text[:500]!r}"
        )


class TestSingleSkillNoGuard:
    """B03 false-positive killer — a genuine ONE-skill request is never lectured."""

    def test_topic_sentences_and_supporting_details_is_one_skill(self, chat):
        # "topic sentences and supporting details" is a SINGLE Smekens skill
        # (the pizza-table paragraph strategy), NOT two -> QU leaves
        # additional_skills empty -> the guard must be ABSENT. Passes in both
        # the current and post-fix delivery states (the guard genuinely never
        # fires here), so it is a plain, always-green lock.
        resp = chat.send(
            "Give me a 3rd grade scripted mini-lesson on topic sentences "
            "and supporting details."
        )
        text = resp.text
        assert _FRAG_HEAD not in text.lower(), (
            f"single-skill request must NOT trigger the one-skill guard; got: {text[:500]!r}"
        )
