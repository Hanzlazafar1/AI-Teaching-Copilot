import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import schema


def test_valid_scripted_spec_has_no_errors():
    spec = {"id": "C1", "type": "scripted", "covers": ["1"],
            "done_whens": ["asks grade before content"],
            "turns": ["Give me a scripted mini-lesson on topic sentences", "3rd grade"]}
    assert schema.validate(spec) == []


def test_valid_dynamic_spec_has_no_errors():
    spec = {"id": "C6", "type": "dynamic", "covers": ["13"],
            "done_whens": ["produces cumulative day-2/day-3 or records the gap"],
            "agenda": {"goal": "get days 2-3 of the same skill",
                       "opening": "Give me a 5-day week for topic sentences",
                       "reactions": "answer any grade/mode question; then push for days 2-3",
                       "done_when_turns": "after asking for days 2-3 and reading the reply"}}
    assert schema.validate(spec) == []


def test_scripted_without_turns_is_an_error():
    spec = {"id": "X", "type": "scripted", "covers": ["1"], "done_whens": ["x"]}
    errs = schema.validate(spec)
    assert any("turns" in e for e in errs)


def test_missing_done_whens_is_an_error():
    spec = {"id": "X", "type": "scripted", "covers": ["1"], "turns": ["hi"]}
    assert any("done_whens" in e for e in schema.validate(spec))


def test_dynamic_without_agenda_is_an_error():
    spec = {"id": "X", "type": "dynamic", "covers": ["1"], "done_whens": ["x"]}
    assert any("agenda" in e for e in schema.validate(spec))
