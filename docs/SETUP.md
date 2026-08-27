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
| **Python 3.10+** | On macOS/Linux the command is usually `python3`; **on Windows it is normally `python`**. Commands below are written for a Unix shell — Windows equivalents are given where they differ |
| **An OpenAI API key** | **Your own.** The project ships no key and never will. Don't reuse a shared or production key: it puts your usage on someone else's bill and inside their rate limit |
| **~150 MB free disk** | For the two indexes you're about to build |
| **~250 MB download** | One dependency (`onnxruntime`, via `fastembed`) is large. On a slow or filtered network it is the step most likely to fail — see §9 |

> **On Windows**, PowerShell is assumed. Everything works, but three things differ: file copying,
> clearing an environment variable, and the fact that `python3` is usually just `python`. Both
> variants are shown at each step.

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

**macOS / Linux:**

```bash
cp backend/.env.example backend/.env
cp frontend/.streamlit/secrets.toml.example frontend/.streamlit/secrets.toml
```

**Windows (PowerShell):**

```powershell
Copy-Item backend\.env.example backend\.env
Copy-Item frontend\.streamlit\secrets.toml.example frontend\.streamlit\secrets.toml
```

Then edit both: paste **your own** OpenAI key into `OPENAI_API_KEY`, and choose any local password
you like for the frontend.

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
# macOS / Linux
cd backend
env -u OPENAI_API_KEY -u OPENAI_BASE_URL \
  python3 -m uvicorn main:app --host 127.0.0.1 --port 8765
```

```powershell
# Windows (PowerShell) — there is no `env -u`; clear the variables first
cd backend
Remove-Item Env:OPENAI_API_KEY  -ErrorAction SilentlyContinue
Remove-Item Env:OPENAI_BASE_URL -ErrorAction SilentlyContinue
python -m uvicorn main:app --host 127.0.0.1 --port 8765
```

Terminal 2 — the frontend:

```bash
# macOS / Linux
cd frontend
python3 -m streamlit run app.py --server.port 8501
```

```powershell
# Windows
cd frontend
python -m streamlit run app.py --server.port 8501
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

---

## 7a · If you are sharing a server with a live deployment

**Read this before you run anything** if your machine also hosts a running instance that someone
else depends on. Four things will bite you, and two of them are visible to *other people*.

### 1 · 🔴 Never run the index build from someone else's directory

`ingest.py` **deletes and recreates** the search index. Run it from the wrong working directory
and you rebuild **their** index — taking a live service down, mid-use, with no warning.

**Before running it, confirm where you are:**

```bash
pwd     # must be YOUR clone's backend/, not anyone else's
```

### 2 · 🔴 Clear any inherited API key

A key exported in the shell **silently overrides your `.env`** — the process environment wins.
On a shared box you may inherit someone else's key without ever seeing it, which puts your
traffic on their account, their bill, and their rate limit.

```bash
echo "${OPENAI_API_KEY:+A KEY IS EXPORTED — clear it}"   # prints a warning if set
unset OPENAI_API_KEY OPENAI_BASE_URL
```

The `env -u ...` prefix in §5 does this per-command. On a shared server, do it for the whole
shell.

### 3 · Use your own ports

A live instance is probably already on the default ports. Pick your own and keep them together:

```bash
# backend
python3 -m uvicorn main:app --host 127.0.0.1 --port 9765

# frontend — it must be told where your backend is
python3 -m streamlit run app.py --server.port 9501
```

> ⚠️ **The frontend has the backend's address hardcoded near the top of its main file, with no
> environment override.** If you move the backend and don't edit that constant, your UI will
> connect to **whatever else is on the default port** — i.e. the other instance. Everything will
> appear to work, you'll be debugging someone else's process, and you'll be consuming their rate
> limit while doing it.
>
> Making that constant read an environment variable (falling back to today's default) is a small,
> genuinely useful first contribution.

Check what's already taken before you choose:

```bash
ss -tlnp | grep LISTEN
```

### 4 · Don't restart shared services

If the live instance runs under the same login as you, you can stop it by accident. Start your
own processes **in the foreground, in your own terminals** — don't touch anything you didn't
start.

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

## 9 · Install problems

### "THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE"

**Almost certainly a truncated download, not tampering.** Look at the hash pip says it *got*:

```
Got  e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
```

**That value is the SHA-256 of an empty file.** pip received **zero bytes** and correctly refused
to install them. The message is generic and alarming; this cause is mundane.

It is usually `onnxruntime` (~200 MB, pulled in by `fastembed`), because it's the largest download
and therefore the one a flaky connection truncates.

```bash
pip cache remove onnxruntime
pip install --no-cache-dir onnxruntime
pip install -r backend/requirements.txt -r backend/requirements-dev.txt
```

If it fails again at the same package, the problem is the **network path** — a corporate proxy,
VPN, or antivirus scanner is truncating the transfer. Try a different network before anything
else.

> **Note:** none of this project's requirements files pin hashes. Any hash pip mentions comes from
> the package index itself. So *"update the hashes"* — pip's own suggestion — is **not** the fix
> here, and there is nothing in this repository to update.

Do **not** work around it by dropping `fastembed`. It provides the keyword half of the search, and
without it retrieval silently degrades to meaning-matching only.

### Anything else during install

Re-run with `--no-cache-dir` first. A corrupted cache entry explains most one-off install failures,
and it costs a minute to rule out.

---

## 10 · What to read next

- **[`../README.md`](../README.md)** — the map of what's where, and the known issues worth knowing
  on day one.
- **[`handbook/00-README.md`](handbook/00-README.md)** — the full engineering handbook: the
  product, the architecture, the teaching method the system encodes, how each part works, how it's
  verified, and the hard-won lessons.

> The handbook is written **conceptually, without file paths** — deliberately. It explains *why*
> the system is shaped the way it is; this file covers the *how*. Read handbook chapters 01, 02
> and 04 before changing anything, and chapter 14 before you trust anything.
