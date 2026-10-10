#!/bin/bash
# Start everything Jarvis needs with one command:  ./start.sh
# Starts Ollama (if not running), the Python backend and the web UI,
# then opens the app in your browser. Ctrl+C stops all of it.
set -e
cd "$(dirname "$0")"

# --- 1. Ollama -----------------------------------------------------------
if ! curl -s http://localhost:11434/api/version >/dev/null 2>&1; then
  echo "▸ Starting Ollama…"
  # Flash attention makes reading long prompts (tool schemas) faster on Apple
  # Silicon; Ollama ignores it for models that don't support it.
  OLLAMA_FLASH_ATTENTION=1 ollama serve >/dev/null 2>&1 &
  OLLAMA_PID=$!
  sleep 2
else
  echo "▸ Ollama already running"
fi

# --- 2. Backend ----------------------------------------------------------
# macOS ships Python 3.9, which can't install the backend (onnxruntime has no
# 3.9 wheel). Pick a 3.11+ interpreter ourselves instead of a bare python3.
is_new_enough() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; }
if [ -x backend/.venv/bin/python ] && ! is_new_enough backend/.venv/bin/python; then
  echo "✗ backend/.venv uses Python $(backend/.venv/bin/python -V 2>&1 | cut -d' ' -f2); Jarvis needs 3.11+."
  echo "  Fix: brew install python@3.12, delete the backend/.venv folder, run ./start.sh again."
  exit 1
fi
if [ ! -x backend/.venv/bin/python ]; then
  PY=""
  for cand in python3.13 python3.12 python3.11 /opt/homebrew/bin/python3 python3; do
    if command -v "$cand" >/dev/null 2>&1 && is_new_enough "$cand"; then PY="$cand"; break; fi
  done
  if [ -z "$PY" ]; then
    echo "✗ Jarvis needs Python 3.11 or newer (macOS's built-in python3 is 3.9)."
    echo "  Install one with:  brew install python@3.12   then run ./start.sh again."
    exit 1
  fi
  echo "▸ First run: creating Python environment with $("$PY" -V)…"
  "$PY" -m venv --clear backend/.venv
fi
# The marker is written only after pip succeeds, so a half-finished install
# (network drop, Ctrl+C) is retried instead of leaving an empty environment;
# a pull that changes requirements.txt reinstalls too.
DEPS_OK=backend/.venv/.deps-installed
if [ ! -f "$DEPS_OK" ] || [ backend/requirements.txt -nt "$DEPS_OK" ]; then
  echo "▸ Installing backend packages…"
  if backend/.venv/bin/pip install -q -r backend/requirements.txt; then
    touch "$DEPS_OK"
  else
    echo "✗ Installing backend packages failed — see the error above, then run ./start.sh again."
    exit 1
  fi
fi
echo "▸ Starting backend on http://127.0.0.1:8765"
(cd backend && .venv/bin/python run.py) &
BACKEND_PID=$!

# --- 3. Frontend ---------------------------------------------------------
# Install on first run, and again whenever a pull changed the dependencies
# (npm records each install in node_modules/.package-lock.json).
if [ ! -d frontend/node_modules ] || \
   [ frontend/package-lock.json -nt frontend/node_modules/.package-lock.json ]; then
  echo "▸ Installing frontend packages…"
  (cd frontend && npm install --no-audit --no-fund)
fi
echo "▸ Starting UI on http://localhost:5173"
(cd frontend && npm run dev) &
FRONTEND_PID=$!

# Open the browser once the UI actually answers, not after a fixed guess.
for _ in $(seq 1 30); do curl -s http://localhost:5173 >/dev/null 2>&1 && break; sleep 0.5; done
open http://localhost:5173

echo ""
echo "✅ Jarvis is running — press Ctrl+C to stop."
trap 'kill $BACKEND_PID $FRONTEND_PID ${OLLAMA_PID:-} 2>/dev/null; exit 0' INT TERM
wait
