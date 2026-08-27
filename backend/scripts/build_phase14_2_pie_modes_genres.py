"""Build Phase 14.2 chunks — PIE scope/sequence + Modes/Genres/Formats.

Produces two chunk files:
  * chunks/38-pie-scope-sequence.json — 9 chunks, one per grade-band × mode
    cell of "00. Essential Skills K-12 PIE bw.pdf". These chunks define
    the authoritative ``pie_tags_by_band`` for the pipeline.
  * chunks/39-writing-modes-genres.json — 5 chunks covering the three
    writing-purpose definitions, per-mode genre lists, and the
    mode-flexible format taxonomy from "Writing Modes, Genres, & Formats.pdf".

No MLs, no library promotion, no HyDE authoring — these are reference
content for retrieval only. All chunks carry ``is_scripted_lesson=False``
and ``content_type`` values that route them away from the SCRIPTED_ML
template (they surface in COACHING_GENERAL / PLAN_UNIT / HOW_TO_TEACH
responses).

Usage:
    python3 scripts/build_phase14_2_pie_modes_genres.py            # write
    python3 scripts/build_phase14_2_pie_modes_genres.py --dry-run  # inspect
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHUNKS_DIR = ROOT / "chunks"

PIE_PDF = "00. Essential Skills K-12 PIE bw.pdf"
MG_PDF = "Writing Modes, Genres, & Formats.pdf"

_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


def slugify(text: str) -> str:
    return "-".join(_WORD_RE.findall(text.lower()))


def topic_keywords(content: str, title: str, top_k: int = 20) -> list[str]:
    stop = {
        "the","and","a","an","of","to","for","in","on","at","is","it","this","that",
        "with","as","by","or","be","are","was","were","you","your","we","our","i",
        "their","this","these","those","not","no","yes","but","so","do","does","did",
        "about","into","out","up","down","will","can","could","should","would",
        "what","how","why","when","where","all","any","some","more","most","like",
        "one","two","three","from","have","has","had","also","after","before","over",
        "under","just","than","there","here","too","only","own","very","each","now",
        "students","write","writing","writer","writers","lesson","grade","skill","skills",
    }
    seen: dict[str, int] = {}
    for tok in (title + " " + content).lower().split():
        for w in _WORD_RE.findall(tok):
            if len(w) < 4 or w in stop:
                continue
            seen.setdefault(w, len(seen))
            if len(seen) >= top_k:
                break
        if len(seen) >= top_k:
            break
    return [w for w, _ in sorted(seen.items(), key=lambda kv: kv[1])]


# ---------------------------------------------------------------------------
# PIE scope-and-sequence chunks (9)
# ---------------------------------------------------------------------------

PIE_PERSUASIVE_K5 = """\
Persuasive Writing Skills — Grades K-5 (Smekens scope & sequence)

This is the suggested sequence of persuasive-writing skills to teach across
grade-level mini-units. Skills marked with * are implicitly required but not
directly stated in grade-level writing standards.

KINDERGARTEN (4 skills):
1. Recognize opinionated/debatable topics.
2. Choose the strongest side.
3. State an opinion or preference (beginning).
4. Give a detail to support an opinion about a topic or text (middle).

GRADE 1 (6 skills):
1. Recognize opinionated/debatable topics.
2. Choose the strongest side.
3. State opinion / Make a proposal (beginning).
4. Give details to support an opinion about a topic (middle).
5. Persuade a particular audience (e.g., a parent, a peer, the principal).
6. Give details to support a proposal (recommendation) about a text (middle).

GRADE 2 (8 skills):
1. Recognize opinionated/debatable topics.
2. Choose the strongest side.
3. Introduce an opinion (beginning).
4. Generate reasons to support an opinion about a topic (middle).
5. Connect opinion & reasons with linking words (e.g., first, second).
6. Include details for each reason.
7. Repeat the opinion within a concluding statement.
8. Generate reasons to support an opinion about a text (middle).

GRADE 3 (11 skills):
1. Recognize opinionated/debatable topics.
2. Determine the strongest side.
3. State an opinion (beginning).
4. Generate reasons to support an opinion about a topic.
5. Support reasons with facts & details about a topic.
6. Generate reasons to support an opinion about a text.
7. Support reasons with facts & details from various sources.
8. Connect reasons to the opinion with transition words & phrases.
9. Provide a concluding statement that restates the opinion.
10. Organize reasons for impact (i.e., save the best for last).
11. Provide an introductory paragraph about the debatable topic or text (include the opinion).

GRADE 4 (12 skills):
1. Recognize opinionated/debatable topics.
2. Determine the strongest side.
3. State an opinion to a particular audience (beginning).
4. Generate reasons to support an opinion about the topic.
5. Support reasons with facts & details about a topic.
6. Generate reasons to support an opinion about a text.
7. Support reasons with facts & details from various sources.
8. Connect reasons to the opinion with transition words & phrases.
9. Provide a concluding statement that restates the opinion.
10. Organize reasons for impact (i.e., save the best for last).
11. Provide an introductory paragraph about the debatable topic or text (include the opinion).
12. Provide a concluding paragraph (including a restatement of the opinion).

GRADE 5 (12 skills):
1. Recognize opinionated/debatable topics.
2. Determine the strongest side.
3. State an opinion/position to an identified audience (beginning).
4. Generate reasons to support an opinion/position about a topic.
5. Support reasons with facts & details about a topic.
6. Connect reasons to the opinion with transition words, phrases, & clauses.
7. Provide a concluding statement that restates the opinion.
8. Support reasons with quantitative (quotations & statistics) and qualitative (anecdotes & examples) details from various sources.
9. Provide an introductory paragraph about a topic or text (including the opinion).
10. Use language appropriate for the identified audience.
11. Organize reasons for impact (i.e., save the best for last).
12. Provide a concluding paragraph (including a restatement of the opinion).

Teachers: use this sequence to plan persuasive mini-units for elementary
grades. The list grows with grade level — K-2 focus on opinion + one or two
reasons; 3-5 add transitions, sourced evidence, and introduction/conclusion
paragraphs.
"""

PIE_ARGUMENTATIVE_6_8 = """\
Argumentative Writing Skills — Grades 6-8 (Smekens scope & sequence)

Grade 6 through Grade 8 transition persuasive into argumentative writing:
claims instead of opinions, counterclaims, evidence from multiple sources,
and formal tone. Skills marked with * are implicitly required.

GRADE 6 (14 skills):
1. Recognize different perspectives of debatable topics.
2. Align with the strongest side.
3. State a claim about a topic or text (introduction).
4. Support a claim with clear reasons.
5. Support reasons with relevant evidence.
6. Use transitions to clarify the relationships among claim(s) and reasons.
7. Provide a concluding statement.
8. Support reasons by explaining the significance of the evidence to the claim.
9. Support reasons with credible evidence.
10. Support reasons with evidence from more than 1 source.
11. Provide an introductory paragraph about the debatable topic or text (including the claim).
12. Provide a concluding paragraph/section (including a restatement of the claim).
13. Maintain a formal style and tone appropriate to the audience.
14. Use precise language for the topic/content.

GRADE 7 (16 skills):
1. Recognize different perspectives of debatable topics.
2. Align with the strongest side.
3. State a claim about a topic or text (introduction).
4. Support a claim with logical reasons.
5. Support reasons with relevant evidence.
6. Use transitions to create cohesion between claim(s) & reasons.
7. Provide a concluding statement.
8. Support reasons by explaining the significance of the evidence to the claim.
9. Support reasons with accurate & credible evidence.
10. Support reasons with evidence from more than 1 source.
11. Introduce the claim and alternate or opposing claims.
12. Develop 1 reason for the opposition within the body.
13. Provide a concluding paragraph (including a restatement of the claim).
14. Use transitions to clarify the relationships between reasons & evidence.
15. Maintain a formal style and tone appropriate to the audience.
16. Use precise language for the topic/content.

GRADE 8 (16 skills):
1. Recognize different perspectives of debatable topics.
2. Align with the strongest side.
3. State a claim about a topic or text (introduction).
4. Support a claim with logical reasons.
5. Support reasons with relevant evidence.
6. Use transitions to create cohesion between claim(s) & reasons.
7. Provide a concluding statement.
8. Support reasons by explaining the significance of the evidence to the claim.
9. Support reasons with accurate & credible evidence.
10. Support reasons with evidence from more than 1 source.
11. Distinguish between the claim and counterclaim in the introduction.
12. Develop 1 reason for the opposition within the body.
13. Use effective transitions to clarify the relationships among claim(s) & counterclaims.
14. Provide a concluding paragraph (including a restatement of the claim).
15. Maintain a formal style and tone appropriate to the audience.
16. Use precise language for the topic/content.

The core progression 6→7→8: grade 6 introduces claim/reasons/evidence with
formal tone; grade 7 adds opposing-claim awareness; grade 8 formalizes the
distinction between claim and counterclaim with cohesion transitions.
"""

PIE_ARGUMENTATIVE_9_12 = """\
Argumentative Writing Skills — Grades 9-12 (Smekens scope & sequence)

High-school argumentative writing adds rhetorical strategies (ethos, logos,
pathos), counterclaim weaving, and acknowledging limitations/biases. Skills
marked with * are implicitly required.

GRADES 9-10 (13 skills):
1. Recognize different perspectives of debatable topics & align with the strongest side.
2. State a claim about a topic or text (introduction).
3. Support a claim with logical reasons.
4. Provide a concluding statement.
5. Support reasons with accurate & credible evidence from multiple sources.
6. Support reasons by explaining the significance of the evidence to the claim.
7. Use transitions to clarify the relationships between reasons & evidence.
8. Distinguish between the claim & counterclaim within the introduction.
9. Develop reasons for the opposition.
10. Utilize rhetorical strategies to appeal to the audience (ethos, logos, pathos).
11. Provide a concluding paragraph that restates the debate & reminds the reader what's at stake.
12. Weave the counterclaim throughout the body paragraphs, effectively transitioning between the claim(s) & counterclaims.
13. Identify limitations & make concessions for both/all perspectives addressed.

GRADES 11-12 (13 skills):
1. Recognize different perspectives of debatable topics & align with the strongest side.
2. State a claim about a topic or text (introduction).
3. Support a claim with logical reasons.
4. Provide a concluding statement.
5. Support reasons with accurate & credible evidence from multiple sources.
6. Support reasons by explaining the significance of the evidence to the claim.
7. Use transitions to clarify the relationships between reasons & evidence.
8. Establish the significance of the debate (naming the claim & counterclaim) within the introduction.
9. Develop reasons for the opposition.
10. Utilize rhetorical strategies to appeal to the audience (ethos, logos, pathos).
11. Provide a concluding paragraph that restates the debate & reminds the reader what's at stake.
12. Weave the counterclaim throughout the body paragraphs, effectively transitioning between the claim(s) & counterclaims.
13. Identify limitations, make concessions, and address biases for both/all perspectives addressed.

Differences 9-10 → 11-12 are subtle: 11-12 escalates "distinguish" to
"establish the significance" in the introduction, and adds "address biases"
to the concession/limitation skill.
"""

PIE_INFORMATIVE_K5 = """\
Informative Writing Skills — Grades K-5 (Smekens scope & sequence)

Suggested sequence of informative writing skills across K-5 mini-units.
Skills marked with * are implicitly required.

KINDERGARTEN (5 skills):
1. Use words & pictures to list facts about a topic or text.
2. Use words & pictures to list details about a topic or text.
3. Group facts & details to fit the organization of the genre.
4. Develop the topic or text.
5. Introduce the topic or text.

GRADE 1 (6 skills):
1. List facts about a topic or text.
2. List details about a topic or text.
3. Group facts & details to fit the organization of the genre.
4. Develop the topic.
5. Introduce the topic or text.
6. Restate the topic in a concluding statement.

GRADE 2 (6 skills):
1. List facts about a topic or text.
2. List details about a topic or text.
3. Group facts & details to fit the organization of the genre.
4. Develop the topic.
5. Introduce the topic or text.
6. Restate the topic in a concluding statement.

GRADE 3 (9 skills):
1. List facts & details about a topic or text.
2. Group related information to fit the organization of the genre.
3. Create a paragraph around each idea.
4. Develop the topic.
5. Introduce the topic or text.
6. Restate the topic or main idea in a concluding statement.
7. Provide an introductory paragraph.
8. Connect ideas across paragraphs with transitions.
9. Provide an introductory paragraph.

GRADE 4 (13 skills):
1. List facts & details about a topic or text.
2. Group related information to fit the organization of the genre.
3. Create a paragraph around each idea.
4. Connect ideas across paragraphs with transitions.
5. Introduce the topic or the text.
6. Restate the topic or main idea in a concluding statement.
7. Develop ideas with specific details, examples, vocabulary, & quotes pulled from sources.
8. Explain facts, details, & quotes.
9. Provide an introductory paragraph.
10. Provide a concluding paragraph.
11. Connect sentences within paragraphs using transitions.
12. Use the right level of seriousness for the audience.
13. Include text features to help the audience understand the information.

GRADE 5 (14 skills):
1. List facts & details about a topic or text.
2. Group related information to fit the organization of the genre.
3. Create a paragraph around each idea.
4. Connect ideas across paragraphs with transitions.
5. Introduce the topic or the text.
6. Restate the topic or main idea in a concluding statement.
7. Develop ideas with specific details, examples, vocabulary, & quotes pulled from sources.
8. Explain facts, details, & quotes.
9. Provide an introductory paragraph.
10. Provide a concluding paragraph.
11. Connect sentences within paragraphs using transitions.
12. Vary sentence lengths for impact.
13. Use the right level of seriousness for the audience.
14. Include text features to help the audience understand the information.

Core progression K-5: K introduces fact/detail lists with pictures; 1-2
formalize the list without pictures; 3-5 escalate to paragraphing,
transitions, sourced evidence, and audience-appropriate tone.
"""

PIE_INFORMATIVE_6_8 = """\
Informative Writing Skills — Grades 6-8 (Smekens scope & sequence)

Middle school informative writing introduces thesis statements, sourced
quotations, paraphrasing, and text features. Skills marked with * are
implicitly required.

GRADE 6 (15 skills):
1. List facts & details about a topic.
2. Group related information to fit the organizational structure.
3. Introduce / State the topic.
4. Develop / Support ideas with relevant facts & concrete details.
5. Describe ideas precisely using topic-specific vocabulary for the audience.
6. Organize paragraphs to fit the topic & text structure.
7. Provide an introductory paragraph (that includes stating the topic).
8. Provide a concluding statement.
9. Develop / Support ideas with quotes pulled from sources.
10. Paraphrase ideas pulled from sources.
11. Extend & explain support provided.
12. Connect ideas across paragraphs using transition sentences.
13. Provide a concluding paragraph (that includes restating the topic).
14. Utilize sentence structure to create efficient sentences with a formal tone.
15. Include text features (e.g., maps, photos, diagrams) to aid reader comprehension.

GRADE 7 (15 skills):
1. List facts & details about a topic.
2. Group related information to fit the organizational structure.
3. Clearly state the narrow focus of a broad topic (i.e., introduction).
4. Develop / Support ideas with relevant facts & concrete details.
5. Describe ideas precisely using topic-specific vocabulary for the audience.
6. Organize paragraphs to fit the topic & text structure.
7. Provide an introductory paragraph (that states the topic & previews the body).
8. Provide a concluding statement.
9. Develop / Support ideas with quotes pulled from sources.
10. Paraphrase ideas pulled from sources.
11. Extend & explain support provided.
12. Connect ideas across paragraphs to create cohesion.
13. Provide a concluding paragraph (that includes restating the topic).
14. Create efficient sentences with a formal tone.
15. Include text features (e.g., maps, photos, diagrams) to aid reader comprehension.

GRADE 8 (15 skills):
1. List facts & details about a topic.
2. Group related information to fit the organizational structure.
3. Clearly state the narrow focus of a broad topic (i.e., thesis statement).
4. Develop multiple main ideas with relevant facts & concrete details.
5. Describe ideas precisely using topic-specific vocabulary for the audience.
6. Organize sections/paragraph blocks to fit the topic & text structure.
7. Provide an introductory paragraph (that states the topic & previews the body).
8. Create cohesion across the sections/paragraphs using a variety of transitions.
9. Provide a concluding statement.
10. Develop / Support ideas with quotes pulled from sources.
11. Paraphrase ideas pulled from sources.
12. Extend & explain support provided.
13. Provide a concluding paragraph (that restates the topic & satisfies the reader).
14. Create efficient sentences with a formal tone.
15. Include text features (e.g., maps, photos, diagrams) to aid reader comprehension.

Progression 6→8: grade 6 introduces the topic; grade 7 narrows to a focus
statement; grade 8 formalizes the thesis statement and multiple main ideas
with cohesion across paragraph blocks.
"""

PIE_INFORMATIVE_9_12 = """\
Informative Writing Skills — Grades 9-12 (Smekens scope & sequence)

High school informative writing emphasizes thesis control, multi-source
synthesis, and a concluding paragraph that outlines significance or
implications. Skills marked with * are implicitly required.

GRADES 9-10 (13 skills):
1. List facts & details about a topic.
2. Group related information to fit the organizational structure.
3. Clearly state the narrow focus of a broad topic (i.e., thesis statement).
4. Provide a concluding statement.
5. Develop multiple main ideas with relevant facts and concrete details.
6. Describe ideas precisely using topic-specific vocabulary for the audience.
7. Organize sections/paragraph blocks to fit the topic & text structure.
8. Provide an introductory paragraph providing background and context for the focused topic.
9. Develop / Support ideas with quotes pulled from credible sources.
10. Extend & explain support provided.
11. Provide a concluding paragraph that outlines the significance or implications of the topic.
12. Clarify relationships and connect ideas across sections/paragraphs to create cohesion.
13. Create efficient sentences with a formal tone.

GRADES 11-12 (13 skills):
1. List facts & details about a topic.
2. Group related information to fit the organizational structure.
3. Clearly state the narrow focus of a broad topic (i.e., thesis statement).
4. Provide a concluding statement.
5. Develop multiple main ideas with relevant facts and concrete details.
6. Describe ideas precisely explaining topic-specific vocabulary for the audience.
7. Organize sections/paragraph blocks to fit the topic & text structure.
8. Clarify relationships and connect ideas across sections/paragraphs to create cohesion.
9. Provide an introductory paragraph providing background and context for the focused topic.
10. Develop / Support ideas with quotes pulled from credible sources.
11. Extend & explain support provided.
12. Provide a concluding paragraph that outlines the significance or implications of the topic.
13. Create efficient sentences with a formal tone.

The 9-10 vs 11-12 lists are nearly identical — 11-12 reorders steps 8/12 (cohesion introduced earlier) and shifts "describe precisely using vocabulary" to "explaining topic-specific vocabulary."
"""

PIE_NARRATIVE_K5 = """\
Narrative Writing Skills — Grades K-5 (Smekens scope & sequence)

Narrative writing teaches story elements — characters, setting, problem,
solution — with events sequenced and described. Skills marked with * are
implicitly required.

KINDERGARTEN (4 skills):
1. Identify what happened (i.e., problem). (middle)
2. Identify a solution. (ending)
3. Establish a character (e.g., I). (beginning)
4. Sequence events in order.

GRADE 1 (6 skills):
1. Identify what happened (i.e., problem). (middle)
2. Identify a solution. (ending)
3. Establish a character (e.g., I). (beginning)
4. Use precise words to describe characters & actions.
5. Organize ideas into a beginning, middle, & ending.
6. Signal event order with temporal words.

GRADE 2 (6 skills):
1. Identify what happened (i.e., problem). (middle)
2. Identify a solution. (ending)
3. Establish a character. (beginning)
4. Provide details to describe character actions, thoughts, & feelings.
5. Sequence events/ideas in order.
6. Use temporal words to signal event order (e.g., first of all).

GRADE 3 (7 skills):
1. Establish a situation or problem. (middle)
2. Provide a solution. (ending)
3. Establish the characters. (beginning)
4. Include events written in sequence.
5. Include specific descriptive details (e.g., character actions, thoughts, & feelings).
6. Include character dialogue.
7. Connect ideas & events with transition words.

GRADE 4 (8 skills):
1. Establish an event or experience or problem. (middle)
2. Provide a solution that fits the event/experience. (ending)
3. Introduce the characters in this situation. (beginning)
4. Introduce the setting of this event or experience. (beginning)
5. Organize events/episodes in the middle so that they unfold gradually.
6. Use transition words & phrases to connect ideas & events.
7. Use description & sensory details (i.e., sight, sound, smell, touch, taste) to give a clear picture of ideas & events.
8. Use dialogue to reveal characters' personalities, feelings, & responses to situations.

GRADE 5 (10 skills):
1. Establish the situation/problem. (middle)
2. Provide a solution. (ending)
3. Introduce the narrator &/or characters. (beginning)
4. Describe the setting. (beginning)
5. Develop an event sequence (e.g., conflict, climax, solution) that unfolds gradually.
6. Use narrative techniques, such as description & pacing, to develop events/scenes.
7. Connect ideas & events using transitions.
8. Use narrative techniques, such as dialogue, actions, reactions/responses, thoughts & feelings, to develop characters within events/scenes.
9. Use precise & expressive vocabulary.
10. Use figurative language for effect.

Progression K-5: K identifies problem + solution + character; 1-2 add
temporal order; 3-5 add dialogue, sensory details, figurative language.
"""

PIE_NARRATIVE_6_8 = """\
Narrative Writing Skills — Grades 6-8 (Smekens scope & sequence)

Middle-school narrative writing shifts from "story" to "event sequence"
with explicit conflict/climax/resolution, pacing, and point of view. Skills
marked with * are implicitly required.

GRADE 6 (12 skills):
1. Establish a conflict. (body)
2. Provide a solution or resolution. (conclusion)
3. Introduce the narrator &/or characters. (introduction)
4. Reveal the world the character lives in & his immediate setting. (introduction)
5. Develop an event sequence (e.g., conflict, climax, resolution).
6. Describe character actions & reactions within pivotal events/scenes.
7. Add depth to characters with dialogue within pivotal events/scenes.
8. Pace events appropriately (use narration to move the plot as well as narrative techniques to develop events/scenes).
9. Signal shifts in setting changes (i.e., time, location, mood).
10. Distinguish events that occur chronologically versus simultaneously.
11. Add dimension to a character by adding thoughts & feelings (among his actions, reactions, & dialogue).
12. Develop scenes with sensory language, expressive vocabulary, & figurative language.

GRADE 7 (11 skills):
1. Establish the situation/conflict. (body)
2. Provide a solution or resolution. (conclusion)
3. Introduce the narrator &/or characters to establish the point of view.
4. Reveal the world the character lives in, name his immediate setting, & provide context for the situation. (introduction)
5. Develop an event sequence (e.g., conflict, climax, resolution).
6. Distinguish events that occur chronologically versus simultaneously.
7. Describe character actions & reactions with sensory language, expressive vocabulary, & figurative language.
8. Add depth to characters with dialogue within pivotal events/scenes.
9. Add character reflection (i.e., thoughts & feelings) to the conclusion.
10. Pace events appropriately (use narration to move the plot as well as narrative techniques to develop events/scenes).
11. Signal shifts in setting changes (i.e., time, location, mood).

GRADE 8 (12 skills):
1. Establish the situation/conflict. (body)
2. Provide a solution or resolution. (conclusion)
3. Introduce the narrator &/or characters to establish the point of view.
4. Reveal the world the character lives in, name his immediate setting, & provide context for the situation. (introduction)
5. Develop an event sequence (e.g., conflict, climax, resolution).
6. Distinguish events that occur chronologically versus simultaneously.
7. Signal shifts in setting changes (i.e., time, location, mood).
8. Describe character actions & reactions with sensory language, expressive vocabulary, & figurative language.
9. Add character reflection (i.e., thoughts & feelings) throughout the events/scenes.
10. Add depth to characters with dialogue within pivotal events/scenes.
11. Pace events appropriately (use narration to move the plot as well as narrative techniques to develop events/scenes).
12. Provide character reflection within the resolution.

Progression 6→8: grade 6 introduces pacing, setting shifts, chronological vs
simultaneous events; grade 7 introduces point of view + context; grade 8
formalizes reflection throughout events and within the resolution.
"""

PIE_NARRATIVE_9_12 = """\
Narrative Writing Skills — Grades 9-12 (Smekens scope & sequence)

High school narrative writing escalates to multiple plotlines, literary
devices (mystery, suspense, tone), and exposition/introduction balance.
Skills marked with * are implicitly required.

GRADES 9-10 (11 skills):
1. Establish the situation/conflict. (body)
2. Resolve the main conflict. (conclusion)
3. Introduce the narrator &/or characters to establish the point of view.
4. Develop a sequence of events that build (e.g., conflict, climax, resolution).
5. Describe character actions & reactions with sensory language, expressive vocabulary, & figurative language.
6. Add character reflection (i.e., thoughts & feelings) throughout the events/scenes.
7. Add depth to characters with dialogue within pivotal events/scenes.
8. Reveal the world the character lives in & provide context for the situation. (exposition/introduction)
9. Resolve the different plotlines and provide character reflection.
10. Create multiple plotlines among the main characters.
11. Pace events to create a smooth progression. (Use narration to move the plot vs. narrative techniques to develop events/scenes.)

GRADES 11-12 (12 skills):
1. Establish the situation/conflict. (body)
2. Resolve the main conflict. (conclusion)
3. Introduce the narrator &/or characters to establish the point of view.
4. Develop a sequence of events that build (e.g., conflict, climax, resolution).
5. Describe character actions & reactions with sensory language, expressive vocabulary, & figurative language.
6. Add character reflection (i.e., thoughts & feelings) throughout the events/scenes.
7. Add depth to characters with dialogue within pivotal events/scenes.
8. Reveal the world the character lives in & provide context for the significance of the situation. (exposition/introduction)
9. Resolve the different plotlines and provide character reflection.
10. Create multiple plotlines among the main characters.
11. Pace events to create a smooth progression. (Use narration to move the plot vs. narrative techniques to develop events/scenes.)
12. Use literary devices (e.g., mystery, suspense) to build toward a tone.

The 9-10 → 11-12 jump adds one skill: use of literary devices (mystery,
suspense) to build toward a tone. Also, 11-12 escalates exposition to
"context for the SIGNIFICANCE of the situation."
"""


PIE_CHUNKS_SPEC = [
    ("pie-persuasive-k5", "Persuasive Writing Skills — Grades K-5", "Persuade",
     "K-5", {"K-2": ["P"], "3-5": ["P"]}, PIE_PERSUASIVE_K5, 2),
    ("pie-argumentative-6-8", "Argumentative Writing Skills — Grades 6-8", "Persuade",
     "6-8", {"6-8": ["P"]}, PIE_ARGUMENTATIVE_6_8, 3),
    ("pie-argumentative-9-12", "Argumentative Writing Skills — Grades 9-12", "Persuade",
     "9-12", {"9-12": ["P"]}, PIE_ARGUMENTATIVE_9_12, 4),
    ("pie-informative-k5", "Informative Writing Skills — Grades K-5", "Inform",
     "K-5", {"K-2": ["I"], "3-5": ["I"]}, PIE_INFORMATIVE_K5, 5),
    ("pie-informative-6-8", "Informative Writing Skills — Grades 6-8", "Inform",
     "6-8", {"6-8": ["I"]}, PIE_INFORMATIVE_6_8, 6),
    ("pie-informative-9-12", "Informative Writing Skills — Grades 9-12", "Inform",
     "9-12", {"9-12": ["I"]}, PIE_INFORMATIVE_9_12, 7),
    ("pie-narrative-k5", "Narrative Writing Skills — Grades K-5", "Entertain",
     "K-5", {"K-2": ["E"], "3-5": ["E"]}, PIE_NARRATIVE_K5, 8),
    ("pie-narrative-6-8", "Narrative Writing Skills — Grades 6-8", "Entertain",
     "6-8", {"6-8": ["E"]}, PIE_NARRATIVE_6_8, 9),
    ("pie-narrative-9-12", "Narrative Writing Skills — Grades 9-12", "Entertain",
     "9-12", {"9-12": ["E"]}, PIE_NARRATIVE_9_12, 10),
]


# ---------------------------------------------------------------------------
# Modes/Genres chunks (5)
# ---------------------------------------------------------------------------

MG_WRITING_PURPOSES = """\
Writing Modes & Purposes (Smekens)

Writing modes define the writer's PURPOSE. The same topic can be written
in any mode depending on what the writer is trying to do.

THREE MODES (aligned to Common Core writing standards):

1. PERSUASIVE / ARGUMENTATIVE
Purpose: To persuade the reader to agree with a side or position on a
debatable topic.
Standard: Write arguments to support claims in an analysis of substantive
topics or texts, using valid reasoning and relevant and sufficient evidence.

2. INFORMATIVE / EXPLANATORY
Purpose: To provide the reader specific information about a topic; to
clarify or explain something.
Standard: Write informative/explanatory texts to examine and convey
complex ideas and information clearly and accurately through the effective
selection, organization, and analysis of content.

3. NARRATIVE / ENTERTAIN
Purpose: To entertain the reader with a real or imaginary problem and
solution.
Standard: Write narratives to develop real or imagined experiences or
events using effective technique, well-chosen details, and well-structured
event sequences.

Teachers should vary genres within mini-units and provide multiple
opportunities for students to write for different purposes. Formats are
mode-flexible — the same format (letter, email, essay, speech) can be
written in any mode depending on the writer's purpose.
"""

MG_GENRES_PERSUASIVE = """\
Persuasive / Argumentative Genres & Formats (Smekens)

Persuasive and argumentative writing share the purpose of convincing a
reader to agree with a claim or opinion. Genres range from informal
opinion pieces to formal research papers.

MODE-SPECIFIC GENRES:
• Opinion
• Testimonial
• Advice Column
• Review / Critique
• Advertisement / Commercial
• Sign, Poster, Bumper Sticker
• Persuasive Letter / Essay
• Editorial / Letter to the Editor
• Constructed Response
• Perspective / Position Paper
• Argumentative Research Paper
• Evaluate an Argument / Argumentative Analysis

STRUCTURE & PATTERNS:
Persuasive writing centers on:
• What I think
• Why I think it

Argumentative writing escalates to:
• Claim
• Reasons
• Evidence from credible sources
• Counterclaim awareness

KEY FORMS:
• A PROPOSAL persuades someone to approve an idea or fund a project.
• A SUGGESTION offers a brief, informal opinion on ways to improve something.
• A REQUEST is more formal persuasive writing asking for specific
  information, permission, or resources.
• A RECOMMENDATION is a personal endorsement of a product, service,
  person, or idea — aiming to convince others to do/not do something.
• A DEBATE is a spoken exchange where opposing sides present strong points
  to win over an audience.
• An ARGUMENTATIVE RESEARCH PAPER is an in-depth report relying on facts
  and evidence to prove a position while addressing other viewpoints.
• An ARGUMENTATIVE ANALYSIS evaluates how effectively the author supported
  his claim and addressed counterclaims.
"""

MG_GENRES_INFORMATIVE = """\
Informative / Explanatory Genres & Formats (Smekens)

Informative writing provides factual information about a topic or explains
a process, concept, or event.

MODE-SPECIFIC GENRES:
• Explanation
• Encyclopedia Entry
• Summary
• Brochure / Pamphlet
• Report
• Speech
• Research Paper
• Application Essay
• Compare-Contrast
• Comparative Analysis
• Literary Analysis
• Newspaper Article
• Biography
• Book Report
• Invitation
• Thank-You Note
• Friendly Letter
• Business Letter
• Interview
• Instructions
• Directions
• Recipe

STRUCTURE & PATTERNS:
• Broad topic or subject
• Specific details grouped by subtopic

KEY FORMS:
• An EXPLANATION clearly describes how or why something happens, helping
  the reader understand a process, concept, or event.
• An ENCYCLOPEDIA ENTRY gives short, factual information about a topic,
  including key details like definitions, dates, and examples.
• DIRECTIONS give step-by-step instructions that tell someone how to do or
  make something, often using command verbs and clear sequencing.
• An INFORMATIVE RESEARCH PAPER is a longer report that collects facts
  from multiple sources to teach the reader about a topic.
• A COMPARE-CONTRAST WRITING presents information about two or more topics
  or texts, helping the reader understand each individually and in
  relation to one another.
• An INTERVIEW presents real questions and answers from a conversation
  with a person who has experience or knowledge about a topic.
"""

MG_GENRES_NARRATIVE = """\
Narrative / Entertain Genres & Formats (Smekens)

Narrative writing develops real or imagined events, entertaining the
reader with a problem and solution.

MODE-SPECIFIC GENRES:
• Fairy Tale
• Legend
• Fable
• Myth
• Tall Tale
• Mystery
• Personal Narrative
• Imaginary Narrative
• Realistic Fiction (fiction based on fact)
• Historical Fiction (fiction based on fact)
• Science Fiction (fiction based on fact)
• Sequel (what happens next / next time)
• Rewrite from a Different Perspective
• Add in the Missing Page / Part
• Memoir
• Anecdote
• Diary Entry
• Scene
• Satire
• Spoof
• Adventure Story
• Apology
• Complaint

STRUCTURE & PATTERNS:
• Character & setting
• Problem / Conflict
• Solution / Resolution

KEY FORMS:
• A PERSONAL NARRATIVE is a true story about one's own experience.
• REALISTIC FICTION is a made-up story that COULD happen in real life
  (e.g., a short story, adventure story, or mystery).
• FANTASY involves magical or supernatural elements (e.g., fairy tales,
  fables, myths, legends).
• A GRAPHIC NOVEL tells a story through a mix of visual art and text.
• A REWRITE FROM A DIFFERENT PERSPECTIVE retells a familiar story through
  the eyes of a different character, showing his unique thoughts,
  feelings, or experiences.
• A FICTION BASED ON FACT is a made-up story that includes real people,
  places, or events gleaned from informational text — blending facts with
  imaginary characters or situations.
"""

MG_MODE_FLEXIBLE_FORMATS = """\
Mode-Flexible Formats (Smekens)

Formats are mode-flexible — the same format can be used across writing
modes. Emphasize the writing PURPOSE over the format. A letter can be
persuasive, informative, or narrative depending on what the writer is
trying to do.

LETTER:
• Persuasive: Complaint, Persuasive business letter, Request for something
• Informative: Friendly letter giving updates, Business letter, Story
  shared within a letter (narrative)
• Narrative: Shared story
Structure: Includes a date, greeting, body, closing, and signature. May
be formatted informally or formally.

EMAIL:
Structure: Includes a to/from address, subject line, body, and signature
line. May include a greeting and closing.

ESSAY:
• Persuasive: Argumentative essay
• Informative: Informative essay
• Narrative: Narrative essay
Structure: Organized in multiple paragraphs with a clear introduction,
body, and conclusion. Written in full sentences.

SPEECH:
• Persuasive: Persuasive speech, Promotion of an idea or event
• Informative: Informational speech
• Narrative: Narrative speech
Structure: Written in full sentences and paragraphs. May include bold
words, pauses, or annotations for emphasis and tone.

POSTER:
Structure: Uses key words and short phrases. Includes visual elements
like images, bold fonts, and color for emphasis.

ARTICLE:
• Persuasive: Editorial
• Informative: Information on a topic, News report, Feature story
• Narrative: Report on something
Structure: Structured in paragraphs with headings or subheadings.
Written in full sentences. May include a byline or dateline.

SCRIPT:
• Persuasive: TV advertisement/commercial script
• Informative: Informational script or skit
• Narrative: Play
Structure: Written as dialogue with speaker labels. May include stage
directions or delivery notes.

SUMMARY:
• Persuasive: Summary of someone else's argument
• Informative: Summary of an informational text
• Narrative: Summary of a narrative text, Teaser for a movie
Structure: Condensed into short paragraphs or bullet points. Focuses
only on main ideas and essential details.

LITERARY ANALYSIS:
• Persuasive: Literary critique, Evaluation of an argument
• Informative: Character analysis, Theme explanation
• Narrative: N/A (literary analysis is inherently persuasive or informative)
Structure: Structured in full paragraphs. Includes analysis of a literary
technique supported with text evidence.
"""


MG_CHUNKS_SPEC = [
    ("mg-writing-purposes", "Writing Modes & Purposes",
     "all", "K-12", MG_WRITING_PURPOSES, 2),
    ("mg-genres-persuasive", "Persuasive / Argumentative Genres & Formats",
     "Persuade", "K-12", MG_GENRES_PERSUASIVE, 1),
    ("mg-genres-informative", "Informative / Explanatory Genres & Formats",
     "Inform", "K-12", MG_GENRES_INFORMATIVE, 1),
    ("mg-genres-narrative", "Narrative / Entertain Genres & Formats",
     "Entertain", "K-12", MG_GENRES_NARRATIVE, 1),
    ("mg-mode-flexible-formats", "Mode-Flexible Formats",
     "all", "K-12", MG_MODE_FLEXIBLE_FORMATS, 3),
]


# ---------------------------------------------------------------------------
# Chunk builders
# ---------------------------------------------------------------------------


def build_pie_chunk(slug: str, title: str, mode: str, grade_band: str,
                    pie_tags_by_band: dict, content: str, page: int) -> dict:
    audience = "ELEM" if grade_band in {"K-5"} else "SEC"
    if grade_band == "K-5":
        audience = "ELEM"
    elif grade_band == "6-8":
        audience = "SEC"
    else:
        audience = "SEC"
    return {
        "chunk_id": slug,
        "source_document": PIE_PDF,
        "tier": 1,
        "content_type": "pie_reference",
        "source_category": "scope_sequence",
        "copilot_mode": "both",
        "step": "overview",
        "grade_level": grade_band,
        "writing_trait": "all",
        "writing_mode": mode,
        "strategy_name": None,
        "is_scripted_example": False,
        "audience": audience,
        "page_number": page,
        "section_name": title,
        "day_number": None,
        "mini_lesson_number": None,
        "episode_number": None,
        "chunk_index": 0,
        "content": content.strip(),
        "book_name": None,
        "chapter_number": None,
        "ml_number": None,
        "skill_title": title,
        "is_scripted_lesson": False,
        "priority_rank": 2,
        "topic_keywords": topic_keywords(content, title),
        "book_reference": f"Smekens Essential Skills K-12 PIE, {title}",
        "pie_tags_by_band": pie_tags_by_band,
        "lesson_trigger": [],
    }


def build_mg_chunk(slug: str, title: str, mode: str, grade_band: str,
                   content: str, page: int) -> dict:
    # Per-mode pie_tags_by_band; "all" mode → all three letters across all bands
    if mode == "all":
        pie = {b: ["E", "I", "P"] for b in ("K-2", "3-5", "6-8", "9-12")}
    elif mode == "Persuade":
        pie = {b: ["P"] for b in ("K-2", "3-5", "6-8", "9-12")}
    elif mode == "Inform":
        pie = {b: ["I"] for b in ("K-2", "3-5", "6-8", "9-12")}
    elif mode == "Entertain":
        pie = {b: ["E"] for b in ("K-2", "3-5", "6-8", "9-12")}
    else:
        pie = {}
    return {
        "chunk_id": slug,
        "source_document": MG_PDF,
        "tier": 1,
        "content_type": "mode_taxonomy",
        "source_category": "taxonomy",
        "copilot_mode": "both",
        "step": "overview",
        "grade_level": grade_band,
        "writing_trait": "all",
        "writing_mode": mode,
        "strategy_name": None,
        "is_scripted_example": False,
        "audience": "K-12",
        "page_number": page,
        "section_name": title,
        "day_number": None,
        "mini_lesson_number": None,
        "episode_number": None,
        "chunk_index": 0,
        "content": content.strip(),
        "book_name": None,
        "chapter_number": None,
        "ml_number": None,
        "skill_title": title,
        "is_scripted_lesson": False,
        "priority_rank": 3,
        "topic_keywords": topic_keywords(content, title),
        "book_reference": f"Smekens Writing Modes, Genres, & Formats — {title}",
        "pie_tags_by_band": pie,
        "lesson_trigger": [],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _existing_chunk_ids() -> set[str]:
    seen: set[str] = set()
    for p in CHUNKS_DIR.glob("*.json"):
        try:
            for c in json.loads(p.read_text()):
                if isinstance(c, dict) and "chunk_id" in c:
                    seen.add(c["chunk_id"])
        except (json.JSONDecodeError, OSError):
            pass
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    existing = _existing_chunk_ids()

    pie_chunks = []
    for slug, title, mode, band, pie, content, page in PIE_CHUNKS_SPEC:
        if slug in existing:
            print(f"[skip] {slug} already present")
            continue
        pie_chunks.append(build_pie_chunk(slug, title, mode, band, pie, content, page))

    mg_chunks = []
    for slug, title, mode, band, content, page in MG_CHUNKS_SPEC:
        if slug in existing:
            print(f"[skip] {slug} already present")
            continue
        mg_chunks.append(build_mg_chunk(slug, title, mode, band, content, page))

    print(f"PIE chunks: {len(pie_chunks)}")
    for c in pie_chunks:
        print(f"  - {c['chunk_id']}  mode={c['writing_mode']} band={c['grade_level']} "
              f"pie={c['pie_tags_by_band']}  ({len(c['content']):,} chars)")
    print(f"Modes/Genres chunks: {len(mg_chunks)}")
    for c in mg_chunks:
        print(f"  - {c['chunk_id']}  mode={c['writing_mode']} band={c['grade_level']}  "
              f"({len(c['content']):,} chars)")

    if args.dry_run:
        print("\n[dry-run: no files written]")
        return 0

    if pie_chunks:
        pie_path = CHUNKS_DIR / "38-pie-scope-sequence.json"
        pie_path.write_text(json.dumps(pie_chunks, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {pie_path}")
    if mg_chunks:
        mg_path = CHUNKS_DIR / "39-writing-modes-genres.json"
        mg_path.write_text(json.dumps(mg_chunks, indent=2, ensure_ascii=False) + "\n")
        print(f"wrote {mg_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
