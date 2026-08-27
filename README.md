# AI Writing Co-Pilot

An AI teaching assistant for K-12 writing teachers.

A teacher types a plain-English question — *"How do I teach paragraphing to my 3rd graders?"* —
and gets back either a **classroom-ready four-step mini-lesson script** they can read aloud
tomorrow morning, or **coaching advice** on the teaching problem behind the question.

Everything it says is grounded in **one publisher's writing methodology**, never in generic
internet writing advice. **That constraint is the entire product.**

---

## Start here

| If you want to… | Read |
|---|---|
| **Run it on your machine** | **[`docs/SETUP.md`](docs/SETUP.md)** — start to finish, about 30 minutes |
| **Understand the project** | **[`docs/handbook/00-README.md`](docs/handbook/00-README.md)** — 18 chapters covering the product, the architecture, the teaching method it encodes, how it's verified, and how the team works |
| **Just get oriented fast** | Handbook chapters `01`, `02`, `04`, and `14` |

> **Read handbook chapter 14 early, not last.** It documents roughly sixteen instances of one
> recurring failure pattern on this project, and it explains why almost everything else is shaped
> the way it is.

---

## What's in here

```
backend/          The engine — one HTTP endpoint, and everything behind it
  api/              the web layer, session storage, the delivery boundary
  query/            "understanding": one structured reading of the whole conversation
  handlers/         the nine kinds of answer, plus citations and clarifying questions
  retrieval/        hybrid search, priority ranking, source assembly
  generation/       the four-step lesson structure
  validation/       the rule checks, the AI judge, the repair loop
  schemas/          the shared contracts everything passes around
  chunks/           the knowledge base — 710 hand-crafted pieces of content
  data/             strategy vocabulary, the 214-lesson library, tuning data
  scripts/          index builders and maintenance tools
  tests/            2,092 fast checks + a live acceptance suite
  campaign/         the verification harness (drive → judge → calibrate → verify)

frontend/         The chat interface the client evaluates against

docs/
  SETUP.md          how to run it locally
  handbook/         the full engineering handbook
```

---

## The stack, in one table

| Layer | Choice |
|---|---|
| Web service | Python, async |
| Search | A **locally embedded** vector store — a folder on disk, no server |
| Retrieval | Meaning-based *and* keyword search, fused by rank |
| Generation | A flagship language model |
| Understanding + judging | A cheaper sibling model — these run on **every** turn |
| Session storage | **In process memory.** Deliberate for a pilot; durable storage is a known, unbuilt item |
| Frontend | A lightweight Python web-app framework |

---

## Verification

The verification machinery is **larger than the product** — roughly 17,600 lines of application
logic against ~27,300 lines of automated checks. That ratio is not gold-plating; handbook chapter
11 explains exactly what it defends against.

```bash
cd backend && python3 -m pytest tests/unit -q     # expect: 2092 passed, ~10 seconds
```

That gate needs **no API key and no network**. It is the first thing to run after setup, and the
fastest way to confirm your environment is sane.

---

## Five things to know before you change anything

**1 · Fidelity is the product.** A generically-good writing lesson is a **failed** output. The
teacher is paying for *this* publisher's method, in *this* publisher's words. "Plausible and
helpful" is the failure mode, not the success criterion.

**2 · Classify first, act second.** One structured pass turns a messy sentence — plus the whole
conversation — into a typed decision that everything downstream trusts.

**3 · The model writes the content; deterministic logic enforces the rules.** Roughly: *arithmetic
and facts are handled in code; judgment is left to the model.* Where this project went wrong, it
went wrong by leaving a **fact** to the model.

**4 · The hard requirements live in multi-turn conversation.** Nearly every serious defect was fine
on turn one and broken on turn two. Testing single questions is **structurally blind** to what
matters most.

**5 · A passing check can protect a defect.** See handbook chapter 14.

---

## Known issues worth knowing on day one

Not blockers — but they will confuse you if you meet them cold. Each is covered in the handbook.

| Issue | Where |
|---|---|
| **The flagship lesson path labels its content request differently from what the search layer checks for** — so it silently gets the wrong result count and skips a filter | ch. 7 |
| **"Is this from the client's books?" detection runs entirely on a fallback** — its primary check matches zero of 703 pieces of content | ch. 7 |
| **An entire pending-question mechanism is inert** — types, a renderer, and a whole instruction section that can never fire | ch. 5, 6 |
| **A repair module isn't wired in** — its only caller is a test | ch. 9 |
| **Two checks on the index build cannot fail**, and one asserts the opposite of reality | ch. 10 |
| **Several configuration settings do nothing** — the real values are fixed in the logic | ch. 4 |
| **Dead code from the previous generation still sits inside the live tree** and is not on any active path | ch. 3 |
| **One maintenance script's selector matches nothing** — harmless now (it fails closed and refuses to write), but don't "fix" it casually | ch. 10 |

---

## Ground rules

- **Never commit a secret.** Not in code, not in documentation. Reference *where* it lives, never
  what it is. `.env` and the frontend password file are gitignored — keep it that way.
- **Verification before completion.** Never claim done, fixed or passing without running it and
  showing the result.
- **Restart the backend before you judge behaviour.** There is no auto-reload, and measuring a
  stale process has produced a wrong conclusion here before.
- **Drive it before you believe it.** Reading the logic gives you a hypothesis, not a finding.
