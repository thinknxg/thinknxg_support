import 'dart:async';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:path_provider/path_provider.dart';

import '../platform/crash_log.dart';
import '../platform/services.dart';
import 'alert_center.dart';
import 'sounds.dart';

/// Android notification channel for alerts and pushes (the server sends the same id).
const alertChannelId = 'support_alerts_v2';

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
      // Play on the notification volume (not media, which is often at zero), briefly ducking other audio.
      await _player.setAudioContext(AudioContext(
        android: const AudioContextAndroid(
          contentType: AndroidContentType.sonification,
          usageType: AndroidUsageType.notificationEvent,
          audioFocus: AndroidAudioFocus.gainTransientMayDuck,
        ),
        iOS: AudioContextIOS(category: AVAudioSessionCategory.ambient),
      ));
      await _notifications.initialize(
        const InitializationSettings(
          android: AndroidInitializationSettings('@mipmap/ic_launcher'),
          iOS: DarwinInitializationSettings(requestAlertPermission: true, requestSoundPermission: true, requestBadgePermission: true),
          macOS: DarwinInitializationSettings(requestAlertPermission: true, requestSoundPermission: true, requestBadgePermission: true),
          windows: WindowsInitializationSettings(
              appName: 'thinkNXG Support Agent',
              appUserModelId: 'com.thinknxg.agent',
              guid: '6f1b7f6e-1a1d-4b7a-9f53-0d3c2e9a4b21'),
        ),
        onDidReceiveNotificationResponse: (r) => PendingLink.fromPayload(r.payload),
      );
      final launch = await _notifications.getNotificationAppLaunchDetails();
      if (launch?.didNotificationLaunchApp == true) PendingLink.fromPayload(launch!.notificationResponse?.payload);
      final android = _notifications.resolvePlatformSpecificImplementation<AndroidFlutterLocalNotificationsPlugin>();
      await android?.requestNotificationsPermission();
      // A channel's sound is fixed when it is created: 1.9.0 test builds made a silent one, so use a new channel
      // (with the system notification sound) and remove the old one. Pushes from the server use the same id.
      await android?.deleteNotificationChannel('support_alerts');
      await android?.createNotificationChannel(const AndroidNotificationChannel(
        alertChannelId,
        'Support alerts',
        description: 'New chats, messages, tickets and escalations',
        importance: Importance.high,
        playSound: true,
        enableVibration: true,
      ));
    } catch (e, st) {
      CrashLog.write('notifications unavailable', e, st);
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
    } catch (e, st) {
      CrashLog.write('alert sound failed ($sound)', e, st);
    }
  }

  @override
  Future<void> notify(int id, String title, String body, String payload) async {
    // macOS with push: Apple's notification service already shows this alert, also when the app is not running.
    if (Platform.isMacOS && PushService.token != null && payload.isNotEmpty) return;
    try {
      await _notifications.show(
        id,
        title,
        body,
        const NotificationDetails(
          android: AndroidNotificationDetails(alertChannelId, 'Support alerts',
              importance: Importance.high, priority: Priority.high, playSound: true, visibility: NotificationVisibility.public),
          iOS: DarwinNotificationDetails(presentSound: true),
          macOS: DarwinNotificationDetails(presentSound: true),
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
  static const macosAppId = String.fromEnvironment('FCM_MACOS_APP_ID');
  static const iosBundleId = String.fromEnvironment('FCM_IOS_BUNDLE_ID', defaultValue: 'com.thinknxg.thinknxgAgent');

  static bool get available =>
      projectId.isNotEmpty && apiKey.isNotEmpty && senderId.isNotEmpty &&
      ((Platform.isAndroid && androidAppId.isNotEmpty) ||
          (Platform.isIOS && iosAppId.isNotEmpty) ||
          (Platform.isMacOS && macosAppId.isNotEmpty));
}

/// FCM on Android, iOS and macOS (Apple devices through APNs). The push itself only says "New support activity";
/// tapping it opens the record after the app has checked access with the server. Windows stays running in the
/// system tray and uses the app's own connection and notifications instead.
class PushService {
  static String? token;

  static Future<String?> start({required void Function(String token) onToken, required VoidCallback onForeground}) async {
    if (!PushConfig.available) return null;
    try {
      await Firebase.initializeApp(
        options: FirebaseOptions(
          apiKey: PushConfig.apiKey,
          appId: Platform.isIOS
              ? PushConfig.iosAppId
              : Platform.isMacOS
                  ? PushConfig.macosAppId
                  : PushConfig.androidAppId,
          messagingSenderId: PushConfig.senderId,
          projectId: PushConfig.projectId,
          iosBundleId: PushConfig.iosBundleId,
        ),
      );
      final m = FirebaseMessaging.instance;
      await m.requestPermission(alert: true, sound: true, badge: true);
      void open(RemoteMessage msg) {
        final delivery = '${msg.data['delivery'] ?? ''}';
        if (delivery.isNotEmpty) AppServices.pushOpened?.call(delivery);
        PendingLink.fromPayload('${msg.data['doctype'] ?? ''}|${msg.data['name'] ?? ''}');
      }

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
    } catch (e, st) {
      CrashLog.write('push unavailable', e, st);
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
