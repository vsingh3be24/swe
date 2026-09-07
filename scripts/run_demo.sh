#!/usr/bin/env bash
#
# FinalSay one-command demo launcher.
#
# Defaults (no flags): SQLite + MOCK comparison model + LOCAL anchor. No paid
# API keys, no external services required.
#
#   scripts/run_demo.sh              # SQLite demo (recommended)
#   scripts/run_demo.sh --postgres   # boot the sandbox PostgreSQL in-session
#
# It creates/reuses the backend virtualenv (Python 3.11), installs backend
# requirements, seeds the database idempotently, starts uvicorn in the
# background, then runs the Vite dev server in the FOREGROUND. Keeping Vite in
# the foreground keeps this script (the parent process) alive, which keeps the
# background uvicorn alive for the whole session. An EXIT trap stops uvicorn
# (and Postgres, if started) on Ctrl-C / shutdown.
#
set -euo pipefail

# --- Resolve paths ------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
WEB_DIR="${ROOT_DIR}/apps/web"
VENV_DIR="${BACKEND_DIR}/.venv"

# Prefer the pyenv 3.11 interpreter (bare python3 is 3.9 on this sandbox).
PYENV_PY="${HOME}/.pyenv/versions/3.11.15/bin/python"
if [[ -x "${PYENV_PY}" ]]; then
  PYTHON_BIN="${PYENV_PY}"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.11)"
else
  PYTHON_BIN="$(command -v python3)"
fi

# --- Args ---------------------------------------------------------------------
USE_POSTGRES=0
for arg in "$@"; do
  case "${arg}" in
    --postgres) USE_POSTGRES=1 ;;
    -h|--help)
      grep '^#' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown argument: ${arg}" >&2; exit 2 ;;
  esac
done

# --- Cleanup trap -------------------------------------------------------------
UVICORN_PID=""
PG_STARTED=0
PGDATA="/var/lib/pgsql/data"

cleanup() {
  local ec=$?
  if [[ -n "${UVICORN_PID}" ]] && kill -0 "${UVICORN_PID}" 2>/dev/null; then
    echo "[run_demo] stopping backend (pid ${UVICORN_PID})..."
    kill "${UVICORN_PID}" 2>/dev/null || true
    wait "${UVICORN_PID}" 2>/dev/null || true
  fi
  if [[ "${PG_STARTED}" -eq 1 ]]; then
    echo "[run_demo] stopping PostgreSQL..."
    sudo -u postgres pg_ctl -D "${PGDATA}" stop -m fast >/dev/null 2>&1 || true
  fi
  exit "${ec}"
}
trap cleanup EXIT INT TERM

# --- PostgreSQL (optional) ----------------------------------------------------
start_postgres() {
  local sockdir="/var/run/postgresql"
  echo "[run_demo] starting PostgreSQL (in-session)..."

  # Ensure the socket directory exists and is owned by postgres.
  sudo mkdir -p "${sockdir}"
  sudo chown postgres:postgres "${sockdir}" 2>/dev/null || true

  # initdb only if the data dir is empty / uninitialized.
  if [[ ! -s "${PGDATA}/PG_VERSION" ]]; then
    echo "[run_demo] initializing PostgreSQL data dir at ${PGDATA}..."
    sudo mkdir -p "${PGDATA}"
    sudo chown postgres:postgres "${PGDATA}"
    sudo -u postgres initdb -D "${PGDATA}" >/dev/null
  fi

  # Start listening on 127.0.0.1 using the writable socket dir (NOT /tmp).
  sudo -u postgres pg_ctl -D "${PGDATA}" \
    -o "-c listen_addresses='127.0.0.1' -k ${sockdir}" \
    -w start >/dev/null
  PG_STARTED=1

  # Create the finalsay role and database if they do not exist yet.
  if ! sudo -u postgres psql -h 127.0.0.1 -tAc \
      "SELECT 1 FROM pg_roles WHERE rolname='finalsay'" | grep -q 1; then
    sudo -u postgres psql -h 127.0.0.1 -c \
      "CREATE ROLE finalsay LOGIN PASSWORD 'finalsay';" >/dev/null
  fi
  if ! sudo -u postgres psql -h 127.0.0.1 -tAc \
      "SELECT 1 FROM pg_database WHERE datname='finalsay'" | grep -q 1; then
    sudo -u postgres psql -h 127.0.0.1 -c \
      "CREATE DATABASE finalsay OWNER finalsay;" >/dev/null
  fi

  export FINALSAY_DATABASE_URL="postgresql+psycopg2://finalsay:finalsay@127.0.0.1:5432/finalsay"
  echo "[run_demo] FINALSAY_DATABASE_URL=${FINALSAY_DATABASE_URL}"
}

if [[ "${USE_POSTGRES}" -eq 1 ]]; then
  start_postgres
else
  echo "[run_demo] using SQLite (default: ${FINALSAY_DATABASE_URL:-sqlite:///./finalsay.db})"
fi

# --- Backend venv + deps ------------------------------------------------------
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "[run_demo] creating backend venv with ${PYTHON_BIN} ($(${PYTHON_BIN} --version 2>&1))..."
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi
VENV_PY="${VENV_DIR}/bin/python"

echo "[run_demo] installing backend requirements..."
"${VENV_PY}" -m pip install --quiet --upgrade pip
"${VENV_PY}" -m pip install --quiet -r "${BACKEND_DIR}/requirements.txt"

# --- Seed (idempotent) --------------------------------------------------------
echo "[run_demo] seeding database (idempotent)..."
( cd "${BACKEND_DIR}" && "${VENV_PY}" -m finalsay.seed.seed )

# --- Backend (background) -----------------------------------------------------
echo "[run_demo] starting backend on http://127.0.0.1:8000 ..."
( cd "${BACKEND_DIR}" && exec "${VENV_PY}" -m uvicorn finalsay.main:app \
    --host 127.0.0.1 --port 8000 ) &
UVICORN_PID=$!

# Wait for the backend health endpoint to answer.
echo "[run_demo] waiting for backend health..."
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:8000/api/health" >/dev/null 2>&1; then
    echo "[run_demo] backend is up."
    break
  fi
  sleep 1
done

# --- Frontend deps ------------------------------------------------------------
echo "[run_demo] installing frontend dependencies (npm install)..."
( cd "${WEB_DIR}" && npm install --no-fund --no-audit )

# --- Banner -------------------------------------------------------------------
cat <<'BANNER'

============================================================
  FinalSay demo is starting
============================================================
  Frontend (PWA):  http://127.0.0.1:5173
  Backend API:     http://127.0.0.1:8000
  API docs:        http://127.0.0.1:8000/docs

  Seeded demo users (email / password):
    student   student@finalsay.demo  / student123
    reviewer  reviewer@finalsay.demo / reviewer123
    admin     admin@finalsay.demo    / admin123
    issuer    issuer@finalsay.demo   / issuer123

  Press Ctrl-C to stop (backend is stopped automatically).
============================================================

BANNER

# --- Frontend (foreground; keeps parent + backend alive) ----------------------
# Not exec'd: the parent shell must survive to run the EXIT trap that stops the
# background uvicorn (and Postgres) when Vite is interrupted.
cd "${WEB_DIR}"
npm run dev -- --host 127.0.0.1 --port 5173
