#!/usr/bin/env bash
# Creates the Windows, macOS, Android and iOS runner projects (flutter create) and applies the settings the app needs:
#  - Android: INTERNET permission, the sign-in callback activity for com.thinknxg.agent://oauth2redirect
#  - iOS: nothing extra (ASWebAuthenticationSession handles the app-scheme callback)
#  - Windows: window title, tray start (hidden window), single instance
#  - macOS: no sandbox (Developer ID distribution), microphone, no App Nap; push is added when the app is signed
#    (tool/sign_macos.sh)
# Safe to run again. Run from agent_app/.
set -euo pipefail
cd "$(dirname "$0")/.."

flutter create --project-name thinknxg_agent --org com.thinknxg --platforms=windows,android,ios,macos .

MANIFEST=android/app/src/main/AndroidManifest.xml
if ! grep -q 'android.permission.INTERNET' "$MANIFEST"; then
  perl -0pi -e 's#<application#<uses-permission android:name="android.permission.INTERNET"/>\n    <application#' "$MANIFEST"
fi
if ! grep -q 'flutter_web_auth_2.CallbackActivity' "$MANIFEST"; then
  perl -0pi -e 's#</application>#    <activity android:name="com.linusu.flutter_web_auth_2.CallbackActivity" android:exported="true">\n            <intent-filter android:label="flutter_web_auth_2">\n                <action android:name="android.intent.action.VIEW" />\n                <category android:name="android.intent.category.DEFAULT" />\n                <category android:name="android.intent.category.BROWSABLE" />\n                <data android:scheme="com.thinknxg.agent" />\n            </intent-filter>\n        </activity>\n    </application>#' "$MANIFEST"
fi
perl -pi -e 's#android:label="thinknxg_agent"#android:label="thinkNXG Agent"#' "$MANIFEST"
# voice notes (1.14)
if ! grep -q 'android.permission.RECORD_AUDIO' "$MANIFEST"; then
  perl -0pi -e 's#<application#<uses-permission android:name="android.permission.RECORD_AUDIO"/>\n    <application#' "$MANIFEST"
fi

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
  if ! grep -q 'NSMicrophoneUsageDescription' "$PLIST"; then  # voice notes (1.14)
    perl -0pi -e 's#<dict>#<dict>\n\t<key>NSMicrophoneUsageDescription</key>\n\t<string>Record voice notes for customers.</string>#' "$PLIST"
  fi
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
# ---- 1.15: background alerts -------------------------------------------------------------------------------
# Tray / menu-bar icons: the app icons flutter create made (replace assets/tray_icon.* with your own artwork).
mkdir -p assets
[ -f assets/tray_icon.ico ] || cp windows/runner/resources/app_icon.ico assets/tray_icon.ico
[ -f assets/tray_icon.png ] || cp macos/Runner/Assets.xcassets/AppIcon.appiconset/app_icon_32.png assets/tray_icon.png

# Windows: the app shows its own window (so a start at sign-in can stay hidden in the tray) ...
FW=windows/runner/flutter_window.cpp
if [ -f "$FW" ]; then perl -0pi -e 's/SetNextFrameCallback\(\[&\]\(\) \{\s*this->Show\(\);\s*\}\);/SetNextFrameCallback([&]() {});/' "$FW"; fi
# ... and a second start brings the running app's window back instead of opening another copy.
if [ -f "$MAIN_CPP" ] && ! grep -q 'thinknxg-single-instance' "$MAIN_CPP"; then
  perl -0pi -e 's#(wWinMain\([^)]*\)\s*\{)#$1\n  // thinknxg-single-instance\n  if (HWND running = ::FindWindow(L"FLUTTER_RUNNER_WIN32_WINDOW", L"thinkNXG Support Agent")) {\n    ::ShowWindow(running, SW_SHOWNORMAL);\n    ::SetForegroundWindow(running);\n    return EXIT_SUCCESS;\n  }\n#' "$MAIN_CPP"
fi

if [ -f "$FW" ] && grep -q 'this->Show();' "$FW"; then echo "configure: could not patch $FW (hidden start)"; exit 1; fi
if [ -f "$MAIN_CPP" ] && ! grep -q 'thinknxg-single-instance' "$MAIN_CPP"; then echo "configure: could not patch $MAIN_CPP (single instance)"; exit 1; fi

# Android: notifications on Android 13+, vibration, and Firebase's default channel = the app's alert channel
if ! grep -q 'android.permission.POST_NOTIFICATIONS' "$MANIFEST"; then
  perl -0pi -e 's#<application#<uses-permission android:name="android.permission.POST_NOTIFICATIONS"/>\n    <uses-permission android:name="android.permission.VIBRATE"/>\n    <application#' "$MANIFEST"
fi
if ! grep -q 'default_notification_channel_id' "$MANIFEST"; then
  perl -0pi -e 's#</application>#    <meta-data android:name="com.google.firebase.messaging.default_notification_channel_id" android:value="support_alerts_v2"/>\n    </application>#' "$MANIFEST"
fi

# macOS: distributed outside the App Store (Developer ID), so no sandbox: the app writes its own Launch Agent
# (start at sign-in), listens on 127.0.0.1 for the sign-in callback and keeps its timers running while hidden.
for ENT in macos/Runner/DebugProfile.entitlements macos/Runner/Release.entitlements; do
  if [ -f "$ENT" ]; then
    perl -0pi -e 's#(<key>com.apple.security.app-sandbox</key>\s*)<true/>#$1<false/>#' "$ENT"
    if ! grep -q 'com.apple.security.device.audio-input' "$ENT"; then  # voice notes under the hardened runtime
      perl -0pi -e 's#</dict>\s*</plist>#\t<key>com.apple.security.device.audio-input</key>\n\t<true/>\n</dict>\n</plist>#' "$ENT"
    fi
  fi
done
MPLIST=macos/Runner/Info.plist
if [ -f "$MPLIST" ]; then
  if ! grep -q 'NSMicrophoneUsageDescription' "$MPLIST"; then
    perl -0pi -e 's#<dict>#<dict>\n\t<key>NSMicrophoneUsageDescription</key>\n\t<string>Record voice notes for customers.</string>\n\t<key>NSAppSleepDisabled</key>\n\t<true/>#' "$MPLIST"
  fi
fi
if [ -f macos/Runner/Configs/AppInfo.xcconfig ]; then
  perl -pi -e 's#^PRODUCT_NAME = .*#PRODUCT_NAME = thinkNXG Support Agent#' macos/Runner/Configs/AppInfo.xcconfig
fi
# Firebase needs macOS 10.15+; the Launch Agent uses `open --env` (macOS 11+)
if [ -f macos/Podfile ]; then perl -pi -e "s/^platform :osx, '10\.1[0-4]'/platform :osx, '10.15'/" macos/Podfile; fi
MPBX=macos/Runner.xcodeproj/project.pbxproj
if [ -f "$MPBX" ]; then perl -pi -e 's/MACOSX_DEPLOYMENT_TARGET = 10\.1[0-4];/MACOSX_DEPLOYMENT_TARGET = 10.15;/g' "$MPBX"; fi
echo "Platforms configured."
