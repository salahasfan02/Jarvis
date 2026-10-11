#!/bin/bash
# Build Jarvis.app and install it in /Applications.
#   cd desktop && npm run install-app
# Run it from your own Terminal: the app is then built by your account.
set -euo pipefail
cd "$(dirname "$0")"

echo "Building Jarvis.app…"
npm run package

APP="dist/mac-arm64/Jarvis.app"
[ -d "$APP" ] || APP="dist/mac/Jarvis.app"
if [ ! -d "$APP" ]; then
  echo "The build didn't produce Jarvis.app — see the messages above."
  exit 1
fi

# Apple Silicon only runs signed apps; sign it locally (no Apple account needed).
codesign --force --deep --sign - "$APP"

# Only one Jarvis at a time: quit the installed one and any `npm start` copies.
osascript -e 'tell application "Jarvis" to quit' >/dev/null 2>&1 || true
pkill -f "jarvis/desktop/node_modules/electron/dist/Electron.app" >/dev/null 2>&1 || true
sleep 1

if [ -d "/Applications/Jarvis.app" ]; then
  rm -rf "/Applications/Jarvis.app"
fi
ditto "$APP" "/Applications/Jarvis.app"

echo "Installed in Applications. Opening Jarvis…"
echo "(It's a new app to macOS: allow the microphone, camera, Accessibility and Screen"
echo " Recording again when asked — Jarvis → Setup check lists anything still missing.)"
open "/Applications/Jarvis.app"
