# FinalSay — developer/demo Makefile
#
# All Python targets use the backend virtualenv interpreter (Python 3.11),
# created on demand from the pyenv 3.11 interpreter. Defaults run offline with
# SQLite + MOCK comparison model + LOCAL anchor (no paid API keys).

ROOT_DIR   := $(shell pwd)
BACKEND    := $(ROOT_DIR)/backend
WEB        := $(ROOT_DIR)/apps/web
VENV       := $(BACKEND)/.venv
VENV_PY    := $(VENV)/bin/python
PYENV_PY   := $(HOME)/.pyenv/versions/3.11.15/bin/python
PYTHON_BIN := $(shell [ -x "$(PYENV_PY)" ] && echo "$(PYENV_PY)" || command -v python3.11 || command -v python3)

.PHONY: help demo backend frontend seed test eval venv install clean

help:
	@echo "FinalSay make targets:"
	@echo "  make demo      Run the full one-command demo (backend + Vite frontend)"
	@echo "  make backend   Run the FastAPI backend only (uvicorn on :8000)"
	@echo "  make frontend  Run the Vite dev server only (:5173)"
	@echo "  make seed      Seed the database idempotently"
	@echo "  make test      Run the backend pytest suite"
	@echo "  make eval      Run the evaluation harness for both splits"
	@echo "  make install   Create the venv and install backend requirements"
	@echo "  make clean     Remove the venv, SQLite db, caches, and node_modules"

# --- Environment --------------------------------------------------------------
$(VENV_PY):
	$(PYTHON_BIN) -m venv $(VENV)
	$(VENV_PY) -m pip install --upgrade pip

venv: $(VENV_PY)

install: venv
	$(VENV_PY) -m pip install -r $(BACKEND)/requirements.txt

# --- Demo ---------------------------------------------------------------------
demo:
	$(ROOT_DIR)/scripts/run_demo.sh

# --- Individual services ------------------------------------------------------
backend: install
	cd $(BACKEND) && $(VENV_PY) -m uvicorn finalsay.main:app --host 127.0.0.1 --port 8000

frontend:
	cd $(WEB) && npm install && npm run dev -- --host 127.0.0.1 --port 5173

# --- Data ---------------------------------------------------------------------
seed: install
	cd $(BACKEND) && $(VENV_PY) -m finalsay.seed.seed

# --- Verification -------------------------------------------------------------
test: install
	cd $(BACKEND) && $(VENV_PY) -m pytest finalsay/tests -q

eval: install
	cd $(BACKEND) && $(VENV_PY) -m finalsay.eval.harness --split temporal
	cd $(BACKEND) && $(VENV_PY) -m finalsay.eval.harness --split institution

# --- Cleanup ------------------------------------------------------------------
clean:
	rm -rf $(VENV)
	rm -f $(BACKEND)/finalsay.db $(ROOT_DIR)/finalsay.db
	find $(BACKEND) -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf $(BACKEND)/.pytest_cache
	rm -rf $(WEB)/node_modules $(WEB)/dist $(WEB)/dev-dist
