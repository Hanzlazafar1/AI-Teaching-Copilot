"""Regression lock for the pilot finding: the 2A/2B depth observable
``validate_lesson_depth`` was not registered in ``campaign/judge.py``, so every
depth verdict came back UNCERTAIN ("not a known validator") and classified as a
false MISALIGNED. It (and its aliases) must resolve to a validator callable.
The behavioural depth check + the F57 young-grade carve-out are validated live
by the pilot (P6 representative grade-5 + edge kindergarten both ALIGNED)."""
from campaign.judge import _resolve_validator


def test_depth_observable_and_aliases_resolve():
    assert _resolve_validator("validate_lesson_depth") is not None
    assert _resolve_validator("depth") is not None
    assert _resolve_validator("2a2b") is not None
    assert _resolve_validator("lesson-depth") is not None
