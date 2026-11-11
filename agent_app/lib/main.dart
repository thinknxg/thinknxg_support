import 'dart:async';
import 'dart:io';

import 'package:app_badge_plus/app_badge_plus.dart';
import 'package:flutter/material.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:window_manager/window_manager.dart';

import 'src/alerts/device.dart';
import 'src/auth/browser.dart';
import 'src/auth/oauth.dart';
import 'src/auth/token_store.dart';
import 'src/platform/crash_log.dart';
import 'src/platform/desktop.dart';
import 'src/platform/services.dart';
import 'src/state/session.dart';
import 'src/ui/sign_in.dart';
import 'src/ui/workspace.dart';

void main(List<String> args) {
  runZonedGuarded(() async {
    WidgetsFlutterBinding.ensureInitialized();
    CrashLog.write('start ${Platform.operatingSystem} ${Platform.operatingSystemVersion}');
    FlutterError.onError = (d) {
      CrashLog.write('flutter error', d.exception, d.stack);
      FlutterError.presentError(d);
    };
    // Device services are optional: if one fails on this PC the app still opens (and the reason is logged).
    try {
      final sink = DeviceAlertSink();
      await sink.init().timeout(const Duration(seconds: 5));
      AppServices.alertSink = sink;
    } catch (e, st) {
      CrashLog.write('alerts unavailable', e, st);
    }
    // Windows and macOS: tray, background mode, start at sign-in. Started by the computer at sign-in: hidden.
    if (Platform.isWindows || Platform.isMacOS) {
      final hidden = args.contains('--hidden') || Platform.environment[hiddenEnv] == '1';
      try {
        final shell = TrayDesktopShell();
        await shell.init(hidden: hidden).timeout(const Duration(seconds: 10));
        AppServices.desktop = shell;
      } catch (e, st) {
        CrashLog.write('desktop shell unavailable', e, st);
        try {
          await windowManager.show(); // never leave the app without a window because the tray failed
        } catch (_) {}
      }
    }
    AppServices.setBadge = (count) async {
      try {
        if (Platform.isMacOS) {
          await windowManager.setBadgeLabel(count > 0 ? '$count' : null);
        } else if (Platform.isIOS) {
          await AppBadgePlus.updateBadge(count);
        }
      } catch (_) {}
    };
    if (Platform.isAndroid || Platform.isIOS) {
      AppServices.openSystemSettings = () async {
        await openAppSettings();
      };
      AppServices.deliveryNote = () async {
        try {
          if (!await Permission.notification.isGranted) {
            return 'Notifications are switched off for this app, so alerts cannot reach you. Allow them in the settings below.';
          }
          if (Platform.isAndroid && !await Permission.ignoreBatteryOptimizations.isGranted) {
            return 'Battery saving can delay alerts on some phones. In the settings below, set Battery to "Unrestricted" '
                'and allow the app to start by itself if your phone has that option.';
          }
        } catch (_) {}
        return null;
      };
    }
    AppServices.startPush = PushService.start;
    AppServices.stopPush = PushService.stop;
    AppServices.pushToken = () => PushService.token;
    AppServices.pushStatus = () => Platform.isWindows
        ? (AppServices.desktop == null
            ? 'Alerts arrive while the app is running'
            : 'Alerts arrive while the app is running, also with its window closed (icon near the clock)')
        : !PushConfig.available
            ? (Platform.isMacOS
                ? 'Push notifications: not set up in this app build — alerts arrive while the app is running (menu bar)'
                : 'Push notifications: not set up in this app build (Firebase settings missing) — alerts only while the app is open')
            : PushService.token == null
                ? 'Push notifications: not registered yet (allow notifications, then reopen the app)'
                : 'Push notifications: on for this device, also when the app is not running';
    final session = Session(store: SecureTokenStore(), oauth: OAuthService(browser: BrowserAuthenticator.forPlatform()));
    // Running in the background with an expired sign-in: say so once, because alerts have stopped.
    var told = false;
    session.addListener(() {
      final expired = session.phase == SessionPhase.expired || session.phase == SessionPhase.signedOut;
      if (!expired) told = false;
      if (expired && !told && (AppServices.desktop?.windowHidden ?? false)) {
        told = true;
        AppServices.alertSink.notify(2, 'thinkNXG Support: sign in again', 'Alerts are paused until you sign in.', '');
      }
    });
    runApp(AgentApp(session: session));
    try {
      await session.restore();
    } catch (e, st) {
      CrashLog.write('restore failed', e, st);
      session.restoreFailed();
    }
  }, (e, st) => CrashLog.write('uncaught', e, st));
}

class AgentApp extends StatelessWidget {
  final Session session;
  const AgentApp({super.key, required this.session});

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFF0F766E);
    return MaterialApp(
      title: 'thinkNXG Support Agent',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: seed, useMaterial3: true),
      darkTheme: ThemeData(colorSchemeSeed: seed, useMaterial3: true, brightness: Brightness.dark),
      home: ListenableBuilder(
        listenable: session,
        builder: (context, _) {
          if (session.phase == SessionPhase.starting) return const Scaffold(body: Center(child: CircularProgressIndicator()));
          final me = session.me;
          if (me == null) return SignInScreen(session: session);
          // Expired mid-work: the workspace (and any unsent draft) stays underneath; sign in again on top.
          return Stack(children: [
            Workspace(key: ValueKey(me.user), session: session),
            if (session.phase != SessionPhase.signedIn)
              Positioned.fill(child: ColoredBox(color: Colors.black54, child: SignInScreen(session: session))),
          ]);
        },
      ),
    );
  }
}
