import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import os

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _read(name):
    with open(os.path.join(_HERE, name)) as f:
        return f.read().lower()

def test_driver_contract_has_prohibitions():
    t = _read("brady_contract.md")
    assert "never" in t and "answer key" in t
    assert "8 turns" in t or "done_when_turns" in t
    assert "8092" in t  # drives the right backend

def test_analyst_contract_whole_conversation():
    t = _read("analyst_contract.md")
    assert "every turn" in t or "whole" in t            # sees the whole convo
    assert "turn 1" in t                                 # turn-1 facts visible
    assert "not_applicable" in t                          # can decline, not fabricate
    assert "verbatim" in t or "quote" in t                # quote, don't paraphrase
    assert "field" in t                                   # read structured fields
    assert "target_id" in t                               # per-target output

def test_analyst_contract_verdict_vocab():
    t = _read("analyst_contract.md")
    for v in ("aligned", "misaligned", "partial", "not_applicable"):
        assert v in t
