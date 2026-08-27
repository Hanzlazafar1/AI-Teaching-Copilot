import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import check_coverage as cc


def _write(convs_dir, name, covers):
    with open(os.path.join(convs_dir, f"{name}.json"), "w") as f:
        json.dump({"id": name, "covers": covers}, f)


def test_full_coverage_returns_empty(tmp_path):
    convs = tmp_path / "conversations"; convs.mkdir()
    reqs = tmp_path / "requirements.json"
    reqs.write_text(json.dumps(["a", "b", "c"]))
    _write(str(convs), "C1", ["a", "b"])
    _write(str(convs), "C2", ["c"])
    assert cc.uncovered(str(convs), str(reqs)) == []


def test_missing_requirement_is_reported(tmp_path):
    convs = tmp_path / "conversations"; convs.mkdir()
    reqs = tmp_path / "requirements.json"
    reqs.write_text(json.dumps(["a", "b", "c"]))
    _write(str(convs), "C1", ["a", "b"])  # "c" is uncovered
    assert cc.uncovered(str(convs), str(reqs)) == ["c"]
