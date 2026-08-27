"""Brady's e9 complaint — a management FOCUS persists across the follow-up.

feedback-docx.txt:127-140. He asked for a routines overview, praised it ("Good
overview"), then asked a follow-up and got writing SKILLS:

  "This is frustrating for the user for several reasons:
   Response listed skills that were not even mentioned in the overview!"

  "Ok, we have a big disconnect here. When 'routines, management, start up,
   writer's workshop, writer habits, expectations, procedures' are the focus,
   then Co-Pilot must pull from Sections 1-5 in the Launch books."

⚠️ The recert claim `e9-overview-self-consistency` tests something else — a
SKILLS overview followed by a skills follow-up, with all three scenarios on
PLAN_UNIT. Brady's complaint is a MANAGEMENT overview whose follow-up drifted
INTO skills. The claim's source cites feedback-7-july.md (our own analysis
doc), not the primary; the quote is real, its scope was not.

MEASURED LIVE (backend :8062, 4 runs): the follow-up routed to COACHING and
retrieved lww312-s6-ml1-define-trait / s8-ml04-details-vs-development /
s8-ml05-table-top-leg-sentences — Sections 6 and 8, 0/3 in Sections 1-5 — and
introduced skills absent from the overview in 3/4 runs.

"are the focus" is the operative phrase: a focus persists across a follow-up;
it is not re-established by each message. Naming a skill re-frames it.
"""
from handlers.coaching import _retrieval_focus
from schemas import (
    Conversation, GradeSpec, Quality, RequestType, Role, SkillSpec, Turn, TurnIntent,
)


def _convo(prior_type: RequestType) -> Conversation:
    return Conversation(session_id="s", user_id="u", turns=[
        Turn(index=0, role=Role.USER, text="How do I set up writing workshop routines?",
             intent=TurnIntent(request_type=prior_type,
                               grade=GradeSpec(value="3", stated_explicit=True))),
        Turn(index=1, role=Role.ASSISTANT, text="Here are your routines...",
             quality=Quality.VALID),
    ])


def _bare_followup() -> TurnIntent:
    return TurnIntent(request_type=RequestType.COACHING)


class TestManagementFocusPersists:
    def test_bare_followup_to_a_management_overview_keeps_management_focus(self):
        assert _retrieval_focus(_bare_followup(), _convo(RequestType.MANAGEMENT)) == "MANAGEMENT"

    def test_followup_to_a_skills_turn_is_unaffected(self):
        assert _retrieval_focus(_bare_followup(), _convo(RequestType.PLAN_UNIT)) == "COACHING_GENERAL"

    def test_naming_a_skill_reframes_away_from_management(self):
        """The teacher moved on — "what about topic sentences?" after a
        routines overview is a skills question and must retrieve as one."""
        intent = TurnIntent(
            request_type=RequestType.COACHING,
            skill=SkillSpec(canonical="topic sentences", as_stated="topic sentences"),
        )
        assert _retrieval_focus(intent, _convo(RequestType.MANAGEMENT)) == "COACHING_GENERAL"

    def test_a_first_turn_has_no_prior_focus(self):
        empty = Conversation(session_id="s", user_id="u", turns=[])
        assert _retrieval_focus(_bare_followup(), empty) == "COACHING_GENERAL"
