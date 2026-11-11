import 'package:flutter/foundation.dart';

import '../alerts/alert_center.dart';

/// Device services the workspace uses. main() installs the real ones; tests keep these quiet defaults.
class AppServices {
  static AlertSink alertSink = SilentAlertSink();

  /// Starts push (Android/iOS with Firebase configured). Returns the device token, or null.
  static Future<String?> Function({required void Function(String token) onToken, required VoidCallback onForeground})?
      startPush;
  static Future<void> Function()? stopPush;
  static String? Function() pushToken = () => null;

  /// One line for the Alerts tab: is push working on this device, and if not, why.
  static String Function() pushStatus = () => 'Push notifications: not available here';

  /// Notification taps waiting for the signed-in workspace: (doctype, name).
  static final ValueNotifier<({String doctype, String name})?> pendingLink = ValueNotifier(null);

  /// A push was opened on this device (delivery tracking). The workspace reports it to the server.
  static void Function(String delivery)? pushOpened;

  /// Windows and macOS: tray, background mode and start at sign-in. Null on phones and in tests.
  static DesktopShell? desktop;

  /// The number on the app icon (iOS, macOS dock): alerts waiting for the agent.
  static Future<void> Function(int count) setBadge = (_) async {};

  /// Phones: what, if anything, on this device can hold alerts back (notifications off, battery saving).
  static Future<String?> Function()? deliveryNote;

  /// Phones: opens the system's settings page for this app (notifications, battery).
  static Future<void> Function()? openSystemSettings;

  static String platform = defaultTargetPlatform == TargetPlatform.iOS
      ? 'iOS'
      : defaultTargetPlatform == TargetPlatform.android
          ? 'Android'
          : defaultTargetPlatform == TargetPlatform.macOS
              ? 'macOS'
              : 'Windows';
  static String appVersion = '1.17.0';
}

/// The desktop app's life outside its window.
abstract class DesktopShell {
  /// Starts when the user signs in to the computer.
  bool get startAtLogin;

  /// Closing the window keeps the app running in the tray / menu bar.
  bool get keepRunning;
  bool get windowHidden;
  Future<void> setStartAtLogin(bool on);
  Future<void> setKeepRunning(bool on);
  Future<void> showWindow();
}

/// Records instead of playing (tests, and platforms without audio).
class SilentAlertSink implements AlertSink {
  final List<String> played = [];
  final List<String> notified = [];
  @override
  Future<void> play(String sound, double volume) async => played.add(sound);
  @override
  Future<void> notify(int id, String title, String body, String payload) async => notified.add(body);
  @override
  Future<void> cancel(int id) async {}
}
