# FinalSay - Live Demo Script (~7 minutes)

A step-by-step walkthrough for demoing FinalSay live from a clean clone. Every
seeded notice named below comes from `backend/finalsay/seed/dataset.py`. The
defaults are offline: **SQLite + MOCK comparison model + LOCAL anchor**, no paid
keys.

## Read this first (before the demo)

- **Image OCR needs a Tesseract engine, which is not installed in this sandbox.**
  Image submissions return **HTTP 422** asking for pasted text. **PDF and pasted
  text work fully.** For the live demo, **submit pasted text** (or a PDF). If you
  want image OCR, install Tesseract and set `FINALSAY_TESSERACT_CMD` (or leave it
  `auto` if `tesseract` is on `PATH`) before the demo.
- Provenance verification only returns `ok:true` after the daily Merkle root is
  built. The seed builds all daily Merkle roots, so **integrity works on a fresh
  seed**. If you re-seed a clean DB you are covered; you do not need to build
  roots manually.
- The classification label/confidence/rationale are returned by the **submit**
  call and cached client-side for the result screen. A cold reload of
  `/result/:id` still shows fields, candidate, and integrity, and hints to
  re-submit - so **do not hard-reload the result page mid-demo**; navigate with
  the app's own links.

## 0. Start from a clean clone (~1 min, do this before the audience arrives)

```bash
make demo
```

This creates/reuses the backend venv (Python 3.11), installs
`backend/requirements.txt`, seeds the database idempotently, starts the FastAPI
backend on `http://127.0.0.1:8000` (background, docs at `/docs`), then installs
frontend deps and starts the Vite dev server on `http://127.0.0.1:5173`
(foreground). Open **http://127.0.0.1:5173**. Press `Ctrl-C` to stop; the backend
is stopped automatically.

Useful adjuncts (optional): `make test` (backend suite), `make smoke` (end-to-end
smoke), `make eval` (both harness splits).

**Fallback:** if `make demo` fails, run the two processes manually  - 
`cd backend && .venv/bin/python -m uvicorn finalsay.main:app --host 127.0.0.1 --port 8000`
in one terminal, and `cd apps/web && npm install && npm run dev` in another. If the
frontend will not start at all, drive the same flow against the API docs at
`http://127.0.0.1:8000/docs`.

## Seeded demo users (one-click login buttons on the login screen)

| Role | Email | Password |
| --- | --- | --- |
| Student | `student@finalsay.demo` | `student123` |
| Reviewer | `reviewer@finalsay.demo` | `reviewer123` |
| Admin | `admin@finalsay.demo` | `admin123` |
| Issuer | `issuer@finalsay.demo` | `issuer123` |

Institution slugs: `northgate`, `riverside`, `summit`. Official external_ids look
like `<slug>-<topic>-<NN>`, e.g. `northgate-exam-00`. Issuers are "Office of the
Registrar, Northgate University", "Academic Section, Riverside Institute", and
"Registrar Office, Summit College".

---

## The walkthrough (in order)

### Step 1 - Log in as the student (~30 s)

**Do:** On `/login`, click the one-click **Student** demo button (or type
`student@finalsay.demo` / `student123`).

**Say:** "A student forwards a notice they received. FinalSay will extract it,
redact personal data, find the matching official notice, and classify how the two
relate - then let them check the official's integrity."

**Notice:** the nav bar is role-aware; the student sees Submit, Notices, Alerts.

**Fallback:** if the demo button does nothing, type the credentials manually. If
login fails, confirm the seed ran (`make seed`) and that the backend is up at
`http://127.0.0.1:8000/docs`.

### Step 2 - Consistent case (~1 min)

**Do:** Go to `/submit`. In the text box, paste a copy of an official notice that
agrees with it. Use the seeded consistent phrasing style - paste this text:

> `Issued by: Office of the Registrar, Northgate University`
> `Subject: Mid-term examination`
> `Date: 1 Sep`
> `To all students.`
> `The mid-term examination is scheduled on 1 Sep for all students.`
> `This matches the official schedule and remains unchanged.`

Optionally set the institution to Northgate. Submit.

**Say:** "This forwarded notice agrees with the official one - same facts, high
overlap. FinalSay should call it **consistent**."

**Notice:** on `/result/:id`, the relationship badge, the confidence, the
rationale, the extracted-fields evidence table, and the closest official
candidate.

**Fallback:** if the label is not `consistent`, that is acceptable to show
honestly - the mock engine keys on cues and high overlap. If submit errors, make
sure you pasted **text** (not an image), since image OCR is disabled here.

### Step 3 - Superseded case, high-signal (~1 min)

**Do:** Submit a new notice. Use the guaranteed-seeded spotlight low-overlap
superseded submission (present in the seed as `northgate-spotlight-2215` /
`riverside-spotlight-2215`) - paste this text:

> `Mid-term exam moved. It is postponed to 22 Sep from the earlier date.`

Tie it to Northgate (or Riverside).

**Say:** "This is a real-world hazard: a later notice quietly replaces an earlier
one. The official said 15 Sep; this says 22 Sep. FinalSay should classify it as
**superseded**, not treat it as a fresh independent notice."

**Notice:** the `superseded` label with a rationale referencing the date change;
the extracted date field `22 Sep`.

**Fallback:** if the label comes back gated to `unresolved`, that is an honest
outcome - point out that FinalSay routes low-confidence cases to a human reviewer
rather than guessing (its false-confirmation rate is 0.000). Then continue.

### Step 4 - Low-vocabulary-overlap date conflict (~1 min)

**Do:** Submit again, this time using the held-out naturalistic superseded
phrasing (the phrasing the temporal split evaluates), which shares almost no
vocabulary with the official - paste this text:

> `Heads up: the mid-term examination originally set for 15 Sep will now take place on 22 Sep instead.`

Tie it to Northgate.

**Say:** "This is why we need a semantic model, not keyword matching. 'Exam
postponed to 22 Sept' and 'exam on 15 Sept' share almost no words but are directly
related. This is the naturalistic phrasing our held-out evaluation uses - not
engineered around the rule cues."

**Notice:** whether the relationship is captured despite the low lexical overlap,
and the two conflicting dates in the evidence.

**Fallback:** if it returns `unresolved` on the mock model, say so plainly - this
is exactly the honest held-out behavior (temporal-split FinalSay F1 is ~0.05 with
the mock model), and the confidence gate sends it to review rather than
confirming a wrong answer. Move on.

### Step 5 - Ambiguous case that correctly returns unresolved (~1 min)

**Do:** Submit a deliberately ambiguous, low-signal notice (the seeded
`unresolved` gold phrasing) - paste this text:

> `Kindly clarify the arrangement mentioned in the circular; the details appear unclear regarding venue and timing.`

**Say:** "When FinalSay is not confident, it must NOT confirm. Below the
confidence threshold (0.6) it labels the case **unresolved** and opens a reviewer
case. That is the safety property - a 0.000 false-confirmation rate."

**Notice:** the `unresolved` label, the `gated:true` tag, confidence below 0.6,
and that a review case was opened.

**Fallback:** if it does not gate, submit an even shorter fragment (e.g. `Please
see the circular.`). The point to land is the gating behavior, not a specific
string.

### Step 6 - Tamper-detection / integrity flow (~1.5 min)

**Do:** On a result or notice detail screen for an official notice, click
**Verify document integrity**. It should show `ok:true` (integrity intact). Then
click **Simulate tamper** (this calls
`GET /api/provenance/verify/{notice_id}?tamper=true`).

**Say:** "Every verified official notice is hashed, and the daily hashes are
combined into a Merkle root that is anchored - locally by default, on the Polygon
Amoy testnet if configured. If a stored document is altered, the recomputed hash
no longer matches the anchored root."

**Notice:** the verify result flips from `ok:true, tamper:false` to
`ok:false, tamper:true`. The seed builds all daily Merkle roots, so this works on
a fresh seed.

**Fallback:** if verify shows a "no proof yet" banner (`ok:false` but not a
tamper), an admin needs to build the daily root: log in as
`admin@finalsay.demo` and `POST /api/provenance/build` (no body → today's UTC
day), or re-run `make seed`. Then retry Verify → Simulate tamper. If the UI
button is unavailable, hit the endpoint directly at
`http://127.0.0.1:8000/docs`.

### Step 7 - (Optional, if time) Reviewer console (~30 s)

**Do:** Log out and log in as `reviewer@finalsay.demo` / `reviewer123`. Open
`/reviewer/queue` to see the unresolved case from Step 5; open
`/reviewer/benchmark` to show the two-annotator screen and the Cohen's kappa
report (**0.625**).

**Say:** "Unresolved cases land here for a human to confirm or correct. And this
is the 308-pair labelled benchmark with two annotators - Cohen's kappa 0.625."

**Fallback:** if the queue is empty, re-run Step 5 to generate an unresolved case,
then refresh the queue.

---

## One-line recap for the close

"FinalSay extracts and redacts a forwarded notice, retrieves the matching official
via semantic comparison, classifies the relationship, refuses to confirm when it
is not sure (0.000 false-confirmation), and gives every official notice a
tamper-evident, anchored provenance trail."
