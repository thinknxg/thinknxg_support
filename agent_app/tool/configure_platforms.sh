#!/usr/bin/env bash
# Creates the Windows, Android and iOS runner projects (flutter create) and applies the settings the app needs:
#  - Android: INTERNET permission, the sign-in callback activity for com.thinknxg.agent://oauth2redirect
#  - iOS: nothing extra (ASWebAuthenticationSession handles the app-scheme callback)
#  - Windows: window title
# Safe to run again. Run from agent_app/.
set -euo pipefail
cd "$(dirname "$0")/.."

flutter create --project-name thinknxg_agent --org com.thinknxg --platforms=windows,android,ios .

MANIFEST=android/app/src/main/AndroidManifest.xml
if ! grep -q 'android.permission.INTERNET' "$MANIFEST"; then
  perl -0pi -e 's#<application#<uses-permission android:name="android.permission.INTERNET"/>\n    <application#' "$MANIFEST"
fi
if ! grep -q 'flutter_web_auth_2.CallbackActivity' "$MANIFEST"; then
  perl -0pi -e 's#</application>#    <activity android:name="com.linusu.flutter_web_auth_2.CallbackActivity" android:exported="true">\n            <intent-filter android:label="flutter_web_auth_2">\n                <action android:name="android.intent.action.VIEW" />\n                <category android:name="android.intent.category.DEFAULT" />\n                <category android:name="android.intent.category.BROWSABLE" />\n                <data android:scheme="com.thinknxg.agent" />\n            </intent-filter>\n        </activity>\n    </application>#' "$MANIFEST"
fi
perl -pi -e 's#android:label="thinknxg_agent"#android:label="thinkNXG Agent"#' "$MANIFEST"

# flutter_secure_storage needs API 23+ for its encrypted preferences
for GRADLE in android/app/build.gradle.kts android/app/build.gradle; do
  if [ -f "$GRADLE" ]; then perl -pi -e 's/minSdk( =|) flutter\.minSdkVersion/minSdk$1 23/' "$GRADLE"; fi
done

# Release signing (CI writes android/key.properties from secrets) and core library desugaring
# (flutter_local_notifications). Added once, at the end of the app's Gradle script.
KTS=android/app/build.gradle.kts
if [ -f "$KTS" ] && ! grep -q 'thinknxg-agent-release-signing' "$KTS"; then
  cat >> "$KTS" <<'GRADLE'

// thinknxg-agent-release-signing
val agentKeystoreFile = rootProject.file("key.properties")
val agentKeystoreProperties: Map<String, String> =
    if (agentKeystoreFile.exists())
        agentKeystoreFile.readLines().filter { it.contains("=") }
            .associate { it.substringBefore("=").trim() to it.substringAfter("=").trim() }
    else emptyMap()
android {
    compileOptions { isCoreLibraryDesugaringEnabled = true }
    signingConfigs {
        if (agentKeystoreFile.exists()) {
            create("agentRelease") {
                keyAlias = agentKeystoreProperties.getValue("keyAlias")
                keyPassword = agentKeystoreProperties.getValue("keyPassword")
                storeFile = file(agentKeystoreProperties.getValue("storeFile"))
                storePassword = agentKeystoreProperties.getValue("storePassword")
            }
        }
    }
    buildTypes {
        getByName("release") {
            if (agentKeystoreFile.exists()) signingConfig = signingConfigs.getByName("agentRelease")
        }
    }
}
dependencies { add("coreLibraryDesugaring", "com.android.tools:desugar_jdk_libs:2.1.4") }
GRADLE
fi

# Firebase (push) needs iOS 15
PBX=ios/Runner.xcodeproj/project.pbxproj
if [ -f "$PBX" ]; then perl -pi -e 's/IPHONEOS_DEPLOYMENT_TARGET = 1[0-4]\.0;/IPHONEOS_DEPLOYMENT_TARGET = 15.0;/g' "$PBX"; fi
if [ -f ios/Podfile ]; then
  perl -pi -e "s/^#?\s*platform :ios, '[0-9.]+'/platform :ios, '15.0'/" ios/Podfile
fi
# iOS: allow notifications in the background (push)
if [ -f ios/Runner/Info.plist ] && ! grep -q 'UIBackgroundModes' ios/Runner/Info.plist; then
  perl -0pi -e 's#<dict>#<dict>\n\t<key>UIBackgroundModes</key>\n\t<array>\n\t\t<string>remote-notification</string>\n\t</array>#' ios/Runner/Info.plist
fi

PLIST=ios/Runner/Info.plist
if [ -f "$PLIST" ]; then
  perl -pi -e 's#<string>Thinknxg Agent</string>#<string>thinkNXG Agent</string>#' "$PLIST"
fi

# flutter_local_notifications' Windows code still uses <experimental/coroutine>, which newer MSVC rejects
WCM=windows/CMakeLists.txt
if [ -f "$WCM" ] && ! grep -q '_SILENCE_EXPERIMENTAL_COROUTINE_DEPRECATION_WARNINGS' "$WCM"; then
  perl -0pi -e 's/(cmake_minimum_required\([^)]*\)\r?\n)/$1add_compile_definitions(_SILENCE_EXPERIMENTAL_COROUTINE_DEPRECATION_WARNINGS)\n/' "$WCM"
fi

MAIN_CPP=windows/runner/main.cpp
if [ -f "$MAIN_CPP" ]; then
  perl -pi -e 's#L"thinknxg_agent"#L"thinkNXG Support Agent"#' "$MAIN_CPP"
fi
echo "Platforms configured."
