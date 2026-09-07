# FinalSay — HANDOFF

Live status of the build. Updated after every task/feature.

## How to run from a clean clone (target state)

```bash
make demo            # SQLite + MOCK model + LOCAL anchor, no paid keys, one command
# backend: http://127.0.0.1:8000  (docs at /docs)   frontend: http://127.0.0.1:5173
make test            # backend pytest suite
make eval            # evaluation harness, both splits
scripts/run_demo.sh --postgres   # optional: boot in-session PostgreSQL instead of SQLite
```

Python must be 3.11: the run script uses `~/.pyenv/versions/3.11.15/bin/python` to create
`backend/.venv`. Node v22 is default.

## Spec files
- `requirements.md` — EARS requirements (authoritative scope, 6 modules + 4 actors).
- `design.md` — architecture, file layout, data model, interfaces, run strategy.
- `tasks.md` — ordered tasks T1–T11 (consolidated into features FEAT-001..005).
- Task state: `.agents/tasks/task-finalsay-prototype/`.

## Feature checklist
- [x] FEAT-001 (T1) Backend scaffold, config, DB+models, JWT auth, logging — DONE (6 pytest pass)
- [x] FEAT-002 (T2–T4) Extraction, Provenance+Anchor, Comparison+ComparisonModel — DONE (20 pytest pass)
- [x] FEAT-003 (T5–T8) Ingestion/adapters, Reviewer+kappa, Seed, Eval harness — DONE (45 pytest pass)
- [x] FEAT-004 (T9) React+Vite PWA, all actor routes — DONE (npm run build green; PWA manifest + service worker emitted; every actor route wired to a live API)
- [x] FEAT-005 (T10–T11) One-command run, Makefile, README, .env.example, deadline-regex fix, final verification — DONE (45 pytest pass; both harness splits exit 0 with deadline F1 1.000; npm run build green; run_demo.sh executable; TestClient happy-path smoke passed)

## Environment findings (sandbox — important for the next session)
- OS Amazon Linux 2023. Python 3.11.15 via pyenv; Node v22; OPEN_INTERNET (pip/npm work).
- **/tmp is tmpfs and is wiped between separate shell/tool invocations.** All venvs, DBs,
  and artifacts must live under `/projects/sandbox`.
- **Background daemons are reaped across separate tool calls** (`--die-with-parent`). A
  server started with `&` in one command is gone by the next command. Servers only survive
  within a single foreground session; tests use in-process TestClient.
- **PostgreSQL 15 is installed** and works (initdb done at /var/lib/pgsql/data; must start
  with `-k /var/run/postgresql` and only that socket dir because `/tmp` lock file perms
  fail; `listen_addresses='127.0.0.1'`). Because daemons don't persist across steps, the
  demo **defaults to SQLite** for reliability; Postgres is supported via
  `FINALSAY_DATABASE_URL` and `run_demo.sh --postgres`.
- **Tesseract binary is NOT installable** in AL2023 repos (no package; EPEL conflicts).
  `pytesseract` imports but there is no OCR engine. Extraction must degrade gracefully:
  images without an engine raise a typed `OcrUnavailable` surfaced as HTTP 422 prompting
  pasted text; PDF/paste paths work fully.

## FEAT-001 build notes (backend foundation)
- `backend/.venv` created with `~/.pyenv/versions/3.11.15/bin/python -m venv`; all
  `backend/requirements.txt` installed. Backend package is `finalsay` under `backend/`.
  Run backend commands from `backend/` (cwd) or with `PYTHONPATH=backend`.
- Implemented: `config.py`, `db.py`, `models.py` (all 11 design §3 models incl. relational
  `relation_edge`), `schemas.py`, `auth.py`, `logging_conf.py`, `main.py` (`create_app()`
  + request-logging middleware + `GET /api/health` + `create_all` on startup),
  `api/auth.py` (register/login/me). Tests: `tests/conftest.py` (in-process TestClient on a
  temp SQLite DB kept under the backend tree, not /tmp) + `tests/test_auth.py` (6 tests,
  all green): health, register→login→me, dup 409, bad password 401, unauth /me 401, and
  `require_role` 403-vs-200.
- Verify: `cd backend && .venv/bin/pytest finalsay/tests -q` (6 passed);
  `.venv/bin/python -c 'import finalsay.models,finalsay.config,finalsay.auth,finalsay.db'`;
  `.venv/bin/python -c 'from finalsay.main import create_app; create_app()'`.
- **DEPENDENCY DEVIATION (important for FEAT-002+):** added `email-validator` (needed by
  Pydantic `EmailStr`) and pinned **`bcrypt<4.1`** (4.0.1 installed) to
  `backend/requirements.txt`. bcrypt 5.0.0 is incompatible with passlib 1.7.4's backend
  detection and breaks password hashing. Keep this pin; do not upgrade bcrypt.
- Added `/projects/sandbox/.gitignore` (venv, `*.db`, `finalsay-test-*`, `__pycache__`,
  `.pytest_cache`, `node_modules`, `dist`, `.env`).
- No git repo initialized yet (orchestrator publishes later); no commit made this feature.

## FEAT-002 build notes (extraction, provenance+anchor, comparison)
- New backend modules (all under `backend/finalsay/`):
  - `services/extraction.py` — `acquire_text()` (PDF via pypdf, image via pytesseract
    only when a binary is present else raises typed `OcrUnavailable`, pasted text direct);
    `extract_fields()` for issuer/date/deadline/audience/action (regex, per-field
    confidence); `redact()` masks emails, phones, roll numbers
    (`\b\d{2}[A-Z]{2}\d{4,}\b`), `Mr./Ms./Dr. Name` and `Name: X`. `extract()` returns
    ONLY redacted text + fields (fields parsed from the redacted text — defense-in-depth
    for GC-5/R2.4).
  - `models_iface/anchor.py` — `Anchor` ABC; `LocalHashChainAnchor` (default) appends
    `anchor_block` rows with `prev_hash`/`this_hash` chaining, never blocks;
    `PolygonAmoyAnchor` (opt-in) lazy-imports `web3` and try/excepts down to local on any
    failure (GC-3/R3.5). `get_anchor(db)` defaults local.
  - `services/provenance.py` — `sha256_notice()` canonical hash;
    `build_daily_merkle(db, day)` binary tree (duplicate last leaf on odd count), stores
    `merkle_root` + one `merkle_proof` per notice, anchors the root; `verify_notice(db,
    id, tamper=False)` recomputes hash + root from stored proof -> `{ok, tamper, details}`
    (detects both the demo tamper flag and real content mutation).
  - `models_iface/comparison_model.py` — `ComparisonModel` ABC;
    `MockComparisonModel` (default, deterministic rule engine + optional fixture map;
    "22 Sept vs 15 Sept" -> superseded, never consistent); `HFComparisonModel` (opt-in)
    lazy-imports `transformers` zero-shot NLI. `get_comparison_model()` defaults mock.
  - `services/comparison.py` — `retrieve_candidates()` (filter official by institution,
    audience boost, Jaccard overlap, top-K=5); `classify_submission()` gates below
    `FINALSAY_CONFIDENCE_THRESHOLD` (0.6) -> label `unresolved` + creates `review_case`,
    always persists a `relation_edge` (label/confidence/rationale/model/status). No
    candidate also routes to unresolved.
  - `api/provenance.py` — `POST /api/provenance/build` (admin), `GET
    /api/provenance/verify/{notice_id}?tamper=`. `api/comparison.py` — `POST
    /api/compare/{submission_id}`. Both routers wired into `main.create_app()`; added
    Merkle/Comparison Pydantic schemas.
- Tests: `test_extraction.py` (5), `test_provenance.py` (5), `test_comparison.py` (5).
  Full suite: **20 passed** (`cd backend && .venv/bin/pytest finalsay/tests -q`).
- Verified defaults need NO env vars: mock model + local anchor; `web3`/`transformers`
  are NOT imported on the default path (confirmed via `sys.modules` check).
- **Gotcha for later features:** this FastAPI/Starlette version represents
  `app.include_router(...)` as `_IncludedRouter` mount objects, so a naive
  `route.path`-based listing will only show `/api/health`. The routes ARE registered —
  confirmed via TestClient (build/verify/compare return correct 404s for missing data).
  Use TestClient or `/openapi.json`, not a route.path filter, to enumerate endpoints.
- Tesseract engine still absent (per FEAT-001): image OCR raises `OcrUnavailable` (to be
  surfaced as HTTP 422 by the ingestion endpoint in FEAT-003); PDF + pasted-text paths
  fully functional.

## FEAT-003 build notes (ingestion, reviewer+kappa, seed, eval)
- New backend modules (all under `backend/finalsay/`):
  - `adapters/base.py` — `InstitutionAdapter` ABC (`fetch() -> list[RawNotice]`),
    `RawNotice` dataclass (text/source_url/institution_slug/external_id), `FixtureAdapter`
    (reads `seed/fixtures/<slug>_official.json`, empty list if missing), `get_adapters()`.
    `adapters/inst_{northgate,riverside,summit}.py` — three fixture adapters.
  - `services/ingestion.py` — shared pipeline: `upsert_official()` (extract->redact->hash,
    **idempotent by (kind, institution, sha256)**), `fetch_all()` (runs all 3 adapters),
    `create_submission()` (student submit), `publish_official()` (issuer stub),
    `get_or_create_institution()`. Only redacted text + fields persisted (GC-5).
  - `services/kappa.py` — `cohen_kappa()` (sklearn `cohen_kappa_score`, manual fallback,
    single-class -> 1.0), `per_label_counts()`.
  - `api/ingestion.py` — `POST /api/ingest/submit` (multipart `file` OR Form `text`; runs
    extraction->hash->comparison; **image w/o OCR engine -> HTTP 422** catching
    `OcrUnavailable`; unknown file type -> 415), `POST /api/ingest/fetch` (admin,
    idempotent), `GET/POST /api/ingest/sources` (admin CRUD, dup slug -> 409).
  - `api/notices.py` — `GET /api/notices` (list, filter by institution/kind),
    `GET /api/notices/{id}` (detail + fields = evidence), `GET /api/notices/{sub_id}/candidates`.
  - `api/issuer.py` — `POST /api/issuer/publish` (role issuer stub; attributes to
    institution by id/slug/first; extraction+hash).
  - `api/reviewer.py` — `GET /api/reviewer/queue` (open cases + edge + both notices),
    `POST /api/reviewer/cases/{id}/resolve {label}` (edge label updated; status
    **confirmed** if label unchanged else **corrected**; case closed + resolved_by/label),
    `GET /benchmark/pairs`, `POST /benchmark/annotate {pair_id,annotator,label}` (upsert per
    (pair,annotator)), `GET /benchmark/kappa` (picks the 2 most-active annotators, compares
    shared pairs, returns kappa + per-label counts).
  - All 7 routers wired into `main.create_app()`. Added ~15 Pydantic schemas to `schemas.py`.
  - `seed/dataset.py` + `seed/seed.py` (`python -m finalsay.seed.seed`): writes 3 official
    fixtures (40 each = **120 officials**) + `gold_submissions.json` (**65 gold-labeled
    submissions** covering EVERY taxonomy label incl. ambiguous->`unresolved` and the
    low-overlap **22-vs-15 Sept -> superseded** spotlights). Seeds **4 demo users**, **14
    benchmark_pairs** with **28 two-annotator annotations** (`reviewer_a`/`reviewer_b`).
    **Idempotent** (guards by slug/email/content-hash/`seed://submission/<key>` marker):
    re-run gives identical counts (3/4/120/65/14/28).
  - `eval/baselines.py` (chronological, page_change, nli, prompted_llm) + `eval/harness.py`
    (`python -m finalsay.eval.harness [--split temporal|institution] [--model mock|hf]`):
    per-field token-set F1 (macro), relationship P/R/F1 (sklearn macro),
    false-confirmation rate, unresolved rate, Cohen's kappa; scores **finalsay + all 4
    baselines** on the split; **both splits exit 0**. temporal holds out `temporal_bucket==1`
    submissions; institution holds out **Summit**.
- Tests: `test_ingestion.py`, `test_reviewer.py` (kappa hand-computed 0.6153846 ±0.001),
  `test_seed.py`, `test_eval.py`. Full suite: **45 passed** (20 prior + 25 new).
- Verify: `cd backend && .venv/bin/python -m finalsay.seed.seed && .venv/bin/python -m
  finalsay.seed.seed` (stable counts); `.venv/bin/python -m finalsay.eval.harness --split
  temporal` and `--split institution` (both exit 0, all metrics for all 4 baselines);
  `.venv/bin/pytest finalsay/tests -q` (45 passed).
- **Gotcha for FEAT-004 (frontend):** demo creds are `student@finalsay.demo`/`student123`,
  `reviewer@finalsay.demo`/`reviewer123`, `admin@finalsay.demo`/`admin123`,
  `issuer@finalsay.demo`/`issuer123`. Endpoints to wire: submit uses **multipart form**
  (`file` and/or `text` Form fields), not JSON. Notices list is `GET /api/notices`.
- **Deadline-F1 quirk — FIXED in FEAT-005** (was: harness `deadline` extraction-F1 read
  ~0.0 because `_DEADLINE_RE` matched `by` inside `Issued by:` before the real deadline).
  See the FEAT-005 build notes below for the fix; deadline F1 is now 1.000 on both splits.

## FEAT-004 build notes (frontend — React + Vite PWA)
- App lives at `apps/web` (do NOT run npm work from /tmp). Stack: **Vite 5 + React 18 +
  react-router-dom 6 + axios + vite-plugin-pwa 0.20** (TypeScript). `type: module`.
- **Verify:** `cd apps/web && npm install && npm run build` → green. Emits
  `dist/manifest.webmanifest`, `dist/sw.js`, `dist/workbox-*.js`, `dist/registerSW.js`
  (installable PWA, R7.2). Build runs `tsc -b && vite build` (strict TS, noUnusedLocals).
- **Dev proxy:** `vite.config.ts` proxies `/api` → `http://127.0.0.1:8000`. The axios
  client (`src/api/client.ts`) uses baseURL `/api`, so relative URLs work in dev + prod.
- **Auth:** `src/auth/AuthContext.tsx` stores the JWT in localStorage; axios request
  interceptor attaches `Authorization: Bearer`. Login uses the **OAuth2 password flow**
  (`application/x-www-form-urlencoded` with `username`/`password`) then `GET /auth/me`;
  register posts JSON to `/auth/register` then auto-logs-in. `NavBar` is role-aware;
  `ProtectedRoute` gates on auth + role.
- **Views (all call a live API, no placeholders — GC-6):**
  - `/login` (+ one-click seeded demo-user buttons), `/register`.
  - Student: `/submit` (multipart `FormData`: `text` and/or `file` + optional
    `institution_id` → `POST /ingest/submit`; image-without-OCR 422 shown as a friendly
    message), `/result/:id` (relationship **LabelBadge** + confidence + rationale + gated
    tag; extracted-fields evidence table + redacted text from `/notices/{id}`; closest
    candidate from `/notices/{id}/candidates`; **Verify integrity** + **Simulate tamper**
    buttons → `/provenance/verify/{id}?tamper=`), `/notices` (list + detail),
    `/alerts` (per-issuer subscribe toggle in localStorage; feed filtered from `/notices`).
  - Reviewer: `/reviewer/queue` (`/reviewer/queue`), `/reviewer/case/:id`
    (confirm/correct → `POST /reviewer/cases/{id}/resolve`), `/reviewer/benchmark`
    (two-annotator annotate → `/reviewer/benchmark/annotate`; kappa report from
    `/reviewer/benchmark/kappa`).
  - Admin: `/admin/sources` (list + add → `/ingest/sources`; **Trigger fetch** →
    `/ingest/fetch`).
  - Issuer: `/issuer/publish` (labeled Tier-2 stub → `/issuer/publish`).
- **Styling:** `src/styles.css` — plain professional (system font, flat colors, simple
  tables/forms/cards). **No gradients/glassmorphism** (GC-8).
- **Icons:** `scripts/gen-icons.mjs` writes real 192/512 PNGs into `public/icons` using
  only Node `zlib` (no image dependency). Re-run with `node scripts/gen-icons.mjs` if
  needed; they are committed under `public/` (not gitignored).
- **Gotcha for FEAT-005 / demo:** the classification label/confidence/rationale are only
  returned by `POST /ingest/submit` (there is no GET that re-derives the relationship for a
  submission). The outcome is cached in `sessionStorage` (`src/api/resultCache.ts`) so
  `/result/:id` shows the label after submitting; a cold reload still shows fields +
  candidate + integrity and hints to re-submit. Provenance verify returns `ok:false` until
  an admin builds the daily Merkle root (`POST /api/provenance/build`) — the UI surfaces
  this as a "no proof yet" banner rather than a tamper.
- Verified the whole frontend↔backend contract in-process (seeded SQLite + TestClient):
  login/me, submit (→ superseded 0.86), notice detail, candidates, verify, notices (120),
  reviewer queue/pairs(14)/kappa(0.6627), admin sources(3)/fetch, issuer publish (201) —
  all pass. Do NOT rely on a persistent `npm run dev` across tool calls (daemon reaping);
  `npm run build` is the durable check. No run scripts/Makefile/README written (FEAT-005).

## FEAT-005 build notes (one-command run, Makefile, README, deadline fix, final pass)
- **`scripts/run_demo.sh`** (executable, `bash -n` clean): resolves the pyenv 3.11 interp
  (`~/.pyenv/versions/3.11.15/bin/python`, falling back to `python3.11`/`python3`),
  creates/reuses `backend/.venv`, `pip install -r backend/requirements.txt`, runs the
  idempotent seed, starts **uvicorn `finalsay.main:app` on 127.0.0.1:8000 in the
  background**, waits on `/api/health`, `npm install`, then runs **`npm run dev` (Vite
  5173) in the FOREGROUND** (NOT `exec`'d, so the parent shell survives to fire the
  `trap ... EXIT INT TERM` cleanup that kills uvicorn + stops Postgres). Prints the demo
  URLs and all four seeded credentials. **`--postgres`** flag: `initdb` only when
  `${PGDATA}/PG_VERSION` is absent, starts via `sudo -u postgres pg_ctl` with
  `-k /var/run/postgresql` and `listen_addresses='127.0.0.1'`, creates the `finalsay`
  role/db if missing, exports
  `FINALSAY_DATABASE_URL=postgresql+psycopg2://finalsay:finalsay@127.0.0.1:5432/finalsay`
  before seeding. Default (no flag) = SQLite, no external service.
- **`Makefile`**: `demo` (→ run_demo.sh), `backend` (uvicorn only), `frontend` (vite only),
  `seed`, `test` (venv pytest), `eval` (harness both splits), plus `install`/`venv`/`clean`/
  `help`. All Python targets use `backend/.venv/bin/python`; `$(PYTHON_BIN)` prefers the
  pyenv 3.11 interp for venv creation.
- **`README.md`**: overview, architecture summary (6 modules + PWA + relational edges),
  prerequisites (Python 3.11, Node 18+), one-command `make demo`, demo-user table +
  one-click login note, clean-clone manual steps, make-target table, PostgreSQL section,
  full `FINALSAY_` env-switch table (SQLite/Postgres, mock/hf, local/polygon, threshold,
  jwt, tesseract), and the **Tesseract-unavailable OCR-degradation note** (image → 422,
  PDF/paste work).
- **`.env.example`**: every `FINALSAY_` var at safe offline defaults (SQLite + mock + local,
  no keys). **`.gitignore`**: added top-level `dist/` and `dev-dist/` (already had venvs,
  `node_modules`, `*.db`/`finalsay.db`, `__pycache__`, `.pytest_cache`, `.env`).
- **Deadline-regex bug fix** (`backend/finalsay/services/extraction.py`): the old
  `_DEADLINE_RE` listed `by` as a cue and matched it inside `Issued by:` (present on every
  official/gold notice), returning the issuer line as the deadline → harness deadline F1
  ~0.0. Fix: factored the date pattern into `_DATE_RE_SRC` (reused by `_DATE_RE`) and
  replaced the single regex + inline logic with a `_extract_deadline(text)` helper backed by
  two anchored patterns —
  `_DEADLINE_BY_RE = (?<!issued )(?:extended to|register by|submit by|before|by)\s+<DATE>`
  (a date MUST immediately follow, and the negative lookbehind excludes the issuer line;
  returns just the date, conf 0.85) and
  `_DEADLINE_EXPLICIT_RE` anchored on `deadline|due|last date|closes|cutoff` that prefers the
  first date inside the captured clause (conf 0.8) else a short trimmed fallback (conf 0.5).
  Now returns `None` for issuer-only notices and the correct date (e.g. `16 Sep`) for
  notices carrying both an `Issued by:` line and a separate `Deadline:` line. No gold
  fixtures or test expectations changed (existing `test_extraction.py` still green).
- **Final integration pass (all green):** `cd backend && .venv/bin/pytest finalsay/tests -q`
  → **45 passed**; `.venv/bin/python -m finalsay.eval.harness --split temporal` and
  `--split institution` → both **exit 0**, **deadline F1 now 1.000** (was ~0.0),
  finalsay relationship F1 1.000; `cd apps/web && npm run build` → green (manifest + sw.js +
  workbox); `test -x scripts/run_demo.sh` OK; seed idempotent (stable 3/4/120/65/14/28);
  **in-process TestClient happy-path smoke** submit→classify (`superseded` 0.86)→provenance
  build+verify (`ok:true, tamper:false`; `?tamper=true` flips)→reviewer resolve (case
  `closed`, edge `corrected`) **PASSED**. Temp smoke script was written under
  `backend/` (not /tmp) and removed after; no stray db/temp artifacts left.
- **run_demo.sh verification note:** because background daemons don't persist across separate
  tool calls (and the tool harness blocks obvious server-start commands), the script was
  verified by static review + `bash -n` + confirming its pieces independently (venv/deps,
  idempotent seed with credential banner, `finalsay.main:app` uvicorn target exists, health
  wait loop, foreground Vite + EXIT trap ordering), rather than by holding the live process
  across calls.
- No git commit made (orchestrator publishes). Tree left committable; `.gitignore` excludes
  the venv, db files, node_modules, dist/dev-dist, caches, and `.env`.

## Post-review fix pass (2026-09-07, from `2026-09-07-090713-review.md`, NEEDS_CHANGES → resolved)
Addressed all 8 review issues (3 blockers + 5 lesser). Backend suite **50 passed** (was 45);
both eval splits **exit 0**; frontend `npm run build` **green**; seed **idempotent** and a
**fresh seed now verifies integrity out of the box**.

- **[BLOCKER 1] Open role self-assignment at registration** — `POST /api/auth/register` no
  longer accepts a `role`. `schemas.UserRegister` dropped the `role` field and
  `api/auth.py` hard-codes `role="student"` (`SELF_REGISTER_ROLE`). The four privileged demo
  accounts are still created by the seed. Frontend `RegisterPage` lost its role dropdown and
  now states new accounts are students; `AuthContext.register()` no longer sends a role.
  New test `test_public_register_cannot_self_assign_privileged_role` asserts a public caller
  asking for admin/reviewer/issuer is downgraded to student AND is 403'd from an admin route.
  Test helpers that needed privileged actors now provision them directly via a new
  `make_user` conftest fixture (mirroring how the seed provisions them).
- **[BLOCKER 2] Integrity check inert on a fresh demo** — added
  `provenance.build_all_missing_roots(db)`, called at the tail of `seed()`. It builds the
  daily Merkle root for every notice-day lacking one, so seeded notices get stored proofs and
  `GET /api/provenance/verify/{id}` returns `ok=true` on a fresh demo (acceptance A-2). It is
  **idempotent** (skips days that already have a root → no duplicate roots/proofs/anchor
  blocks); re-running the seed keeps counts stable (1 root / 185 proofs / 1 anchor block).
  New test `test_fresh_seed_verifies_a_notice`; the idempotency test now also covers
  merkle/anchor counts.
- **[BLOCKER 3] Self-fulfilling eval metrics** — `seed/dataset.py` now emits two phrasing
  styles. Early/training rounds (`temporal_bucket==0`) keep cue phrasings (so the seeded demo
  still shows every taxonomy label), but the **held-out** round (`temporal_bucket==1`, which
  the temporal split evaluates) uses **naturalistic phrasings not engineered around the mock
  cues** (`_naturalistic_text`). Metrics are now honest: on the temporal (all-naturalistic)
  split FinalSay's relationship F1 is ~0.05 and on the institution split ~0.74 — no longer a
  round-trip 1.000. FinalSay uniquely keeps a **0.000 false-confirmation rate** (its actual
  value for this safety-critical task; baselines range 0.14–0.43). The harness docstring and
  printed report now state this explicitly. Eval sanity tests updated:
  `test_finalsay_has_lowest_false_confirmation_rate` (temporal) and
  `test_institution_split_finalsay_beats_naive_page_change`.
- **[lesser 4] `leaf_index` collision** — `build_daily_merkle` now stores the positional
  `enumerate` index instead of `leaves.index(notice.sha256)`, which collided on duplicate
  content hashes. New test `test_leaf_index_is_positional_on_duplicate_hashes`.
- **[lesser 5] Dead MockComparisonModel fixtures seam** — removed the unused `fixtures`
  constructor arg and the dead fixture-lookup branch (nothing in production, eval, or tests
  used it); corrected the class + module docstrings to say classification is 100% rule-based.
- **[lesser 6] `submit` not student-gated** — `POST /api/ingest/submit` now depends on
  `require_role("student", "admin")` (submit is a Student action per the scope note; admin is
  kept as an operational/demo override) instead of any authenticated role. The frontend flow
  (student submit) is unaffected.
- **[lesser 7] `sha256_notice` omitted deadline/audience/action** — the canonical hash now
  covers issuer, date, deadline, audience, action, and redacted_text (labelled + newline
  joined), so a targeted edit to any single stored column is tamper-detectable. All callers
  (`ingestion._apply_extraction`, `ingestion.upsert_official`, `provenance.build_daily_merkle`,
  `provenance.verify_notice`) updated. New test
  `test_structured_field_edit_is_tamper_detectable`. No tests hard-coded a hash.
- **[lesser 8] localStorage-only alerts** — `AlertsPage` now carries a clear
  **"Prototype stub"** banner explaining subscriptions live in this browser only
  (localStorage), with no server-side persistence or push/email delivery; the feed remains
  real `GET /api/notices` data. Left as a labelled stub (no backend persistence added), which
  the review deemed acceptable for the prototype.

Re-verify (from `backend/`): `.venv/bin/pytest finalsay/tests -q` (50 passed);
`.venv/bin/python -m finalsay.seed.seed && .venv/bin/python -m finalsay.seed.seed` (identical
counts incl. 1 merkle_root / 185 merkle_proofs / 1 anchor_block); `.venv/bin/python -m
finalsay.eval.harness --split temporal` and `--split institution` (both exit 0);
`cd apps/web && npm run build` (green). No git commit (orchestrator publishes).

## Autonomous decisions (with reasoning)
- **Repo layout at workspace root** (`backend/`, `apps/web/`, `scripts/`, `Makefile`) rather
  than a nested `finalsay/` folder — simpler one-command demo. Backend Python package is
  `finalsay` under `backend/`.
- **SQLite is the default DB** (design §2). Deviation from the scope note's "PostgreSQL
  default" driven by the daemon-reaping constraint above; architecture stays faithful
  (SQLAlchemy models, temporal relations as relational edge tables). Postgres fully wired
  and documented as opt-in.
- **DB defaults**: db `finalsay`, user `finalsay`, password `finalsay`, host 127.0.0.1:5432.
- **Confidence threshold default 0.6** (`FINALSAY_CONFIDENCE_THRESHOLD`); below → unresolved.
- **Comparison default `mock`, anchor default `local`** — no paid keys, offline.
- **Institution names**: Northgate, Riverside, Summit (Summit is the held-out institution
  in the eval `institution` split).
- **HF model default name** `facebook/bart-large-mnli` (only used when `FINALSAY_COMPARISON_MODEL=hf`).

## Env vars / config the next session may set
- `FINALSAY_DATABASE_URL` (default `sqlite:///./finalsay.db`)
- `FINALSAY_COMPARISON_MODEL` = `mock` (default) | `hf`; `FINALSAY_HF_MODEL_NAME`
- `FINALSAY_ANCHOR` = `local` (default) | `polygon`; `FINALSAY_POLYGON_RPC_URL` /
  `FINALSAY_POLYGON_PRIVATE_KEY` / `FINALSAY_POLYGON_CONTRACT`
- `FINALSAY_CONFIDENCE_THRESHOLD` (default `0.6`); `FINALSAY_JWT_SECRET`;
  `FINALSAY_TESSERACT_CMD`

## Known issues / blocked
- Tesseract OCR engine unavailable in sandbox (see above) — image OCR path degrades; PDF and
  pasted-text paths are fully functional. Not blocking the demo.
- Persistent DB server across steps not possible in sandbox — mitigated by SQLite default.
- The `.docx` scope note was not present in the workspace (orchestrator could not extract it)
  and no readable copy was found via search; specs were derived from the detailed prompt +
  use-case diagram summary. Logged per instructions.
