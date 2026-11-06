import 'dart:io';

/// Startup and crash log, so a failure on a customer PC can be diagnosed:
/// Windows %LOCALAPPDATA%\thinkNXG Support Agent\agent.log (other platforms: the system temp folder).
/// Never contains tokens or message text: only errors and stack traces.
class CrashLog {
  static File? _file;

  static File get file {
    if (_file != null) return _file!;
    final base = Platform.isWindows
        ? (Platform.environment['LOCALAPPDATA'] ?? Directory.systemTemp.path)
        : Directory.systemTemp.path;
    final dir = Directory('$base${Platform.pathSeparator}thinkNXG Support Agent');
    try {
      dir.createSync(recursive: true);
    } catch (_) {}
    return _file = File('${dir.path}${Platform.pathSeparator}agent.log');
  }

  static void write(String what, [Object? error, StackTrace? stack]) {
    try {
      final f = file;
      if (f.existsSync() && f.lengthSync() > 512 * 1024) f.writeAsStringSync(''); // keep it small
      f.writeAsStringSync('${DateTime.now().toIso8601String()} $what${error == null ? '' : ': $error'}\n'
          '${stack ?? ''}\n', mode: FileMode.append, flush: true);
    } catch (_) {}
  }
}
