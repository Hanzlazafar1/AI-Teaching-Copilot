"""Pre-deploy gate: do the configured chat models answer, and can the
judge/query model (nano) produce STRUCTURED output? Run under a clean env
(unset a stale shell OPENAI_API_KEY so .env's key loads; base_url empty =
OpenAI-direct). Never prints the key."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def verdict(results: dict[str, bool]) -> str:
    """Map per-check results to a go/no-go string (pure, unit-tested)."""
    if not results.get("gen"):
        return "BLOCKER"
    if results.get("gen") and results.get("nano_gen") and results.get("nano_struct") and results.get("emb"):
        return "PROCEED"
    if results.get("gen") and not results.get("nano_struct") and results.get("gen_struct") and results.get("emb"):
        return "FALLBACK"
    return "MIXED"


async def main() -> None:
    from config import settings
    from api.dependencies import get_openai_client
    from validation.judge_v4 import JudgeVerdict

    client = get_openai_client()
    print(f"base_url={settings.openai_base_url!r} (empty => OpenAI-direct) key_present={bool(settings.openai_api_key)}")
    gen, nano = settings.openai_generation_model, settings.openai_query_model
    results: dict[str, bool] = {}

    async def plain(model: str) -> bool:
        try:
            await client.chat.completions.create(model=model, messages=[{"role": "user", "content": "Reply: ok"}])
            return True
        except Exception as e:  # noqa: BLE001
            print(f"  {model} generate FAIL: {type(e).__name__}: {e}")
            return False

    async def structured(model: str) -> bool:
        try:
            await client.chat.completions.parse(
                model=model,
                messages=[{"role": "system", "content": "Judge a mini-lesson."},
                          {"role": "user", "content": "a short 4-step mini-lesson"}],
                response_format=JudgeVerdict, temperature=0,
            )
            return True
        except Exception as e:  # noqa: BLE001
            print(f"  {model} structured FAIL: {type(e).__name__}: {e}")
            return False

    async def embeddings() -> bool:
        try:
            await client.embeddings.create(model=settings.openai_embedding_model, input="hello")
            return True
        except Exception as e:  # noqa: BLE001
            print(f"  embeddings FAIL: {type(e).__name__}: {e}")
            return False

    results["gen"] = await plain(gen)
    results["nano_gen"] = await plain(nano)
    results["nano_struct"] = await structured(nano)
    results["gen_struct"] = await structured(gen)
    results["emb"] = await embeddings()
    print(f"results={results}")
    print(f"VERDICT: {verdict(results)}")


if __name__ == "__main__":
    asyncio.run(main())
