# PostgreSQL path verification (design.md §8)

**Status: VERIFIED — Postgres ran in-sandbox and the app worked against it.**

design.md §8 names PostgreSQL as the production database while the zero-setup
demo defaults to SQLite. This document records a genuine, in-session attempt to
bring up PostgreSQL, apply the schema, seed it, and exercise real FinalSay
behavior against it, so the documented Postgres support is reproducible rather
than aspirational.

Run date: 2026-09-07. Branch: `work/finalsay-prototype`.

## What actually ran

The full sequence below ran inside a **single foreground shell command** (the
sandbox reaps background daemons between separate tool calls, so a container
started in one call is gone by the next; everything had to happen in one shot).

| Step | Command (abridged) | Result |
| --- | --- | --- |
| Start Postgres | `podman run -d --name finalsay-pg -e POSTGRES_USER=finalsay -e POSTGRES_PASSWORD=finalsay -e POSTGRES_DB=finalsay -p 127.0.0.1:5432:5432 postgres:16-alpine` | image pulled + container up |
| Readiness | `podman exec finalsay-pg pg_isready -U finalsay -d finalsay` loop | ready after ~5s |
| Schema (migrations) | `FINALSAY_DATABASE_URL=<pg> .venv/bin/python -c 'from finalsay.db import Base, engine; Base.metadata.create_all(bind=engine)'` | `create_all OK` |
| Seed (run 1) | `FINALSAY_DATABASE_URL=<pg> .venv/bin/python -m finalsay.seed.seed` | counts below |
| Seed (run 2, idempotency) | same command again | identical counts |
| Behavior smoke | `FINALSAY_DATABASE_URL=<pg> .venv/bin/python -m finalsay.tests.pg_smoke` | `PASS` |
| Teardown | `podman rm -f finalsay-pg` | no leftover container |

The Postgres URL used is exactly the one documented in `.env.example` /
`run_demo.sh`:

```
postgresql+psycopg2://finalsay:finalsay@127.0.0.1:5432/finalsay
```

## Seed counts observed on PostgreSQL

Identical across both seed runs (idempotent) and identical to the SQLite demo
counts:

| Table | Count |
| --- | --- |
| institutions | 3 |
| users | 4 |
| official_notices | 120 |
| submissions | 65 |
| notice_fields | 925 |
| benchmark_pairs | 308 |
| benchmark_annotations | 616 |
| merkle_roots | 1 |
| merkle_proofs | 185 |
| anchor_blocks | 1 |

## Behavior exercised against PostgreSQL

`backend/finalsay/tests/pg_smoke.py` (a targeted script, NOT part of the default
pytest run — see the conftest note below) ran against the live Postgres and
passed:

1. **Submit + classify** — a fresh submission was created and classified through
   the real comparison pipeline. Outcome: `label='unresolved' confidence=0.40
   gated=True` (a genuine, correctly gated below-threshold result, not a mock
   short-circuit).
2. **Provenance build + verify** — the daily Merkle root was built and a seeded
   official notice verified: `ok.ok=True`, and with `tamper=True` the result
   correctly flipped to `ok=False, tamper=True`.
3. **Live counts** from Postgres after the extra submission:
   `official_notices=120, submissions=66, users=4`.

## Decisions

- **"Migrations" = SQLAlchemy `create_all`, NOT Alembic.** The app has no Alembic
  setup; `backend/finalsay/db.py` builds the engine from `FINALSAY_DATABASE_URL`
  and the schema is created via `Base.metadata.create_all`. For this prototype
  that is the schema-provisioning step, and the seed script calls it in `main()`.
  Adding Alembic was deliberately **not** done: it is out of scope for verifying
  that the Postgres path runs, and `create_all` is the project's actual
  mechanism. This is called out so the choice is explicit.
- **Direct container, not `docker compose`.** A committed `docker-compose.yml`
  exists at the repo root (the documented artifact), but the compose invocation
  path could not be used in this sandbox — see limitations. A direct
  `podman`/`docker run` container was used instead and worked.

## Limitations / caveats (honest)

- **No compose runtime in this sandbox.** `docker`/`podman` is Podman 5.2.3 and
  runs containers fine, but there is **no `docker-compose` / `podman-compose`
  binary and no Compose v2 plugin** (`docker compose version` fails with
  "looking up compose provider failed"). The committed `docker-compose.yml` is
  correct and usable on a normal Docker host; here it was reproduced with an
  equivalent `docker run` because compose itself is not installed.
- **Containers/daemons do not persist across tool calls** (`--die-with-parent`).
  That is why the entire start → schema → seed → smoke → teardown ran in one
  command and the container was torn down at the end. There is no long-lived
  Postgres to connect to afterward.
- **The default pytest suite does NOT run on Postgres.**
  `backend/finalsay/tests/conftest.py` sets `FINALSAY_DATABASE_URL` to a temp
  SQLite path *before* the app is imported, so the suite always pins SQLite and
  will not honor an external `FINALSAY_DATABASE_URL`. This is intentional (fast,
  hermetic, offline tests) and was left unchanged. To exercise real behavior on
  Postgres we therefore ran the targeted `pg_smoke` script (seed + submit/classify
  + provenance build/verify) rather than the full suite. Making the whole suite
  run on Postgres would require overriding that pinning and is out of scope.

## Reproduce it

On a host with Docker Compose:

```bash
docker compose up -d db
export FINALSAY_DATABASE_URL=postgresql+psycopg2://finalsay:finalsay@127.0.0.1:5432/finalsay
( cd backend && .venv/bin/python -c 'from finalsay.db import Base, engine; Base.metadata.create_all(bind=engine)' )
( cd backend && .venv/bin/python -m finalsay.seed.seed )
( cd backend && FINALSAY_DATABASE_URL="$FINALSAY_DATABASE_URL" .venv/bin/python -m finalsay.tests.pg_smoke )
docker compose down
```

Without a compose runtime (as in this sandbox), replace `docker compose up -d db`
with the equivalent `docker run -d --name finalsay-pg -e POSTGRES_USER=finalsay
-e POSTGRES_PASSWORD=finalsay -e POSTGRES_DB=finalsay -p 127.0.0.1:5432:5432
postgres:16-alpine` and `docker compose down` with `docker rm -f finalsay-pg`.

The default demo is unaffected: SQLite remains the default and `make test` /
both eval splits stay green.
