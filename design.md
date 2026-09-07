# FinalSay — Design

This describes how the prototype meets `requirements.md`. It is a real architecture with
stubbed-where-necessary internals, sized for a runnable college demo.

## 1. High-level architecture

```
apps/
  web/            React + Vite PWA (student, reviewer, admin, issuer views)
backend/
  finalsay/
    main.py               FastAPI app factory + router wiring + logging
    config.py             pydantic-settings Settings (env-driven feature switches)
    db.py                 SQLAlchemy engine/session; DATABASE_URL (sqlite default)
    models.py             ORM models (institutions, notices, edges, users, reviews, ...)
    schemas.py            Pydantic request/response models
    auth.py               JWT issue/verify, password hashing, role dependencies
    logging_conf.py       basic logging setup
    api/
      auth.py             /api/auth/*  (register/login/me)
      ingestion.py        /api/ingest/*  (submit, admin fetch, sources CRUD)
      notices.py          /api/notices/* (list/detail/candidates)
      provenance.py       /api/provenance/* (verify, merkle build)
      comparison.py       /api/compare/* (run comparison for a submission)
      reviewer.py         /api/reviewer/* (queue, resolve, benchmark, kappa)
      issuer.py           /api/issuer/*  (publish official notice - stub)
    services/
      extraction.py       OCR + field extraction + redaction
      provenance.py       sha256, merkle tree build, proof, verify
      comparison.py       candidate retrieval + classify(); confidence gating
      kappa.py            Cohen's kappa
    adapters/
      base.py             InstitutionAdapter ABC (fetch() -> list[RawNotice])
      inst_northgate.py   adapter 1 (fixtures)
      inst_riverside.py   adapter 2 (fixtures)
      inst_summit.py      adapter 3 (fixtures)
    models_iface/
      comparison_model.py ComparisonModel ABC + MockComparisonModel + HFComparisonModel
      anchor.py           Anchor ABC + LocalHashChainAnchor + PolygonAmoyAnchor
    eval/
      harness.py          CLI: metrics + baselines + splits
      baselines.py        chronological / page-change / nli / prompted-llm baselines
    seed/
      seed.py             idempotent synthetic data generator
      fixtures/           per-institution official notice fixtures + submission fixtures
    tests/                pytest suite
scripts/
  run_demo.sh             one-command orchestration (db + seed + backend + frontend)
Makefile                  make demo / make backend / make frontend / make test / make seed
```

Design intent: interfaces (`ComparisonModel`, `Anchor`, `InstitutionAdapter`) isolate the
swappable/stubbed parts so the architecture stays faithful while defaults run offline.

## 2. Environment and feature switches (config.py)

`Settings` (pydantic-settings, `FINALSAY_` env prefix, `.env` supported):

| Setting | Env | Default | Effect |
|---|---|---|---|
| database_url | `FINALSAY_DATABASE_URL` | `sqlite:///./finalsay.db` | SQLAlchemy URL; set to `postgresql+psycopg2://finalsay:finalsay@127.0.0.1:5432/finalsay` for Postgres |
| comparison_model | `FINALSAY_COMPARISON_MODEL` | `mock` | `mock` \| `hf` |
| hf_model_name | `FINALSAY_HF_MODEL_NAME` | `facebook/bart-large-mnli` | used only when `hf` |
| anchor | `FINALSAY_ANCHOR` | `local` | `local` \| `polygon` |
| confidence_threshold | `FINALSAY_CONFIDENCE_THRESHOLD` | `0.6` | below → unresolved |
| jwt_secret | `FINALSAY_JWT_SECRET` | dev default | HS256 signing |
| polygon_rpc_url / polygon_private_key / polygon_contract | `FINALSAY_POLYGON_*` | unset | only when anchor=polygon |
| tesseract_cmd | `FINALSAY_TESSERACT_CMD` | auto | path to tesseract if present |

Rationale for SQLite default (deviation from "PostgreSQL default"): the sandbox reaps
background daemons across steps and wipes `/tmp`, so a persistent Postgres server is not
reliable for a bare one-command demo. SQLite via the same SQLAlchemy models keeps the
architecture faithful (temporal edges still relational tables) and honors GC-1 (one command,
no external service). PostgreSQL is fully supported and documented via `DATABASE_URL`, and
`scripts/run_demo.sh --postgres` boots Postgres in the foreground session. Logged in
HANDOFF.md.

## 3. Data model (models.py) — relational temporal edges, NO graph DB

- `institution(id, name, slug, source_url, active, created_at)`
- `user(id, email, hashed_password, role, display_name, created_at)` role ∈
  {student, reviewer, admin, issuer}
- `notice(id, institution_id, kind, issuer, notice_date, deadline, audience, action,
  redacted_text, source_url, retrieved_at, sha256, created_at)` — `kind` ∈
  {official, submission}; official notices link to an institution, submissions may link to
  a submitting user.
- `notice_field(id, notice_id, field_name, value, confidence)` — per-field extraction for
  F1 scoring and evidence display.
- `relation_edge(id, src_notice_id, dst_notice_id, label, confidence, rationale, model,
  status, created_at)` — the **typed temporal relation as a relational edge**. `label` ∈
  taxonomy; `status` ∈ {auto, unresolved, confirmed, corrected}.
- `merkle_root(id, day, root_hash, anchor_kind, anchor_ref, created_at)` — daily root and
  anchor reference (local chain index or tx hash).
- `merkle_proof(id, notice_id, root_id, proof_json, leaf_index)` — per-notice proof.
- `anchor_block(id, index, prev_hash, data_hash, this_hash, created_at)` — local append-only
  hash chain blocks (LOCAL anchor).
- `review_case(id, edge_id, status, assigned_role, resolved_by, resolved_label, created_at)`
  — reviewer queue; created for every `unresolved` edge.
- `benchmark_pair(id, submission_id, official_id, gold_label)` and
  `benchmark_annotation(id, pair_id, annotator, label, created_at)` — two-annotator screen +
  kappa.

Indexes on `notice.institution_id`, `notice.kind`, `relation_edge.status`,
`merkle_proof.notice_id`.

## 4. Ingestion (module 1)

- `InstitutionAdapter.fetch() -> list[RawNotice]` reads that institution's fixture file
  (`seed/fixtures/<inst>_official.json`) and returns raw notices with `source_url`.
- Admin endpoint `POST /api/ingest/fetch` iterates the three adapters synchronously, runs
  each raw notice through extraction → redaction → provenance, and upserts by content hash
  (idempotent).
- Student submission `POST /api/ingest/submit` accepts multipart file (image/pdf) or JSON
  `{text}`; runs the same extraction pipeline; creates a `submission` notice; immediately
  triggers comparison (R4) and returns the result.
- Sources CRUD `GET/POST /api/ingest/sources` (admin) manages `institution` rows.

## 5. Extraction (module 2) — services/extraction.py

1. **Text acquisition**: PDF → `pypdf` text; image → `pytesseract` if binary available,
   else raise a typed `OcrUnavailable` that the API surfaces as a 422 asking for pasted
   text (graceful degradation, GC/R2.1). Pasted text used directly.
2. **Field extraction**: rule/regex-based extractor for issuer, date, deadline, audience,
   action (deterministic, offline). Dates parsed with `dateutil`-style regexes; returns
   value + a heuristic confidence per field.
3. **Redaction**: regex masks for emails, phone numbers, roll/registration numbers
   (e.g. `\b\d{2}[A-Z]{2}\d{4,}\b`), and a small name-pattern pass ("Mr./Ms./Dr. Name",
   "Name: X"). Produces `redacted_text`. Only redacted text is stored (GC-5, R2.4).

**Retention policy (scope note §1, §6).** Personal identifiers (names, roll/registration
numbers, contact details such as email/phone) are redacted at ingestion **before** the
notice is stored or indexed, and field extraction runs over the redacted text so no
identifier reaches a stored field. The **unredacted original is not retained**: this is
enforced *structurally*, not just procedurally. The `notice` table stores only
`redacted_text` and has **no** unredacted-original column (see §3), so `extraction.extract()`
returns only `redacted_text` + fields and the ingestion service has nowhere to persist the
original. As a **stated operational policy** (not a runtime guarantee automated by the
prototype, which has no deletion/expiry path), raw fetched files are intended to be kept
**only for the duration of the project evaluation** and not retained beyond it. The
**benchmark released with the report contains redacted text only**.

## 6. Provenance (module 3) — services/provenance.py + models_iface/anchor.py

- `sha256_notice(redacted_text, issuer, notice_date)` → canonical SHA-256.
- **Merkle build**: `build_daily_merkle(day)` collects that day's notice hashes, builds a
  binary Merkle tree (duplicate last leaf on odd count), stores `merkle_root` and one
  `merkle_proof` per notice (sibling path as JSON).
- **Anchor interface** `Anchor.anchor(root_hash) -> AnchorRef`:
  - `LocalHashChainAnchor`: appends an `anchor_block` (prev_hash chained), returns block
    hash+index. Always available, never blocks (GC-3).
  - `PolygonAmoyAnchor`: uses `web3.py` to send the root to a testnet contract/tx when
    `FINALSAY_ANCHOR=polygon` and creds set; failures are caught and downgraded to local so
    ingestion never blocks.
- **Verify** `GET /api/provenance/verify/{notice_id}`: recompute hash, recompute root from
  stored proof, compare to stored root → `{ok, tamper: bool, details}`. A simulated tamper
  (query flag in demo) shows the mismatch path.

## 7. Comparison (module 4) — services/comparison.py + models_iface/comparison_model.py

- **Candidate retrieval**: filter official notices by same institution/audience when known,
  rank by token-overlap (Jaccard/TF cosine over normalized tokens), take top-K (K=5).
- **ComparisonModel** `classify(premise, hypothesis) -> (label, confidence, rationale)`:
  - `MockComparisonModel` (default): deterministic. Uses fixture-keyed predictions when the
    pair matches a seeded fixture; otherwise a rule engine keyed on cues (date change →
    superseded/extended, "cancelled" → cancelled, "correction/erratum" → corrected,
    negation/date-conflict → contradictory, high overlap + same facts → consistent, else
    low-confidence). Guarantees the "22 Sept vs 15 Sept" case is contradictory/superseded.
  - `HFComparisonModel` (opt-in): `transformers` zero-shot NLI over the taxonomy labels.
- **Confidence gating** (GC-4): if `confidence < threshold`, label overridden to
  `unresolved`, and a `review_case` is created. Edge persisted with model name + rationale.

## 8. Reviewer console (module 5)

- `GET /api/reviewer/queue` lists unresolved `review_case`s with edge + both notices.
- `POST /api/reviewer/cases/{id}/resolve {label}` sets edge label, marks status
  confirmed/corrected, closes the case.
- Benchmark: `GET /api/reviewer/benchmark/pairs` returns benchmark pairs;
  `POST /api/reviewer/benchmark/annotate {pair_id, annotator, label}` records annotations;
  `GET /api/reviewer/benchmark/kappa` computes Cohen's kappa across the two annotators
  (services/kappa.py) and returns agreement + per-label counts.

## 9. Issuer (Tier 2 stub, module actors)

- `POST /api/issuer/publish` (role issuer, synthetic accounts) creates an `official` notice
  attributed to the issuer's institution, runs it through extraction/provenance. Clearly
  labeled stub in UI.

## 10. Evaluation harness (module 6) — eval/harness.py

- Loads gold-labeled fixtures (submission↔official pairs with gold relationship + gold
  fields). CLI: `python -m finalsay.eval.harness [--split temporal|institution] [--model mock|hf]`.
- Metrics: per-field extraction F1 (token-set F1 per field, macro), relationship
  precision/recall/F1 (sklearn), false-confirmation rate (predicted confirmed but gold not
  consistent), unresolved-case rate, Cohen's kappa (from benchmark annotations).
- Baselines (eval/baselines.py): `chronological` (predict by recency), `page_change`
  (predict superseded if text changed), `nli` (off-the-shelf mapping), `prompted_llm`
  (prompt-style mock). All four scored on the same split for comparison.
- Splits: `temporal` holds out the latest notices by date; `institution` holds out one full
  institution (Summit) as unseen.

## 11. Frontend (React + Vite PWA) — apps/web

- Vite + React + React Router. Plain professional CSS (no gradients/glass). PWA via
  `vite-plugin-pwa` (manifest + service worker) → installable (R7.2).
- Auth context stores JWT; axios client attaches bearer.
- Routes / views (every actor has a working path, GC-6):
  - `/login`, `/register`
  - Student: `/submit` (upload/paste), `/result/:id` (label + confidence + evidence trail +
    integrity check button), `/notices` (browse official), `/alerts` (subscribe toggle).
  - Reviewer: `/reviewer/queue`, `/reviewer/case/:id`, `/reviewer/benchmark` (two-annotator
    + kappa report).
  - Admin: `/admin/sources` (list/add), button to trigger fetch.
  - Issuer: `/issuer/publish`.
- Dev proxy: Vite proxies `/api` → `http://127.0.0.1:8000`.

## 12. Auth & logging

- JWT HS256 via python-jose; passlib bcrypt hashing. `require_role(...)` FastAPI dependency.
- Seeded demo users per role (documented in README/HANDOFF). Basic logging via
  `logging_conf.py` (request log middleware).

## 13. One-command run (scripts/run_demo.sh + Makefile)

`make demo`:
1. create/reuse backend venv (Python 3.11), install `backend/requirements.txt`.
2. `python -m finalsay.seed.seed` (idempotent) against SQLite default.
3. start uvicorn (127.0.0.1:8000) in background of the foreground script.
4. `npm install` + `npm run dev` (Vite on 5173) — foreground, keeps parent alive so the
   backend survives.

`scripts/run_demo.sh --postgres` additionally boots the sandbox Postgres in-session and
sets `FINALSAY_DATABASE_URL` before seeding.

## 14. Testing

- pytest suite under `backend/finalsay/tests/`: extraction+redaction, provenance
  merkle/verify + tamper, comparison gating (unresolved on low confidence, contradiction on
  the 22/15 Sept case), reviewer resolve, kappa math, auth/roles, ingestion adapters
  idempotency, eval harness smoke. Tests run on SQLite in-memory/temp file.

## 15. Traceability (requirements → design)

- Module 1 → §4; Module 2 → §5; Module 3 → §6; Module 4 → §7; Module 5 → §8; Module 6 → §10.
- GC-2/GC-3 → §2, §7, §6 (interfaces + defaults). GC-4 → §7 gating. GC-5 → §5 redaction.
- GC-6 → §11 routes. GC-7 → whole design (relational edges §3, sync FastAPI, interfaces).
