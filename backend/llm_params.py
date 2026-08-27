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
