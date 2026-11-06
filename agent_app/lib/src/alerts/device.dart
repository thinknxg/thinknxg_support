import 'dart:async';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:path_provider/path_provider.dart';

import '../platform/services.dart';
import 'alert_center.dart';
import 'sounds.dart';

/// A link from a notification or push, waiting until the workspace is signed in and can check access.
class PendingLink {
  static void fromPayload(String? payload) {
    final p = (payload ?? '').split('|');
    if (p.length == 2 && p[0].isNotEmpty && p[1].isNotEmpty) AppServices.pendingLink.value = (doctype: p[0], name: p[1]);
  }
}

/// Sounds through audioplayers (WAV made on the device), notifications through flutter_local_notifications.
class DeviceAlertSink implements AlertSink {
  final _player = AudioPlayer();
  final _notifications = FlutterLocalNotificationsPlugin();
  final Map<String, String> _files = {};
  bool _ready = false;

  Future<void> init() async {
    if (_ready) return;
    _ready = true;
    try {
      await _player.setReleaseMode(ReleaseMode.stop);
      await _notifications.initialize(
        const InitializationSettings(
          android: AndroidInitializationSettings('@mipmap/ic_launcher'),
          iOS: DarwinInitializationSettings(requestAlertPermission: true, requestSoundPermission: false),
          windows: WindowsInitializationSettings(
              appName: 'thinkNXG Support Agent',
              appUserModelId: 'com.thinknxg.agent',
              guid: '6f1b7f6e-1a1d-4b7a-9f53-0d3c2e9a4b21'),
        ),
        onDidReceiveNotificationResponse: (r) => PendingLink.fromPayload(r.payload),
      );
      final launch = await _notifications.getNotificationAppLaunchDetails();
      if (launch?.didNotificationLaunchApp == true) PendingLink.fromPayload(launch!.notificationResponse?.payload);
      await _notifications
          .resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>()
          ?.requestNotificationsPermission();
    } catch (e) {
      debugPrint('notifications unavailable: $e');
    }
  }

  Future<String> _file(String sound, double volume) async {
    final key = '$sound@${(volume * 10).round()}';
    final known = _files[key];
    if (known != null) return known;
    final dir = await getTemporaryDirectory();
    final f = File('${dir.path}${Platform.pathSeparator}alert_${sound.replaceAll(' ', '_')}_${(volume * 10).round()}.wav');
    await f.writeAsBytes(synthesizeWav(sound, volume: volume), flush: true);
    return _files[key] = f.path;
  }

  @override
  Future<void> play(String sound, double volume) async {
    try {
      await _player.stop();
      await _player.play(DeviceFileSource(await _file(sound, volume)));
    } catch (e) {
      debugPrint('alert sound failed: $e');
    }
  }

  @override
  Future<void> notify(int id, String title, String body, String payload) async {
    try {
      await _notifications.show(
        id,
        title,
        body,
        const NotificationDetails(
          android: AndroidNotificationDetails('support_alerts', 'Support alerts',
              importance: Importance.high, priority: Priority.high, playSound: false, visibility: NotificationVisibility.public),
          iOS: DarwinNotificationDetails(presentSound: false),
          windows: WindowsNotificationDetails(),
        ),
        payload: payload,
      );
    } catch (e) {
      debugPrint('notification failed: $e');
    }
  }

  @override
  Future<void> cancel(int id) async {
    try {
      await _notifications.cancel(id);
    } catch (_) {}
  }
}

/// Firebase settings come from the build (--dart-define), so no project details live in the source.
class PushConfig {
  static const projectId = String.fromEnvironment('FCM_PROJECT_ID');
  static const apiKey = String.fromEnvironment('FCM_API_KEY');
  static const senderId = String.fromEnvironment('FCM_SENDER_ID');
  static const androidAppId = String.fromEnvironment('FCM_ANDROID_APP_ID');
  static const iosAppId = String.fromEnvironment('FCM_IOS_APP_ID');
  static const iosBundleId = String.fromEnvironment('FCM_IOS_BUNDLE_ID', defaultValue: 'com.thinknxg.thinknxgAgent');

  static bool get available =>
      projectId.isNotEmpty && apiKey.isNotEmpty && senderId.isNotEmpty &&
      ((Platform.isAndroid && androidAppId.isNotEmpty) || (Platform.isIOS && iosAppId.isNotEmpty));
}

/// FCM on Android and iOS. The push itself only says "New support activity"; tapping it opens the record after
/// the app has checked access with the server. Windows uses the app's own polling and notifications instead.
class PushService {
  static String? token;

  static Future<String?> start({required void Function(String token) onToken, required VoidCallback onForeground}) async {
    if (!PushConfig.available) return null;
    try {
      await Firebase.initializeApp(
        options: FirebaseOptions(
          apiKey: PushConfig.apiKey,
          appId: Platform.isIOS ? PushConfig.iosAppId : PushConfig.androidAppId,
          messagingSenderId: PushConfig.senderId,
          projectId: PushConfig.projectId,
          iosBundleId: PushConfig.iosBundleId,
        ),
      );
      final m = FirebaseMessaging.instance;
      await m.requestPermission(alert: true, sound: true, badge: true);
      void open(RemoteMessage msg) => PendingLink.fromPayload('${msg.data['doctype'] ?? ''}|${msg.data['name'] ?? ''}');
      FirebaseMessaging.onMessageOpenedApp.listen(open);
      FirebaseMessaging.onMessage.listen((_) => onForeground()); // in the app: polling plays the sound
      final initial = await m.getInitialMessage();
      if (initial != null) open(initial);
      m.onTokenRefresh.listen((t) {
        token = t;
        onToken(t);
      });
      token = await m.getToken();
      if (token != null) onToken(token!);
      return token;
    } catch (e) {
      debugPrint('push unavailable: $e');
      return null;
    }
  }

  static Future<void> stop() async {
    if (!PushConfig.available) return;
    try {
      await FirebaseMessaging.instance.deleteToken();
    } catch (_) {}
    token = null;
  }
}
