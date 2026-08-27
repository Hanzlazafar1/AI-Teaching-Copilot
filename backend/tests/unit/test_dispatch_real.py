"""F64 (D3): exercise REAL dispatch (not a stub) at the deterministic
clarification seam.

A SCRIPTED_ML intent missing grade+skill must route through real ``dispatch`` to
``_clarify_missing`` and return a clarifying question with NO LLM call. This
complements the live golden-master (C1), which exercises the full real
understand -> dispatch -> handler path end-to-end. Ref: plan Task D3.
"""
import pytest

from api.models import ModelSet
from handlers import dispatch
from handlers.formatting import format_one_skill_guard
from schemas import (
    Conversation,
    GradeSpec,
    ModeSpec,
    Quality,
    RequestType,
    SessionHandshakes,
    TurnIntent,
    TurnOutcome,
)


@pytest.mark.asyncio
async def test_real_dispatch_clarifies_missing_grade_and_skill():
    intent = TurnIntent(
        request_type=RequestType.SCRIPTED_ML,
        missing_required=["grade", "skill"],
    )
    outcome = await dispatch(
        intent,
        Conversation(session_id="s"),
        SessionHandshakes(),
        "give me a lesson",
        client=None,        # unused on the clarification path — no LLM is called
        models=ModelSet("gpt-4o", "gpt-4o-mini", "gpt-4o-mini"),
        canonicalizer=None,
        retrieval_fn=None,
        library=None,
    )
    text = (outcome.response_text or "").lower()
    assert "grade" in text or "skill" in text, "real dispatch must ask for the missing info"
    assert outcome.structured is None, "a clarification must not produce a generated lesson"


@pytest.mark.asyncio
async def test_dispatch_passes_judge_model_to_scripted_ml(monkeypatch):
    """dispatch destructures the ModelSet: SCRIPTED_ML receives generation as
    `model` AND judge as `judge_model`. Locks the F27 judge split."""
    import handlers as handlers_pkg
    captured: dict = {}

    async def _fake(**kwargs):
        captured.update(kwargs)
        return TurnOutcome(response_text="ok", structured=None, grounding=[], quality=Quality.VALID)

    monkeypatch.setitem(handlers_pkg._HANDLERS, RequestType.SCRIPTED_ML, _fake)
    await dispatch(
        # Grade is stated so the turn reaches the handler: this test locks the
        # F27 model plumbing, not the clarify gate, and SCRIPTED_ML derives an
        # unstated grade as a structural prerequisite (u3 — handlers/clarify.py).
        TurnIntent(request_type=RequestType.SCRIPTED_ML,
                   grade=GradeSpec(value="4", stated_explicit=True)),
        Conversation(session_id="s"), SessionHandshakes(), "lesson on leads",
        client=object(), models=ModelSet("GEN", "QRY", "JDG"),
        canonicalizer=object(), retrieval_fn=None, library=None,
    )
    assert captured["model"] == "GEN"
    assert captured["judge_model"] == "JDG"


@pytest.mark.asyncio
async def test_dispatch_omits_judge_model_for_non_judge_handler(monkeypatch):
    import handlers as handlers_pkg
    captured: dict = {}

    async def _fake(**kwargs):
        captured.update(kwargs)
        return TurnOutcome(response_text="ok", structured=None, grounding=[], quality=Quality.VALID)

    monkeypatch.setitem(handlers_pkg._HANDLERS, RequestType.COACHING, _fake)
    await dispatch(
        TurnIntent(request_type=RequestType.COACHING),
        Conversation(session_id="s"), SessionHandshakes(), "quick tip",
        client=object(), models=ModelSet("GEN", "QRY", "JDG"),
        canonicalizer=object(), retrieval_fn=None, library=None,
    )
    assert captured["model"] == "GEN"
    assert "judge_model" not in captured


# --- Brady S3: one-skill-per-mini-lesson guard (dispatch branch) --------------
# When QU flags scope-creep — the teacher tried to cram a SECOND distinct,
# independently-teachable skill into ONE mini-lesson — dispatch prepends Brady's
# deterministic guard as a preface to the lesson generated on the PRIMARY skill
# (guard leads, correct single-skill lesson follows). Scoped to LESSON-SHAPED
# request types only (SCRIPTED_ML / DEEPEN_PRIOR); it must NEVER fire on
# PLAN_UNIT / HOW_TO_TEACH / COACHING, which enumerate many skills by design.
# Empty additional_skills (the back-compat default) leaves the body untouched.

# A stand-in lesson body the fake handler "generates" on the PRIMARY skill.
_LESSON_BODY = "Grade 3 | Informative\n\nStep 1 ... (full lesson on the primary skill)"


def _stub_handler(body: str):
    """An async handler stub that ignores its kwargs and returns ``body``."""
    async def _fake(**kwargs):
        return TurnOutcome(
            response_text=body, structured=None, grounding=[], quality=Quality.VALID
        )
    return _fake


async def _dispatch_stubbed(monkeypatch, request_type, *, additional_skills, body):
    """Run REAL dispatch with the given request_type's handler stubbed to
    return ``body`` and the intent carrying ``additional_skills``."""
    import handlers as handlers_pkg

    monkeypatch.setitem(handlers_pkg._HANDLERS, request_type, _stub_handler(body))
    return await dispatch(
        # See _dispatch_stubbed_structured: grade + mode are supplied so the
        # turn reaches the stubbed handler (the S3 guard runs after generation).
        # PLAN_UNIT derives both as structural prerequisites (u3).
        TurnIntent(
            request_type=request_type,
            additional_skills=additional_skills,
            grade=GradeSpec(value="3", stated_explicit=True),
            mode=ModeSpec(value="Persuade", stated_explicit=True),
        ),
        Conversation(session_id="s"),
        SessionHandshakes(),
        "one lesson that covers A and B",
        client=object(),
        models=ModelSet("GEN", "QRY", "JDG"),
        canonicalizer=object(),
        retrieval_fn=None,
        library=None,
    )


@pytest.mark.asyncio
async def test_dispatch_prepends_guard_for_scripted_ml_with_extras(monkeypatch):
    outcome = await _dispatch_stubbed(
        monkeypatch, RequestType.SCRIPTED_ML,
        additional_skills=["transitions"], body=_LESSON_BODY,
    )
    guard = format_one_skill_guard(["transitions"])
    assert guard, "sanity: the guard must render for a real extra"
    # Guard leads, exact code separator, primary-skill lesson follows verbatim.
    assert outcome.response_text == f"{guard}\n\n{_LESSON_BODY}"


@pytest.mark.asyncio
async def test_dispatch_prepends_guard_for_deepen_prior_with_extras(monkeypatch):
    outcome = await _dispatch_stubbed(
        monkeypatch, RequestType.DEEPEN_PRIOR,
        additional_skills=["conclusions"], body=_LESSON_BODY,
    )
    guard = format_one_skill_guard(["conclusions"])
    assert outcome.response_text == f"{guard}\n\n{_LESSON_BODY}"


@pytest.mark.asyncio
async def test_dispatch_guard_leads_and_primary_lesson_follows(monkeypatch):
    outcome = await _dispatch_stubbed(
        monkeypatch, RequestType.SCRIPTED_ML,
        additional_skills=["strong verbs"], body=_LESSON_BODY,
    )
    guard = format_one_skill_guard(["strong verbs"])
    assert outcome.response_text.startswith(guard), "guard must LEAD"
    assert outcome.response_text.endswith(_LESSON_BODY), (
        "the primary-skill lesson must FOLLOW, unmodified"
    )


@pytest.mark.asyncio
async def test_dispatch_names_multiple_extras_via_natural_join(monkeypatch):
    # dispatch feeds additional_skills faithfully into the formatter; the
    # natural-join lives in the formatter (locked by T2), not the branch.
    outcome = await _dispatch_stubbed(
        monkeypatch, RequestType.SCRIPTED_ML,
        additional_skills=["introductions", "conclusions"], body=_LESSON_BODY,
    )
    guard = format_one_skill_guard(["introductions", "conclusions"])
    assert "introductions and conclusions" in guard, "sanity: natural-join"
    assert outcome.response_text == f"{guard}\n\n{_LESSON_BODY}"


@pytest.mark.asyncio
async def test_dispatch_no_guard_when_additional_skills_empty(monkeypatch):
    # Back-compat: empty (the overwhelming default) -> totally inert.
    outcome = await _dispatch_stubbed(
        monkeypatch, RequestType.SCRIPTED_ML,
        additional_skills=[], body=_LESSON_BODY,
    )
    assert outcome.response_text == _LESSON_BODY


@pytest.mark.asyncio
async def test_dispatch_no_guard_for_plan_unit_even_with_extras(monkeypatch):
    # Scoping false-positive reducer: PLAN_UNIT lists many skills by design.
    outcome = await _dispatch_stubbed(
        monkeypatch, RequestType.PLAN_UNIT,
        additional_skills=["conclusions"], body="PLAN BODY",
    )
    assert outcome.response_text == "PLAN BODY"


@pytest.mark.asyncio
async def test_dispatch_no_guard_for_how_to_teach_even_with_extras(monkeypatch):
    outcome = await _dispatch_stubbed(
        monkeypatch, RequestType.HOW_TO_TEACH,
        additional_skills=["transitions"], body="HOWTO BODY",
    )
    assert outcome.response_text == "HOWTO BODY"


@pytest.mark.asyncio
async def test_dispatch_no_guard_for_coaching_even_with_extras(monkeypatch):
    outcome = await _dispatch_stubbed(
        monkeypatch, RequestType.COACHING,
        additional_skills=["voice"], body="COACHING BODY",
    )
    assert outcome.response_text == "COACHING BODY"


# --- S3 delivery: the guard must reach the STRUCTURED payload too -------------
# SCRIPTED_ML / DEEPEN_PRIOR return outcome.structured (a MiniLesson dict), and
# api.routes_v4._build_response delivers THAT dict as the API `response`,
# DROPPING response_text whenever structured is non-None. So prepending the
# guard to response_text ALONE never reaches the teacher on the real delivery
# path (empirically confirmed shipped gap). The guard must ALSO be surfaced in
# outcome.structured['one_skill_guard'] — mirroring how _finalize_ml_delivery injects
# structured['header'] (Fm4). The stubbed tests above returned structured=None,
# so they never exercised this path — which is exactly how the gap shipped.
# These tests drive the REAL shape: structured is a dict, NOT None.


def _stub_handler_structured(body: str, structured: dict):
    """Async handler stub returning a MiniLesson-shaped structured payload
    (a dict, NOT None) — the real SCRIPTED_ML / DEEPEN_PRIOR delivery shape."""
    async def _fake(**kwargs):
        return TurnOutcome(
            response_text=body,
            structured=dict(structured),
            grounding=[],
            quality=Quality.VALID,
        )
    return _fake


async def _dispatch_stubbed_structured(
    monkeypatch, request_type, *, additional_skills, body, structured
):
    """REAL dispatch with the handler stubbed to return a dict `structured`."""
    import handlers as handlers_pkg

    monkeypatch.setitem(
        handlers_pkg._HANDLERS,
        request_type,
        _stub_handler_structured(body, structured),
    )
    return await dispatch(
        # Grade + mode are supplied because these tests exercise the S3 guard
        # AFTER generation — they must reach the handler. PLAN_UNIT derives both
        # as structural prerequisites (u3 — handlers/clarify.py), so omitting
        # them would divert the turn to the clarify path and the stub would
        # never run. Harmless for the other request types.
        TurnIntent(
            request_type=request_type,
            additional_skills=additional_skills,
            grade=GradeSpec(value="3", stated_explicit=True),
            mode=ModeSpec(value="Persuade", stated_explicit=True),
        ),
        Conversation(session_id="s"),
        SessionHandshakes(),
        "one lesson that covers A and B",
        client=object(),
        models=ModelSet("GEN", "QRY", "JDG"),
        canonicalizer=object(),
        retrieval_fn=None,
        library=None,
    )


@pytest.mark.asyncio
async def test_dispatch_surfaces_guard_in_structured_for_scripted_ml(monkeypatch):
    # THE regression assertion that would have caught the shipped gap: on the
    # real delivery path (structured is a dict), the guard must land in
    # structured['one_skill_guard'] or _build_response drops it before it
    # reaches the teacher.
    lesson = {
        "skill_focus": "topic sentences",
        "grade_level": "3",
        "step_1_introduce": "…",
        "header": "Grade 3 | Informative",
    }
    outcome = await _dispatch_stubbed_structured(
        monkeypatch, RequestType.SCRIPTED_ML,
        additional_skills=["transitions"], body=_LESSON_BODY, structured=lesson,
    )
    guard = format_one_skill_guard(["transitions"])
    assert guard, "sanity: the guard must render for a real extra"
    # 1. Delivered path — guard surfaced as a NEW structured key.
    assert outcome.structured is not None
    assert outcome.structured.get("one_skill_guard") == guard
    # 2. Existing lesson fields are preserved (the new key never overwrites).
    assert outcome.structured["skill_focus"] == "topic sentences"
    assert outcome.structured["header"] == "Grade 3 | Informative"
    assert outcome.structured["step_1_introduce"] == "…"
    # 3. response_text STILL carries the guard too (covers any text-path case).
    assert outcome.response_text == f"{guard}\n\n{_LESSON_BODY}"


@pytest.mark.asyncio
async def test_dispatch_surfaces_guard_in_structured_for_deepen_prior(monkeypatch):
    lesson = {"skill_focus": "transitions", "grade_level": "3", "step_1_introduce": "…"}
    outcome = await _dispatch_stubbed_structured(
        monkeypatch, RequestType.DEEPEN_PRIOR,
        additional_skills=["conclusions"], body=_LESSON_BODY, structured=lesson,
    )
    guard = format_one_skill_guard(["conclusions"])
    assert outcome.structured.get("one_skill_guard") == guard
    assert outcome.response_text == f"{guard}\n\n{_LESSON_BODY}"


@pytest.mark.asyncio
async def test_dispatch_structured_untouched_when_no_extras(monkeypatch):
    # Back-compat: a normal single-skill lesson (empty additional_skills) leaves
    # structured completely untouched — NO one_skill_guard key is added.
    lesson = {"skill_focus": "topic sentences", "grade_level": "3", "step_1_introduce": "…"}
    outcome = await _dispatch_stubbed_structured(
        monkeypatch, RequestType.SCRIPTED_ML,
        additional_skills=[], body=_LESSON_BODY, structured=lesson,
    )
    assert "one_skill_guard" not in outcome.structured
    assert outcome.structured == lesson
    assert outcome.response_text == _LESSON_BODY


@pytest.mark.asyncio
async def test_dispatch_no_structured_key_for_plan_unit_even_with_extras(monkeypatch):
    # Scope false-positive reducer: the guard never fires on PLAN_UNIT, so its
    # structured payload stays clean (no one_skill_guard key) there too.
    lesson = {"skill_focus": "many skills", "grade_level": "3"}
    outcome = await _dispatch_stubbed_structured(
        monkeypatch, RequestType.PLAN_UNIT,
        additional_skills=["conclusions"], body="PLAN BODY", structured=lesson,
    )
    assert "one_skill_guard" not in outcome.structured
    assert outcome.response_text == "PLAN BODY"
