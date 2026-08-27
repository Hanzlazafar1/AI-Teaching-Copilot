"""Tests for llm_params.temperature_kwargs — per-model temperature compat.

The GPT-5.6 family (terra/luna/sol) are reasoning-style models that 400 on
ANY explicit temperature (including 0), so the helper must OMIT temperature
for them. gpt-5.4* and gpt-4o* honor an explicit temperature normally.
"""

from llm_params import temperature_kwargs


def test_gpt_5_6_terra_omits_temperature():
    # Reasoning-style model rejects any explicit temperature, even non-zero.
    assert temperature_kwargs("gpt-5.6-terra", 0.2) == {}


def test_gpt_5_6_luna_omits_temperature_even_zero():
    # Even temperature=0 must be omitted for the 5.6 family.
    assert temperature_kwargs("gpt-5.6-luna", 0) == {}


def test_gpt_5_4_honors_temperature():
    assert temperature_kwargs("gpt-5.4", 0.2) == {"temperature": 0.2}


def test_gpt_5_4_nano_honors_zero_temperature():
    assert temperature_kwargs("gpt-5.4-nano", 0) == {"temperature": 0}


def test_gpt_4o_honors_temperature():
    assert temperature_kwargs("gpt-4o", 0.3) == {"temperature": 0.3}
