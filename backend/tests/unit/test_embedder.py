"""Tests for retrieval/embedder.py retry behavior (F21)."""
import httpx
import openai
import pytest

from retrieval import embedder


@pytest.mark.asyncio
async def test_embed_query_retries_on_openai_timeout(monkeypatch):
    """F21: OpenAI SDK errors don't subclass builtin TimeoutError, so the
    retry must target openai.* exception types to fire at all."""
    calls = {"n": 0}

    async def fake_create(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise openai.APITimeoutError(request=httpx.Request("POST", "http://x"))
        return type("Resp", (), {"data": [type("D", (), {"embedding": [0.1, 0.2]})()]})()

    fake_client = type("C", (), {"embeddings": type("E", (), {"create": staticmethod(fake_create)})()})()
    monkeypatch.setattr(embedder, "get_openai_async_client", lambda: fake_client)

    result = await embedder.embed_query("hello")
    assert calls["n"] == 3          # retried twice, succeeded on the third
    assert result == [0.1, 0.2]
