import 'dart:math';
import 'dart:typed_data';

/// The alert sounds of the web alert centre, synthesised the same way (no audio files shipped):
/// each sound is distinct so agents know the activity without looking.
const alertSoundNames = ['Chime', 'Bell', 'Ping', 'Pop', 'Ring', 'Double Beep', 'Knock', 'Siren', 'Alarm'];

class _Tone {
  final double at, freq, dur, vol;
  final String wave;
  final double? toFreq;
  const _Tone(this.at, this.freq, this.dur, this.vol, [this.wave = 'sine', this.toFreq]);
}

List<_Tone> _pattern(String name) {
  switch (name) {
    case 'Chime':
      return const [_Tone(0, 784, .35, .6), _Tone(.18, 1175, .5, .55)];
    case 'Bell':
      return [for (var i = 0; i < 3; i++) _Tone(0, 660 * const <double>[1, 2.76, 5.4][i], 1.1 - i * .3, .6 / (i + 1))];
    case 'Ping':
      return const [_Tone(0, 1568, .25, .55)];
    case 'Pop':
      return const [_Tone(0, 420, .12, .7, 'triangle', 900)];
    case 'Ring':
      return [
        for (var k = 0; k < 2; k++)
          for (var i = 0; i < 8; i++) _Tone(k * .6 + i * .06, i.isOdd ? 1320 : 1100, .055, .4, 'square'),
      ];
    case 'Double Beep':
      return const [_Tone(0, 988, .12, .5, 'square'), _Tone(.18, 988, .12, .5, 'square')];
    case 'Knock':
      return [for (final x in const [0.0, .16, .32]) _Tone(x, 180, .09, 1, 'triangle', 90)];
    case 'Siren':
      return [
        for (var i = 0; i < 3; i++) ...[
          _Tone(i * .5, 620, .25, .55, 'sawtooth', 1240),
          _Tone(i * .5 + .25, 1240, .25, .55, 'sawtooth', 620),
        ],
      ];
    case 'Alarm':
      return [for (var i = 0; i < 6; i++) _Tone(i * .2, i.isOdd ? 1046 : 784, .16, .55, 'square')];
  }
  return const [];
}

double _wave(String w, double phase) {
  final p = phase - phase.floorToDouble();
  switch (w) {
    case 'square':
      return p < .5 ? 1 : -1;
    case 'triangle':
      return 1 - 4 * (p - .5).abs();
    case 'sawtooth':
      return 2 * p - 1;
  }
  return sin(2 * pi * p);
}

/// 16-bit mono PCM WAV of the named sound at [volume] (0..1). Empty for "None" or unknown names.
Uint8List synthesizeWav(String name, {double volume = .8, int sampleRate = 22050}) {
  final tones = _pattern(name);
  if (tones.isEmpty || volume <= 0) return Uint8List(0);
  final length = tones.map((t) => t.at + t.dur + .03).reduce(max);
  final n = (length * sampleRate).ceil();
  final mix = Float64List(n);
  for (final t in tones) {
    final start = (t.at * sampleRate).floor();
    final count = (t.dur * sampleRate).floor();
    var phase = 0.0;
    for (var i = 0; i < count && start + i < n; i++) {
      final x = i / count;
      final f = t.toFreq == null ? t.freq : t.freq + (t.toFreq! - t.freq) * x;
      phase += f / sampleRate;
      // the web version's envelope: 15 ms attack, exponential decay to silence
      final attack = min(1.0, i / (0.015 * sampleRate));
      final env = attack * pow(0.0001 / max(0.0002, t.vol), x).toDouble() * t.vol;
      mix[start + i] += _wave(t.wave, phase) * env;
    }
  }
  final peak = mix.fold<double>(0, (a, v) => max(a, v.abs()));
  final gain = peak > 1 ? volume / peak : volume;
  final data = ByteData(44 + n * 2);
  void str(int o, String s) {
    for (var i = 0; i < s.length; i++) {
      data.setUint8(o + i, s.codeUnitAt(i));
    }
  }

  str(0, 'RIFF');
  data.setUint32(4, 36 + n * 2, Endian.little);
  str(8, 'WAVE');
  str(12, 'fmt ');
  data.setUint32(16, 16, Endian.little);
  data.setUint16(20, 1, Endian.little); // PCM
  data.setUint16(22, 1, Endian.little); // mono
  data.setUint32(24, sampleRate, Endian.little);
  data.setUint32(28, sampleRate * 2, Endian.little);
  data.setUint16(32, 2, Endian.little);
  data.setUint16(34, 16, Endian.little);
  str(36, 'data');
  data.setUint32(40, n * 2, Endian.little);
  for (var i = 0; i < n; i++) {
    data.setInt16(44 + i * 2, (mix[i] * gain * 32767).clamp(-32768, 32767).round(), Endian.little);
  }
  return data.buffer.asUint8List();
}
