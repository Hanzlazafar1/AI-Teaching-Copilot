"""META handler — canned responses for greetings, capability questions,
and off-topic redirects.

No retrieval. No LLM call. No validators. Just a handful of tidy
responses for the narrow set of intents QU classifies as META.

The full flow is still:
  intent → handler → TurnOutcome
— because every handler must obey the same contract. META is just
the simplest shape, which makes it a good canary for the dispatcher.
"""

from __future__ import annotations

import string
from typing import Any, Optional

from openai import AsyncOpenAI

from canonicalizer import Canonicalizer
from schemas import (
    Conversation,
    Quality,
    SessionHandshakes,
    TurnIntent,
    TurnOutcome,
)


# Three canned replies. QU's META covers three situations; we pick by
# simple keyword scan since the user message is the carrier here.
_OFF_TOPIC_REPLY = (
    "I'm Brady's writing co-pilot — I focus on writing instruction using "
    "the Smekens methodology (the 4-step mini-lesson framework, 6+1 "
    "traits, writing modes, and Smekens strategies). That question is "
    "outside my scope, but I'd be glad to help with writing instruction. "
    "What writing skill, grade, or unit are you working on?"
)

# Brady's E8 redline, VERBATIM. In feedback.docx he typed a replacement
# sentence and struck one clause out of it; this constant is what survived:
#   "...directly here, but [STRUCK: I can format the mini-lesson into a clean,
#    copy-ready layout] you can copy & paste this text into Google Docs or Word
#    and save as a PDF. [STRUCK: Just say the word and I'll prepare it so it's
#    ready to export.]"
# Those are the ONLY two strikethrough runs in the entire document (2 of 468),
# so both deletions are deliberate. The second was removed in Wave 1b; this is
# the first. On the video: "So Copilot doesn't have to do anything else."
#
# The reply therefore states the limitation and hands the teacher the whole
# remedy in one turn. It must promise NO further action — there is no second
# step to accept, which is the point: Brady's complaint was that the app made
# an offer it then couldn't honour. (Brady's text has no em-dash; the "—" in
# the previous version was punctuation the implementation added to graft on the
# struck clause, so it goes with it.)
_PDF_CAPABILITY_REPLY = (
    "I can't generate or attach a PDF directly here, but you can copy & "
    "paste this text into Google Docs or Word and save as a PDF."
)

_GENERAL_CAPABILITY_REPLY = (
    "I'm Brady's AI Writing Co-Pilot. I help with writing instruction "
    "using the Smekens methodology — scripted 4-step mini-lessons, "
    "how-to-teach outlines, unit and skill planning, classroom-management "
    "routines, and coaching. What writing skill, grade, or unit are you "
    "working on?"
)

_GREETING_REPLY = (
    "Hi! I'm Brady's AI Writing Co-Pilot. What are you preparing to "
    "teach in writing? Or would you like a list of priority writing "
    "skills for a particular grade or writing mode (informative, "
    "persuasive, narrative)?"
)


# Punctuation that may sit at the EDGE of a word without changing the word.
# ASCII punctuation plus the smart quotes/dashes/ellipsis a teacher's keyboard
# (or a paste from Word) actually produces.
_EDGE_PUNCTUATION = string.punctuation + "—–…“”‘’"

_OFF_TOPIC_MARKERS = (
    "weather",
    "stock",
    "math problem",
    "recipe",
    "joke",
    "super bowl",
    "who won",
)
# The output-packaging family: asks about getting the lesson OUT of the chat.
# Brady's E8 requirement covers "PDF / copy-ready" requests, and the reply
# itself advertises "you can copy & paste this text into Google Docs or Word" —
# so an ask phrased in that same vocabulary must reach the capability answer.
# Only the PDF half used to be recognised, so "copy ready" fell through to the
# off-topic refusal — which is precisely Brady's original complaint: he asked
# for "copy ready" and got "This question is outside my scope. What?"
#
# NB: bare "copy" is deliberately NOT a marker — students copy sentences and
# teachers copy handouts. Only packaging phrasings belong here.
_OUTPUT_PACKAGING_MARKERS = (
    "pdf",
    "export",
    "download",
    "copy-ready",
    "copy ready",
    "copy-paste",
    "copy/paste",
    "copy & paste",
    "copy and paste",
)
_GENERAL_CAPABILITY_MARKERS = (
    "how does this work",
    "what can you do",
)
_GREETING_MARKERS = (
    "hi",
    "hello",
    "hey",
    "thanks",
    "thank you",
    "ok",
    "okay",
)

# Writing-instruction domain roots. A META query mentioning any of these is
# writing-RELATED (a vague opener — e.g. the U2 "How can I help?" buttons,
# which are questions QU classifies as META), NOT off-topic. It gets the warm
# capability redirect (which asks for the grade/skill/unit needed to proceed),
# never the "outside my scope" refusal. This is the "clearly writing-related"
# discriminator handle_meta's docstring already assumes. Substring match:
# "writ" covers writing/write/writer/written.
_WRITING_DOMAIN_ROOTS = (
    "writ",
    "teach",
    "lesson",
    "skill",
    "grade",
    "student",
    "unit",
    "trait",
    "essay",
    "paragraph",
    "sentence",
    "workshop",
)


async def handle_meta(
    intent: TurnIntent,
    conversation: Conversation,
    handshakes: SessionHandshakes,
    new_user_message: str,
    *,
    client: AsyncOpenAI,
    model: str,
    canonicalizer: Canonicalizer,
    retrieval_fn: Optional[Any] = None,
    library: Optional[Any] = None,
) -> TurnOutcome:
    """Route META intents to one of three canned replies.

    We scan the user's message text for simple markers to pick the
    right reply. If nothing matches, default to off-topic redirect —
    the safest fallback for any query that isn't clearly writing-related.
    """
    text = (new_user_message or "").lower().strip()

    reply: str
    if _matches_any(text, _OUTPUT_PACKAGING_MARKERS):
        reply = _PDF_CAPABILITY_REPLY
    elif _matches_any(text, _GENERAL_CAPABILITY_MARKERS):
        reply = _GENERAL_CAPABILITY_REPLY
    elif _matches_any(text, _GREETING_MARKERS) and len(text) < 40:
        # Short greetings — avoid matching "hi I'd like a lesson on X"
        reply = _GREETING_REPLY
    elif _is_writing_related(text):
        # Writing-related but vague (e.g. the U2 opener buttons) — warmly
        # redirect and ask for specifics; never refuse an in-domain query.
        reply = _GENERAL_CAPABILITY_REPLY
    else:
        reply = _OFF_TOPIC_REPLY

    return TurnOutcome(
        response_text=reply,
        structured=None,
        grounding=[],
        quality=Quality.VALID,
        handshake_updates=None,
        retry_count=0,
    )


def _matches_any(text: str, markers: tuple[str, ...]) -> bool:
    """Whole-word marker match (not just substring) so 'hello' doesn't
    trigger on 'hello world essay'. Multi-word markers match as substrings.

    Punctuation is stripped from the EDGES of each word, never from inside it,
    so 'Hi!' still matches 'hi' while 'copy-ready' and 'copy/paste' survive
    intact as single tokens. This matters more than it looks: every marker miss
    falls through to the off-topic refusal, so before this normalisation a
    trailing '!' was enough to answer a teacher's "Hi!" with "That question is
    outside my scope." Recognition must not hinge on how someone punctuates.
    """
    words = {w.strip(_EDGE_PUNCTUATION) for w in text.split()}
    return any(m in text if " " in m else m in words for m in markers)


def _is_writing_related(text: str) -> bool:
    """True if the message mentions any writing-instruction domain root.
    Substring match (so "writing"/"writer" and "grade-level" both count) —
    the discriminator between a vague in-domain opener (warm redirect) and a
    genuinely off-topic query (off-topic refusal)."""
    return any(root in text for root in _WRITING_DOMAIN_ROOTS)


