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

  /// Notification taps waiting for the signed-in workspace: (doctype, name).
  static final ValueNotifier<({String doctype, String name})?> pendingLink = ValueNotifier(null);

  static String platform = defaultTargetPlatform == TargetPlatform.iOS
      ? 'iOS'
      : defaultTargetPlatform == TargetPlatform.android
          ? 'Android'
          : 'Windows';
  static String appVersion = '1.9.0';
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
