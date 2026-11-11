#!/usr/bin/env bash
# Signs the macOS app for distribution outside the App Store (Developer ID), with push (APNs), then notarizes it
# and makes a .dmg. Push on macOS needs a "Developer ID" provisioning profile for the app id with Push
# Notifications switched on; its entitlements are used as they are.
#   tool/sign_macos.sh <App.app> <profile.provisionprofile> [notary key id] [notary issuer id] [AuthKey.p8]
# The Developer ID Application certificate must be in a keychain on the search list.
set -euo pipefail
APP="$1"; PROFILE="$2"; KEY_ID="${3:-}"; ISSUER="${4:-}"; KEY_FILE="${5:-}"
WORK=$(mktemp -d)
IDENTITY=$(security find-identity -v -p codesigning | grep 'Developer ID Application' | head -1 | sed -E 's/.*"(.*)"/\1/')
[ -n "$IDENTITY" ] || { echo "No Developer ID Application certificate found"; exit 1; }

cp "$PROFILE" "$APP/Contents/embedded.provisionprofile"
security cms -D -i "$PROFILE" > "$WORK/profile.plist"
/usr/libexec/PlistBuddy -x -c 'Print :Entitlements' "$WORK/profile.plist" > "$WORK/entitlements.plist"
/usr/libexec/PlistBuddy -c 'Add :com.apple.security.device.audio-input bool true' "$WORK/entitlements.plist" || true
grep -q 'aps-environment' "$WORK/entitlements.plist" || echo "Warning: this profile has no push entitlement; the app will run without push."

# inside out: libraries and frameworks first, the app (with its entitlements) last
find "$APP/Contents" -depth \( -name '*.dylib' -o -name '*.framework' \) -print0 |
  xargs -0 -n1 codesign --force --options runtime --timestamp -s "$IDENTITY"
codesign --force --options runtime --timestamp --entitlements "$WORK/entitlements.plist" -s "$IDENTITY" "$APP"
codesign --verify --deep --strict "$APP"

mkdir -p build/dist
DMG="build/dist/thinkNXG-Support-Agent.dmg"
if [ -n "$KEY_ID" ] && [ -n "$ISSUER" ] && [ -f "$KEY_FILE" ]; then
  ditto -c -k --keepParent "$APP" "$WORK/app.zip"
  xcrun notarytool submit "$WORK/app.zip" --key "$KEY_FILE" --key-id "$KEY_ID" --issuer "$ISSUER" --wait
  xcrun stapler staple "$APP"
else
  echo "Not notarized (no App Store Connect key): macOS will warn when the app is first opened."
fi
hdiutil create -volname "thinkNXG Support Agent" -srcfolder "$APP" -ov -format UDZO "$DMG"
codesign --force --timestamp -s "$IDENTITY" "$DMG"
echo "Signed: $DMG"
