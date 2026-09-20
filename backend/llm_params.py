"""Per-model OpenAI call-parameter compatibility."""
from __future__ import annotations


def temperature_kwargs(model: str, temperature: float) -> dict:
    """Return {"temperature": temperature}, or {} for models that reject an
    explicit temperature. The GPT-5.6 family (terra/luna/sol) are
    reasoning-style models that 400 on ANY explicit temperature (including 0)
    — they only run at the provider default. gpt-5.4* and gpt-4o* honor it."""
    if model.startswith("gpt-5.6"):
        return {}
    return {"temperature": temperature}


def call_params(model: str, temperature: float, max_tokens: int = 4096) -> dict:
    """Return temperature and max_tokens kwargs compatible with the model and provider.

    OpenRouter enforces key balance limits against the theoretical maximum output
    tokens (up to 65536) if max_tokens is omitted. Providing a sensible bound
    (2048 for query understanding/judge, 4096 for lesson generation) prevents
    HTTP 402 Payment Required credit-reservation errors.
    """
    params = temperature_kwargs(model, temperature)
    params["max_tokens"] = max_tokens
    return params
