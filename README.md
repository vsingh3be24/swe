# FinalSay

FinalSay is a cross-institution notice verification platform prototype. Students
submit a notice (pasted text or a PDF/image); FinalSay extracts and redacts it,
compares it against officially-ingested notices, classifies the temporal
relationship (consistent, contradictory, superseded, corrected, extended,
cancelled, or unresolved), and provides a tamper-evident provenance trail. Low
confidence predictions are gated to a human reviewer queue.

## Architecture

- **Backend** — synchronous FastAPI app (`backend/finalsay`) over SQLAlchemy
  (SQLite by default, PostgreSQL opt-in). Six modules mirror the design:
  1. **Ingestion** — institution adapters (fixtures) + student submission.
  2. **Extraction** — PDF/image/text acquisition, regex field extraction
     (issuer, date, deadline, audience, action) and PII redaction. Only
     redacted text and extracted fields are ever stored.
  3. **Provenance** — canonical SHA-256, daily Merkle tree, and a pluggable
     anchor (`LocalHashChainAnchor` default, `PolygonAmoyAnchor` opt-in).
  4. **Comparison** — candidate retrieval + a pluggable `ComparisonModel`
     (`MockComparisonModel` default, `HFComparisonModel` opt-in) with
     confidence gating.
  5. **Reviewer console** — unresolved-case queue, resolve/correct, plus a
     two-annotator benchmark with Cohen's kappa.
  6. **Evaluation harness** — per-field extraction F1, relationship
     precision/recall/F1, false-confirmation and unresolved rates, kappa, and
     four baselines across `temporal` / `institution` holdout splits.
- **Frontend** — React + Vite PWA (`apps/web`) with role-aware routes for the
  student, reviewer, admin, and issuer actors. Installable (manifest + service
  worker). In dev, Vite proxies `/api` to the backend on `127.0.0.1:8000`.

Temporal relations are stored as **relational edge rows** (`relation_edge`), not
a graph database. The swappable parts (comparison model, anchor, institution
adapters) sit behind ABCs so the defaults run fully offline with no paid keys.

See [`design.md`](design.md) for the full architecture and [`requirements.md`](requirements.md)
for the EARS requirements.

## Prerequisites

- **Python 3.11** (the tooling uses `~/.pyenv/versions/3.11.15/bin/python` when
  present, otherwise `python3.11`).
- **Node.js 18+** (Node 22 recommended) with `npm`.
- No paid API keys. No external services for the default demo.

## Quick start (one command)

From a clean clone:

```bash
make demo
```

This will:

1. Create/reuse the backend virtualenv (Python 3.11) and install
   `backend/requirements.txt`.
2. Seed the database idempotently (`python -m finalsay.seed.seed`).
3. Start the FastAPI backend on `http://127.0.0.1:8000` (background).
4. Install frontend dependencies and start the Vite dev server on
   `http://127.0.0.1:5173` (foreground).

Open the frontend at **http://127.0.0.1:5173**. API docs are at
**http://127.0.0.1:8000/docs**. Press `Ctrl-C` to stop; the backend is stopped
automatically.

Defaults: **SQLite + MOCK comparison model + LOCAL anchor** — offline, no keys.

### Demo users

| Role     | Email                    | Password     |
|----------|--------------------------|--------------|
| Student  | `student@finalsay.demo`  | `student123` |
| Reviewer | `reviewer@finalsay.demo` | `reviewer123`|
| Admin    | `admin@finalsay.demo`    | `admin123`   |
| Issuer   | `issuer@finalsay.demo`   | `issuer123`  |

The login screen also has one-click buttons for each seeded demo user.

### Clean-clone steps (manual, without `make`)

```bash
# 1. Backend venv + deps
~/.pyenv/versions/3.11.15/bin/python -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt

# 2. Seed (idempotent)
cd backend && ../backend/.venv/bin/python -m finalsay.seed.seed && cd ..

# 3. Backend (terminal 1)
cd backend && .venv/bin/python -m uvicorn finalsay.main:app --host 127.0.0.1 --port 8000

# 4. Frontend (terminal 2)
cd apps/web && npm install && npm run dev
```

## Make targets

| Target          | Description                                             |
|-----------------|---------------------------------------------------------|
| `make demo`     | Full one-command demo (backend + Vite frontend).        |
| `make backend`  | Run the FastAPI backend only (uvicorn on `:8000`).      |
| `make frontend` | Run the Vite dev server only (`:5173`).                 |
| `make seed`     | Seed the database idempotently.                         |
| `make test`     | Run the backend pytest suite.                           |
| `make eval`     | Run the evaluation harness for both splits.             |
| `make install`  | Create the venv and install backend requirements.       |
| `make clean`    | Remove venv, SQLite db, caches, and `node_modules`.     |

Frontend production build (PWA smoke): `cd apps/web && npm run build`.

## PostgreSQL (optional)

The demo defaults to SQLite for reliability. To run against PostgreSQL instead:

```bash
scripts/run_demo.sh --postgres
```

This boots the local PostgreSQL instance in-session (initializing the data
directory if empty, listening on `127.0.0.1`, using the `/var/run/postgresql`
socket directory), creates the `finalsay` role/database if missing, and exports:

```
FINALSAY_DATABASE_URL=postgresql+psycopg2://finalsay:finalsay@127.0.0.1:5432/finalsay
```

before seeding. You can also point any command at your own database by exporting
`FINALSAY_DATABASE_URL` yourself.

## Configuration (environment switches)

All settings use the `FINALSAY_` prefix (pydantic-settings; a `.env` file in the
working directory is honored). See [`.env.example`](.env.example).

| Variable | Default | Effect |
|---|---|---|
| `FINALSAY_DATABASE_URL` | `sqlite:///./finalsay.db` | SQLAlchemy URL. Set to `postgresql+psycopg2://finalsay:finalsay@127.0.0.1:5432/finalsay` for Postgres. |
| `FINALSAY_COMPARISON_MODEL` | `mock` | `mock` (offline rule engine) or `hf` (HuggingFace zero-shot NLI). |
| `FINALSAY_HF_MODEL_NAME` | `facebook/bart-large-mnli` | Model used only when `FINALSAY_COMPARISON_MODEL=hf`. |
| `FINALSAY_ANCHOR` | `local` | `local` (append-only hash chain) or `polygon` (Polygon Amoy testnet). |
| `FINALSAY_POLYGON_RPC_URL` / `FINALSAY_POLYGON_PRIVATE_KEY` / `FINALSAY_POLYGON_CONTRACT` | unset | Only used when `FINALSAY_ANCHOR=polygon`; failures downgrade to local. |
| `FINALSAY_CONFIDENCE_THRESHOLD` | `0.6` | Predictions below this become `unresolved` and go to the reviewer queue. |
| `FINALSAY_JWT_SECRET` | dev default | HS256 signing secret (override outside local demos). |
| `FINALSAY_TESSERACT_CMD` | `auto` | Path to the tesseract binary; `auto` autodetects it on `PATH`. |

## OCR / Tesseract note

Image OCR requires a Tesseract engine. **In this sandbox the Tesseract binary is
not available**, so image submissions degrade gracefully: the ingestion endpoint
returns **HTTP 422** with a message prompting the user to paste the notice text
instead. **PDF and pasted-text paths work fully** without any OCR engine. To
enable image OCR, install Tesseract and set `FINALSAY_TESSERACT_CMD` (or leave it
`auto` if `tesseract` is on `PATH`).

## Data handling and retention

FinalSay redacts personal data before it stores anything:

- **Redaction happens at ingestion, before storage or indexing.** Personal
  identifiers — names, roll/registration numbers, and contact details (email and
  phone) — are masked as soon as a notice is extracted, and field extraction runs
  over the redacted text, so no identifier reaches a stored field.
- **The unredacted original is not retained.** There is no column or attribute
  that holds the pre-redaction text; the `notice` table stores only
  `redacted_text`, so the guarantee is enforced structurally, not just by
  convention.
- **Raw fetched files: stated operational policy.** As an operational policy (not a
  runtime guarantee automated by the prototype, which has no deletion/expiry path), raw
  fetched files are intended to be kept only for the duration of the project evaluation
  and not retained beyond it.
- **The benchmark released with the report contains redacted text only.**

## Testing and evaluation

```bash
make test          # backend pytest suite
make eval          # evaluation harness, temporal + institution splits
```

The harness prints per-field extraction F1, relationship metrics, false
confirmation / unresolved rates, and Cohen's kappa for FinalSay and four
baselines, and exits 0 on success regardless of metric values.
