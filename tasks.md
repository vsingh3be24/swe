# FinalSay — Tasks

Small, ordered, independently completable tasks. Execute top to bottom. Each task lists the
files it touches and how to verify it. Status legend: `not-started` / `in-progress` / `done`
(tracked live in HANDOFF.md).

Env note (sandbox): Python 3.11.15 via `~/.pyenv/versions/3.11.15/bin/python`; Node v22;
PostgreSQL 15 installed but daemons die across tool calls, `/tmp` non-persistent; Tesseract
binary NOT available (OCR degrades to text/PDF). Default demo uses SQLite + MOCK model +
LOCAL anchor.

---

## T1 — Backend scaffold, config, DB, auth, logging
- Create `backend/` package `finalsay` with `pyproject.toml`/`requirements.txt`, `config.py`
  (Settings per design §2), `db.py` (SQLAlchemy engine/session, SQLite default), `main.py`
  (app factory, router include, request-logging middleware, `/api/health`),
  `logging_conf.py`, `auth.py` (JWT HS256, bcrypt, `require_role`), `models.py` (all ORM
  models per design §3), `schemas.py` (base Pydantic models), and `api/auth.py`
  (register/login/me).
- Verify: `pip install -r backend/requirements.txt`; `uvicorn` import OK;
  `pytest backend/finalsay/tests/test_auth.py` passes (register→login→me, role guard 403).

## T2 — Extraction service (OCR + fields + redaction)
- `services/extraction.py`: text acquisition (pypdf for PDF; pytesseract if
  `FINALSAY_TESSERACT_CMD`/binary present, else typed `OcrUnavailable`), field extractor
  (issuer/date/deadline/audience/action) with per-field confidence, redaction pass
  (emails/phones/roll numbers/name patterns). Only redacted text returned for storage.
- Verify: `pytest backend/finalsay/tests/test_extraction.py` — fields extracted from sample,
  emails/phones/roll numbers masked, unredacted text never returned.

## T3 — Provenance service + Anchor interface
- `services/provenance.py` (sha256_notice, build_daily_merkle, proof gen, verify) and
  `models_iface/anchor.py` (`Anchor` ABC, `LocalHashChainAnchor` default,
  `PolygonAmoyAnchor` opt-in with try/except downgrade). `api/provenance.py` (build root,
  `verify/{notice_id}` with tamper detection).
- Verify: `pytest backend/finalsay/tests/test_provenance.py` — merkle proof verifies for
  all leaves; tampered content flips `tamper=true`; local anchor chain links prev_hash.

## T4 — ComparisonModel interface + comparison service (confidence gating)
- `models_iface/comparison_model.py` (`ComparisonModel` ABC, `MockComparisonModel` default,
  `HFComparisonModel` opt-in), `services/comparison.py` (candidate retrieval by
  overlap/institution, classify, threshold gating → unresolved + `review_case`),
  `api/comparison.py`.
- Verify: `pytest backend/finalsay/tests/test_comparison.py` — "exam postponed to 22 Sept"
  vs "exam on 15 Sept" → contradictory/superseded (not consistent); low-confidence pair →
  `unresolved` + review_case created; edge persisted with rationale.

## T5 — Ingestion: adapters + submit + admin fetch + sources CRUD
- `adapters/base.py` + three institution adapters (fixtures), `api/ingestion.py`
  (`POST /submit` upload/paste runs extraction→provenance→comparison; `POST /fetch` admin
  runs all adapters idempotently; `GET/POST /sources` admin), `api/notices.py`
  (list/detail/candidates), `api/issuer.py` (publish stub).
- Verify: `pytest backend/finalsay/tests/test_ingestion.py` — fetch is idempotent (second
  run adds no dupes by hash); submit returns a classified result; sources CRUD works;
  issuer publish creates official notice.

## T6 — Reviewer console API + Cohen's kappa
- `services/kappa.py` (Cohen's kappa), `api/reviewer.py` (queue, resolve, benchmark pairs,
  annotate, kappa report).
- Verify: `pytest backend/finalsay/tests/test_reviewer.py` — resolve updates edge + closes
  case; kappa on known annotation set matches hand-computed value (±0.001).

## T7 — Seed script (idempotent synthetic data)
- `seed/seed.py` + `seed/fixtures/`: 3 fictional institutions, ~40 official notices each,
  ~60 submissions covering every relationship type incl. ambiguous→unresolved and
  low-overlap pairs; gold labels + gold fields for eval; benchmark pairs + two-annotator
  annotations; demo users per role. Re-running makes no duplicates.
- Verify: run seed twice; row counts stable on 2nd run; every taxonomy label present among
  submissions; `pytest backend/finalsay/tests/test_seed.py` smoke.

## T8 — Evaluation harness (CLI) + baselines
- `eval/harness.py` + `eval/baselines.py`: field F1, relationship P/R/F1, false-confirmation
  rate, unresolved rate, kappa; temporal + institution splits; four baselines.
  `python -m finalsay.eval.harness` prints a readable report.
- Verify: `python -m finalsay.eval.harness --split temporal` and `--split institution` both
  print all metrics for all four baselines and exit 0; `pytest test_eval.py` smoke.

## T9 — Frontend PWA (React + Vite), all actor routes
- `apps/web`: Vite React app, router, auth context, axios client, plain professional CSS,
  vite-plugin-pwa (manifest + SW). Views for every actor/use case per design §11, wired to
  the API (no placeholder screens). Vite dev proxy `/api` → 127.0.0.1:8000.
- Verify: `npm install && npm run build` succeeds; manifest + SW emitted; each route renders
  and calls its API (manual smoke via run_demo).

## T10 — One-command run, Makefile, README, docker-optional
- `scripts/run_demo.sh` (venv+install, idempotent seed, uvicorn bg, vite fg;
  `--postgres` boots in-session PG), `Makefile` (`demo/backend/frontend/seed/test/eval`),
  `README.md` (clean-clone setup, demo users, env switches, Postgres/HF/Polygon opt-in),
  `.gitignore`, `.env.example`.
- Verify: fresh `make demo` seeds and serves; README single command documented; `make test`
  runs full pytest suite green; `make eval` prints metrics.

## T11 — Full integration verification pass
- Run backend test suite, build frontend, run eval harness for both splits, exercise the
  submit→classify→verify→review happy path via httpx against a live app instance.
- Verify: all green; HANDOFF.md updated with final status, decisions, known issues, run
  instructions.
