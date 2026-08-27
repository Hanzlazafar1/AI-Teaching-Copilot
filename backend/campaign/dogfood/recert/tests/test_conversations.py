import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import glob, json, os
import recert_schema as rs
import validate_targets as vt

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _targets():
    with open(os.path.join(_HERE, "targets.json")) as f:
        return json.load(f)

def _briefs():
    out = []
    for p in sorted(glob.glob(os.path.join(_HERE, "conversations", "*.json"))):
        with open(p) as f:
            out.append((os.path.basename(p), json.load(f)))
    return out

def test_at_least_35_briefs():
    assert len(_briefs()) >= 35

def test_every_brief_validates():
    ids = vt.target_ids(_targets())
    bad = {name: rs.validate(b, ids) for name, b in _briefs() if rs.validate(b, ids)}
    assert bad == {}, bad

def test_every_target_covered_by_an_anchored_brief():
    ids = set(vt.target_ids(_targets()))
    covered = set()
    for _, b in _briefs():
        covered.update(b.get("covers", []))
    assert ids - covered == set(), f"UNCOVERED: {sorted(ids - covered)}"

def test_brief_done_whens_match_target_text_verbatim():
    tmap = {t["id"]: t["done_when"] for t in _targets()}
    mismatches = []
    for name, b in _briefs():
        for dw in b.get("done_whens", []):
            if tmap.get(dw["target_id"]) != dw["text"]:
                mismatches.append((name, dw["target_id"]))
    assert mismatches == [], mismatches
