"""Brady Protected-Set — the canonical prompts that exercise must-not-break behaviors.

Imported by BOTH safety-net layers (see session-management/implementation-strategy.md §1):
  * the deterministic gate (tests/unit) — where an invariant can be checked offline;
  * the live golden-master (tests/acceptance) — for full end-to-end + semantic invariants.

Each case names the INVARIANTS that must hold for its response. The checkers live in
the test layers. EDITING THIS PACK CHANGES WHAT THE SAFETY NET PROTECTS — do so deliberately.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProtectedCase:
    id: str
    message: str
    query_type: str                    # expected QU classification (informational label)
    invariants: tuple[str, ...]        # keys into INVARIANT_KEYS
    prior_messages: tuple[str, ...] = ()  # optional same-session setup turns sent first


# The invariant vocabulary. Checkers are implemented in the test layers; this set is the
# contract the well-formedness test enforces (every case invariant must be listed here).
INVARIANT_KEYS: frozenset[str] = frozenset({
    "four_step",             # response is a structured 4-step MiniLesson
    "depth_2a2b",            # Steps 2A/2B carry the deep first-person think-aloud modeling
    "smekens_step3",         # Step 3 contains the exact Smekens interaction phrases
    "no_forbidden",          # no banned words (discuss/activity/PD/…) in teacher voice
    "ending_k2",             # K-2 lesson closes "Let's go be writers!"
    "ending_3_12",           # 3-12 lesson closes "Now it's your turn!" (Brady E1)
    "ending_how_to_teach",   # HOW_TO_TEACH ends with the scripted-ML offer
    "ending_plan_unit",      # PLAN_UNIT ends with its designated closing question
    "names_strategy_explained",  # a named Smekens strategy is explained in-context
    "grade_locks",           # grade carried from a prior turn, not re-asked
    "header_correct",        # Fm4: leading "Grade X[ | <Mode|Management>]" header is well-formed
    # --- citations ---------------------------------------------------------
    # Until these two, this pack was CITATION-BLIND: 11 keys, none of them about
    # the book or page a response points a teacher at. So every "golden
    # re-baselined, zero new regressions" claim made about citation work — the
    # Fm5 redesign, plan (1), plan (2) — was structurally unfailable on the one
    # dimension that work changed. A live gate that cannot fail on the thing
    # being changed is not a gate.
    "no_marker_survives",    # no raw "[[src:" marker is ever teacher-visible (EVERY case)
    "cites_own_grade_band",  # a Grade-3 answer must not cite the K-2 book (pages collide)
})


# `no_marker_survives` is on EVERY case — a raw marker is never acceptable
# anywhere, and the cases that pass no citation_resolver (PLAN_UNIT, MANAGEMENT,
# THINK_ALOUD) are exactly where an accidentally-wired resolver would show up.
#
# `cites_own_grade_band` is on every case whose ASK names a grade — 12 of 16.
# The other four (coaching_wont_start, management_routines, pizza_table_named,
# think_aloud_topic_sentences) state no grade, so their responses carry no Fm4
# header and there is nothing to band a citation against. That is a real, known
# hole and it is not theoretical: `pizza_table_named` cites the K-2 book today
# with no grade anywhere in the response, and nothing here can say whether that
# is right. Closing it needs a grade on the response, not a weaker invariant.
PROTECTED_SET: tuple[ProtectedCase, ...] = (
    ProtectedCase("ml_topic_sentences_g4",
        "Give me a 4th grade scripted mini-lesson on topic sentences",
        "SCRIPTED_ML", ("four_step", "depth_2a2b", "smekens_step3", "no_forbidden", "ending_3_12", "header_correct", "no_marker_survives", "cites_own_grade_band")),
    ProtectedCase("ml_narrative_leads_g2",
        "Scripted mini-lesson on narrative leads for 2nd grade",
        "SCRIPTED_ML", ("four_step", "depth_2a2b", "smekens_step3", "ending_k2", "no_forbidden", "header_correct", "no_marker_survives", "cites_own_grade_band")),
    ProtectedCase("ml_persuasive_g8",
        "8th grade scripted mini-lesson on persuasive writing",
        "SCRIPTED_ML", ("four_step", "depth_2a2b", "no_forbidden", "ending_3_12", "header_correct", "no_marker_survives", "cites_own_grade_band")),
    ProtectedCase("how_to_teach_paragraphing_g3",
        "How do I teach paragraphing to 3rd graders?",
        "HOW_TO_TEACH", ("ending_how_to_teach", "no_forbidden", "no_marker_survives", "cites_own_grade_band")),
    ProtectedCase("plan_unit_5th_persuasive",
        "Help me plan a 5th grade persuasive writing unit",
        "PLAN_UNIT", ("ending_plan_unit", "no_forbidden", "no_marker_survives", "cites_own_grade_band")),
    ProtectedCase("coaching_wont_start",
        "My students freeze and won't start writing. What do I do?",
        "COACHING", ("no_forbidden", "no_marker_survives")),
    ProtectedCase("management_routines",
        "How do I set up writing workshop routines?",
        "MANAGEMENT", ("no_forbidden", "no_marker_survives")),
    ProtectedCase("management_procedure_g3",
        "How do I set up a Help Desk routine for my 3rd grade writers?",
        "MANAGEMENT", ("no_forbidden", "header_correct", "no_marker_survives", "cites_own_grade_band")),
    ProtectedCase("launch_first_narrative_g9",
        "Teach narrative introductions for grade 9",
        "SCRIPTED_ML", ("four_step", "no_forbidden", "ending_3_12", "header_correct", "no_marker_survives", "cites_own_grade_band")),
    ProtectedCase("pizza_table_named",
        "Is there a pizza-table lesson?",
        "SCRIPTED_ML", ("names_strategy_explained", "no_marker_survives")),
    ProtectedCase("no_activity_word_g1",
        "Give me a 1st grade lesson on labeling pictures",
        "SCRIPTED_ML", ("four_step", "no_forbidden", "header_correct", "no_marker_survives", "cites_own_grade_band")),
    ProtectedCase("dissected_web_g6",
        "6th grade mini-lesson using the Dissected Web",
        "SCRIPTED_ML", ("four_step", "smekens_step3", "no_forbidden", "header_correct", "no_marker_survives", "cites_own_grade_band")),
    ProtectedCase("k2_ending_kinder",
        "Kindergarten scripted mini-lesson on adding details to drawings",
        "SCRIPTED_ML", ("four_step", "ending_k2", "no_forbidden", "header_correct", "no_marker_survives", "cites_own_grade_band")),
    ProtectedCase("session_lock_grade",
        "Now give me one on narrative leads",
        "SCRIPTED_ML", ("grade_locks", "four_step", "header_correct", "no_marker_survives", "cites_own_grade_band"),
        prior_messages=("Give me a 4th grade scripted mini-lesson on topic sentences",)),
    ProtectedCase("how_to_teach_sentence_variety_g7",
        "What's the best way to teach sentence variety in 7th grade?",
        "HOW_TO_TEACH", ("ending_how_to_teach", "no_forbidden", "no_marker_survives", "cites_own_grade_band")),
    ProtectedCase("think_aloud_topic_sentences",
        "Show me a think-aloud for teaching topic sentences",
        "THINK_ALOUD", ("depth_2a2b", "no_marker_survives")),
)
