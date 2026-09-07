# FinalSay — Requirements

FinalSay is a working prototype of a cross-institution notice verification platform. A
student receives a forwarded institutional notice (screenshot, PDF, or pasted text).
FinalSay extracts its key fields, compares it against verified official notices scraped
from at least three institutions, and classifies the relationship between the submission
and the closest official notice. Every ingested notice is hashed (SHA-256); hashes are
batched into a daily Merkle tree and only the root is anchored (locally by default,
optionally on-chain), giving tamper-evident provenance.

This document defines requirements in EARS-style ("The system SHALL ...") grouped by the
scope note's six modules and four actors. It is authoritative for scope; `design.md`
describes how these are met and `tasks.md` sequences the build.

## Global constraints

- GC-1. The demo SHALL run with **one command** and **no paid API keys** by default.
- GC-2. The ComparisonModel SHALL default to the deterministic **MOCK** implementation;
  the HuggingFace zero-shot NLI implementation SHALL be **opt-in via env var only**.
- GC-3. The Anchor SHALL default to the **LOCAL append-only hash-chain**; Polygon Amoy
  on-chain anchoring SHALL be **opt-in via env var only** and SHALL NEVER block ingestion.
- GC-4. **Hard confidence rule**: when the comparison model is not confident (score below
  a configured threshold), the result SHALL be `unresolved` and SHALL be routed into the
  reviewer queue. The system SHALL NEVER force a guess.
- GC-5. Unredacted originals SHALL NEVER be persisted. Redaction SHALL run before storage.
- GC-6. Every actor and every use case SHALL have a reachable, working UI path. No
  placeholder screens.
- GC-7. The tech stack SHALL NOT be substituted: React + Vite PWA frontend; synchronous
  FastAPI backend (no async worker queue, no microservices); PostgreSQL via SQLAlchemy
  with temporal relations stored as edges in relational tables (NO graph database);
  Tesseract (pytesseract) for OCR; single-step ComparisonModel interface; web3.py Anchor
  interface; basic JWT auth and basic logging.
- GC-8. The UI SHALL be plain and professional (no gradient/glassmorphism decoration).

## Actors

- **Student**: submit notice, view verification result, view evidence trail, verify
  document integrity, subscribe to alerts.
- **Reviewer/Annotator**: review unresolved cases, confirm/correct relationship, annotate
  benchmark pairs.
- **Admin**: manage institution sources, trigger scheduled fetch.
- **Institution Issuer** (Tier 2, stretch): publish official notice (stub, synthetic
  accounts only).

## Relationship taxonomy

The comparison classifies the relationship of a submission to the closest official notice
as exactly one of: `consistent`, `contradictory`, `superseded`, `corrected`, `extended`,
`cancelled`, `unresolved`.

---

## 1. Ingestion

- R1.1. The system SHALL provide scheduled fetch of official notices from **at least three**
  fictional institutions via **three per-institution adapter classes**, each independently
  replaceable behind a common adapter interface.
- R1.2. An Admin SHALL be able to trigger the scheduled fetch on demand (synchronous, in
  process; no worker queue).
- R1.3. A Student SHALL be able to submit a notice by **file upload** (image or PDF) or by
  **pasted text**. Email ingestion is out of scope.
- R1.4. Each fetched official notice SHALL record its **source URL** and **retrieval
  timestamp**.
- R1.5. Adapters SHALL read from local synthetic fixtures (no live scraping required for
  the demo) while preserving the adapter interface so a real HTTP fetch could replace them.

## 2. Extraction

- R2.1. The system SHALL run OCR on uploaded images via Tesseract (pytesseract) when a
  Tesseract binary is available, and SHALL extract embedded text from PDFs. When no OCR
  binary is available, the system SHALL degrade gracefully and accept pasted/embedded text
  without crashing (deviation logged in HANDOFF.md).
- R2.2. The system SHALL extract structured fields from notice text: **issuer, date,
  deadline, audience, action**.
- R2.3. The system SHALL run a **redaction pass** masking personal data (names, roll
  numbers, contact details such as email/phone) **before storage**.
- R2.4. The system SHALL persist only redacted text and extracted fields. Unredacted
  originals SHALL NOT be persisted (GC-5).

### Data handling and retention policy (scope note §1, §6)

- R2.5. Personal identifiers — **names, roll/registration numbers, and contact details
  (email/phone)** — SHALL be redacted at ingestion **before** the notice is stored or
  indexed. Field extraction SHALL run over the redacted text so no identifier reaches a
  stored field value.
- R2.6. The system **SHALL NOT retain the unredacted original.** No column, attribute, or
  side artifact SHALL hold the pre-redaction text once ingestion completes; the
  redaction-before-storage guarantee is enforced structurally (the `notice` table has a
  `redacted_text` column and **no** unredacted-original column).
- R2.7. Raw fetched files SHALL be kept **only for the duration of the project
  evaluation**, and SHALL NOT be retained beyond it.
- R2.8. The **benchmark released with the report SHALL contain redacted text only.**

## 3. Provenance

- R3.1. The system SHALL compute a **SHA-256** hash per ingested notice over its
  canonical redacted content.
- R3.2. The system SHALL store source URL and retrieval timestamp per notice (see R1.4).
- R3.3. The system SHALL build a **daily Merkle tree** over that day's notice hashes,
  store a **per-notice Merkle proof**, and anchor the **root** via the Anchor interface.
- R3.4. The system SHALL expose a **verification endpoint** that recomputes a notice's hash
  and checks its Merkle proof against the stored/anchored root. A mismatch SHALL be
  surfaced to the student as a **tamper signal**.
- R3.5. On-chain anchoring SHALL be optional and SHALL NEVER block ingestion (GC-3).

## 4. Comparison

- R4.1. Given a submission, the system SHALL retrieve **candidate** official notices
  (filtered by issuer/audience, ranked by lexical similarity).
- R4.2. The system SHALL classify the relationship to the best candidate in a **single
  NLI/LLM step** behind the **ComparisonModel** interface, producing a label and a
  **confidence score** in [0, 1].
- R4.3. When confidence is **below the configured threshold**, the label SHALL be forced
  to `unresolved` and the case SHALL be enqueued into the reviewer queue (GC-4).
- R4.4. The comparison SHALL correctly handle low-lexical-overlap contradictions such as
  "exam postponed to 22 Sept" vs "exam on 15 Sept" (via the MOCK fixtures at minimum).
- R4.5. The system SHALL persist typed temporal relations as **edges in relational tables**
  linking submission and official notice with label, confidence, and rationale.

## 5. Reviewer console

- R5.1. A Reviewer SHALL see an **unresolved queue** of cases.
- R5.2. A Reviewer SHALL be able to **confirm or correct** the relationship label of a case,
  which updates the stored edge and removes it from the queue.
- R5.3. The system SHALL provide a **two-annotator benchmark screen** where two annotators
  label the same set of pairs, and SHALL compute and display a **Cohen's kappa** report of
  inter-annotator agreement.

## 6. Evaluation harness (CLI)

- R6.1. The system SHALL provide a **CLI script** that computes: field-extraction **F1 per
  field**, relationship **precision/recall/F1**, **false-confirmation rate**,
  **unresolved-case rate**, and **Cohen's kappa**.
- R6.2. The harness SHALL support a **temporal holdout** split and a **fully held-out
  institution** split.
- R6.3. The harness SHALL evaluate against four baselines: **chronological feed**,
  **page-change monitor**, **off-the-shelf NLI**, and **prompted LLM** (the latter two may
  be represented by the MOCK/HF model paths in the prototype).
- R6.4. The harness SHALL print a readable report and exit non-zero only on execution error
  (not on poor metrics).

## 7. Auth, platform, and seed data

- R7.1. The system SHALL provide **JWT-based auth** with roles: student, reviewer, admin,
  issuer. Role-appropriate routes SHALL be protected.
- R7.2. The frontend SHALL be an **installable PWA** (manifest + service worker).
- R7.3. A **seed script** SHALL create synthetic data for **3 fictional institutions**
  (~40 official notices each) and **~60 student submissions** covering **every relationship
  type**, including deliberately ambiguous pairs that resolve to `unresolved` and
  low-lexical-overlap pairs. The seed script SHALL be **idempotent**.
- R7.4. The system SHALL provide basic request logging.

## 8. Acceptance (demo-level)

- A-1. `make demo` (or documented single command) starts backend + frontend with seeded
  data, no paid keys, MOCK model, LOCAL anchor.
- A-2. From the UI, a student can submit a notice and see a classified result with
  confidence, evidence trail, and integrity check.
- A-3. An ambiguous submission surfaces as `unresolved` and appears in the reviewer queue.
- A-4. A reviewer can resolve a case and run the two-annotator kappa screen.
- A-5. An admin can list/add institution sources and trigger a fetch.
- A-6. The issuer can publish a notice (stubbed, synthetic).
- A-7. `python -m finalsay.eval.harness` prints all required metrics for all baselines.
- A-8. Backend unit/integration tests pass via `pytest`.
