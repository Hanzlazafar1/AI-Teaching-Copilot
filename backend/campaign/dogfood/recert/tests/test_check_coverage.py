import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json, os, tempfile
import check_coverage as cc

def _write(d, name, obj):
    p = os.path.join(d, name)
    with open(p, "w") as f:
        json.dump(obj, f)
    return p

def test_static_flags_uncovered_target():
    with tempfile.TemporaryDirectory() as d:
        conv = os.path.join(d, "conversations"); os.makedirs(conv)
        targets = _write(d, "targets.json", [{"id":"1"},{"id":"2"}])
        _write(conv, "A.json", {"id":"A","covers":["1"]})
        assert cc.static_uncovered(conv, targets) == ["2"]

def test_static_all_covered():
    with tempfile.TemporaryDirectory() as d:
        conv = os.path.join(d, "conversations"); os.makedirs(conv)
        targets = _write(d, "targets.json", [{"id":"1"}])
        _write(conv, "A.json", {"id":"A","covers":["1"]})
        assert cc.static_uncovered(conv, targets) == []

def test_runtime_na_does_not_count_as_covered():
    with tempfile.TemporaryDirectory() as d:
        targets = _write(d, "targets.json", [{"id":"1"},{"id":"2"}])
        verdicts = _write(d, "verdicts.json", [
            {"conversation_id":"A","verdicts":[
                {"target_id":"1","verdict":"ALIGNED"},
                {"target_id":"2","verdict":"NOT_APPLICABLE"}]}])
        assert cc.runtime_uncovered(verdicts, targets) == ["2"]

def test_runtime_misaligned_counts_as_exercised():
    with tempfile.TemporaryDirectory() as d:
        targets = _write(d, "targets.json", [{"id":"1"}])
        verdicts = _write(d, "verdicts.json", [
            {"conversation_id":"A","verdicts":[{"target_id":"1","verdict":"MISALIGNED"}]}])
        assert cc.runtime_uncovered(verdicts, targets) == []
