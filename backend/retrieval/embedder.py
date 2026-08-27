"""OpenAI embedding wrapper with tenacity retry."""

from __future__ import annotations

import logging

import openai
from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def get_openai_async_client() -> AsyncOpenAI:
    """Lazy singleton for the async OpenAI client."""
    global _client
    if _client is None:
        kwargs = {"api_key": settings.openai_api_key, "timeout": 10.0}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        _client = AsyncOpenAI(**kwargs)
    return _client


@retry(
    retry=retry_if_exception_type(
        (openai.APITimeoutError, openai.APIConnectionError, openai.RateLimitError)
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
async def embed_query(text: str) -> list[float]:
    """Embed a single query string. Returns a 3072-dim float vector."""
    client = get_openai_async_client()
    response = await client.embeddings.create(
        model=settings.openai_embedding_model,
        input=text,
    )
    return response.data[0].embedding
