import 'dart:convert';
import 'dart:io';

import 'package:tray_manager/tray_manager.dart';
import 'package:window_manager/window_manager.dart';

import 'crash_log.dart';
import 'services.dart';

/// Windows and macOS: the app lives in the system tray (menu bar on macOS), starts when the user signs in to the
/// computer and keeps running when its window is closed, so alerts still arrive. Both can be switched off in the
/// Alerts tab; the operating system's own startup settings always win.
class TrayDesktopShell with TrayListener, WindowListener implements DesktopShell {
  static const _runKey = r'HKCU\Software\Microsoft\Windows\CurrentVersion\Run';
  static const _runName = 'thinkNXG Support Agent';
  static const _agentLabel = 'com.thinknxg.agent';

  Map<String, Object?> _prefs = {};
  bool _hidden = false;
  bool _autostart = false;

  @override
  bool get windowHidden => _hidden;
  @override
  bool get startAtLogin => _autostart;
  @override
  bool get keepRunning => _prefs['keep_running'] != false;

  File get _prefsFile => File('${CrashLog.file.parent.path}${Platform.pathSeparator}settings.json');

  /// [hidden]: started by the computer at sign-in, so no window until the agent asks for it.
  Future<void> init({required bool hidden}) async {
    try {
      final f = _prefsFile;
      if (f.existsSync()) _prefs = (jsonDecode(f.readAsStringSync()) as Map).cast<String, Object?>();
    } catch (_) {}
    await windowManager.ensureInitialized();
    windowManager.addListener(this);
    try {
      await windowManager.setPreventClose(keepRunning);
    } catch (e, st) {
      CrashLog.write('window close handling unavailable', e, st);
    }
    try {
      await trayManager.setIcon(Platform.isWindows ? 'assets/tray_icon.ico' : 'assets/tray_icon.png');
      if (!Platform.isLinux) await trayManager.setToolTip('thinkNXG Support Agent');
      await trayManager.setContextMenu(Menu(items: [
        MenuItem(key: 'open', label: 'Open thinkNXG Support'),
        MenuItem.separator(),
        MenuItem(key: 'quit', label: 'Quit (stops alerts on this computer)'),
      ]));
      trayManager.addListener(this);
    } catch (e, st) {
      CrashLog.write('tray unavailable', e, st);
    }
    try {
      _autostart = await _readAutostart();
      // macOS has no installer to ask: start at sign-in is switched on the first time the app runs, and can be
      // switched off in the Alerts tab or in System Settings > Login Items. On Windows the installer asks.
      if (Platform.isMacOS && _prefs['autostart_set'] != true) {
        await setStartAtLogin(true);
      }
    } catch (e, st) {
      CrashLog.write('start at sign-in unavailable', e, st);
    }
    _hidden = hidden;
    if (!hidden) {
      await showWindow(); // Windows: the runner no longer shows the window by itself (tool/configure_platforms.sh)
    } else if (Platform.isMacOS) {
      await windowManager.hide();
    }
  }

  void _save() {
    try {
      _prefsFile.writeAsStringSync(jsonEncode(_prefs), flush: true);
    } catch (_) {}
  }

  @override
  Future<void> showWindow() async {
    _hidden = false;
    try {
      await windowManager.show();
      if (await windowManager.isMinimized()) await windowManager.restore();
      await windowManager.focus();
    } catch (e, st) {
      CrashLog.write('show window failed', e, st);
    }
  }

  Future<void> _hide() async {
    _hidden = true;
    await windowManager.hide();
    if (_prefs['tray_hint_shown'] != true) {
      _prefs['tray_hint_shown'] = true;
      _save();
      await AppServices.alertSink.notify(
          1, 'thinkNXG Support is still running', 'Alerts keep arriving. Use the icon near the clock to open or quit.', '');
    }
  }

  @override
  Future<void> setKeepRunning(bool on) async {
    _prefs['keep_running'] = on;
    _save();
    try {
      await windowManager.setPreventClose(on);
    } catch (_) {}
  }

  // ---------------------------------------------------------------- window and tray events
  @override
  void onWindowClose() async {
    if (keepRunning) {
      await _hide();
    } else {
      await _quit();
    }
  }

  @override
  void onTrayIconMouseDown() {
    if (Platform.isMacOS) {
      trayManager.popUpContextMenu();
    } else {
      showWindow();
    }
  }

  @override
  void onTrayIconRightMouseDown() => trayManager.popUpContextMenu();

  @override
  void onTrayMenuItemClick(MenuItem menuItem) {
    if (menuItem.key == 'open') showWindow();
    if (menuItem.key == 'quit') _quit();
  }

  Future<void> _quit() async {
    try {
      await trayManager.destroy();
      await windowManager.setPreventClose(false);
      await windowManager.destroy();
    } catch (_) {}
    exit(0);
  }

  // ---------------------------------------------------------------- start when the user signs in
  String get _macPlist => '${Platform.environment['HOME']}/Library/LaunchAgents/$_agentLabel.plist';

  /// The .app folder this executable lives in (…/X.app/Contents/MacOS/x).
  String get _macBundle => File(Platform.resolvedExecutable).parent.parent.parent.path;

  Future<bool> _readAutostart() async {
    if (Platform.isWindows) {
      final r = await Process.run('reg', ['query', _runKey, '/v', _runName]);
      return r.exitCode == 0;
    }
    if (Platform.isMacOS) return File(_macPlist).existsSync();
    return false;
  }

  @override
  Future<void> setStartAtLogin(bool on) async {
    _prefs['autostart_set'] = true;
    _save();
    if (Platform.isWindows) {
      final r = on
          ? await Process.run('reg',
              ['add', _runKey, '/v', _runName, '/t', 'REG_SZ', '/d', '"${Platform.resolvedExecutable}" --hidden', '/f'])
          : await Process.run('reg', ['delete', _runKey, '/v', _runName, '/f']);
      if (r.exitCode != 0 && on) throw ProcessException('reg', const [], '${r.stderr}'.trim(), r.exitCode);
    } else if (Platform.isMacOS) {
      final f = File(_macPlist);
      if (on) {
        f.parent.createSync(recursive: true);
        f.writeAsStringSync(macLaunchAgent(_agentLabel, _macBundle), flush: true);
      } else if (f.existsSync()) {
        f.deleteSync();
      }
    }
    _autostart = await _readAutostart();
  }
}

/// Set by the macOS Launch Agent (macOS does not hand command-line arguments to the app's Dart code).
const hiddenEnv = 'THINKNXG_AGENT_HIDDEN';

String _xml(String s) => s.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');

/// A per-user Launch Agent: macOS opens the app (without bringing it to the front) when the user signs in.
String macLaunchAgent(String label, String bundlePath) => '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>${_xml(label)}</string>
	<key>ProgramArguments</key>
	<array>
		<string>/usr/bin/open</string>
		<string>-g</string>
		<string>-j</string>
		<string>--env</string>
		<string>$hiddenEnv=1</string>
		<string>-a</string>
		<string>${_xml(bundlePath)}</string>
	</array>
	<key>RunAtLoad</key>
	<true/>
	<key>ProcessType</key>
	<string>Interactive</string>
</dict>
</plist>
''';
