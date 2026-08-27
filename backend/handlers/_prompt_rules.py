"""Shared prompt fragments spliced into multiple builders.

Keeps cross-builder rules in one place so they can't drift out of one
handler while staying in the others. Currently: the N1/N2 vocabulary
non-negotiables (all six builders), the E4 single-closing-question rule
(coaching only, since Brady E3 split management off) and the E3 management
overview closer (management only).
"""

# Brady E4: coaching/management replies must close with ONE question, never
# two — a natural next-step offer OR the generic closer, not both stacked.
# Shared verbatim by the coaching + management builders (spliced into the
# prompt as a standalone part, like GLOBAL_VOCAB_RULES) so the wording can't
# fork between the two handlers.
SINGLE_CLOSING_QUESTION_RULE = """\
## Closing question (end with exactly ONE)

End with ONE closing question — never two. If a concrete next-step
offer fits naturally (e.g. "Want me to map out a week of lessons?"),
make THAT your single closing question and do NOT also add "Does
this make sense? Is this helpful?" after it. If no natural offer
fits, close with exactly:

  Does this make sense? Is this helpful?"""

# Brady E3 (28:30, doc 128): a MANAGEMENT response is a broad overview, so it
# closes with a scope-narrowing question — NOT the generic "Does this make
# sense? Is this helpful?" closer above. Today every MANAGEMENT reply is an
# overview (the routine-specific mini-lesson path is a future build), so this
# is the UNCONDITIONAL management closer. Spliced into the management builder
# IN PLACE OF SINGLE_CLOSING_QUESTION_RULE; validation.endings keys
# _ENDING_REQUIRED["MANAGEMENT"] on this closer's distinctive fragments so the
# instruction the model is given and the check it must pass can't drift apart.
MANAGEMENT_CLOSING_QUESTION_RULE = """\
## Closing question (end with exactly this)

Your response is a broad overview. End it with this exact closing
question, on its own final paragraph — put nothing after it:

  This was an overview. Which ONE area or SINGLE routine would you like to start with?"""

GLOBAL_VOCAB_RULES = """\
## Vocabulary non-negotiables (apply everywhere)

- DETAILS, not "reasons" (Brady N1): In opinion/persuasive/argument writing, say
  "details" when brainstorming, listing, or thinking of ideas — NEVER "reasons".
  In Kindergarten and 1st grade, always say "details" (or "details why") and NEVER
  the word "reasons" at all. In grades 2-12, "reasons" is acceptable ONLY when the
  student is actually writing a paragraph — never while brainstorming or listing.
- STORY only for narrative (Brady N2): Use "story", "storytelling", or "writing a
  story" ONLY for narrative writing. For informative or persuasive writing, say
  "your writing", "your writing piece", "your informative/persuasive piece or
  picture", or "when informing/persuading your audience" — never "story"."""

# Brady SG2 (57:30, doc 286): for a subgroup / early writer, grade level matters
# less than the current WRITING LEVEL — teach the grade-level skill AT that
# developmental stage. This is the SHARED CORE of the rule: it is true of any
# leveled output, so it is spliced into BOTH the HOW_TO_TEACH outline builder
# and the SCRIPTED_ML 4-step-lesson builder, ONLY when writing_level is set (a
# no-op for normal on-grade generation). Keeping it in ONE constant is what
# stops the principle drifting out of one builder while staying in the other —
# a real risk, since SCRIPTED_ML shipped WITHOUT it (task #64: the grade-clarify
# gate and this composer were both writing_level-blind).
EARLY_WRITER_STAGE_RULE = """\
## Developmental writing stage (subgroup / early writer)

The teacher gave a current WRITING LEVEL — the developmental stage
(e.g. picture, label, word, or sentence). For a subgroup or early
writer, grade level matters less than this stage: teach the grade-level
skill AT that stage — show it at the picture / label / word / sentence
level, not the full on-grade written form."""

# Brady SG3 (58:40, doc 290): restate the stage in EACH bulleted skill (better
# to repeat the stage in every bullet than state it once). This is PRESENTATION-
# SPECIFIC — it only means something where there IS a bulleted skill list. It is
# spliced into BOTH leveled builders — the HOW_TO_TEACH outline AND COACHING —
# appended after the shared core above (the two joined reproduce the original
# single rule verbatim). COACHING carries it because the C7 case is a leveled
# coaching FOLLOW-UP ("teach it at the picture/label stage") that renders a
# bulleted skill list; when a COACHING reply is prose with no bullets it is
# simply a no-op. It is NOT spliced into the SCRIPTED_ML 4-step lesson: that has
# no bulleted skill list, so "restate the stage in every bullet" would be an
# instruction to do something its output shape doesn't contain.
EARLY_WRITER_STAGE_PER_BULLET_RULE = """\
Restate the stage in EACH bulleted skill — name "at the <stage> stage"
in every bullet. Better to repeat the stage in every bullet than to
state it once and move on."""

# Citation identity, the markdown half — "the model POINTS, the code SPEAKS".
#
# The page used to be chosen from retrieval RANK before generation ran, so "you
# will find THIS LESSON on p.N" was decided before "this lesson" existed. The
# model reads "Source: <chunk_id>" on every retrieved block (assembler.py:79)
# and is the only thing that knows which one it actually taught from — so it
# points, and handlers/citation.py::resolve_markers speaks the sentence from
# that chunk's TYPED metadata.
#
# WHY PER CLAIM, measured: Brady's own approved responses carry citations per
# claim — image39 has 5 sites / 6 pages, image3 has 2 — while we ship exactly
# ONE footer (max = min = 1 across 25 live turns). Retrieval was never the
# constraint: every page his artifacts cite is already in the retrieved context
# on every run. His second citation (p.124) is 0/5, unreachable by construction,
# because one footer from rank 1 structurally cannot carry a second page.
#
# WHY IT IS SHARED: HOW_TO_TEACH and COACHING are the two per-claim producers
# (_base_text.py:371-373 — the footer is the default for every OTHER text
# handler, so MANAGEMENT / PLAN_UNIT / THINK_ALOUD stay uncited). Splicing ONE
# constant into both is what stops the rule drifting out of one while staying in
# the other; the SG2 comment below records that happening for real.
#
# WHAT IS DELIBERATELY *NOT* IN THE STRING BELOW:
#   * No rationale — a prompt is not a scratchpad.
#   * No example citation. The reverted Fm5 attempt had the model reformat raw
#     "Book:/Page:" headers and leaked the label words + blank page slots to
#     teachers; handing it a page-shaped exemplar here is the same mistake in
#     new clothes. The marker carries a POINTER and nothing else — no book, no
#     page — which is why a leaked marker can never become a wrong citation.
#   * No instruction to cite everything. Brady's artifacts show silence is
#     correct: image39 cites its lead and points 2-5 but is silent on point 1;
#     image3 cites points 1 and 4 and leaves its lead uncited. He praised both.
#     A claim is ELIGIBLE, never obliged.
#
# The placement clause ("END of that claim's own line", "never on a line of its
# own") is load-bearing, not cosmetic: picklist.py:73 ends a list at the first
# non-list line, and _base_text.py:596 extracts offered_skills AFTER a citation
# enters the text at :586. A citation on its own line mid-list truncates the
# pick-list, "number 4" falls out of range, and the nn4 fix — a teacher asking
# for 4 and silently getting 3 — reverts.
#
# The `[[src:<id>]]` grammar is pinned against citation.py::_MARKER_RE. If the
# two drift, every marker resolves to nothing and the citations vanish silently
# and green (the resolver sweeps what it cannot resolve), so a test binds them.
PER_CLAIM_SOURCE_MARKER_RULE = """\
## Point at the source of each claim

The Launch-book pointer is still added for you automatically — you never
write one. You only point at the block it should name.

After any claim you built from a retrieved block:

  * Append that block's `Source:` id at the END of that claim's own line,
    in this exact form: [[src:<id>]]
  * Copy the id character-for-character from the block's header.
  * Never put a marker on a line of its own.
  * If one claim came from several blocks, append one marker per block.
  * Append nothing when a claim was not built from a retrieved block.
    A claim with no marker is expected and correct.
  * Never write the id anywhere else in your answer.
  * Never write a book title or a page number of your own."""

LIST_FORMAT_RULE = """\
## List formatting (numbers vs bullets)

Use a NUMBERED list ONLY when the items are an ordered sequence — steps
performed in order (e.g. the four steps of a mini-lesson). For a set of
options, facets, characteristics, or discrete choices with no required
order, use BULLETS ("- "), never numbers. In a mixed list, bullet the
generic/opening items and number only a genuinely ordered run."""

# Brady S5 (D0143/T0449): "recognize that the skill order is correct". When the
# teacher presents their OWN scope-and-sequence or ordered skill list, affirm
# the order is sound rather than reshuffling or second-guessing it. SHARED by
# the PLAN_UNIT + COACHING builders: an explicit unit-plan request routes to
# PLAN_UNIT, but the "does my order work?" message routes to COACHING (dogfood
# C5), so the rule must live in BOTH. Keeping it in ONE constant is what stops
# the wording forking between the two handlers — the SG2 comment above records
# that drift happening for real. UNLIKE EARLY_WRITER_STAGE_RULE it is spliced
# UNCONDITIONALLY: the rule self-gates in its own text ("If the teacher presents
# their own..."), so it is a no-op when no order was given — exactly how it
# behaved inside _PLAN_UNIT_RULES before this promotion.
SKILL_ORDER_AFFIRM_RULE = """\
## The teacher's skill order is correct

If the teacher presents their own scope-and-sequence or ordered skill
list, recognize that the skill order is correct — affirm it is sound and
do NOT reshuffle or second-guess the sequence they presented."""

# Brady C10 (dogfood C10; coaching C1 @52:50): validate the EMOTION FIRST, THEN
# the practical guidance. This instruction lived ONLY in COACHING's bespoke
# rules (coaching.py's "## Responding to frustration"), so it fired only when a
# frustrated opener happened to route to COACHING — a frustrated "how do I teach
# X?" routes to HOW_TO_TEACH and got NO validation. Measured live it fired ~1/4:
# a routing lottery, because the rule was tied to one handler while frustration
# is orthogonal to request_type. Promoted here and spliced into ALL FIVE text
# handlers (how_to_teach, coaching, plan_unit, management, think_aloud) gated on
# the deterministic expressed_frustration QU signal, so the emotion is validated
# wherever the turn lands. Mirrors EARLY_WRITER_STAGE_RULE: QU makes the semantic
# judgment (is this frustration?), a deterministic gate splices this in, and the
# validating sentence itself stays LLM-authored. NOT spliced into SCRIPTED_ML —
# a structured 4-step lesson has no prose opener to validate in (same reasoning
# as EARLY_WRITER_STAGE_PER_BULLET_RULE being outline-only). Brady's exemplar is
# kept verbatim so the model has his register.
FRUSTRATION_VALIDATION_RULE = """\
## Validate the frustration first

The teacher voiced frustration or being stuck. OPEN with ONE brief
sentence validating that it's normal and hard — e.g. "This is not unusual
— it's hard for students to express an idea AND apply all the convention
rules at once" — THEN give the practical guidance. Validate the emotion
first; never skip straight to the fix."""

# Brady C10 — the CLARIFY-path counterpart of FRUSTRATION_VALIDATION_RULE above.
# That rule is an LLM *instruction* spliced into a generation prompt, so it only
# fires when a handler actually calls the model. But a frustrated FIRST-contact
# turn whose grade/skill is missing short-circuits in dispatch() to a pure
# clarify CONSTRUCTOR (handlers.__init__._clarify_outcome — no LLM), so that
# instruction never runs and the teacher gets a bare "Which grade level are you
# teaching?" with no acknowledgment of the frustration they just voiced.
#
# This is the deterministic counterpart: a short, topic-agnostic, warm sentence
# in Brady's register that _clarify_outcome PREPENDS (gated on the same
# expressed_frustration signal) before the clarifying question. It deliberately
# carries NO skill/grade specifics — it renders exactly when those are still
# unknown, so naming either would be the wrong-specifics assumption Brady
# objects to. It is a fixed CODE string, never LLM text (the anti-Fm5 pattern,
# like the one-skill guard), and is a SEPARATE constant from
# FRUSTRATION_VALIDATION_RULE on purpose: that is a prompt instruction, this is
# the literal sentence the teacher reads.
FRUSTRATION_VALIDATION_CLARIFY = (
    "I hear you — that's a really frustrating place to be, and teaching "
    "writing is genuinely hard."
)
