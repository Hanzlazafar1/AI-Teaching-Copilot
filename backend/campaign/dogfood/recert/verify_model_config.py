"""One-shot check of July #15 (gpt-5.4 default). Not agent-driven — a config fact.
Verified once in the Workflow preflight + locked by a unit test."""

_EXPECTED = {
    "openai_generation_model": "gpt-5.4",
    "openai_query_model": "gpt-5.4-mini",
    "openai_judge_model": "gpt-5.4-mini",
}


def check(settings):
    errs = []
    for attr, want in _EXPECTED.items():
        got = getattr(settings, attr, None)
        if got != want:
            label = attr.replace("openai_", "").replace("_model", "")
            errs.append(f"{label} model = {got!r}, expected {want!r}")
    return errs
