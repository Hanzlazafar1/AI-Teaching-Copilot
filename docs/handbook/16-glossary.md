# 16 — Glossary

Every domain and project term you'll meet. Keep this open while you read the rest.

---

## The teaching method

| Term | Plain English |
|---|---|
| **Mini-lesson** | A short, scripted, single-skill teaching block a teacher reads aloud in about 15 minutes. The product's flagship output |
| **The four-step lesson** | Introduce · Tell · Show · Interact · Close. **Five pieces; "four steps" because Step 2 splits into Tell and Show** |
| **Step 2A / 2B** | *Tell* versus *Show*. 2A explains the strategy; 2B models it in first person. **The depth lives here** — 2A at least twice, 2B at least three times the length of Step 1 |
| **Think-aloud** | First-person narration of the teacher's own thinking while doing the skill, so students hear the invisible mental work. The client's illustrative phrasing: *"I close my eyes, I wonder…"* It is Step 2B's content, and it has its own request type and its own check |
| **Turn and talk / Back to me** | Two of the four required Step-3 phrases. *"Turn and talk"* is the method's replacement for the **banned** word "discuss" |
| **The grade-band close** | The required last line of Step 4: **the youngest band** gets *"Let's go be writers!"*, **everyone else** gets *"Now it's your turn!"* |
| **Grade band** | K-2, 3-5, 6-8, 9-12 (plus "K-12" and "all"). **A stated band counts as a stated grade** and must never be re-asked |
| **Mode / PIE** | Persuade · Inform · Entertain. Rendered to teachers as **adjectives** — *"Informative"* — never as the internal token |
| **The traits** | Ideas, Organization, Voice, Word Choice, Sentence Fluency, Conventions |
| **The Launch books** | The client's two flagship titles — one for the youngest band, one for older students. **Always ranked first** |
| **Part 1 / the first sections** | The routines-and-management first ~60 pages of a Launch book. **Not writing skills** |
| **Named strategy** | A memorable nickname for a technique — *pizza table*, *Snapple details*, *read-up-write-down*. **46** of them, with **180** spoken synonyms |
| **Details not reasons** | A conditional vocabulary rule: brainstorming and listing → always "details"; the youngest grades in opinion writing → a **hard ban** on "reasons"; older students composing a paragraph → "reasons" is allowed |
| **Story only for narrative** | "Story" may label the *piece* only in narrative writing. Deliberately **not** a blanket ban on the word |
| **Banned words** | "activity", "discuss", and professional-development plugs. Never emitted; a cleaning pass is the last-resort backstop |
| **One-skill guard** | The fixed note prepended when a teacher crams a second skill into one lesson |
| **Series** | One skill taught across 2–4 cumulative days — layering the explanation, escalating the rigour |
| **Procedure lesson** | A four-step lesson whose subject is a **routine** rather than a writing skill. The client's rule of thumb: *"writing is a skill; **writer** is a procedure or habit or management"* |
| **Day map** | The client's per-skill plan of what each day of a series should teach. **Owed by him — the only genuine client dependency left** |
| **Subgroup / writing level** | For particular student populations, **grade matters less than the current writing level** — picture, label, word, or sentence stage. The assistant asks rather than assuming |

> ⚠️ There is an **internal colour short-code** for one of the books. It was removed from the
> content and **must never reach a teacher** — teachers recognise the full title, not a colour.

---

## The system

| Term | Meaning |
|---|---|
| **Understanding pass** | The single classify-first stage that reads the whole conversation and produces one typed reading |
| **The reading** | That typed result: the request type, grade, mode, trait, skill, plus signals. **Everything downstream derives from it and nothing else** |
| **Request type** | One of **nine**: scripted mini-lesson, how-to-teach, plan-a-unit, think-aloud, deepen-the-previous, coaching, management, meta, correction |
| **Answer shape** | The mandated layout for each request type |
| **Closer / closing question** | The mandated last question per request type — client-verbatim wording |
| **The answer contract** | The single structure every answer type returns, so delivery can treat them uniformly |
| **The delivery switch** | Whichever form is present — structured lesson or prose — decides what the teacher receives, and setting the structured one **discards** the prose. **The single most consequential contract in the system** |
| **Conversation-as-memory** | The core design: an append-only list of turns, re-read in full every turn, with no mutable session record |
| **The offered list** | What a turn actually showed the teacher, recorded so that *"number 4"* resolves by counting next turn |
| **The pending question** | Which request an open clarifying question was asked on behalf of, so a bare answer resumes it |
| **Piece of content / chunk** | One hand-crafted pedagogical unit plus about 31 labels — "its catalog card". **710** in total |
| **Ranking category** | An absolute rank computed at query time. **Categories beat scores — that *is* the "books first" guarantee** |
| **Rank fusion** | How the meaning-based and keyword-based result lists are combined |
| **Hand-written retrieval questions** | 1,254 teacher-phrased questions written by hand, covering 183 lessons, so problem-language finds lesson-language |
| **The lesson library** | 214 complete ready-to-teach lessons, each linked back to its source |
| **Verbatim pull** | Serving a stored lesson's text rather than generating. **Effectively dormant** — it needs a similarity score measured firing zero times |
| **The sink** | The ranking demotion of the books' routines sections for skill questions — with a **bounded escape hatch** when a teacher *names* the lesson |

---

## Process and verification

| Term | Meaning |
|---|---|
| **Protected Set** | The curated pack of canonical questions plus the must-never-break properties they're checked against |
| **Protected invariant** | A named, machine-checkable property of a whole answer — *not* "the answer equals X" |
| **Golden baseline** | A recorded set of correct live answers, checked against **on properties, not exact text** |
| **Green gate** | The start-of-session rule: re-run the fast suite and compare against the recorded count. **A mismatch is a hard stop** |
| **Wave** | A themed batch of work. One per session; finished only when its definition of done is met |
| **Live gate / driving it** | Running a real multi-turn conversation against a **freshly restarted** system and **reading the output by hand.** The only evidence that counts for a behaviour change |
| **Claim** | The unit of certification: a client rule, its source in his own materials, how to judge it, how important it is, and the conversations that exercise it |
| **Calibration gate** | Measuring the judge against a hand-labelled answer key **before** the campaign runs. Tolerance for wrongly certifying a bad answer: **zero** |
| **Dogfooding** | Campaigns where AI agents role-play the client in genuine multi-turn conversations, and analysts judge whole transcripts, human-ratified |
| **A check that cannot fail** | One that cannot fail, cannot pass, or manufactures its own input. **The failure mode this team hunts** |
| **Inert value** | Something that exists but is written by nobody, or read by nobody. **Several live examples** |
| **"Implemented, awaiting acceptance"** | A deliberate honest middle state |

### The status vocabulary

```
proposed → agreed → in progress → implemented → accepted
```

> **"Accepted" means the client signed off. Nothing else does.**

---

## People

| | |
|---|---|
| **The client** | A K-12 writing-instruction publisher. Owns the books, the course, and the methodology |
| **The client contact** | The pedagogical authority on the project. **Their feedback *is* the specification** |
| **The vendor** | Us — the engineering team |
| **The teacher** | The end user — a K-12 writing teacher inside the client's online course. Not a technical user |

---

**Next:** [17 — Working Through It](17-first-two-weeks.md)
