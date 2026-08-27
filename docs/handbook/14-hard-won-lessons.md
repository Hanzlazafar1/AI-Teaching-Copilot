# 14 — The Hard-Won Lessons

> **Read this chapter twice.** Everything else in this handbook tells you how the system works.
> This chapter tells you how this *team* has been wrong, roughly sixteen times, in the same shape —
> and how not to be wrong that way. It is the highest-value chapter here, and the one most likely to
> save you from shipping something confidently broken.

---

## 14.1 The pattern, in one sentence

> **Almost every real defect in this project was born in *our own analysis* of what the client
> asked for, was implemented faithfully, and was then defended by a check that passed.**

Not one of these was a coding mistake. The implementation did exactly what it was told. **The
telling was wrong** — and because a check encoded the same wrong reading, the safety net locked the
defect in place instead of catching it.

The project tracks this as a running count. It stands at roughly **sixteen recorded instances.**

Read a few of them concretely — the abstraction is useless without the specifics.

---

## 14.2 The instances worth knowing

### (a) The strikethrough that got flattened

The client's feedback arrived as an annotated document. Somewhere between his document and our
internal notes, a **struck-through clause was transcribed as live text.** We then built to it. The
product was wrong because our transcript of his document was wrong.

**Second-order damage:** a later verification pass flagged the product's *correct* behaviour as a
defect, because it was being judged against our mis-transcription.

### (b) The quote attached to the wrong screenshot

The client's feedback document is, in his own words, *"mostly snips from the co-pilot"* — 72
screenshots with handwritten notes. Our text export of that document **dropped all 72 images** and
kept the annotations. An annotation belonging to one kind of screenshot therefore floated free and
was read as applying to a completely different feature.

We concluded the client had **contradicted themselves**, and were about to ask them to adjudicate —
a conflict we had manufactured. The real document is a clean two-by-two table with both rows marked
approved.

> **Cost avoided:** asking a client to resolve our own transcription error spends trust you cannot
> buy back.

### (c) The rule that got inverted

The client asked for **"one skill per lesson."** We shipped **"one lesson per skill"** — the mirror
image. That inversion directly contradicted his single biggest new request (a *multi-day series* on
one skill), and **an automated check asserted the inverted rule**, so everything stayed green the
whole time.

### (d) The boundary nobody ever stated

Our ranking logic demoted a specific range of book sections for management questions, and a check
asserted that boundary. **No client document anywhere contains that range.** Both his written
feedback and his recorded walkthrough state a *narrower* one. The boundary was ours: we invented it,
encoded it, and verified it.

*(Nuance worth keeping: a later check found the wider range **does** appear — inside the client's
own book, on its planning page, which is ingested content. So it wasn't fabricated from nothing. But
it was never his instruction, and we cited it as if it were.)*

### (e) "The client said this, verbatim" — quoting ourselves. Four instances.

Four separate internal claims are labelled as the client's own words and, when you follow the
citation, **point at one of our own status documents.** The most striking:

> *"Better to stay silent than lie"* — quoted for months as the client's rule.
>
> What he actually said: *"I loved that **you said**, 'We're going to stay silent rather than lie.'
> Perfect."*
>
> **The phrase is ours.** He endorsed it emphatically — so it is genuinely a requirement — but we
> then hardened a rule of *our own authorship* past anything he had asked for.

### (f) The true finding killed by a comforting sentence

An audit found a real root cause, rated it **low priority**, and explained it away in a single
clause: *"the fallback covers it."*

**That fallback is exactly what failed.** Eight days later the same root cause resurfaced as the
worst product defect of the entire verification campaign: a teacher asked for **"number 4"** and
silently received **item 3** — confidently, correctly formatted, correctly titled, wrong skill, with
no signal anything had gone wrong.

> **The lesson isn't "the audit missed it." The audit *found* it.** An unverified reassuring clause
> downgraded a true finding into noise.

### (g) A passing check that manufactured its own input

The value that makes *"number 4"* work — what the assistant actually showed the teacher last turn —
was **read by production logic and written by nobody except a test fixture.** The check passed
forever. Production never populated it.

Its mirror also exists: another signal is **written but never read** — computed on every turn,
instructed in three separate places, and acted on nowhere.

> Two failure shapes, one family: **a value that exists is not a value that is wired.**

### (h) "Shipped and passing" ≠ the teacher sees it

A formatting requirement was logged as shipped, with everything passing, for weeks. Its history
showed it **never worked a single day** — the delivery boundary discarded the value it produced
before the answer left the system.

This is common enough here to have its own rule (§14.3.4).

### (i) "Blocked on the client" is a hypothesis — four instances, all refuted

Four times an item sat blocked for days awaiting a client decision. Four times **our own data
answered it in about ten minutes**:

| The blocked question | What the data said |
|---|---|
| *"Which lesson should this strategy nickname point to?"* | It's attached to **14 different lessons** — 19 of 40 nicknames name more than one. There is nothing to point at. **And our own protected set already asserted the answer.** |
| *"Which closing question did he mean here?"* | The conflict was ours (see (b)) |
| *"Did our citation change break a form he praised?"* | One live probe: still shipping it, **three times out of three** |
| *"Is this feature blocked on his planning materials?"* | **His own book contains the plan** — and it was already ingested |

### (j) A reading of the implementation is a hypothesis, not a finding

The clearest example had **two true premises and a category error between them**:

1. True: the coaching instruction says *"do not include a book or page citation."*
2. True: the client praised an answer that pointed at a book.
3. **False conclusion:** "we broke the thing they praised."

*"Check the book and its digital resources"* is a **resource pointer**, not a **citation** — a
different speech act. The prohibition never suppressed it. One live probe, three runs, killed a
question that was about to be sent to the client.

### (k) A measurement that measured something else

Several probes were later found to have measured a different question than they claimed. One drove a
whole session's priorities and a client-facing claim, while describing behaviour that had been
**replaced roughly thirty commits earlier.**

A related one: a headline improvement was reported as **"10 out of 30 down to 2 out of 30."** True —
but **25 of those 30 cases were on the path that had been fixed.** On the path that hadn't, the
honest rate was **9 out of 15**. Same numerator, wildly different meaning.

### (l) The check that cannot fail

Across two sessions, **19 checks were found that could not fail** — or, in one case, could not
*pass*: rubrics satisfied by any output, judges shown the criteria and the final answer with the
setup discarded, an answer key lifted from the input itself, and a circular check whose perfect
score proved only that a value equalled itself.

The re-adjudication verdict is worth memorising:

> **The product was largely right. The certification was largely broken.**
>
> Of twelve re-examined verdicts, **not one had been reached by a method capable of detecting a
> violation** — in either direction.

### (m) The most expensive shape: it infects what you *say*

The newest instance wasn't in the implementation at all. A requirement was explained to a colleague
**from our own one-line paraphrase of it**, and the paraphrase had drifted three ways. They asked
*"are you sure?"* — and the client's original recording showed the feature **already partly
worked.**

> **A requirements line is a lossy compression of a client's paragraph.** Open the original before
> you *explain* it, not just before you build it.

---

## 14.3 The working rules that fall out of this

These are not aspirations. They are the practices that actually caught things.

### 14.3.1 Go back to the original before you build *or* explain

Never work from a summary — not a requirements line, not a status report, not this handbook. Open
the client's own artifact: the annotated document, the recording, the screenshot.

**And beware lossy exports.** The text export of the feedback document silently drops all 72
screenshots and flattens colour-coding that carries meaning (one colour = tested and approved,
another = a new request). **A quote pulled from that export is unanchored** until you open the image
it refers to.

### 14.3.2 A reading of the implementation is a hypothesis. Test it.

You read the instruction, you read the logic, you are *certain* what the system does. You are not.
You have a hypothesis about behaviour. **Send the request and read the answer.**

Three live probes cost about ten minutes. That is cheaper than every alternative, **including being
right.**

### 14.3.3 Ask of every check: *could this ever fail? could it ever pass?*

Before you trust a check, a rubric or a probe:

- Construct the output that *should* fail it. Does it?
- Construct the output that *should* pass it. Does it?
- Where did the expected value come from — **did it leak in from the input?**
- Is the check seeing enough context to judge? *(A multi-turn behaviour judged on the last turn
  alone is **guaranteed** to lie.)*

**Mutation testing is what caught these.** Break the thing on purpose; if the check stays green, the
check is decoration.

### 14.3.4 "Shipped and passing" is not delivery. Trace it to the user.

The recurring delivery gap here is a rule wired to **one** kind of answer while the teacher's
phrasing routes to **another**. The general fix is a shared rule gated on a signal — **not a second
copy of the rule.**

Before calling anything done, follow the value all the way to what the user actually receives.
There is a specific trap here: **the delivery switch is a switch, not a container.** Setting it
changes what the user gets and discards the alternative. See [Chapter 4](04-request-lifecycle.md).

### 14.3.5 Check what a number's denominator is made of

A rate over a mixed population hides the case you care about. **Split by path before you quote it**
— especially to a client.

### 14.3.6 Does the data already answer this "question for the client"?

Before writing a client question: search the content, run the probe, read the protected set. **Four
for four, it was already answered.**

### 14.3.7 Distinguish what you measured from what you believe

The honesty conventions here are load-bearing, not politeness:

- Never claim done, fixed or passing without running it and showing the result.
- Don't label partial wins "resolved."
- Treat a borderline result as a **possible regression** until probed several times — model output
  varies, and **one sample is not a measurement.**
- Say plainly when something is *implemented but never exercised live.* **That bucket is where the
  surprises live.**

### 14.3.8 Freeze changes during a live measurement

A parallel change landing mid-run invalidates the numbers even when the production behaviour didn't
move. Same family as measuring a system that hasn't been restarted since your edit.

---

## 14.4 Why the safety net is built the way it is

Once you accept that a passing check can defend a defect, the whole verification strategy makes
sense:

| Design choice | The failure it exists to prevent |
|---|---|
| Assert **properties**, never exact text, for model output | A brittle string match that breaks on paraphrase and proves nothing about pedagogy |
| **Instruction-content check + behavioural check**, paired | *"We told the model"* and *"the model obeyed"* are different claims |
| The instruction and the check read the **same table** | They can never drift apart |
| A **live** gate at every milestone | Repeatable offline checks cannot see a delivery gap |
| The protected set is **small, deliberate and hand-maintained** | A regression suite nobody curates decays into noise |
| The protected set **names its own blind spots** | It was citation-blind through three consecutive citation projects — so every "zero regressions" claim on that dimension was **structurally incapable of failing** |

That last row is the culture in miniature. The protected set says, about itself:

> **"A live gate that cannot fail on the thing being changed is not a gate."**

---

## 14.5 Your personal checklist

Pin this somewhere:

- [ ] Did I read **the client's own words**, or somebody's summary of them?
- [ ] Is my belief about behaviour **tested**, or inferred from reading the implementation?
- [ ] **Can my check fail? Can it pass?** Did I break something on purpose to find out?
- [ ] Did I follow the change all the way to **what the user actually receives**?
- [ ] Does my number's **denominator** hide the case that matters?
- [ ] Before I ask anyone a question — **does the data already answer it?**
- [ ] Am I reporting what I **measured**, or what I **expect**?

---

**Next:** [15 — Current State and Roadmap](15-current-state-and-roadmap.md)
