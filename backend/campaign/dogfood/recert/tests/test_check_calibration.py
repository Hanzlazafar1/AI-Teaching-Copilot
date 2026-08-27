import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import check_calibration as ck


def test_all_match_is_empty():
    exp = {"a": "ALIGNED", "b": "MISALIGNED"}
    assert ck.mismatches({"a": "ALIGNED", "b": "MISALIGNED"}, exp) == []


def test_wrong_verdict_flagged():
    exp = {"bad_close": "MISALIGNED"}
    m = ck.mismatches({"bad_close": "ALIGNED"}, exp)
    assert len(m) == 1 and "bad_close" in m[0]


def test_missing_result_flagged():
    exp = {"a": "ALIGNED"}
    m = ck.mismatches({}, exp)
    assert len(m) == 1 and "a" in m[0]
