import 'dart:async';

import 'package:flutter/foundation.dart';

import '../api/models.dart';

/// Plays sounds and shows device notifications. The device implementation uses audioplayers and
/// flutter_local_notifications; tests use a recording fake.
abstract class AlertSink {
  Future<void> play(String sound, double volume);

  /// Generic text only (kind, never customer details): the device may show it on a lock screen.
  Future<void> notify(int id, String title, String body, String payload);

  Future<void> cancel(int id);
}

/// What an alert should do, decided from the team rules merged with the agent's preferences (same as the web).
class _Ringing {
  final AgentAlert alert;
  DateTime last;
  int plays;
  _Ringing(this.alert, this.last, this.plays);
}

/// Turns the server's open alerts into sounds and notifications: once for new alerts, repeating until acknowledged
/// where the rule says so. Acknowledging (here, on the web or on another device) stops it everywhere.
class AlertCenter extends ChangeNotifier {
  final AlertSink sink;
  final bool Function() appInForeground;
  final DateTime Function() clock;
  AlertConfig config = const AlertConfig(enabled: true);
  final Map<String, _Ringing> _ringing = {};
  final Set<String> _known = {};
  bool _primed = false;
  Timer? _timer;

  AlertCenter(this.sink, {required this.appInForeground, DateTime Function()? clock}) : clock = clock ?? DateTime.now;

  void start() => _timer ??= Timer.periodic(const Duration(seconds: 1), (_) => tick());

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  static const _labels = {
    'New Chat': 'New chat waiting',
    'Chat Message': 'New chat message',
    'New Ticket': 'New ticket',
    'Ticket Assigned': 'Ticket assigned to you',
    'Conversation Message': 'Customer replied',
    'Escalation': 'Escalation',
    'Negative Feedback': 'Negative feedback',
    'Positive Feedback': 'Positive feedback',
  };

  /// Called with every poll of open alerts.
  Future<void> update(List<AgentAlert> open) async {
    final ids = {for (final a in open) a.id};
    for (final gone in _ringing.keys.where((k) => !ids.contains(k)).toList()) {
      _ringing.remove(gone);
      await sink.cancel(gone.hashCode);
    }
    final fresh = open.where((a) => !_known.contains(a.id)).toList();
    _known.addAll(ids);
    // First load after sign-in: alerts already open ring again only if they repeat (like the web after a reload).
    final first = !_primed;
    _primed = true;
    for (final a in fresh) {
      final rule = config.rules[a.kind];
      if (rule != null && !rule.enabled) continue;
      final repeat = rule?.repeat ?? false;
      if (first && !repeat) continue;
      await _ring(a, rule);
      if (repeat) _ringing[a.id] = _Ringing(a, clock(), 1);
    }
    notifyListeners();
  }

  Future<void> _ring(AgentAlert a, AlertRule? rule) async {
    final sound = rule?.sound ?? 'Chime';
    if (!config.muteAll && sound != 'None') {
      await sink.play(sound, ((rule?.volume ?? 80) / 100).clamp(0.0, 1.0));
    }
    if ((rule?.popup ?? true) && !appInForeground()) {
      await sink.notify(a.id.hashCode, 'thinkNXG Support', _labels[a.kind] ?? 'New support activity',
          '${a.referenceDoctype ?? ''}|${a.referenceName ?? ''}');
    }
  }

  /// Alerts that are not stored (new chat messages, customer replies, positive feedback): one sound each.
  Future<void> events(List<AgentAlert> list) async {
    for (final a in list) {
      if (_known.contains(a.id)) continue;
      _known.add(a.id);
      final rule = config.rules[a.kind];
      if (rule != null && !rule.enabled) continue;
      await _ring(a, rule);
    }
  }

  /// "Test sound": the New Chat sound (or Chime) at the agent's volume, ignoring mute so the speaker can be checked.
  Future<void> testSound() async {
    final rule = config.rules['New Chat'];
    final sound = rule == null || rule.sound == 'None' ? 'Chime' : rule.sound;
    await sink.play(sound, ((rule?.volume ?? 80) / 100).clamp(0.2, 1.0));
  }

  /// Repeats for alerts that ring until acknowledged (every N seconds, up to the rule's limit or 5 minutes).
  Future<void> tick() async {
    final now = clock();
    for (final r in _ringing.values.toList()) {
      final rule = config.rules[r.alert.kind];
      if (rule == null) continue;
      final max = rule.maxRepeats > 0 ? rule.maxRepeats : (300 / rule.repeatSeconds).ceil();
      if (r.plays >= max) {
        _ringing.remove(r.alert.id);
        continue;
      }
      if (now.difference(r.last).inSeconds >= rule.repeatSeconds) {
        r.last = now;
        r.plays++;
        if (!config.muteAll && rule.sound != 'None') await sink.play(rule.sound, (rule.volume / 100).clamp(0.0, 1.0));
      }
    }
  }

  /// Stop ringing right away when the agent acknowledges in the app.
  void acknowledged(Iterable<String> ids) {
    for (final id in ids) {
      _ringing.remove(id);
      sink.cancel(id.hashCode);
    }
    notifyListeners();
  }

  @visibleForTesting
  int get ringingCount => _ringing.length;
}
