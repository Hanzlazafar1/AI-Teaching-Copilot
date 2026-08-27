"""u3 root-cause probe — does QU ever put "mode" in missing_required for PLAN_UNIT?

WHAT THIS MEASURES (read before citing it):
  The OFFLINE QU call only — understand() -> TurnIntent.missing_required.
  It does NOT measure the teacher-visible reply. It isolates exactly one
  hypothesis: the Phase-4 adjudicator INFERRED "gpt-5.4-mini never emits mode"
  by READING the qu_v4_prompt hedge ("rare"), and never measured it. The whole
  clarify chain downstream (handlers/__init__.py _MODE_REQUIRED={PLAN_UNIT},
  clarify.py PLAN_UNIT -> PLAN_UNIT_MODE_Q) is already wired and fires IFF
  "mode" lands in missing_required. So this field is the hinge.

Case 3 is the decisive one: grade STATED, mode absent. If QU omits "mode" even
there, the hedge is the cause. If QU emits it, the recorded root cause is FALSE
and the defect lives somewhere else.
"""
import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from config import settings  # noqa: E402
from api.dependencies import get_openai_client  # noqa: E402
from query.qu_v4 import understand  # noqa: E402
from schemas import Conversation, Role, Turn  # noqa: E402

N = 5
CASES = [
    ("0 drive-scenario-0 (no grade, no mode)", "I want to plan a writing unit for my class."),
    ("3 hostile drive-scenario-3", "Just build me a unit plan — whatever grade and writing type you think is best."),
    ("D DECISIVE: grade stated, mode absent", "I want to plan a writing unit for my 5th graders."),
    ("C CONTROL: grade + mode both stated", "I want to plan a persuasive writing unit for my 5th graders."),
]


async def main():
    client = get_openai_client()
    model = settings.openai_query_model
    print(f"QU model = {model}\n")
    for label, msg in CASES:
        rts, missings, modes = Counter(), Counter(), Counter()
        for _ in range(N):
            intent = await understand(
                Conversation(session_id="u3probe", turns=[]),
                msg,
                client=client,
                model=model,
            )
            rts[str(getattr(intent.request_type, "value", intent.request_type))] += 1
            missings[tuple(sorted(intent.missing_required or []))] += 1
            # NB: TurnIntent has NO `writing_mode` field (that name exists only
            # in the API's parsed_query projection). The real field is `mode`
            # (ModeSpec). Reading the wrong name is how a probe silently
            # measures nothing — record BOTH specs' concrete values.
            modes[(
                intent.mode.value if intent.mode else None,
                intent.grade.value if intent.grade else None,
            )] += 1
        print(f"--- {label}")
        print(f"    msg              : {msg!r}")
        print(f"    request_type     : {dict(rts)}")
        print(f"    missing_required : {dict(missings)}")
        print(f"    (mode, grade)    : {dict(modes)}")
        emits_mode = sum(v for k, v in missings.items() if "mode" in k)
        print(f"    ==> emits 'mode' : {emits_mode}/{N}\n")

    # ---- THE DECISIVE ONE -------------------------------------------------
    # The drive's 4/4 "never asks mode" evidence only ever measured TURN 0.
    # QU reports one gap at a time (grade first). So the real question is
    # whether mode is asked on the NEXT turn, once the teacher supplies grade.
    # If yes, the app satisfies Brady over two turns and the "defect" is a
    # turn-0-only artifact. This replays the real clarify flow.
    print("=" * 66)
    print("MULTI-TURN: does 'mode' surface AFTER the teacher answers grade?")
    print("=" * 66)
    missings2 = Counter()
    for _ in range(N):
        convo = Conversation(session_id="u3probe-mt", turns=[])
        convo.append(Turn(index=0, role=Role.USER, text="I want to plan a writing unit for my class."))
        convo.append(Turn(
            index=1, role=Role.ASSISTANT,
            text="Which grade level are you teaching? That will help me give you the most relevant guidance.",
        ))
        intent = await understand(convo, "5th grade", client=client, model=model)
        missings2[(
            str(getattr(intent.request_type, "value", intent.request_type)),
            tuple(sorted(intent.missing_required or [])),
        )] += 1
    print(f"    T2 '5th grade' -> (request_type, missing_required): {dict(missings2)}")
    emits = sum(v for (_, mk), v in missings2.items() if "mode" in mk)
    print(f"    ==> emits 'mode' on turn 2 : {emits}/{N}")


asyncio.run(main())
