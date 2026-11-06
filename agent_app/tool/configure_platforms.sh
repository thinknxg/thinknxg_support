#!/usr/bin/env bash
# Creates the Windows, Android and iOS runner projects (flutter create) and applies the settings the app needs:
#  - Android: INTERNET permission, the sign-in callback activity for com.thinknxg.agent://oauth2redirect
#  - iOS: nothing extra (ASWebAuthenticationSession handles the app-scheme callback)
#  - Windows: window title
# Safe to run again. Run from agent_app/.
set -euo pipefail
cd "$(dirname "$0")/.."

flutter create --project-name thinknxg_agent --org com.thinknxg --platforms=windows,android,ios . >/dev/null

MANIFEST=android/app/src/main/AndroidManifest.xml
if ! grep -q 'android.permission.INTERNET' "$MANIFEST"; then
  perl -0pi -e 's#<application#<uses-permission android:name="android.permission.INTERNET"/>\n    <application#' "$MANIFEST"
fi
if ! grep -q 'flutter_web_auth_2.CallbackActivity' "$MANIFEST"; then
  perl -0pi -e 's#</application>#    <activity android:name="com.linusu.flutter_web_auth_2.CallbackActivity" android:exported="true">\n            <intent-filter android:label="flutter_web_auth_2">\n                <action android:name="android.intent.action.VIEW" />\n                <category android:name="android.intent.category.DEFAULT" />\n                <category android:name="android.intent.category.BROWSABLE" />\n                <data android:scheme="com.thinknxg.agent" />\n            </intent-filter>\n        </activity>\n    </application>#' "$MANIFEST"
fi
perl -pi -e 's#android:label="thinknxg_agent"#android:label="thinkNXG Agent"#' "$MANIFEST"

# flutter_secure_storage needs API 23+ for its encrypted preferences
GRADLE=$(ls android/app/build.gradle.kts android/app/build.gradle 2>/dev/null | head -1)
perl -pi -e 's/minSdk( =|) flutter\.minSdkVersion/minSdk$1 23/' "$GRADLE"

PLIST=ios/Runner/Info.plist
if [ -f "$PLIST" ]; then
  perl -pi -e 's#<string>Thinknxg Agent</string>#<string>thinkNXG Agent</string>#' "$PLIST"
fi

MAIN_CPP=windows/runner/main.cpp
if [ -f "$MAIN_CPP" ]; then
  perl -pi -e 's#L"thinknxg_agent"#L"thinkNXG Support Agent"#' "$MAIN_CPP"
fi
echo "Platforms configured."
