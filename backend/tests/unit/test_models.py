"""Tests for api/models.py — request/response schema validation."""

import pytest
from pydantic import ValidationError

from api.models import ChatRequest, ChatResponse, ParsedQueryInfo, SourceInfo


class TestChatRequest:
    """Request validation."""

    def test_valid_request(self):
        req = ChatRequest(message="teach me about topic sentences")
        assert req.message == "teach me about topic sentences"
        assert req.session_id is None
        assert req.user_id is None

    def test_with_session(self):
        req = ChatRequest(
            message="hello",
            session_id="sess-123",
            user_id="user-456",
        )
        assert req.session_id == "sess-123"

    def test_max_length_enforced(self):
        # Long inputs up to 100,000 chars (e.g. video transcripts) pass validation
        req = ChatRequest(message="x" * 50000)
        assert len(req.message) == 50000
        with pytest.raises(ValidationError):
            ChatRequest(message="x" * 100001)

    def test_empty_message_allowed(self):
        # Empty string is technically valid — the route handles this
        req = ChatRequest(message="")
        assert req.message == ""


class TestChatResponse:
    """Response schema."""

    def test_minimal_response(self):
        resp = ChatResponse(
            response="Hello",
            intent="coaching",
            quality="validated",
        )
        assert resp.quality == "validated"
        assert resp.sources == []
        assert resp.ungrounded_terms == []

    def test_full_response(self):
        resp = ChatResponse(
            response={"skill_focus": "test"},
            intent="mini_lesson",
            quality="acceptable",
            quality_warning="Needs review.",
            sources=[
                SourceInfo(
                    chunk_id="c-1",
                    source_document="doc.pdf",
                    content_type="lesson_script",
                    relevance_score=0.85,
                )
            ],
            retrieved_context="context here",
            judge_score=78.0,
            ungrounded_terms=["Fake Strategy"],
            follow_up_question=None,
            parsed_query=ParsedQueryInfo(
                intent="mini_lesson",
                grade_level="3",
                writing_mode="Inform",
            ),
        )
        assert resp.judge_score == 78.0
        assert len(resp.sources) == 1
        assert resp.sources[0].chunk_id == "c-1"
