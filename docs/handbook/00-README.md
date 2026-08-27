# AI Writing Co-Pilot — Engineering Handbook

**Everything you need to understand this project — the product, the architecture, the pedagogy it
encodes, how it is built and verified, and how the team works.**

2026-08-25

---

## What this is

An AI teaching assistant for K-12 writing teachers.

A teacher types a plain-English question — *"How do I teach paragraphing to my 3rd graders?"* —
and gets back either a **classroom-ready four-step mini-lesson script** they can read aloud
tomorrow morning, or **coaching advice** on the teaching problem behind the question.

Everything it says is grounded in **one publisher's writing methodology**, never in generic
internet writing advice. That constraint is the entire product.

It runs live today: a Python web service, a hybrid search engine over a hand-crafted knowledge
base built from the client's books and course, a large language model doing the writing, and a
layer of deterministic checks that enforce the client's teaching rules mechanically rather than
hoping the model remembers them.

---

## How to read this

This handbook is self-contained. It explains the system in concepts and diagrams, so you can
finish it with a complete picture of the project before you ever open an editor.

**If you read four chapters, read these:** `01`, `02`, `04`, `14`.

---

## The chapters

### Start here

| | Chapter | What's in it |
|---|---|---|
| **01** | [Orientation](01-orientation.md) | What the product is, who it's for, why *fidelity* is the whole game, and the two design principles that explain every decision downstream |
| **02** | [Domain Primer](02-domain-primer.md) | The teaching method the system encodes — the four-step lesson, the think-aloud, the required classroom phrases, the writing modes, the traits, the named strategies |
| **03** | [The System at a Glance](03-system-overview.md) | Four generations of this system and why three were replaced · the technology and why each piece was chosen · the component map |

### How it works

| | Chapter | What's in it |
|---|---|---|
| **04** | [Life of a Request](04-request-lifecycle.md) | The spine: eight stages from a teacher pressing Enter to an answer on screen — including **the delivery switch**, the most consequential contract in the system |
| **05** | [Understanding the Question](05-query-understanding.md) | Classify first, act second: one structured reading of the whole conversation, and the three places where **plain arithmetic overrules the model** |
| **06** | [Memory](06-session-memory.md) | "The conversation *is* the memory" — why a mutable session record was deleted, what that cost, and the trap of a field that exists but is never filled |
| **07** | [Finding the Right Content](07-retrieval.md) | Meaning-based and keyword search, fused — and how *"the client's books always come first"* is made a **structural guarantee** rather than a scoring preference |
| **08** | [The Nine Kinds of Answer](08-handlers.md) | Where the product behaviour lives: each request type, its shape, its exact closing question · clarifying questions · numbered pick-lists · honest citations |
| **09** | [Writing and Checking a Lesson](09-generation-and-validation.md) | The hard four-step structure, the write→check→repair loop, all eleven rule checks, and the AI quality judge |
| **10** | [The Knowledge Base](10-knowledge-base.md) | 710 hand-crafted pieces of content, 31 labels each, a 214-lesson library, 1,254 hand-written retrieval questions — and why none of it was automated |

### How the work gets done

| | Chapter | What's in it |
|---|---|---|
| **11** | [How It Is Verified](11-testing-and-verification.md) | The five-layer safety net — and the testing philosophy this team enforces on itself, including **the four shapes of a test that cannot fail** |
| **12** | [How It Runs in Production](12-running-and-ops.md) | The deployment shape, the operational constraints, the failure modes that mislead people, and an honest security picture |
| **13** | [How This Team Works](13-ways-of-working.md) | Working memory between sessions, the start and end rituals, the green gate, delivery in waves, and the working agreements |
| **14** | [The Hard-Won Lessons](14-hard-won-lessons.md) | ⭐ **The most valuable chapter.** Roughly sixteen recorded instances of a single failure pattern — and the working rules that came out of them |
| **15** | [Current State and Roadmap](15-current-state-and-roadmap.md) | Where things stand, the requirement ledger with honest statuses, what is owed, and the proposed next phase |

### Reference

| | Chapter | What's in it |
|---|---|---|
| **16** | [Glossary](16-glossary.md) | Every domain and project term, in plain English |
| **17** | [Working Through It](17-first-two-weeks.md) | A suggested path, the habits that matter here, and the questions worth arguing about |

---

## The five things to know before anything else

**1 · Fidelity is the product.**
A generically-good writing lesson is a **failed** output here. The teacher is paying for *this*
publisher's method, in *this* publisher's words. "Plausible and helpful" is the failure mode, not
the success criterion — because a plausible wrong answer is invisible to the teacher and destroys
the client's trust in a single turn.

**2 · Classify first, act second.**
One structured pass turns a messy human sentence — plus the entire conversation so far — into a
crisp, typed decision. Everything downstream trusts that decision instead of re-interpreting raw
text. It is why the assistant never re-asks for a grade you gave three messages ago.

**3 · The model writes the content; deterministic logic enforces the rules.**
Roughly: **arithmetic and facts are handled in code; judgment is left to the model.** Where this
project went wrong, it went wrong by leaving a *fact* to the model.

**4 · The hard requirements live in multi-turn conversation.**
Nearly every serious defect found here was fine on turn one and broken on turn two. Testing a
single question in isolation is **structurally blind** to the things that matter most.

**5 · A passing test can protect a defect.**
This project has roughly sixteen recorded instances of a misreading becoming the specification,
being implemented faithfully, and then being **held in place by a test that passed**. Chapter 14
is about that, and it is the reason the verification machinery is larger than the product itself.

---

## A note on this document

Everything here was established by examining the running system directly and measuring it — not
by summarising earlier documentation. That distinction matters more than it sounds, and Chapter
14 explains why: on this project, *"our summary of the thing became the specification"* is the
single most expensive recurring mistake.

So treat this handbook the way the team treats every other document: **if it disagrees with the
running system, the system wins — and this document needs fixing.** Say so when you find one.
