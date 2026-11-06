# thinkNXG Support Agent app

One Flutter codebase for **Windows**, **Android** and **iOS**. Support agents sign in with their own staff account
and work the same conversations and Helpdesk tickets as the web console (`/app/support-chat`). All three use the
same records on the server; nothing is stored on the device except the sign-in token (in the OS secure store).

* Backend contract: [`../docs/agent-api.md`](../docs/agent-api.md)
* Server setup: *Support Agent App Settings* in the desk (thinkNXG Support 1.9+)

## What works in this release (increment 1)

| Area | |
|---|---|
| Sign-in | Site address → system browser → Frappe OAuth (authorization code + PKCE). Session restored on launch, sign-in prompt on expiry (work stays underneath), sign-out revokes the token and clears the device |
| Inbox | Portal, Live Chat, WhatsApp. All / Mine / Unassigned / Waiting, channel, status and queue filters, search, unread counts (per agent), cursor paging, polling |
| Conversation | Timeline (paged back, polled forward), read acknowledgement, claim (one winner), transfer, take over / return to assistant, End chat with wrap-up questions, linked ticket |
| Composer | Clearly labelled **Reply to customer** / **Internal note**, Sending / Sent / Failed, draft kept on failure, Retry never sends twice, server reasons shown (e.g. WhatsApp 24-hour window) |
| Tickets | Helpdesk queue (Mine / Unassigned / All I can see), timeline of emails and internal notes, reply through Helpdesk's email workflow, internal note, status and priority changes, assign to me, SLA dates, open the linked conversation |
| Alerts | Open alerts from the server; acknowledging clears them on the web console and other devices; opening an alert re-checks access |
| Layouts | Windows / tablets: navigation rail, resizable list, thread, details panel (≥1280 px). Phones: bottom navigation, threads full screen, composer above the keyboard |
| Keyboard (Windows) | Ctrl+1/2/3 sections · Ctrl+K search · Alt+↑/↓ previous / next conversation · Ctrl+E composer · Ctrl+Shift+N internal note · Ctrl+Enter send · Ctrl+R refresh |

Next increments: alert sounds, push notifications (FCM/APNs, generic lock-screen text), signed Windows installer,
store builds. See *Roadmap* in `docs/agent-api.md`.

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
bash tool/configure_platforms.sh   # once: creates windows/, android/, ios/ and applies the app's settings
flutter pub get
flutter analyze --no-fatal-infos
flutter test                       # unit + widget tests against an in-memory fake of the staff API
flutter run -d windows             # or: -d <android device id>, -d <iPhone simulator>
flutter build windows --release    # build/windows/x64/runner/Release/
flutter build apk --release        # build/app/outputs/flutter-apk/
flutter build ios --release --no-codesign
```

For a local bench over plain http, sign in with `http://localhost:8000` (only localhost may use http).

CI: `.github/workflows/agent-app.yml` analyses, tests and builds Windows, Android and iOS on every change under
`agent_app/`; `.github/workflows/backend.yml` runs the server tests on a Frappe v16 bench with Helpdesk.

## Layout

```
lib/main.dart                 app, theme, session gate
lib/src/api/                  ApiClient (bearer, refresh, error mapping), StaffApi (typed v1), models
lib/src/auth/                 PKCE, OAuth (authorize / token / refresh / revoke), browser callbacks, secure store
lib/src/state/                Session, Inbox / Conversation / Tickets / Ticket / Alerts controllers
lib/src/ui/                   workspace (responsive shell), inbox, conversation, composer, tickets, alerts, sign-in
test/fake_server.dart         in-memory staff API used by the tests
```
