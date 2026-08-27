# 01 — Orientation: What This Thing Is

## 1.1 The one-sentence version

**A K-12 writing teacher types a plain-English question and gets back either a classroom-ready
four-step mini-lesson script or coaching advice — grounded entirely in one publisher's teaching
methodology, never in generic writing advice.**

Everything else in this handbook serves the words *"entirely"* and *"never."*

---

## 1.2 Who's who

| Party | Role |
|---|---|
| **The client** | A K-12 writing-instruction publisher. Sells books, video courses and teacher training built on a proprietary writing methodology. |
| **The client contact** | The pedagogical authority on this project. **Their feedback *is* the specification** — and much of it arrives as annotated screenshots and video walkthroughs rather than as written requirements. |
| **The vendor** | Us — the engineering team. |
| **The end user** | A K-12 writing teacher, inside the client's online course. Not a technical user. Wants something they can teach tomorrow morning. |

> **Why this matters to you as an engineer:** on most projects "the spec" is a document. Here the
> spec is *a person's pedagogy*, expressed in their own vocabulary — and a large fraction of the
> system exists to enforce it mechanically. Rules like *"never use the word 'activity'"* or *"a
> K-2 lesson must end with 'Let's go be writers!'"* are not styling preferences. They are hard
> requirements with automated checks behind them.

---

## 1.3 What a teacher actually gets

Two broad modes, decided automatically from the question.

**Mode 1 — a scripted mini-lesson.** A complete, ready-to-read-aloud teaching script in a fixed
four-step shape. This is the flagship output.

**Mode 2 — coaching and planning.** Instructional advice, unit plans, "how do I teach X" outlines,
classroom-routine guidance, or a modelled think-aloud on its own.

Here is a real, abbreviated example of the flagship output:

> **Teacher:** *"Give me a 4th grade scripted mini-lesson on topic sentences"*
>
> ---
>
> **Grade 4 | Informative**
>
> ### Write a topic sentence that tells what the whole part is about
>
> **Step 1 — Introduce**
> *Writers, we've been working on making each part of our writing match what the whole piece is
> about. Today we're going to focus on topic sentences…*
>
> **Step 2A — Tell** *(the strategy, explained)*
>
> **Step 2B — Show** *(the teacher thinks aloud, in first person, at length — this is where the
> depth lives)*
>
> **Step 3 — Interact** *(students join in, using four exact required phrases)*
>
> **Step 4 — Close**
> *…Now it's your turn!*
>
> *If you have the 3-12 Launch book, you'll find this lesson on p. 66.*

Notice what is load-bearing in that output — and note that **every one of these is enforced by
logic, not by hoping the model complies**:

- the **header** (`Grade 4 | Informative`) — computed from what the *teacher* said, never from
  what the model decided the writing mode was
- the **verb-led title** — a statement of what students will *do*
- the **four separate steps** — a required structure, not a formatting convention
- **Step 2B is by far the longest section** — the think-aloud is the pedagogy
- the **four exact classroom phrases** in Step 3 — required, and checked
- the **grade-band closing line** — *"Now it's your turn!"* because this is grade 4; a K-2 lesson
  would say *"Let's go be writers!"*
- the **citation** — built from the actual source the lesson was written from, or **omitted
  entirely**. Never guessed.

---

## 1.4 Why this is harder than it looks

If you have built a retrieval-augmented chatbot before, the temptation is to see this as
*"find some relevant text, prompt a model, return the answer."* That version was built. It failed
— repeatedly, and instructively. Four things make this domain unusually demanding.

### (a) Fidelity is the product

A generically-good writing lesson is a **failed** output. The teacher is paying for *this*
publisher's method. "Plausible and helpful" is the failure mode — because a plausible wrong
answer is undetectable to the teacher and destroys trust in one turn.

### (b) The rules are numerous, specific, and interacting

Vocabulary rules that depend on grade *and* writing mode. Closing phrases that depend on grade
band. Formatting that depends on the kind of question. Ranking that must always favour two
specific books. Words that may never appear. A lesson may teach exactly one skill. Dozens of
these — each individually trivial, collectively a system.

### (c) The hard requirements live in **multi-turn** conversation

Nearly every serious defect found in this project was fine on turn one and broken on turn two:

- the teacher states a grade, then asks a follow-up — the grade must survive
- the assistant offers a numbered list and the teacher says *"number 4"* — that must resolve to
  the right item
- *"go deeper on that"* must inherit the skill, grade and mode without re-asking
- *"actually, make it 7th grade"* must rebuild the previous request — and corrections must
  **accumulate**
- *"what page is that on?"* is meaningless without the previous turn

Testing single questions in isolation is **structurally blind** to all of it.

### (d) The output is non-deterministic, so the checking must be property-based

You cannot assert exact text against a language model. Every rule therefore needs two things: a
check that the rule was actually *given* to the model, and a check that the output *satisfies the
property*. Chapter 11 is entirely about this distinction.

---

## 1.5 The two design principles that explain everything

If you remember nothing else architectural, remember these.

### 1 · Classify first, act second

One structured "understanding" pass converts a messy human sentence — **plus the entire
conversation so far** — into a crisp, typed decision. Everything downstream trusts that decision
instead of re-interpreting the raw text.

This is why the assistant doesn't re-ask for a grade you gave three messages ago: **the whole
conversation is re-read, in full, on every single turn.**

### 2 · The model writes the content; deterministic logic enforces the rules

Every client rule that *can* be enforced mechanically, is:

| Enforced mechanically | Left to the model |
|---|---|
| Which sources outrank which | The teaching prose itself |
| Banned words | Whether a metaphorical "story" is legitimate |
| The exact required classroom phrases | The content of the think-aloud |
| The grade-band closing line | Which sub-skills to list |
| The header line | Judgment calls the client explicitly wanted judged |
| Which page is cited — or that none is | A fuzzy match on a lesson name |
| *"Number 4"* resolving to the fourth item shown | |

The dividing line is roughly:

> **Arithmetic and facts are handled in code. Judgment is left to the model.**

Where this project got it wrong, it got it wrong by leaving a *fact* to the model. The most
expensive example: an ordinal pick — *"number 4"* — was inferred rather than counted, and the
assistant silently returned the **third** item. Confidently. Correctly formatted. Wrong lesson.
No signal to the teacher that anything had happened.

---

**Next:** [02 — Domain Primer](02-domain-primer.md)
