# 17 — Working Through It

A suggested path. Not a rulebook — but **the order matters more here than it usually does**, because
much of this system's design only makes sense once you know what it is defending against.

---

## The reading path

### First — the ground

| Order | Chapter | Why this order |
|---|---|---|
| 1 | [Orientation](01-orientation.md) | What the thing is, and why *fidelity* rather than helpfulness is the product |
| 2 | [Domain Primer](02-domain-primer.md) | **You cannot follow anything else without this vocabulary** |
| 3 | [The Hard-Won Lessons](14-hard-won-lessons.md) | Read this **early**, not last. It explains why almost everything else is shaped the way it is |
| 4 | [Life of a Request](04-request-lifecycle.md) | The spine |
| 5 | [The System at a Glance](03-system-overview.md) | The pieces, and why each technology was chosen |

> **Do the exercise at the end of Chapter 4 before moving on.** If you can explain the delivery
> switch to someone else — what it is, and why a correctly-implemented rule can silently never reach
> a user — you have the single most important idea in the system.

### Then — how it works

Chapters [05](05-query-understanding.md) through [10](10-knowledge-base.md), in order. They build on
each other: understanding → memory → finding content → shaping an answer → writing and checking it →
where the content came from.

**A worthwhile exercise while you read:** each of those chapters names things that *exist but do
nothing* — a signal computed and never acted on, a whole mechanism that is never populated, a repair
module nothing calls. **Keep a list.** By chapter 10 you will have internalised the most useful
instinct on this project: **existence is not wiring.**

### Then — how the work gets done

| Chapter | Why |
|---|---|
| [How It Is Verified](11-testing-and-verification.md) | The five layers — and the four shapes of a check that cannot fail |
| [How It Runs in Production](12-running-and-ops.md) | The constraints and the failure modes that mislead people |
| [How This Team Works](13-ways-of-working.md) | The rituals, the green gate, and the working agreements |
| [Current State and Roadmap](15-current-state-and-roadmap.md) | What's real, what's owed, what's next |

---

## The habits that actually matter here

These separate the people who do well from the people who ship confident mistakes.

**1 · Go to the original.** Not a requirements line, not a status report, not this handbook. The
client's own annotated document, his recording, his screenshot. **Every one of roughly sixteen
recorded defects started as a summary that had drifted.**

**2 · Test it before you believe it.** You read the logic, you're certain. You're not — you have a
hypothesis about behaviour. Three live probes cost ten minutes.

**3 · Ask whether your check could fail.** And whether it could pass. Construct the output that
*should* break it. If you can't, you don't have a check.

**4 · Restart before you observe.** The engine does not reload on change. This has caused a wrong
verdict here before.

**5 · Follow it to the user.** "Implemented and passing" is not delivery. One feature passed
everything for weeks and **never worked a single day.**

**6 · Report what you measured, not what you expect.** *"Implemented but never exercised live"* is a
respected answer here. **A confident wrong number is not.**

**7 · When you disagree, say so with evidence.** Several of the best catches in this project's
history came from someone executing a brief and pushing back on it. **That is expected, not rude.**

---

## Questions worth arguing about in your first week

Not because they're unanswered — because working through them is how the architecture lands.

1. **Why is memory a *re-derivation* rather than a stored state object?** What did the previous
   approach get wrong — and what did deleting it cost? *(Both halves have real answers.)*
2. **Why is "the client's books first" an absolute category rather than a large score bonus?**
   There's a specific piece of arithmetic that killed the bonus approach. Reconstruct it.
3. **Why does the presence of one form control delivery, instead of both being sent?** There is a
   real answer — and also a real critique. Form your own view.
4. **The quality judge fails *open* — twice.** When is that the right call, and when would it be
   badly wrong?
5. **The knowledge base was built by hand, at considerable cost.** Where would automation have been
   safe, and where would it have been fatal?
6. **Roughly sixteen defects were born in the team's own analysis.** Pick two from Chapter 14 and
   work out what specific practice would have caught each one *earlier* than it was caught.

---

## How to think about this document

Treat it exactly the way the team treats every other document here.

Everything in it was established by examining the running system and measuring it. But documents
decay — **and on this project, "our summary of the thing became the specification" is the single most
expensive recurring mistake.** Several documents inside the project describe a version that was
replaced months ago while still looking authoritative.

So:

> **If this handbook and the real system disagree, the system wins — and this handbook needs
> fixing.** Say so when you find one. That is the most useful thing a new pair of eyes can do here.

---

**Back to:** [Start Here](00-README.md)
