import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import recert_schema as rs

_TARGETS = ["1","2","3"]

def _good():
    return {
        "id": "R01", "type": "dynamic", "covers": ["2","3"],
        "agenda": {"goal":"g","opening":"o","reactions":"r","edges":"e","done_when_turns":"t"},
        "done_whens": [{"target_id":"2","text":"x"}, {"target_id":"3","text":"y"}],
    }

def test_good_dynamic_passes():
    assert rs.validate(_good(), _TARGETS) == []

def test_scripted_needs_turns():
    s = _good(); s["type"] = "scripted"; s.pop("agenda");
    assert any("turns" in e for e in rs.validate(s, _TARGETS))

def test_covers_unknown_target_flagged():
    s = _good(); s["covers"] = ["2","99"]
    assert any("99" in e for e in rs.validate(s, _TARGETS))

def test_done_when_must_be_object_with_target_id():
    s = _good(); s["done_whens"] = ["just a string"]
    assert any("target_id" in e for e in rs.validate(s, _TARGETS))

def test_dynamic_agenda_keys_required():
    s = _good(); s["agenda"].pop("edges")
    assert any("agenda" in e for e in rs.validate(s, _TARGETS))

def test_no_target_ids_arg_skips_cross_check():
    # validate structure without a universe to check covers against
    assert rs.validate(_good()) == []
