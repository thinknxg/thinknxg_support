import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:http/http.dart' as http;

/// Errors the UI tells apart. Messages come from the server where it sent one.
sealed class ApiException implements Exception {
  final String message;
  const ApiException(this.message);
  @override
  String toString() => message;
}

/// Token expired or revoked and could not be refreshed: the app asks the agent to sign in again.
class SessionExpired extends ApiException {
  const SessionExpired([super.message = 'Your session has expired. Sign in again.']);
}

/// Signed in, but this account (or this record) is not allowed.
class AccessDenied extends ApiException {
  const AccessDenied(super.message);
}

class NotFound extends ApiException {
  const NotFound(super.message);
}

/// Someone else changed it first (claim, transfer, status). `current` is the record as it is now.
class ConflictError extends ApiException {
  final Map<String, dynamic> current;
  const ConflictError(super.message, this.current);
}

/// The server needs something else first, e.g. code `whatsapp_window_closed`. `actions` are what it offers.
class ActionRequired extends ApiException {
  final String code;
  final List<Map<String, dynamic>> actions;
  const ActionRequired(super.message, this.code, this.actions);
}

class ValidationFailed extends ApiException {
  const ValidationFailed(super.message);
}

/// No answer (offline, timeout). The request may or may not have reached the server: retry with the same
/// client request id so the server can de-duplicate.
class NetworkError extends ApiException {
  const NetworkError([super.message = 'No connection to the server. Check your network and try again.']);
}

class ServerError extends ApiException {
  const ServerError([super.message = 'The server could not complete this. Try again shortly.']);
}

/// Supplies the bearer token and refreshes it once when the server says it is no longer valid.
abstract class TokenProvider {
  Future<String?> accessToken();

  /// Returns true when a new token is available.
  Future<bool> refresh();
}

String newRequestId([Random? rng]) {
  final r = rng ?? Random.secure();
  final b = List<int>.generate(16, (_) => r.nextInt(256));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  final h = b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
  return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-${h.substring(16, 20)}-${h.substring(20)}';
}

/// Thin client over Frappe's /api/method. Always HTTPS in production; the bearer token is the agent's own.
class ApiClient {
  final Uri site;
  final TokenProvider tokens;
  final http.Client _http;
  final Duration timeout;
  static const prefix = 'thinknxg_support.api.staff.v1.';

  ApiClient({required this.site, required this.tokens, http.Client? httpClient, this.timeout = const Duration(seconds: 20)})
      : _http = httpClient ?? http.Client();

  Uri _uri(String method, [Map<String, String?>? query]) {
    final q = {for (final e in (query ?? {}).entries) if (e.value != null && e.value!.isNotEmpty) e.key: e.value!};
    return site.replace(path: '/api/method/$prefix$method', queryParameters: q.isEmpty ? null : q);
  }

  Future<dynamic> get(String method, [Map<String, String?>? query]) => _send('GET', _uri(method, query));

  Future<dynamic> post(String method, Map<String, Object?> body) => _send('POST', _uri(method), body);

  Future<dynamic> _send(String verb, Uri uri, [Map<String, Object?>? body], {bool retried = false}) async {
    final token = await tokens.accessToken();
    if (token == null) throw const SessionExpired();
    final req = http.Request(verb, uri)
      ..headers['Authorization'] = 'Bearer $token'
      ..headers['Accept'] = 'application/json';
    if (body != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode({for (final e in body.entries) if (e.value != null) e.key: e.value});
    }
    http.Response res;
    try {
      res = await http.Response.fromStream(await _http.send(req).timeout(timeout));
    } on TimeoutException {
      throw const NetworkError('The server did not answer in time. Your message may not have been sent; retry to make sure.');
    } on http.ClientException {
      throw const NetworkError();
    } catch (e) {
      if (e is ApiException) rethrow;
      throw const NetworkError();
    }
    if (res.statusCode == 401 && !retried) {
      if (await tokens.refresh()) return _send(verb, uri, body, retried: true);
      throw const SessionExpired();
    }
    return decode(res);
  }

  static dynamic decode(http.Response res) {
    Map<String, dynamic> j = {};
    try {
      final d = jsonDecode(utf8.decode(res.bodyBytes));
      if (d is Map) j = Map<String, dynamic>.from(d);
    } catch (_) {}
    if (res.statusCode >= 200 && res.statusCode < 300) return j['message'];
    final msg = errorMessage(j);
    final code = j['error_code']?.toString();
    switch (res.statusCode) {
      case 401:
        throw const SessionExpired();
      case 403:
        throw AccessDenied(msg ?? 'You do not have access to this.');
      case 404:
        throw NotFound(msg ?? 'Not found.');
      case 409:
        throw ConflictError(msg ?? 'Someone else changed this first.',
            j['conflict'] is Map ? Map<String, dynamic>.from(j['conflict']) : {});
      case 417:
      case 422:
        if (code != null && code != 'conflict') {
          throw ActionRequired(msg ?? 'This needs another step.', code,
              [for (final a in (j['actions'] is List ? j['actions'] as List : const [])) if (a is Map) Map<String, dynamic>.from(a)]);
        }
        throw ValidationFailed(msg ?? 'Check what you entered and try again.');
      case 429:
        throw ValidationFailed(msg ?? 'Too many requests. Wait a moment and try again.');
    }
    if (res.statusCode >= 500) throw ServerError(msg ?? const ServerError().message);
    throw ValidationFailed(msg ?? 'The request was not accepted (${res.statusCode}).');
  }

  /// Frappe puts user-facing messages in `_server_messages` (JSON list of JSON objects) or `exception`.
  static String? errorMessage(Map<String, dynamic> j) {
    if (j['error_message'] is String && (j['error_message'] as String).isNotEmpty) return j['error_message'];
    final sm = j['_server_messages'];
    if (sm is String) {
      try {
        final list = jsonDecode(sm) as List;
        final parts = <String>[];
        for (final m in list) {
          final o = m is String ? jsonDecode(m) : m;
          final t = o is Map ? o['message']?.toString() : o?.toString();
          if (t != null && t.isNotEmpty) parts.add(t.replaceAll(RegExp(r'<[^>]+>'), ''));
        }
        if (parts.isNotEmpty) return parts.join('\n');
      } catch (_) {}
    }
    final exc = j['exception'];
    if (exc is String && exc.contains(':')) return exc.substring(exc.indexOf(':') + 1).trim();
    return null;
  }

  void close() => _http.close();
}
