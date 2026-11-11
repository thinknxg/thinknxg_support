# thinkNXG Support Agent app

One Flutter codebase for **Windows**, **Android** and **iOS**. Support agents sign in with their own staff account
and work the same conversations and Helpdesk tickets as the web console (`/app/support-chat`). All three use the
same records on the server; nothing is stored on the device except the sign-in token (in the OS secure store).

* Backend contract: [`../docs/agent-api.md`](../docs/agent-api.md)
* Server setup: *Support Agent App Settings* in the desk (thinkNXG Support 1.9+)

## What the app does

| Area | |
|---|---|
| Sign-in | Site address → system browser → Frappe OAuth (authorization code + PKCE). Session restored on launch, sign-in prompt on expiry (work stays underneath), sign-out revokes the token, stops push to the device and clears local data |
| Inbox | Portal, Live Chat, WhatsApp. All / Mine / Unassigned / Waiting, channel, status and queue filters, search, unread counts (per agent), cursor paging |
| Conversation | Timeline (paged back, polled forward), read acknowledgement, claim (one winner), transfer picker (agents online first, with their open chats, or a queue), take over / return to assistant, End chat with wrap-up questions, customer typing / visitor online, customer history (earlier chats and tickets), linked ticket |
| Composer | **Reply to customer** / **Internal note**, canned responses (search or `/shortcut`, placeholders filled by the server), one attachment per message, Sending / Sent / Failed, draft kept on failure, Retry never sends twice, server reasons shown (WhatsApp 24-hour window, files over WhatsApp) |
| Files | Attachments open after the server checks access (per file); downloads are kept in the app's temporary folder and removed at sign-out |
| Tickets | Helpdesk queue, timeline of e-mails and internal notes with attachments, reply (with a file) through Helpdesk's e-mail workflow, internal note, status, priority and team, assign to me, SLA dates, open the linked conversation |
| Alerts | The web alert centre's sounds and rules (repeat until acknowledged, volume, mute), device notifications with generic text when the app is in the background, acknowledgement shared with the web console and other devices |
| Push | Android, iOS and (signed builds) macOS through Firebase (when configured): generic lock-screen text, icon badge, the record opens only after the server re-checks access; deliveries are tracked and retried on the server |
| Background (desktop) | Windows and macOS: starts when the user signs in to the computer, stays in the tray / menu bar when the window is closed, keeps alerting; both can be switched off in the Alerts tab |
| Connection | Polling (inbox 10 s, conversation 4 s, alerts 15 s), offline banner, full refresh on reconnect and on resume, presence heartbeat |
| Layouts | Windows / tablets: navigation rail, resizable list, thread, details panel (≥1280 px). Phones: bottom navigation, threads full screen, details in a sheet, composer above the keyboard |
| Keyboard (Windows) | Ctrl+1/2/3 sections · Ctrl+K search · Alt+↑/↓ previous / next conversation · Ctrl+E composer · Ctrl+Shift+N internal note · Ctrl+/ canned responses · Ctrl+Enter send · Ctrl+R refresh |

## Set up the server (once per site)

1. Update thinkNXG Support to 1.9 and migrate: `bench --site <site> migrate`
2. Desk → **Support Agent App Settings** → keep the sign-in addresses (or change them to match your builds) →
   **Create OAuth Client**. The OAuth client is public (no secret in the app) and restricted to staff roles.
3. Agents need a desk (System User) account with a support role (Support Agent / Support Manager, or Helpdesk's
   Agent roles). Customers and website users cannot use the staff API.

Example settings (placeholders):

```
Windows Sign-in Address : http://127.0.0.1:43823/callback
Mobile Sign-in Address  : com.thinknxg.agent://oauth2redirect
Inbox / Thread / Alerts : 10 / 4 / 15 seconds
```

## Build and run

Requires Flutter 3.35+ (stable). Windows builds need Visual Studio 2022 with *Desktop development with C++*;
iOS builds need macOS with Xcode.

```bash
cd agent_app
bash tool/configure_platforms.sh   # once: creates windows/, macos/, android/, ios/ and applies the app's settings
flutter pub get
flutter analyze --no-fatal-infos
flutter test                       # unit + widget tests against an in-memory fake of the staff API
flutter run -d windows             # or: -d <android device id>, -d <iPhone simulator>
flutter build windows --release    # build/windows/x64/runner/Release/ (installer: installer/thinknxg_agent.iss)
flutter build apk --release        # build/app/outputs/flutter-apk/
flutter build ios --release --no-codesign
flutter build macos --release      # sign for distribution and push: tool/sign_macos.sh

# with push (values from your Firebase project):
flutter build apk --release --dart-define=FCM_PROJECT_ID=... --dart-define=FCM_API_KEY=... \
  --dart-define=FCM_SENDER_ID=... --dart-define=FCM_ANDROID_APP_ID=... --dart-define=FCM_IOS_APP_ID=... \
  --dart-define=FCM_MACOS_APP_ID=...
```

For a local bench over plain http, sign in with `http://localhost:8000` (only localhost may use http).

CI: `.github/workflows/agent-app.yml` analyses, tests and builds the Windows installer, the macOS disk image, the Android APK and
App Bundle and the iOS app (signed and uploaded to TestFlight when the signing secrets are set — see
`docs/agent-api.md`, *Packaging*); `.github/workflows/backend.yml` runs the server tests on a Frappe v16 bench with Helpdesk.

## Layout

```
lib/main.dart                 app, theme, session gate
lib/src/api/                  ApiClient (bearer, refresh, error mapping), StaffApi (typed v1), models
lib/src/auth/                 PKCE, OAuth (authorize / token / refresh / revoke), browser callbacks, secure store
lib/src/state/                Session, Inbox / Conversation / Tickets / Ticket / Alerts controllers
lib/src/ui/                   workspace (responsive shell), inbox, conversation, composer, tickets, alerts, sign-in
test/fake_server.dart         in-memory staff API used by the tests
```
