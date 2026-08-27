# Setup — Running It Locally

Everything you need to get the co-pilot running on your own machine.

**Budget about 30 minutes**, most of it waiting for two index builds. **Total API cost of a full
setup: well under a dollar.**

> Follow the steps **in order.** Two of them depend on artifacts the previous step creates, and
> skipping ahead produces confusing failures rather than clear ones.

---

## 0 · Prerequisites

| | |
|---|---|
| **Python 3.10+** | On many machines the command is `python3`, not `python`. Every command below uses `python3` |
| **An OpenAI API key** | Your own. **The project ships no key and never will** |
| **~150 MB free disk** | For the two indexes you're about to build |

---

## 1 · Install dependencies

```bash
git clone <this-repo>
cd <this-repo>

pip3 install -r backend/requirements.txt -r backend/requirements-dev.txt
pip3 install -r frontend/requirements.txt
```

> `requirements-dev.txt` is **not optional** if you want to run the tests — the suite will not
> even collect without `pytest-asyncio`.

---

## 2 · Configure

```bash
cp backend/.env.example backend/.env
# edit backend/.env — paste your OpenAI key into OPENAI_API_KEY

cp frontend/.streamlit/secrets.toml.example frontend/.streamlit/secrets.toml
# edit it — choose any local password you like
```

Both files are gitignored. **Read the comments in `.env.example`** — two of them will save you a
confusing hour.

---

## 3 · Build the two indexes

Neither can be shipped in the repository — one is derived, the other is ~93 MB, far past what a
repository should hold. Both are built from content that **is** in the repository, so all you need
is your key.

### 3a · The search index

```bash
cd backend
python3 ingest.py
```

A couple of minutes. Costs roughly **four cents**. Creates `backend/qdrant_data/`.

> ⚠️ **This is destructive.** Its own description says "idempotent" — which means *the end state
> is the same*, not that nothing is destroyed along the way. It **deletes and recreates** the
> collection. If it fails halfway you have a partial index and no backup.
>
> **Never run it while the backend is running** — they contend for the same exclusive lock.

### 3b · The lesson-question index

```bash
cd backend
python3 scripts/build_ml_library_index.py
```

Produces `backend/data/ml_library_embeddings.json` (~93 MB). There's a fingerprint cache, so
re-running after editing a single lesson costs **one API call rather than 1,471**.

---

## 4 · Verify

```bash
cd backend
python3 -m pytest tests/unit -q
```

**Expect: `2092 passed` in about ten seconds.**

```bash
cd frontend
python3 -m pytest -q
```

**Expect: `20 passed`.**

The backend suite makes **no network calls** — every model call in it is substituted. But it does
need step 3b's index file on disk, and one check confirms your key is actually configured. That's
why verification comes *after* setup, not before.

> Don't run a bare `python3 -m pytest` from `backend/` — that also collects the live acceptance
> suite, which needs a running server and real money, and you'll get a wall of confusing failures.

**If you get 23 failures** all mentioning a missing embedding index, you skipped step 3b.
**If exactly one fails** complaining about an empty key, you skipped step 2.

---

## 5 · Run it

**Two terminals.**

Terminal 1 — the backend:

```bash
cd backend
env -u OPENAI_API_KEY -u OPENAI_BASE_URL \
  python3 -m uvicorn main:app --host 127.0.0.1 --port 8765
```

Terminal 2 — the frontend:

```bash
cd frontend
python3 -m streamlit run app.py --server.port 8501
```

Open **http://localhost:8501**, enter your password, and ask it something:

> *"Give me a 4th grade scripted mini-lesson on topic sentences"*

### Why the odd `env -u` prefix?

Because **a stale key exported in your shell silently overrides `.env`** — the process environment
wins. Clearing those two variables for the command guarantees you're running the configuration you
think you are.

### Why `cd backend` rather than pointing at it?

Because several configured locations are **relative to the working directory** — the `.env` file,
the content directory, the index folder. Starting from elsewhere fails in **two different ways**,
and the second is nasty. See §7.

---

## 6 · Confirm it's healthy

```bash
curl -s http://127.0.0.1:8765/health/live      # is the process up?
curl -s http://127.0.0.1:8765/health/ready     # can it actually serve?
```

Readiness runs three real probes **in parallel** — the search index, the lesson library, and the
model provider. All three must report ok. A failure returns a 503 with per-probe detail, which
usually names exactly which setup step you skipped.

> ⚠️ Readiness makes a real (tiny) API call whenever it isn't cached. Don't point an aggressive
> uptime monitor at it.

---

## 7 · The five traps that will actually bite you

Every one of these is real and has cost someone time on this project.

### 1 · Only ONE backend process at a time

The search index takes an **exclusive lock** on its folder. A second process is refused.

**The nasty part is *when* it fails.** The connection is made lazily, so a second backend **starts
fine, binds its port, and reports itself alive** — then fails on the first request that needs
content, and keeps failing forever after.

> **Symptom:** greetings and clarifying questions work perfectly; **anything needing content
> fails.** Find and kill the other process.

Same applies to running `ingest.py` while the backend is up.

### 2 · The backend does not reload on change

There is no auto-reload. **Editing a file changes nothing that is running.** Restart before you
judge any behaviour.

> Measuring a not-yet-restarted backend has produced a **wrong conclusion** in this project's
> history. If a change "didn't work", check this first.

### 3 · A wrong working directory fails two ways

- With a clean environment: startup fails with *"missing required secret"*, because `.env` is
  found relative to where you started.
- **Worse:** if a key happens to be exported, **it starts successfully anyway** — and the loader
  for the methodology rules quietly returns *"(framework rules unavailable)"*.

> **The system then generates lessons with no methodology rules at all.** The readiness probe
> catches the index half of this. **Nothing catches this half.** Always `cd backend` first.

### 4 · `python`, not `python3`

On many machines the bare `python` command doesn't exist.

### 5 · Rate limiting is per caller identity

50 requests per hour. The frontend sends **one fixed identity for everyone**, so all users share a
single bucket. If you script test conversations, **vary the identity** — a sweep under one identity
once produced 54 rejections that were misread as 28 behavioural regressions.

---

## 8 · The live acceptance suite

Beyond the fast checks, there's a layer that talks to a running backend and **spends real money**:

```bash
cd backend
BRADY_API_BASE=http://127.0.0.1:8765 python3 -m pytest tests/acceptance -q
```

> ⚠️ **It defaults to the wrong port.** You *must* set `BRADY_API_BASE`, or it tries port 8000 and
> fails confusingly.

Don't run this casually. It exists for milestone verification, not routine development.

---

## 9 · What to read next

- **[`../README.md`](../README.md)** — the map of what's where, and the known issues worth knowing
  on day one.
- **[`handbook/00-README.md`](handbook/00-README.md)** — the full engineering handbook: the
  product, the architecture, the teaching method the system encodes, how each part works, how it's
  verified, and the hard-won lessons.

> The handbook is written **conceptually, without file paths** — deliberately. It explains *why*
> the system is shaped the way it is; this file covers the *how*. Read handbook chapters 01, 02
> and 04 before changing anything, and chapter 14 before you trust anything.
