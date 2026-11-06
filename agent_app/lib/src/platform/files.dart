import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../api/api_client.dart';

/// Picking files to send and opening downloaded ones. Replaced by a fake in tests.
abstract class FileService {
  static FileService instance = DeviceFileService();

  /// Up to [maxBytes]; returns null when the agent cancels.
  Future<UploadFile?> pick({int maxBytes = 10 * 1024 * 1024});

  /// Saves into the app's private temporary folder and opens it with the system viewer.
  Future<void> open(DownloadedFile file);
}

class FileTooLarge implements Exception {
  final int limitMb;
  const FileTooLarge(this.limitMb);
  @override
  String toString() => 'Files can be up to $limitMb MB.';
}

class DeviceFileService implements FileService {
  @override
  Future<UploadFile?> pick({int maxBytes = 10 * 1024 * 1024}) async {
    final r = await FilePicker.platform.pickFiles(withData: true);
    final f = r?.files.single;
    if (f == null) return null;
    final bytes = f.bytes ?? (f.path != null ? await File(f.path!).readAsBytes() : null);
    if (bytes == null) return null;
    if (bytes.length > maxBytes) throw FileTooLarge((maxBytes / (1024 * 1024)).round());
    return UploadFile(f.name, bytes);
  }

  @override
  Future<void> open(DownloadedFile file) async {
    final dir = await getTemporaryDirectory();
    final safe = file.name.replaceAll(RegExp(r'[\\/:*?"<>|]'), '_');
    final out = File('${dir.path}${Platform.pathSeparator}thinknxg_agent_$safe');
    await out.writeAsBytes(file.bytes, flush: true);
    if (Platform.isWindows || Platform.isMacOS || Platform.isLinux) {
      await launchUrl(Uri.file(out.path));
    } else {
      await OpenFilex.open(out.path);
    }
  }
}

/// Removes files this app saved for viewing (called at sign-out).
Future<void> clearDownloadedFiles() async {
  try {
    final dir = await getTemporaryDirectory();
    await for (final e in dir.list()) {
      if (e is File && e.uri.pathSegments.last.startsWith('thinknxg_agent_')) await e.delete();
    }
  } catch (_) {}
}
