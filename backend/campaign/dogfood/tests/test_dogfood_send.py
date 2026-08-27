import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dogfood_send as ds


def test_text_response_captures_envelope_and_returns_reply(tmp_path, monkeypatch):
    fake = {"response": "Grade 3 | Informative\n\nStep 1 ...",
            "intent": "SCRIPTED_ML", "sources": [], "retrieved_context": "ctx",
            "quality": {"ok": True}, "header": "Grade 3 | Informative"}
    monkeypatch.setattr(ds, "_do_post", lambda api, payload: fake)
    record, reply = ds.send("sess1", "hi", user_id="u1", transcripts_dir=str(tmp_path))
    assert reply == fake["response"]
    assert record["response_kind"] == "text"
    assert record["turn_index"] == 0
    assert record["message"] == "hi"
    assert record["intent"] == "SCRIPTED_ML"
    # second turn on the same session increments the index and appends
    record2, _ = ds.send("sess1", "again", user_id="u1", transcripts_dir=str(tmp_path))
    assert record2["turn_index"] == 1
    lines = (tmp_path / "sess1.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["message"] == "hi"


def test_structured_response_captures_dict_fields(tmp_path, monkeypatch):
    fake = {"response": {"skill_focus": "topic sentences",
                         "one_skill_guard": "Mini-lessons are focused on one skill...",
                         "book_citation": "p.64"},
            "intent": "SCRIPTED_ML"}
    monkeypatch.setattr(ds, "_do_post", lambda api, payload: fake)
    record, reply = ds.send("sess2", "lesson please", transcripts_dir=str(tmp_path))
    assert record["response_kind"] == "structured"
    assert record["one_skill_guard"].startswith("Mini-lessons")
    assert record["book_citation"] == "p.64"
    assert isinstance(record["response"], dict)  # captured verbatim


def test_absent_user_id_is_unique_not_anonymous(tmp_path, monkeypatch):
    monkeypatch.setattr(ds, "_do_post", lambda api, payload: {"response": "x"})
    seen = set()
    for _ in range(3):
        record, _ = ds.send("s", "m", transcripts_dir=str(tmp_path))
        seen.add(record["user_id"])
    assert all(u.startswith("dogfood-") and u != "anonymous" for u in seen)
    assert len(seen) == 3  # a fresh user_id per call
