"""Smekens AI Writing Co-Pilot — Streamlit testing frontend.

Designed for Brady's review of the v3 pilot. Focuses on:
  * A clean chat experience that looks close to production.
  * A diagnostic sidebar that surfaces every pipeline signal Brady might
    want to inspect: parsed query, session memory (what the system
    remembers across turns), quality flags, sources, retrieved context.
  * One-click example queries covering the common scenario shapes so
    Brady can exercise the pipeline without re-typing.
  * Per-response request-id so bug reports can be cross-referenced with
    backend logs.
"""

from __future__ import annotations

import uuid
from typing import Any

import requests
import streamlit as st

from ui_content import (
    EXAMPLE_QUERIES,
    HELP_HEADER,
    format_lesson_header_display,
    lesson_display_title,
)


# ---------------------------------------------------------------------------
# Password gate
# ---------------------------------------------------------------------------


def _check_password() -> bool:
    """Simple password gate using Streamlit secrets."""
    if st.session_state.get("authenticated"):
        return True

    password = st.text_input("Password", type="password", key="pw_input")
    if password:
        if password == st.secrets["password"]:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")
    return False


if not _check_password():
    st.stop()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


API_BASE = "http://localhost:8765"
REQUEST_TIMEOUT_SECONDS = 90

# Model is fixed to GPT-5.4 (Brady removed the 4.0 choice, req #15 / U1:
# "I stopped using 4.0 ... make it the default/automatic, don't even give
# them the choice of 4.0"). Kept as a dict (not a bare string) so the
# display label and the backend profile key stay defined in one place.
MODEL_PROFILES: dict[str, str] = {
    "GPT-5.4 (generation=gpt-5.4, judge=gpt-5.4-mini)": "gpt-5.4",
}
DEFAULT_MODEL_LABEL = next(iter(MODEL_PROFILES))  # only entry

QUALITY_COLORS = {
    "validated": "green",
    "acceptable": "orange",
    "low_quality": "red",
    "unscored": "gray",
    "error": "red",
}



# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------


if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    # Each message: {role, content, raw_response?, metadata?}
    st.session_state.messages = []
if "last_metadata" not in st.session_state:
    st.session_state.last_metadata = None
if "pending_example_query" not in st.session_state:
    st.session_state.pending_example_query = None
if "model_label" not in st.session_state:
    st.session_state.model_label = DEFAULT_MODEL_LABEL


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------


st.set_page_config(
    page_title="Brady AI Writing Co-Pilot",
    page_icon="✏️",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_session_id(sid: str) -> str:
    """First 8 chars for display — enough to distinguish sessions without
    cluttering the header."""
    return sid.split("-")[0]


def _humanize_response_type(raw: str | None) -> str:
    """Match the backend's rendering so the sidebar reads as prose, not
    enum. Keeps Brady's mental model in natural language."""
    if not raw:
        return "—"
    mapping = {
        # v4 request types
        "SCRIPTED_ML":  "Scripted 4-step mini-lesson",
        "HOW_TO_TEACH": "How-to-teach outline",
        "PLAN_UNIT":    "Unit-plan skill sequence",
        "MANAGEMENT":   "Classroom-management guidance",
        "COACHING":     "Coaching response",
        "THINK_ALOUD":  "Think-aloud monologue",
        "META":         "Greeting / acknowledgment",
        "DEEPEN_PRIOR": "Follow-up / deepen prior",
        "CORRECTION":   "Correction / revision",
        # v3 legacy keys (kept so stored history still renders)
        "COACHING_GENERAL":   "Coaching response",
        "EARLY_WRITER":       "K-2 early-writer support",
        "TRIGGER_SPECIFIC":   "Smekens-trigger explainer",
        "DEFAULT":            "General response",
        "META_CONVERSATIONAL": "Greeting / acknowledgment",
    }
    return mapping.get(raw, raw.lower().replace("_", " ").capitalize())


def _quality_badge(quality: str | None, score: float | None = None) -> str:
    """Compact colored markdown label for use inline with responses."""
    q = quality or "—"
    color = QUALITY_COLORS.get(q, "gray")
    score_part = f" · {score:.1f}/10" if isinstance(score, (int, float)) else ""
    return f":{color}[**{q}**]{score_part}"


def _render_lesson(lesson: dict) -> None:
    """Render a MiniLesson as formatted steps with clear section dividers."""
    # Brady S3: when the teacher tried to cram a SECOND skill into ONE lesson,
    # the backend prefaces the delivered lesson with a deterministic one-skill
    # guard, surfaced as a NEW `one_skill_guard` field on the structured payload
    # (mirrors the Fm4 `header` field). Render it as a prominent lead-in ABOVE
    # the skill heading. Absent on normal single-skill lessons → nothing shown.
    guard = lesson.get("one_skill_guard")
    if guard:
        st.info(guard)

    # Brady C1: prefer the model-authored, verb-led lesson_title; fall back to
    # the teacher-vocab skill_focus (old history / library-verbatim have none).
    title = lesson_display_title(lesson)

    st.markdown(f"### {title}")
    header = format_lesson_header_display(lesson)
    if header:
        st.caption(header)

    steps = [
        ("Step 1 — Introduce",            "step_1_introduce"),
        ("Step 2A — Tell",                "step_2a_tell"),
        ("Step 2B — Show (Think-Aloud)",  "step_2b_show"),
        ("Step 3 — Interact",             "step_3_interact"),
        ("Step 4 — Close",                "step_4_close"),
    ]
    for label, key in steps:
        text = lesson.get(key, "")
        if not text:
            continue
        st.markdown(f"**{label}**")
        st.markdown(text)

    # Brady Fm5: soft book-citation footer (present only when a page-verified
    # Launch citation exists). Rendered AFTER the steps (a footer, not a lead-in
    # like the S3 guard). Absent on lessons with no known page → nothing shown.
    citation = lesson.get("book_citation")
    if citation:
        st.markdown(citation)

    # Brady E2: the teacher-facing customization follow-up, delivered as its own
    # `followup` field on the structured payload (like `book_citation` above).
    # LAST — after the citation — and as its own paragraph, never glued to Step 4:
    # it addresses the TEACHER, whereas Step 4's close is spoken to students.
    followup = lesson.get("followup")
    if followup:
        st.markdown(followup)


def _lesson_as_text(lesson: dict) -> str:
    """Flat markdown of a lesson — used for copy-to-clipboard."""
    lines: list[str] = []
    # Brady S3 one-skill guard (see _render_lesson) — keep it with the copied
    # lesson so the guard isn't silently dropped from the copy path.
    guard = lesson.get("one_skill_guard")
    if guard:
        lines.extend([f"> {guard}", ""])
    lines += [
        # Brady C1: verb-led lesson_title preferred, skill_focus as fallback.
        f"# {lesson_display_title(lesson)}",
        format_lesson_header_display(lesson),
        "",
    ]
    for label, key in (
        ("Step 1 — Introduce",           "step_1_introduce"),
        ("Step 2A — Tell",               "step_2a_tell"),
        ("Step 2B — Show (Think-Aloud)", "step_2b_show"),
        ("Step 3 — Interact",            "step_3_interact"),
        ("Step 4 — Close",               "step_4_close"),
    ):
        text = lesson.get(key, "")
        if text:
            lines.append(f"## {label}")
            lines.append(text)
            lines.append("")
    # Brady Fm5 book-citation footer (see _render_lesson) — keep it with the
    # copied lesson so the citation isn't silently dropped from the copy path.
    citation = lesson.get("book_citation")
    if citation:
        lines.append(citation)
        lines.append("")
    # Brady E2 follow-up (see _render_lesson) — likewise kept on the copy path.
    followup = lesson.get("followup")
    if followup:
        lines.append(followup)
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Sidebar — diagnostics panel
# ---------------------------------------------------------------------------


def _render_session_memory(session_state: dict | None) -> None:
    """Brady's key diagnostic: what does the system remember across turns?

    Renders the active session state as two small tables — "Teacher facts"
    (grade, mode, trait, skill) and "Last turn" (response type, citations,
    etc.). Empty when the session is fresh.
    """
    st.sidebar.subheader("Session Memory")
    if not session_state:
        st.sidebar.caption("Fresh session — nothing remembered yet.")
        return

    # Teacher facts — v4 uses grade/mode/trait; fall back to v3 keys for history
    fact_rows = []
    for label, key, fallback in (
        ("Grade",  "grade",  "grade_level"),
        ("Mode",   "mode",   "writing_mode"),
        ("Trait",  "trait",  "writing_trait"),
        ("Skill",  "skill",  "skill"),
    ):
        val = session_state.get(key) or session_state.get(fallback)
        if val:
            fact_rows.append((label, str(val)))
    skill_can = session_state.get("skill_canonical")
    if skill_can:
        fact_rows.append(("Canonical", str(skill_can)))

    if fact_rows:
        st.sidebar.markdown("**Teacher facts**")
        st.sidebar.markdown(
            "\n".join(f"- **{label}:** {val}" for label, val in fact_rows)
        )

    # Last-turn artifacts
    last_rows = []
    last_type = session_state.get("last_response_type")
    if last_type:
        last_rows.append(("Last response", _humanize_response_type(last_type)))
    last_req = session_state.get("last_request_type")
    if last_req:
        last_rows.append(("Request type", last_req))
    turn_count = session_state.get("turn_count")
    if turn_count is not None:
        last_rows.append(("Turns", str(turn_count)))
    for label, key in (
        ("Last cited page", "last_book_page_reference"),
        ("Last trigger",    "last_trigger_mentioned"),
        ("Last organizer",  "last_organizer_mentioned"),
    ):
        val = session_state.get(key)
        if val:
            last_rows.append((label, str(val)))
    triggers = session_state.get("required_triggers") or []
    if triggers:
        last_rows.append(("Triggers", ", ".join(str(t) for t in triggers)))
    offered = session_state.get("last_offered_skills") or []
    if offered:
        last_rows.append(("Offered skills", "; ".join(str(s) for s in offered)))
    missing = session_state.get("missing_required") or []
    if missing:
        last_rows.append(("Missing fields", ", ".join(missing)))

    if last_rows:
        st.sidebar.markdown("**Last turn**")
        st.sidebar.markdown(
            "\n".join(f"- **{label}:** {val}" for label, val in last_rows)
        )

    # Pending flags (only if something is actually pending)
    pending = []
    if session_state.get("pending_library_offer"):
        pending.append("library offer")
    # v4: pending_ml_confirmation; v3: pending_scripted_ml_confirmation
    if session_state.get("pending_ml_confirmation") or session_state.get("pending_scripted_ml_confirmation"):
        pending.append("scripted-ML confirmation")
    # v4: clarification_pending; v3: deferred_query
    if session_state.get("clarification_pending"):
        pending.append("clarification needed")
    if session_state.get("deferred_query"):
        pending.append(f"topic-shift: \"{session_state['deferred_query'][:40]}…\"")
    if pending:
        st.sidebar.markdown("**Pending**")
        st.sidebar.markdown("\n".join(f"- {p}" for p in pending))


def _render_parsed_query(pq: dict | None) -> None:
    st.sidebar.subheader("Parsed Query")
    if not pq:
        st.sidebar.caption("No parsed query yet.")
        return

    cols = st.sidebar.columns(2)
    cols[0].metric("Intent", pq.get("intent") or "—")
    cols[1].metric("Grade",  pq.get("grade_level") or "—")
    cols2 = st.sidebar.columns(2)
    cols2[0].metric("Trait", pq.get("writing_trait") or "—")
    cols2[1].metric("Mode",  pq.get("writing_mode") or "—")

    qt = pq.get("query_type")
    if qt:
        st.sidebar.markdown(f"**Query type:** `{qt}`")

    spec = pq.get("query_specificity")
    if spec:
        st.sidebar.markdown(f"**Specificity:** {spec}")

    follow_up = pq.get("follow_up_type", "none")
    if follow_up != "none":
        fu_color = "blue" if follow_up == "refinement" else "violet"
        st.sidebar.markdown(f"**Follow-up:** :{fu_color}[{follow_up}]")

    if pq.get("strategy_name"):
        st.sidebar.markdown(f"**Strategy:** {pq['strategy_name']}")

    terms = pq.get("smekens_terms", [])
    if terms:
        st.sidebar.markdown(
            "**Search terms:** " + ", ".join(f"`{t}`" for t in terms)
        )


def _render_quality(meta: dict) -> None:
    st.sidebar.subheader("Quality")
    quality = meta.get("quality") or "—"
    color = QUALITY_COLORS.get(quality, "gray")
    score = meta.get("judge_score")
    score_display = f"{score:.1f}/10" if score is not None else "—"
    st.sidebar.markdown(
        f"**Rating:** :{color}[{quality}] &nbsp; **Score:** {score_display}"
    )
    if meta.get("quality_warning"):
        st.sidebar.warning(meta["quality_warning"])


def _render_ungrounded(meta: dict) -> None:
    ungrounded = meta.get("ungrounded_terms") or []
    if not ungrounded:
        return
    st.sidebar.subheader("Ungrounded Terms")
    st.sidebar.warning(", ".join(ungrounded))


def _render_sources(meta: dict) -> None:
    sources = meta.get("sources") or []
    st.sidebar.subheader(f"Sources ({len(sources)})")
    if not sources:
        st.sidebar.caption("No sources retrieved.")
        return
    for src in sources[:10]:
        score_val = src.get("relevance_score", 0)
        with st.sidebar.expander(
            f"{src['chunk_id'][:45]}  ({score_val:.3f})"
        ):
            st.markdown(f"**Document:** {src.get('source_document', '—')}")
            st.markdown(f"**Type:** {src.get('content_type', '—')}")


def _render_retrieved_context(meta: dict) -> None:
    ctx = meta.get("retrieved_context") or ""
    st.sidebar.subheader("Full Retrieved Context")
    if not ctx:
        st.sidebar.caption("No context retrieved.")
        return
    st.sidebar.text_area(
        "Context passed to LLM",
        value=ctx,
        height=300,
        disabled=True,
        label_visibility="collapsed",
    )


def render_sidebar() -> None:
    """Render the sidebar with metadata from the last API response."""
    meta = st.session_state.last_metadata or {}

    _render_session_memory(meta.get("session_state"))
    st.sidebar.divider()

    _render_parsed_query(meta.get("parsed_query"))
    st.sidebar.divider()

    if meta:
        _render_quality(meta)
        _render_ungrounded(meta)
        st.sidebar.divider()
        _render_sources(meta)
        st.sidebar.divider()
        _render_retrieved_context(meta)


render_sidebar()


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------


st.title("Brady AI Writing Co-Pilot")
st.caption(
    f"Testing interface · Session `{_short_session_id(st.session_state.session_id)}` · "
    f"{len(st.session_state.messages)//2} turns"
)

# Model is fixed to GPT-5.4 (Brady removed the 4.0 choice, req #15 / U1).
st.session_state.model_label = DEFAULT_MODEL_LABEL
st.caption("Model: **GPT-5.4** (generation gpt-5.4 · judge gpt-5.4-mini)")

# Example-query quick-start — only shown before the first message to keep
# the chat area clean once a conversation is underway.
if not st.session_state.messages:
    st.markdown(f"#### {HELP_HEADER}")
    # Two columns, 3 buttons each — tight layout.
    cols = st.columns(2)
    for i, (label, msg) in enumerate(EXAMPLE_QUERIES):
        col = cols[i % 2]
        if col.button(label, key=f"example_{i}", use_container_width=True):
            st.session_state.pending_example_query = msg
            st.rerun()
    st.divider()


# ---------------------------------------------------------------------------
# Chat history rendering
# ---------------------------------------------------------------------------


def _render_assistant_message(msg: dict) -> None:
    """Render a stored assistant message. If the stored payload was a
    lesson dict, re-render as structured steps; otherwise markdown."""
    raw = msg.get("raw_response")
    if isinstance(raw, dict):
        _render_lesson(raw)
    else:
        st.markdown(msg.get("content", ""))

    # Inline metadata caption — quality badge + model profile + request id.
    meta = msg.get("metadata") or {}
    parts: list[str] = []
    if meta.get("quality"):
        parts.append(_quality_badge(meta.get("quality"), meta.get("judge_score")))
    if meta.get("model_profile"):
        parts.append(f"<span style='color:#888'>model `{meta['model_profile']}`</span>")
    rid = meta.get("request_id")
    if rid:
        parts.append(f"<span style='color:#888'>req_id `{rid[:8]}`</span>")
    if parts:
        st.markdown(
            " · ".join(parts),
            unsafe_allow_html=True,
        )

    # Inline warning directly under the response — so Brady sees the
    # violation without having to glance at the sidebar.
    if meta.get("quality_warning"):
        st.warning(meta["quality_warning"])


for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            _render_assistant_message(msg)
        else:
            st.markdown(msg["content"])


# ---------------------------------------------------------------------------
# Chat input — accept either manual input or a queued example query
# ---------------------------------------------------------------------------


manual_prompt = st.chat_input("Ask about writing instruction...")
example_prompt = st.session_state.pending_example_query

prompt = manual_prompt or example_prompt
if example_prompt:
    # Consume the queued example so it only fires once.
    st.session_state.pending_example_query = None


def _call_api(message: str) -> dict[str, Any] | None:
    """POST to /api/chat. Returns the parsed JSON, or None on error
    (caller shows the error and stops the turn)."""
    try:
        resp = requests.post(
            f"{API_BASE}/api/chat",
            json={
                "message": message,
                "session_id": st.session_state.session_id,
                "user_id": "streamlit-tester",
                # Current model-profile selection. Backend validates
                # against its whitelist; unknown values silently fall
                # back to the configured default.
                "model": MODEL_PROFILES[st.session_state.model_label],
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        st.error(
            f"Cannot connect to backend at {API_BASE}. "
            f"Is the server running? (`uvicorn main:app --port 8765`)"
        )
        return None
    except requests.exceptions.Timeout:
        st.error(
            f"Backend didn't respond within {REQUEST_TIMEOUT_SECONDS}s. "
            f"Check backend logs for a long retry loop."
        )
        return None
    except requests.exceptions.HTTPError as e:
        # Surface structured error envelope if backend returned one.
        try:
            body = e.response.json()
            code = body.get("code") or e.response.status_code
            message = body.get("message") or str(e)
            st.error(f"Backend error [{code}]: {message}")
        except ValueError:
            st.error(f"Backend error: {e}")
        return None
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return None


if prompt:
    # Show the user message immediately.
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Call the backend.
    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            data = _call_api(prompt)
        if data is None:
            st.stop()

        # Save all diagnostics for the sidebar.
        metadata = {
            "parsed_query":     data.get("parsed_query"),
            "session_state":    data.get("session_state"),
            "quality":          data.get("quality"),
            "judge_score":      data.get("judge_score"),
            "quality_warning":  data.get("quality_warning"),
            "sources":          data.get("sources", []),
            "retrieved_context": data.get("retrieved_context", ""),
            "ungrounded_terms": data.get("ungrounded_terms", []),
            "request_id":       data.get("request_id"),
            # Remember which profile produced this turn so the caption can
            # show it. Model is now fixed to gpt-5.4 (Brady removed the
            # 4.0 choice, req #15 / U1) — kept per-turn for symmetry with
            # the other per-turn metadata fields above.
            "model_profile":    MODEL_PROFILES[st.session_state.model_label],
        }
        st.session_state.last_metadata = metadata

        # Render the response body (lesson dict or markdown string).
        response_body = data.get("response", "")
        if isinstance(response_body, dict):
            _render_lesson(response_body)
            # Brady C1: store the verb-led lesson_title as the history label
            # (skill_focus fallback for older/other producers).
            stored_content = lesson_display_title(response_body)
            st.session_state.messages.append({
                "role":         "assistant",
                "content":      stored_content,
                "raw_response": response_body,
                "metadata":     metadata,
            })
            # Copy-as-text expander directly under the lesson.
            with st.expander("Copy as markdown"):
                st.code(_lesson_as_text(response_body), language="markdown")
        else:
            text = str(response_body)
            st.markdown(text)
            st.session_state.messages.append({
                "role":     "assistant",
                "content":  text,
                "metadata": metadata,
            })

        # Inline caption: quality + model profile + req_id + warning.
        caption_parts: list[str] = []
        if metadata.get("quality"):
            caption_parts.append(_quality_badge(
                metadata.get("quality"), metadata.get("judge_score")
            ))
        if metadata.get("model_profile"):
            caption_parts.append(
                f"<span style='color:#888'>model `{metadata['model_profile']}`</span>"
            )
        if metadata.get("request_id"):
            caption_parts.append(
                f"<span style='color:#888'>req_id `{metadata['request_id'][:8]}`</span>"
            )
        if caption_parts:
            st.markdown(" · ".join(caption_parts), unsafe_allow_html=True)
        if metadata.get("quality_warning"):
            st.warning(metadata["quality_warning"])

    st.rerun()


# ---------------------------------------------------------------------------
# Footer controls
# ---------------------------------------------------------------------------


st.divider()
col1, col2, col3 = st.columns([1, 1, 4])
with col1:
    if st.button("Clear Chat"):
        st.session_state.messages = []
        st.session_state.last_metadata = None
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.pending_example_query = None
        st.rerun()
with col2:
    if st.button("New Session"):
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.last_metadata = None
        st.toast("New session started")
