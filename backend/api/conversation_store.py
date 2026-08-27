"""In-memory Conversation + SessionHandshakes store.

Layer 1 persistence for the pilot. Redis-backed storage is a drop-in
replacement — the ConversationStore protocol is small by design so
swapping implementations doesn't touch the rest of the code.

Responsibilities:
  * Load-or-create Conversation by session_id.
  * Load-or-create SessionHandshakes by session_id.
  * Enforce the history-cap policy (§10 of QU-DRIVEN-DESIGN):
    - 120 turns OR 240k-char proxy (~60k tokens), whichever trips first
    - Evict oldest user/assistant pairs atomically (never orphan)
    - Pin the most recent VALID SCRIPTED_ML turn + the user turn that
      triggered it — DEEPEN_PRIOR must remain reliable even in long
      sessions.
  * LRU cap at the registry level so pilot workers don't leak memory
    when a teacher opens 100 tabs over the day.

No locks: FastAPI runs each request on a single event-loop thread and
the handlers' critical section (load → mutate → save) is synchronous
relative to the store. If we later move to a multi-worker deployment
with shared state, Redis provides the atomicity.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Optional

from schemas import (
    Conversation,
    Quality,
    Role,
    SessionHandshakes,
    Turn,
)


# Per-session history cap. Modern LLMs have 128k-token windows; we
# budget ~60k tokens (~240k chars at ~4 chars/token) for conversation
# context, leaving the remaining ~70k for the system prompt, retrieved
# chunks (~30k), repair feedback, and output. 120 turns keeps long
# Brady-style iterative sessions intact without ever making turn-count
# the tight constraint — char budget trips first on typical traffic.
_MAX_TURNS = 120
_MAX_CHARS = 240_000

# Registry-level caps. Single-worker pilot deployment; an LRU on
# session_id keeps the process from growing without bound when a
# classroom rolls through the frontend over the day.
_MAX_SESSIONS = 500
_EVICT_BATCH = 50


class ConversationStore:
    """In-memory store of Conversation + SessionHandshakes per session.

    Thread-/task-safety: mutation is only ever called from within a
    single FastAPI request handler, which runs on the event loop's
    thread. No concurrent mutation of a single session_id.
    """

    def __init__(self) -> None:
        self._conversations: dict[str, Conversation] = {}
        self._handshakes: dict[str, SessionHandshakes] = {}
        # OrderedDict: LRU ordering by insertion/touch timestamp.
        # Keys are session_ids; values are touch times for debugging
        # (the OrderedDict ordering is what drives eviction).
        self._touches: OrderedDict[str, float] = OrderedDict()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(
        self, session_id: str, user_id: Optional[str] = None
    ) -> tuple[Conversation, SessionHandshakes]:
        """Return (Conversation, SessionHandshakes), creating both if new."""
        self._touch(session_id)
        conv = self._conversations.get(session_id)
        if conv is None:
            conv = Conversation(session_id=session_id, user_id=user_id)
            self._conversations[session_id] = conv
        elif user_id and conv.user_id is None:
            conv.user_id = user_id

        hs = self._handshakes.get(session_id)
        if hs is None:
            hs = SessionHandshakes()
            self._handshakes[session_id] = hs

        return conv, hs

    def save(
        self,
        session_id: str,
        conversation: Conversation,
        handshakes: SessionHandshakes,
    ) -> None:
        """Persist updated conversation + handshakes, then trim history."""
        self._conversations[session_id] = conversation
        self._handshakes[session_id] = handshakes
        self._touch(session_id)
        _trim_conversation(conversation)

    def exists(self, session_id: str) -> bool:
        return session_id in self._conversations

    def clear(self, session_id: str) -> None:
        """Remove a single session. Used by tests."""
        self._conversations.pop(session_id, None)
        self._handshakes.pop(session_id, None)
        self._touches.pop(session_id, None)

    def reset(self) -> None:
        """Wipe the entire store. Used by tests."""
        self._conversations.clear()
        self._handshakes.clear()
        self._touches.clear()

    @property
    def session_count(self) -> int:
        return len(self._conversations)

    # ------------------------------------------------------------------
    # LRU registry management
    # ------------------------------------------------------------------

    def _touch(self, session_id: str) -> None:
        """Mark session as just-used; evict oldest if over cap."""
        if session_id in self._touches:
            self._touches.move_to_end(session_id)
        else:
            self._touches[session_id] = time.time()
        if len(self._touches) > _MAX_SESSIONS:
            self._evict_lru_batch()

    def _evict_lru_batch(self) -> None:
        """Drop the oldest _EVICT_BATCH sessions in one pass."""
        for _ in range(_EVICT_BATCH):
            if not self._touches:
                return
            sid, _ = self._touches.popitem(last=False)
            self._conversations.pop(sid, None)
            self._handshakes.pop(sid, None)


# ----------------------------------------------------------------------
# History trimming (§10)
# ----------------------------------------------------------------------


def _trim_conversation(conversation: Conversation) -> None:
    """Apply the history cap: trim oldest user/assistant PAIRS until
    we're under both the turn cap and char budget.

    Pinning: the most recent VALID SCRIPTED_ML assistant turn AND the
    user turn that triggered it are preserved even if the cap would
    otherwise drop them. The in-memory index stays monotonic — we
    REINDEX surviving turns starting at 0 to keep the invariant that
    ``turn.index == position`` (schemas.turn.Conversation.append
    enforces this).
    """
    pinned = _indices_to_pin(conversation)

    # Walk oldest-first; drop pairs that are neither pinned nor needed
    # to hit the cap. A "pair" is (user turn i, assistant turn i+1)
    # so we never orphan one side of a question.
    while _needs_trim(conversation):
        dropped = _drop_oldest_unpinned_pair(conversation, pinned)
        if not dropped:
            # Everything left is pinned — can't trim further without
            # breaking the guarantee. Bail out silently; the prompt
            # budget is only a soft limit.
            break

    _reindex_in_place(conversation)


def _needs_trim(conversation: Conversation) -> bool:
    if len(conversation.turns) > _MAX_TURNS:
        return True
    total_chars = sum(len(t.text) for t in conversation.turns)
    return total_chars > _MAX_CHARS


def _indices_to_pin(conversation: Conversation) -> set[int]:
    """The most recent VALID SCRIPTED_ML assistant turn + its preceding
    user turn. Returns the set of indices to preserve (in the CURRENT
    index space — callers use it before re-indexing)."""
    pinned: set[int] = set()
    for i in range(len(conversation.turns) - 1, -1, -1):
        t = conversation.turns[i]
        if (
            t.role is Role.ASSISTANT
            and t.quality is Quality.VALID
            and isinstance(t.structured, dict)
            and "skill_focus" in t.structured
        ):
            pinned.add(i)
            # Walk back to find the user turn that triggered it.
            for j in range(i - 1, -1, -1):
                if conversation.turns[j].role is Role.USER:
                    pinned.add(j)
                    break
            break
    return pinned


def _drop_oldest_unpinned_pair(
    conversation: Conversation, pinned: set[int]
) -> bool:
    """Find the oldest (user, assistant) pair that is NOT pinned and
    remove both turns from conversation.turns in place. Returns True
    if a pair was dropped."""
    turns = conversation.turns
    for i in range(len(turns) - 1):
        if i in pinned or (i + 1) in pinned:
            continue
        if turns[i].role is Role.USER and turns[i + 1].role is Role.ASSISTANT:
            # Drop both; shift the pinned indices left by 2 for any
            # index > i+1 (so pinning stays correct mid-trim).
            del turns[i : i + 2]
            _shift_pinned(pinned, after=i, by=-2)
            return True
    # No clean pair found — drop just the oldest turn if it's unpinned.
    if turns and 0 not in pinned:
        del turns[0]
        _shift_pinned(pinned, after=-1, by=-1)
        return True
    return False


def _shift_pinned(pinned: set[int], *, after: int, by: int) -> None:
    """Mutate `pinned` so indices strictly greater than `after` are
    shifted by `by` (negative for deletions)."""
    shifted = {(idx + by) if idx > after else idx for idx in pinned}
    pinned.clear()
    pinned.update(shifted)


def _reindex_in_place(conversation: Conversation) -> None:
    """After trimming, rewrite turn.index so 0..N-1 is contiguous.

    Turn is a frozen Pydantic model for some fields but index is
    mutable via validate_assignment. We reassign directly.
    """
    for i, t in enumerate(conversation.turns):
        if t.index != i:
            t.index = i


# ----------------------------------------------------------------------
# Module-level singleton (pilot)
# ----------------------------------------------------------------------


_store: Optional[ConversationStore] = None


def get_store() -> ConversationStore:
    """Process-wide ConversationStore. Lazy-initialized so tests that
    import this module without using HTTP don't create state."""
    global _store
    if _store is None:
        _store = ConversationStore()
    return _store


def reset_store() -> None:
    """Reset the module-level store. Tests only."""
    global _store
    _store = None


def convert_new_turn_to_append(
    conversation: Conversation, role: Role, text: str, **kwargs
) -> Turn:
    """Helper: build a Turn with the correct index for ``conversation`` and
    append it in-place. Returns the appended Turn."""
    turn = Turn(index=len(conversation.turns), role=role, text=text, **kwargs)
    conversation.append(turn)
    return turn
