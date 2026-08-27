"""Verbatim-cluster seam trace (OFFLINE — no backend needed).

Phase-1 root-cause instrumentation for the recert `verbatim-vocab-mode-gate`
defect. BOTH recorded root-cause stories are unverified:

  * the ledger/backlog says QU tags the ask `specificity=broad` so
    `_decide_specific` is never reached — but `scripted_ml.py:304` passes
    `query_specificity="specific"` HARDCODED; QU's label never reaches it.
  * the Phase-4 adjudicator read `parsed_query.query_specificity == "broad"`
    off the API envelope and concluded the same thing — same mistake: that
    envelope field is QU's label, not the value the handler passes.

So this prints what each boundary ACTUALLY produces, per the project's own
lesson: a root-cause story is a hypothesis until probed.

Run:
  cd copilot-v4 && env -u OPENAI_API_KEY -u OPENAI_BASE_URL PYTHONPATH=. \
      python3 campaign/recert/probe_verbatim.py
"""
import asyncio

from config import settings
from api.dependencies import get_openai_client
from query.qu_v4 import understand
from schemas.turn import Conversation
from retrieval.ml_library import get_library
from retrieval.embedder import embed_query
from retrieval.library_precheck import (
    ASK_USER_CONFIDENCE_THRESHOLD,
    VERBATIM_CONFIDENCE_THRESHOLD,
    _mode_compatible,
    _vocab_overlap,
    library_precheck,
)

PROBES = [
    # (label, message) — scenarios 0/1 of the recert claim + a bare-title ask.
    ("s0 Inform (mode MATCHES the entry tag)",
     "Give me the Smekens scripted mini-lesson on adding interest with "
     "Snapple details for a 5th-grade informative piece."),
    ("s1 Persuasive (hostile — the observed ad-lib)",
     "Give me the 'Snapple details' scripted mini-lesson for my 5th-grade "
     "PERSUASIVE essay."),
    ("s2 bare named ask, no mode",
     "Give me the Snapple details mini-lesson for 5th grade."),
]


async def main() -> None:
    client = get_openai_client()
    library = get_library()
    print(f"library entries: {len(library.entries)}")

    # What does the library actually hold for this named lesson?
    print("\n=== library entries matching 'snapple' ===")
    for e in library.entries:
        if "snapple" in (e.skill_title or "").lower() or "snapple" in (e.ml_id or "").lower():
            print(f"  ml_id={e.ml_id!r}")
            print(f"  title={e.skill_title!r}")
            print(f"  writing_modes={e.writing_modes!r}  grades={e.grade_levels!r}")

    for label, msg in PROBES:
        print("\n" + "=" * 72)
        print(f"### {label}")
        print(f"MSG: {msg}")

        # --- Layer 1: QU -> intent -------------------------------------
        intent = await understand(
            Conversation(session_id="probe", turns=[]),
            msg,
            client=client,
            model=settings.openai_query_model,
        )
        skill_as_stated = intent.skill.as_stated if intent.skill else None
        print("\n-- Layer 1 QU --")
        print(f"  request_type      = {intent.request_type}")
        print(f"  grade             = {intent.grade.value if intent.grade else None!r}")
        print(f"  mode              = {intent.mode.value if intent.mode else None!r}")
        print(f"  skill.as_stated   = {skill_as_stated!r}")
        print(f"  query_specificity = {getattr(intent, 'query_specificity', '<absent>')!r}"
              "   <- QU's label (NOT what the handler passes)")
        print(f"  smekens_terms     = {getattr(intent, 'smekens_terms', '<absent>')!r}")

        # --- Layer 2: handler preconditions ----------------------------
        print("\n-- Layer 2 _try_library_verbatim preconditions --")
        blocked = library is None or intent.skill is None or intent.grade is None
        print(f"  library loaded={library is not None} skill={intent.skill is not None} "
              f"grade={intent.grade is not None} -> early-return None? {blocked}")
        if blocked:
            print("  !! verbatim path never runs for this probe")
            continue

        # --- Layer 3: embedding -> candidates --------------------------
        emb = await embed_query(msg)
        top5 = library.find_matches(emb, user_grade=intent.grade.value, top_k=5)
        print("\n-- Layer 3 library.find_matches (top 5) --")
        for m in top5:
            print(f"  conf={m.confidence:.4f} grade_ok={m.grade_compatible} "
                  f"modes={m.entry.writing_modes!r} title={m.entry.skill_title!r}")

        # --- Layer 4: the decision + the two gates ---------------------
        result = library_precheck(
            library=library,
            query_embedding=emb,
            user_grade=intent.grade.value,
            query_specificity="specific",  # exactly what scripted_ml.py:304 passes
            user_skill_phrase=skill_as_stated,
            user_writing_mode=intent.mode.value if intent.mode else None,
        )
        print("\n-- Layer 4 library_precheck --")
        print(f"  effective_specificity = {result.query_specificity!r}")
        print(f"  DECISION              = {result.decision}")

        in_grade = [m for m in top5 if m.grade_compatible]
        if in_grade:
            best = in_grade[0]
            vocab_ok = _vocab_overlap(skill_as_stated, best.entry.skill_title)
            mode_ok = _mode_compatible(
                intent.mode.value if intent.mode else None, best.entry.writing_modes
            )
            print(f"  best                  = {best.entry.skill_title!r} "
                  f"(conf={best.confidence:.4f})")
            print(f"  conf >= VERBATIM({VERBATIM_CONFIDENCE_THRESHOLD}) ? "
                  f"{best.confidence >= VERBATIM_CONFIDENCE_THRESHOLD}")
            print(f"  conf >= ASK_USER({ASK_USER_CONFIDENCE_THRESHOLD:.2f}) ? "
                  f"{best.confidence >= ASK_USER_CONFIDENCE_THRESHOLD}")
            print(f"  V1 vocab_ok           = {vocab_ok}")
            print(f"  V2 mode_ok            = {mode_ok}")
        else:
            print("  (no grade-compatible candidates)")


if __name__ == "__main__":
    asyncio.run(main())
