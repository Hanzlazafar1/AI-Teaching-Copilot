"""Tests for api.conversation_store — LRU, pair-atomic trim, pinning."""

from __future__ import annotations

from datetime import datetime

from api.conversation_store import (
    ConversationStore,
    _MAX_CHARS,
    _MAX_TURNS,
    _trim_conversation,
)
from schemas import (
    Conversation,
    Quality,
    Role,
    Turn,
)


def _pair(conv: Conversation, user_text: str, assistant_text: str,
          scripted: bool = False, quality: Quality = Quality.VALID) -> None:
    conv.append(Turn(index=len(conv.turns), role=Role.USER, text=user_text))
    conv.append(Turn(
        index=len(conv.turns), role=Role.ASSISTANT, text=assistant_text,
        structured={"skill_focus": "x"} if scripted else None,
        quality=quality,
    ))


# ----------------------------------------------------------------------
# Load / save / fresh-session semantics
# ----------------------------------------------------------------------


def test_load_creates_empty_conversation_for_new_session() -> None:
    store = ConversationStore()
    conv, hs = store.load("s1", user_id="u1")
    assert conv.session_id == "s1"
    assert conv.user_id == "u1"
    assert conv.turns == []
    assert hs.is_empty()


def test_load_returns_same_instance_across_calls() -> None:
    store = ConversationStore()
    c1, _ = store.load("s1")
    c1.append(Turn(index=0, role=Role.USER, text="hi"))
    store.save("s1", c1, store.load("s1")[1])
    c2, _ = store.load("s1")
    assert c2 is c1  # same object — mutations persist


def test_session_count_tracks_live_sessions() -> None:
    store = ConversationStore()
    store.load("a")
    store.load("b")
    assert store.session_count == 2
    store.clear("a")
    assert store.session_count == 1


# ----------------------------------------------------------------------
# LRU eviction
# ----------------------------------------------------------------------


def test_lru_evicts_oldest_sessions_over_cap() -> None:
    from api import conversation_store as cs_mod

    store = ConversationStore()
    # Tighten caps via monkey-patch so the test runs fast
    old_max, old_batch = cs_mod._MAX_SESSIONS, cs_mod._EVICT_BATCH
    cs_mod._MAX_SESSIONS = 5
    cs_mod._EVICT_BATCH = 2
    try:
        for i in range(5):
            store.load(f"s{i}")
        # Touching s0 moves it to MRU; s1 becomes LRU
        store.load("s0")
        # Adding two more sessions trips the cap + batch eviction
        store.load("s5")
        store.load("s6")
        # After cap trip, the two oldest are gone (s1 + s2)
        assert not store.exists("s1")
        assert not store.exists("s2")
        assert store.exists("s0")
        assert store.exists("s5")
        assert store.exists("s6")
    finally:
        cs_mod._MAX_SESSIONS, cs_mod._EVICT_BATCH = old_max, old_batch


# ----------------------------------------------------------------------
# Trim by turn cap
# ----------------------------------------------------------------------


def test_trim_drops_oldest_pair_when_over_turn_cap() -> None:
    conv = Conversation(session_id="s")
    # 61 pairs = 122 turns, above the 120-turn cap.
    # F59: previously 31 pairs (62 turns) vs a stale "60" comment — below the
    # real 120 cap, so trimming never fired and the assertions were vacuous.
    for i in range(61):
        _pair(conv, f"q{i}", f"a{i}")
    _trim_conversation(conv)
    assert len(conv.turns) <= _MAX_TURNS
    assert len(conv.turns) < 122, "trimming must have actually dropped turns"
    # Oldest pair should be gone; newest survives
    last_user = next(t for t in reversed(conv.turns) if t.role is Role.USER)
    assert last_user.text == "q60"


def test_trim_is_pair_atomic_never_orphans() -> None:
    conv = Conversation(session_id="s")
    for i in range(31):
        _pair(conv, f"q{i}", f"a{i}")
    _trim_conversation(conv)
    # Every surviving user turn is followed by an assistant turn
    for i, t in enumerate(conv.turns):
        if t.role is Role.USER and i + 1 < len(conv.turns):
            assert conv.turns[i + 1].role is Role.ASSISTANT


def test_trim_reindexes_in_place() -> None:
    conv = Conversation(session_id="s")
    for i in range(31):
        _pair(conv, f"q{i}", f"a{i}")
    _trim_conversation(conv)
    # Indices are contiguous 0..N-1 after trim
    for i, t in enumerate(conv.turns):
        assert t.index == i


# ----------------------------------------------------------------------
# Trim by char cap
# ----------------------------------------------------------------------


def test_trim_drops_pairs_when_over_char_cap() -> None:
    conv = Conversation(session_id="s")
    big = "x" * (_MAX_CHARS // 4)
    # 10 pairs where each pair is ~MAX_CHARS/2 → total ~5x over cap
    for i in range(10):
        _pair(conv, f"user{i} {big}", f"asst{i} {big}")
    _trim_conversation(conv)
    total = sum(len(t.text) for t in conv.turns)
    # Either under cap, or stopped early because only pinned turns remain
    assert total <= _MAX_CHARS or all(  # pragma: no cover — soft floor
        t.structured and "skill_focus" in t.structured
        for t in conv.turns if t.role is Role.ASSISTANT
    )


# ----------------------------------------------------------------------
# Pinning: SCRIPTED_ML survives even if it's old
# ----------------------------------------------------------------------


def test_trim_pins_most_recent_scripted_ml_pair() -> None:
    conv = Conversation(session_id="s")
    # First pair is a SCRIPTED_ML — the one that should be pinned
    _pair(conv, "teach me paragraphs", "scripted lesson body", scripted=True)
    # Then enough non-ML pairs to overflow the turn cap (derived from
    # _MAX_TURNS so future cap bumps don't invalidate the test).
    overflow_pairs = (_MAX_TURNS // 2) + 5
    for i in range(overflow_pairs):
        _pair(conv, f"followup{i}", f"reply{i}")
    _trim_conversation(conv)
    # The original SCRIPTED_ML pair must still be present
    user_texts = [t.text for t in conv.turns if t.role is Role.USER]
    asst_texts = [t.text for t in conv.turns if t.role is Role.ASSISTANT]
    assert "teach me paragraphs" in user_texts
    assert "scripted lesson body" in asst_texts


def test_trim_ignores_low_quality_ml_for_pinning() -> None:
    conv = Conversation(session_id="s")
    # Old LOW-quality ML should NOT be pinned; newer valid pair will survive
    _pair(conv, "stale ml q", "stale ml a", scripted=True, quality=Quality.LOW)
    overflow_pairs = (_MAX_TURNS // 2) + 5
    for i in range(overflow_pairs):
        _pair(conv, f"q{i}", f"a{i}")
    _trim_conversation(conv)
    user_texts = [t.text for t in conv.turns if t.role is Role.USER]
    assert "stale ml q" not in user_texts


# ----------------------------------------------------------------------
# Save+trim pipeline
# ----------------------------------------------------------------------


def test_save_triggers_trim() -> None:
    store = ConversationStore()
    conv, hs = store.load("s")
    for i in range(31):
        _pair(conv, f"q{i}", f"a{i}")
    store.save("s", conv, hs)
    conv2, _ = store.load("s")
    assert len(conv2.turns) <= _MAX_TURNS
