import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# tests/test_verify_model_config.py
import types
import verify_model_config as vm

def _settings(gen, qu, judge):
    return types.SimpleNamespace(
        openai_generation_model=gen, openai_query_model=qu, openai_judge_model=judge)

def test_correct_config_passes():
    assert vm.check(_settings("gpt-5.4", "gpt-5.4-mini", "gpt-5.4-mini")) == []

def test_wrong_generation_flagged():
    errs = vm.check(_settings("gpt-4o", "gpt-5.4-mini", "gpt-5.4-mini"))
    assert any("generation" in e for e in errs)

def test_wrong_query_flagged():
    errs = vm.check(_settings("gpt-5.4", "gpt-5.4", "gpt-5.4-mini"))
    assert any("query" in e for e in errs)

def test_real_config_matches_15():
    # the live #15 fact — imports the app's real settings
    import sys, os
    sys.path.insert(0, os.path.abspath("."))  # run from copilot-v4/
    from config import settings
    assert vm.check(settings) == []
