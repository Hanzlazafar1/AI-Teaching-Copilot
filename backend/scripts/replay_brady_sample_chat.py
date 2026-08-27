"""Phase 13.2 — baseline replay of Brady's SAMPLE CHAT (BRADY-COMPLETION-PLAN §26.2).

Replays 7 conversational scenarios extracted from
``braddy-feedback-16april/shared-drive/Tier 1 Content/SAMPLE CHAT--
Smekens AI Writing Co-Pilot.docx`` against the v3 backend and scores each
response against Brady's specific margin criticisms (SC:NN references in
FEEDBACK-ISSUES.md).

Each scenario is a multi-turn chain; the criticisms target the CHAIN's
final response (or intermediate response where specified). Verdicts:

    PASS   — every Brady-specified criterion met
    PARTIAL — some criteria met, some missed (with diff)
    FAIL   — Brady's core criticism still present

Produces ``docs/brady-sample-chat-replay-baseline.md``. This is the
pre-Phase-14 baseline; a post-chunking re-run happens at Phase 15.3.
"""

from __future__ import annotations

import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
API_BASE = "http://127.0.0.1:8001"
TIMEOUT = 90


@dataclass
class Turn:
    user: str
    # Checks run against THIS turn's response only (if populated).
    checks: list["Check"] = field(default_factory=list)


@dataclass
class Check:
    """One verifiable criterion from Brady's annotation."""
    b_id: str
    description: str
    # predicate takes (response_text_lower, response_body, parsed_query) → bool.
    predicate: Any


@dataclass
class Scenario:
    name: str
    brady_context: str      # what Brady was testing + her annotated criticisms
    turns: list[Turn]


# ---------------------------------------------------------------------------
# Check predicates
# ---------------------------------------------------------------------------


def contains_all(text: str, phrases: list[str]) -> bool:
    t = text.lower()
    return all(p.lower() in t for p in phrases)


def contains_any(text: str, phrases: list[str]) -> bool:
    t = text.lower()
    return any(p.lower() in t for p in phrases)


def lacks_all(text: str, phrases: list[str]) -> bool:
    t = text.lower()
    return all(p.lower() not in t for p in phrases)


def mini_lesson_step_meets_ratio(body: dict, step: str, ref_step: str, multiplier: float) -> bool:
    ref = len((body.get(ref_step) or "").split())
    target = len((body.get(step) or "").split())
    return ref > 0 and target >= int(ref * multiplier)


# ---------------------------------------------------------------------------
# Scenario definitions — the 7 scenarios from SAMPLE CHAT
# ---------------------------------------------------------------------------


SCENARIOS: list[Scenario] = [
    # ---- A: paragraph-writing coaching → lesson request → skill → grade ----
    Scenario(
        name="A. Paragraph writing → scripted ML chain [B-G08/G09/G11/G12/P01/P02]",
        brady_context=(
            "Brady asks about paragraph writing (coaching), then requests a "
            "lesson, clarifies to 'topic sentence and supporting details' and "
            "'third grade'. Brady flagged on the generated lesson: SC:20 "
            "(skill vocab swap → B-G12), SC:29 (Step 3 should open 'Help me "
            "with the next') → B-G08, SC:30 ('never use discuss') → B-P01, "
            "SC:33-35 (turn-and-talk / back-to-me / this-is-some-of-what) → "
            "B-G09, SC:34 ('I'll listen in' banned) → B-G11."
        ),
        turns=[
            Turn(user="How do I teach paragraph writing to 3rd graders?"),
            Turn(user="Can you put this in a lesson for me to deliver to my students?"),
            Turn(user="Topic sentence and supporting details"),
            Turn(
                user="Third",
                checks=[
                    Check(
                        b_id="B-G12",
                        description="skill_focus preserves 'topic sentence' vocabulary",
                        predicate=lambda t, b, _: isinstance(b, dict)
                            and "topic sentence" in (b.get("skill_focus") or "").lower(),
                    ),
                    Check(
                        b_id="B-G08",
                        description="Step 3 contains 'help me with the next'",
                        predicate=lambda t, b, _: isinstance(b, dict)
                            and "help me with the next" in (b.get("step_3_interact") or "").lower(),
                    ),
                    Check(
                        b_id="B-G09",
                        description="Step 3 contains 'turn and talk' + 'back to me' + 'this is some of what'",
                        predicate=lambda t, b, _: isinstance(b, dict) and contains_all(
                            (b.get("step_3_interact") or "").lower(),
                            ["turn and talk", "back to me", "this is some of what"],
                        ),
                    ),
                    Check(
                        b_id="B-G11",
                        description="no 'I'll listen in'",
                        predicate=lambda t, b, _: "i'll listen in" not in t and "i’ll listen in" not in t,
                    ),
                    Check(
                        b_id="B-P01",
                        description="no 'discuss'",
                        predicate=lambda t, b, _: not re.search(r"\bdiscuss\b", t),
                    ),
                ],
            ),
        ],
    ),

    # ---- B: transitions rewrite → must use Smekens trigger ----
    Scenario(
        name="B. Transitions rewrite [B-G06 trigger usage]",
        brady_context=(
            "Brady asks for a scripted think-aloud on transitions. Flagged "
            "SC:68: the original used 'bridges' analogy, which is NOT Smekens. "
            "The Launch book uses road-sign/merge or colored-yarn triggers. "
            "Response must surface one of those."
        ),
        turns=[
            Turn(
                user="Give me a scripted mini-lesson on using transitions for 5th graders",
                checks=[
                    Check(
                        b_id="B-G06",
                        description="response uses a Smekens transition trigger (road-sign / colored-yarn / merge)",
                        predicate=lambda t, b, _: contains_any(
                            t,
                            ["road sign", "road-sign", "colored yarn", "colored-yarn", "merge"],
                        ),
                    ),
                ],
            ),
        ],
    ),

    # ---- C: pizza-table → organizer? → what page? ----
    Scenario(
        name="C. Pizza-table recall chain [B-S03 session memory + B-P05 book/page citation]",
        brady_context=(
            "Brady asks about pizza-table lesson, then 'where can I get that "
            "organizer?', then 'What page?'. Flagged in v1: system forgot its "
            "own output (asked 'what graphic organizer?'). After fix: organizer "
            "reference should carry forward; page citation should appear."
        ),
        turns=[
            Turn(user="Is there a lesson with a pizza table?"),
            Turn(
                user="Where can I get that graphic organizer?",
                checks=[
                    Check(
                        b_id="B-S03",
                        description="response does NOT ask 'what organizer' (Brady's explicit criticism)",
                        predicate=lambda t, b, _: "what organizer" not in t and "what specific graphic" not in t,
                    ),
                    Check(
                        b_id="B-P05",
                        description="response mentions digital resources or a page",
                        predicate=lambda t, b, _: "digital resource" in t or bool(re.search(r"page\s*\d+", t)),
                    ),
                ],
            ),
            Turn(
                user="What page?",
                checks=[
                    Check(
                        b_id="B-P05",
                        description="numeric page reference present",
                        predicate=lambda t, b, _: bool(re.search(r"page\s*\d+", t)),
                    ),
                ],
            ),
        ],
    ),

    # ---- D: think-aloud → put into full ML ----
    Scenario(
        name="D. Think-aloud → ML format repurpose [B-S04]",
        brady_context=(
            "Brady produces a think-aloud about 'My mom is having surgery / "
            "She is very anxious'. Then asks the system to put that think-"
            "aloud into a 4-step ML for grade 4. Flagged SC:130: v1 changed "
            "the example entirely. Fix: Step 2B should reuse the think-aloud."
        ),
        turns=[
            Turn(
                user=(
                    "Provide a scripted think-aloud to determine the "
                    "transition between these two sentences: "
                    "'My mom is having surgery' and 'She is very anxious'"
                ),
            ),
            Turn(
                user="Insert this entire think-aloud into a new mini-lesson script for step 2B. Add steps 1, 2A, 3, and 4 for grade 4.",
                checks=[
                    Check(
                        b_id="B-S04",
                        description="Step 2B references the surgery/anxious example (not a new one)",
                        predicate=lambda t, b, _: isinstance(b, dict) and contains_any(
                            (b.get("step_2b_show") or "").lower(),
                            ["surgery", "anxious"],
                        ),
                    ),
                ],
            ),
        ],
    ),

    # ---- E: persuasive unit plan → is this a mini-unit? ----
    Scenario(
        name="E. Persuasive unit plan [B-G13/G14 unit structure]",
        brady_context=(
            "Brady asks for a persuasive unit plan. Flagged SC:145: 'Each "
            "skill is getting a single day. Too much for 1 lesson.' SC:181: "
            "'NOT a mini unit as it teaches ALL the skills in 1 unit.' "
            "Known limitation — full unit-structure depth is in §25 deferred."
        ),
        turns=[
            Turn(
                user="Give me a persuasive writing unit plan, please",
                checks=[
                    Check(
                        b_id="B-R05",
                        description="response surfaces multiple skills/lessons (list shape)",
                        predicate=lambda t, b, _: bool(re.search(r"\n\s*\d+\.", t)) or "skill" in t,
                    ),
                ],
            ),
        ],
    ),

    # ---- F: list of report skills → lesson on this → grade ----
    Scenario(
        name="F. Report-skills list → pickup → grade [B-S05 + B-F03]",
        brady_context=(
            "Brady asks 'do you have any lessons on skills for teaching report "
            "writing', gets a list, asks 'provide me a lesson to teach on this', "
            "provides grade. Flagged SC:202: generated lesson must map to the "
            "earlier list, not invent a new skill. SC:200: system should "
            "confirm 'So you want this skill, for this grade, in a 4-step ML?'"
        ),
        turns=[
            Turn(user="Do you have any lessons on skills for teaching report writing?"),
            Turn(user="Please provide me a lesson to teach on this"),
            Turn(
                user="6",
                checks=[
                    # Either we got a lesson on a report skill, OR a confirmation prompt fired
                    Check(
                        b_id="B-S05",
                        description="response is report-skill-adjacent OR confirms scripted-ML intent",
                        predicate=lambda t, b, _: (
                            isinstance(b, dict)
                            and contains_any(
                                (b.get("skill_focus") or "").lower(),
                                ["fact", "detail", "report", "topic", "organize", "conclusion", "introduction"],
                            )
                        ) or (
                            "correct?" in t or "so you want" in t or "verbatim" in t
                        ),
                    ),
                ],
            ),
        ],
    ),

    # ---- G: K-2 drawing details → "don't have book" → scripted lesson ----
    Scenario(
        name="G. K-2 drawing details → scripted-ML pickup [B-R02 / B-S04 skill fidelity]",
        brady_context=(
            "Fresh session. Brady asks 'how do I get students to add details "
            "to pictures', then refines to 'magnify close-up details' lesson, "
            "then asks for a scripted lesson. Flagged SC:244: 'magnify close-"
            "up details' is ALREADY scripted in Launch K-2 (Mini-Lesson #9) "
            "and should be returned verbatim, not a different skill."
        ),
        turns=[
            Turn(user="How do I get my students to add details to the pictures for K-2?"),
            Turn(
                user="I don't have that book. But can you tell me more about the magnify close up details lesson?",
                checks=[
                    Check(
                        b_id="B-R02",
                        description="response is focused on magnify / close-up details",
                        predicate=lambda t, b, _: contains_any(
                            t,
                            ["magnify", "close-up", "close up details"],
                        ),
                    ),
                ],
            ),
            Turn(
                user="Can you give me a scripted lesson for this",
                checks=[
                    Check(
                        b_id="B-S04",
                        description="generated lesson's skill_focus is about magnify / close-up / details (not an unrelated skill)",
                        predicate=lambda t, b, _: (
                            isinstance(b, dict)
                            and contains_any(
                                (b.get("skill_focus") or "").lower(),
                                ["magnify", "close-up", "close up", "detail"],
                            )
                        ) or contains_any(t, ["magnify", "close-up", "close up details"]),
                    ),
                ],
            ),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Replay + scoring
# ---------------------------------------------------------------------------


@dataclass
class TurnResult:
    user: str
    response_text: str
    is_lesson: bool
    elapsed: float
    check_results: list[tuple[Check, bool]] = field(default_factory=list)


@dataclass
class ScenarioResult:
    scenario: Scenario
    turn_results: list[TurnResult]

    @property
    def total_checks(self) -> int:
        return sum(len(tr.check_results) for tr in self.turn_results)

    @property
    def passed_checks(self) -> int:
        return sum(sum(1 for _, ok in tr.check_results if ok) for tr in self.turn_results)

    @property
    def verdict(self) -> str:
        if self.total_checks == 0:
            return "N/A"
        if self.passed_checks == self.total_checks:
            return "PASS"
        if self.passed_checks == 0:
            return "FAIL"
        return "PARTIAL"


def _send(session_id: str, user: str) -> dict:
    t0 = time.time()
    r = requests.post(
        f"{API_BASE}/api/chat",
        json={"message": user, "session_id": session_id, "user_id": "replay"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    payload = r.json()
    payload["_elapsed"] = time.time() - t0
    return payload


def _run_scenario(scenario: Scenario) -> ScenarioResult:
    session_id = f"replay-{uuid.uuid4()}"
    turn_results: list[TurnResult] = []
    for turn in scenario.turns:
        resp = _send(session_id, turn.user)
        body = resp.get("response")
        text = body if isinstance(body, str) else ""
        if isinstance(body, dict):
            # MiniLesson — flatten to text for lower-case checks
            text = " ".join(str(v) for v in body.values() if isinstance(v, str))
        parsed = resp.get("parsed_query") or {}
        t_lower = text.lower()
        results: list[tuple[Check, bool]] = []
        for check in turn.checks:
            try:
                ok = bool(check.predicate(t_lower, body, parsed))
            except Exception:
                ok = False
            results.append((check, ok))
        turn_results.append(TurnResult(
            user=turn.user,
            response_text=text,
            is_lesson=isinstance(body, dict) and "step_2b_show" in body,
            elapsed=resp["_elapsed"],
            check_results=results,
        ))
    return ScenarioResult(scenario=scenario, turn_results=turn_results)


def _render_report(results: list[ScenarioResult]) -> str:
    lines = [
        "# Brady Sample-Chat Replay — Baseline (Phase 13.2)",
        "",
        f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S UTC')}  ",
        f"**Backend**: {API_BASE}  ",
        "**Scope**: 7 scenarios extracted from `SAMPLE CHAT-- Smekens AI "
        "Writing Co-Pilot.docx`. Each scenario replays the full turn chain "
        "and scores the final-turn response against Brady's annotated "
        "criticisms. This is the PRE-Phase-14 baseline; a final pass runs "
        "at Phase 15.3 after the 14 new docs are chunked.",
        "",
        "## Summary",
        "",
        "| Scenario | Turns | Checks | Verdict |",
        "|---|---:|---:|---|",
    ]
    total_checks = 0
    total_passed = 0
    for res in results:
        total_checks += res.total_checks
        total_passed += res.passed_checks
        lines.append(
            f"| {res.scenario.name} | {len(res.turn_results)} | "
            f"{res.passed_checks}/{res.total_checks} | **{res.verdict}** |"
        )
    overall_pct = (100 * total_passed / total_checks) if total_checks else 0
    lines.append(
        f"| **Overall** | {sum(len(r.turn_results) for r in results)} | "
        f"**{total_passed}/{total_checks}** ({overall_pct:.0f}%) | |"
    )
    lines.append("")
    lines.append(
        f"**§26.2 target: ≥90% alignment.** Baseline (pre-chunking) result: "
        f"**{overall_pct:.0f}%** across {total_checks} criteria. "
        f"Items blocked by B-C01 (missing content) expected to flip at Phase 15.3."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Per-scenario detail")
    for res in results:
        lines.append("")
        lines.append(f"### {res.scenario.name}")
        lines.append("")
        lines.append(f"**Brady's context**: {res.scenario.brady_context}")
        lines.append("")
        for i, tr in enumerate(res.turn_results, 1):
            lines.append(f"**Turn {i}** ({tr.elapsed:.1f}s) — `{tr.user}`")
            if tr.is_lesson:
                lines.append(f"  - Response: MiniLesson ({len(tr.response_text)} chars)")
            else:
                preview = tr.response_text[:160].replace("\n", " ")
                lines.append(f"  - Response: {preview!r}…")
            for check, ok in tr.check_results:
                mark = "✅" if ok else "❌"
                lines.append(f"  - {mark} **{check.b_id}** — {check.description}")
            lines.append("")
        lines.append(f"**Scenario verdict: {res.verdict} "
                     f"({res.passed_checks}/{res.total_checks})**")
        lines.append("")
        lines.append("---")
    return "\n".join(lines)


def main() -> int:
    # Health check first
    try:
        h = requests.get(f"{API_BASE}/health/live", timeout=5)
        h.raise_for_status()
    except Exception as exc:
        print(f"Backend not reachable at {API_BASE}: {exc}")
        return 1

    print(f"Running {len(SCENARIOS)} scenarios "
          f"({sum(len(s.turns) for s in SCENARIOS)} turns total)...")
    results: list[ScenarioResult] = []
    for scenario in SCENARIOS:
        print(f"  {scenario.name}")
        try:
            results.append(_run_scenario(scenario))
        except Exception as exc:
            print(f"    ERROR: {exc}")
            continue

    report = _render_report(results)
    out = ROOT / "docs" / "brady-sample-chat-replay-baseline.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(f"Wrote {out.relative_to(ROOT)} ({out.stat().st_size} bytes)")

    # Summary for stdout
    total = sum(r.total_checks for r in results)
    passed = sum(r.passed_checks for r in results)
    pct = 100 * passed / total if total else 0
    print(f"\nOverall: {passed}/{total} ({pct:.0f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
