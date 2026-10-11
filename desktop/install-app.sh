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

# Apple Silicon only runs signed apps. Sign with a local certificate (no Apple
# account needed): macOS ties permissions to the signature, and this one stays
# the same across rebuilds — a temporary ("ad-hoc") signature changes every
# build, so macOS would treat each new build as a stranger.
IDENTITY="Jarvis Local Signing"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
identity_hash() {
  { security find-identity -p codesigning "$KEYCHAIN" 2>/dev/null || true; } \
    | awk -v name="\"$IDENTITY\"" 'index($0, name) { print $2; exit }'
}
NEW_IDENTITY=0
if [ -z "$(identity_hash)" ]; then
  echo "Creating a signing certificate for Jarvis in your login keychain (one time)…"
  TMP="$(mktemp -d)"
  if ( umask 077
       printf '%s\n' "[req]" "distinguished_name = dn" "x509_extensions = ext" "prompt = no" \
         "[dn]" "CN = $IDENTITY" "[ext]" "basicConstraints = critical, CA:false" \
         "keyUsage = critical, digitalSignature" "extendedKeyUsage = critical, codeSigning" \
         > "$TMP/cert.cnf"
       PASS="$(/usr/bin/openssl rand -hex 16)"
       /usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -config "$TMP/cert.cnf" \
         -keyout "$TMP/key.pem" -out "$TMP/cert.pem" 2>/dev/null &&
       /usr/bin/openssl pkcs12 -export -inkey "$TMP/key.pem" -in "$TMP/cert.pem" \
         -name "$IDENTITY" -out "$TMP/id.p12" -passout "pass:$PASS" &&
       security import "$TMP/id.p12" -k "$KEYCHAIN" -P "$PASS" -T /usr/bin/codesign >/dev/null ); then
    NEW_IDENTITY=1
  else
    echo "Couldn't create the certificate."
  fi
  rm -f "$TMP/cert.cnf" "$TMP/key.pem" "$TMP/cert.pem" "$TMP/id.p12"
  rmdir "$TMP"
fi
HASH="$(identity_hash)"
echo "Signing Jarvis… (if macOS asks to let codesign use the key, enter your Mac password and choose Always Allow)"
if [ -n "$HASH" ] && codesign --force --deep --keychain "$KEYCHAIN" --sign "$HASH" "$APP"; then
  echo "Signed with \"$IDENTITY\"."
  if [ "$NEW_IDENTITY" = 1 ]; then
    # Permissions given to earlier builds belong to their old signature and
    # can't work any more; clear them so macOS asks afresh.
    tccutil reset All com.jarvis.assistant >/dev/null 2>&1 || true
    echo "Cleared Jarvis's old permissions (they belonged to the previous signature)."
  fi
else
  echo "Using a temporary signature — macOS may ask for permissions again after the next rebuild."
  codesign --force --deep --sign - "$APP"
fi

# Only one Jarvis at a time: quit the installed one and any `npm start` copies.
osascript -e 'tell application "Jarvis" to quit' >/dev/null 2>&1 || true
pkill -f "jarvis/desktop/node_modules/electron/dist/Electron.app" >/dev/null 2>&1 || true
# Let their backend shut down so the new app starts a fresh one.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  lsof -nP -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1 || break
  sleep 0.5
done

if [ -d "/Applications/Jarvis.app" ]; then
  rm -rf "/Applications/Jarvis.app"
fi
ditto "$APP" "/Applications/Jarvis.app"

echo "Installed in Applications. Opening Jarvis…"
echo "(Allow the microphone, camera, Accessibility and Screen Recording when asked —"
echo " Jarvis → Setup check lists anything still missing.)"
open "/Applications/Jarvis.app"
