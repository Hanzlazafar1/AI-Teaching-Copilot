import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import validate_targets as vt

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    with open(os.path.join(_HERE, "targets.json")) as f:
        return json.load(f)


def test_valid_targets_pass():
    assert vt.validate(_load()) == []


def test_all_26_targets_present():
    ids = set(vt.target_ids(_load()))
    expected = {"1","2","3","4","5","6","7","8","9","10","11","12","13","14",
                "15b","16","17","18a","18b","18c","18d","18e","e5b","h2t","u2","c10"}
    assert ids == expected


def test_missing_done_when_flagged():
    bad = [{"id": "x", "requirement": "r", "source": "s"}]  # no done_when
    assert any("done_when" in e for e in vt.validate(bad))


def test_duplicate_id_flagged():
    bad = [{"id":"1","requirement":"r","done_when":"d","source":"s"},
           {"id":"1","requirement":"r","done_when":"d","source":"s"}]
    assert any("duplicate" in e for e in vt.validate(bad))


def test_empty_flagged():
    assert vt.validate([]) != []
