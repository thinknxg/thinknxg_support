import 'dart:async';
import 'dart:io';

import 'package:audioplayers/audioplayers.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

import '../api/api_client.dart';

/// Records voice notes (AAC in .m4a, which every channel can play, WhatsApp included). Replaced by a fake in tests.
abstract class VoiceRecorder {
  static VoiceRecorder Function() factory = DeviceVoiceRecorder.new;

  /// False when the microphone is not allowed (or not present).
  Future<bool> start();

  /// The recording, or null when nothing was recorded.
  Future<UploadFile?> stop();

  Future<void> cancel();

  void dispose();
}

class DeviceVoiceRecorder implements VoiceRecorder {
  final AudioRecorder _rec = AudioRecorder();
  String? _path;

  @override
  Future<bool> start() async {
    try {
      if (!await _rec.hasPermission()) return false;
      final dir = await getTemporaryDirectory();
      _path = '${dir.path}${Platform.pathSeparator}thinknxg_agent_voice_${DateTime.now().millisecondsSinceEpoch}.m4a';
      await _rec.start(const RecordConfig(encoder: AudioEncoder.aacLc, bitRate: 64000, sampleRate: 44100), path: _path!);
      return true;
    } catch (_) {
      return false;
    }
  }

  @override
  Future<UploadFile?> stop() async {
    final path = await _rec.stop() ?? _path;
    if (path == null) return null;
    final f = File(path);
    if (!await f.exists()) return null;
    final bytes = await f.readAsBytes();
    unawaited(f.delete().catchError((_) => f));
    return bytes.isEmpty ? null : UploadFile('voice-note-${DateTime.now().millisecondsSinceEpoch}.m4a', bytes);
  }

  @override
  Future<void> cancel() async {
    try {
      await _rec.cancel();
    } catch (_) {}
  }

  @override
  void dispose() {
    _rec.dispose();
  }
}

/// Plays a downloaded voice note inline. Replaced by a fake in tests.
abstract class VoicePlayer {
  static VoicePlayer instance = DeviceVoicePlayer();
  Future<void> play(DownloadedFile file);
  Future<void> stop();
}

class DeviceVoicePlayer implements VoicePlayer {
  AudioPlayer? _player;

  @override
  Future<void> play(DownloadedFile file) async {
    final dir = await getTemporaryDirectory();
    final safe = file.name.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_');
    final out = File('${dir.path}${Platform.pathSeparator}thinknxg_agent_$safe');
    await out.writeAsBytes(file.bytes, flush: true);
    await stop();
    _player = AudioPlayer();
    await _player!.play(DeviceFileSource(out.path));
  }

  @override
  Future<void> stop() async {
    await _player?.stop();
    await _player?.dispose();
    _player = null;
  }
}
