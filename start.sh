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
if [ ! -d backend/.venv ]; then
  echo "▸ First run: creating Python environment…"
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q -r backend/requirements.txt
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

sleep 3
open http://localhost:5173

echo ""
echo "✅ Jarvis is running — press Ctrl+C to stop."
trap 'kill $BACKEND_PID $FRONTEND_PID ${OLLAMA_PID:-} 2>/dev/null; exit 0' INT TERM
wait
