import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// What the app keeps between launches. Tokens live only in OS-backed secure storage
/// (Android Keystore, iOS and macOS Keychain, Windows Credential Manager via DPAPI).
class StoredSession {
  final String site;
  final String clientId;
  final String accessToken;
  final String? refreshToken;
  final DateTime? expiresAt;
  final String? user;

  const StoredSession({
    required this.site,
    required this.clientId,
    required this.accessToken,
    this.refreshToken,
    this.expiresAt,
    this.user,
  });

  StoredSession copyWith({String? accessToken, String? refreshToken, DateTime? expiresAt, String? user}) => StoredSession(
        site: site,
        clientId: clientId,
        accessToken: accessToken ?? this.accessToken,
        refreshToken: refreshToken ?? this.refreshToken,
        expiresAt: expiresAt ?? this.expiresAt,
        user: user ?? this.user,
      );

  Map<String, Object?> toJson() => {
        'site': site,
        'client_id': clientId,
        'access_token': accessToken,
        'refresh_token': refreshToken,
        'expires_at': expiresAt?.toIso8601String(),
        'user': user,
      };

  static StoredSession? fromJson(Object? j) {
    if (j is! Map || j['access_token'] == null || j['site'] == null) return null;
    return StoredSession(
      site: '${j['site']}',
      clientId: '${j['client_id'] ?? ''}',
      accessToken: '${j['access_token']}',
      refreshToken: j['refresh_token'] as String?,
      expiresAt: j['expires_at'] is String ? DateTime.tryParse(j['expires_at'] as String) : null,
      user: j['user'] as String?,
    );
  }
}

abstract class TokenStore {
  Future<StoredSession?> read();
  Future<void> write(StoredSession s);
  Future<void> clear();
  Future<String?> lastSite();
  Future<void> rememberSite(String site);
}

class SecureTokenStore implements TokenStore {
  static const _key = 'thinknxg_agent_session';
  static const _siteKey = 'thinknxg_agent_last_site';
  final FlutterSecureStorage _s;

  SecureTokenStore([FlutterSecureStorage? storage])
      : _s = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
              iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
              // macOS, outside the App Store: the login keychain (the data-protection keychain needs a
              // keychain-sharing entitlement that unsigned and Developer ID test builds do not have)
              mOptions: MacOsOptions(useDataProtectionKeyChain: false),
            );

  @override
  Future<StoredSession?> read() async {
    try {
      final raw = await _s.read(key: _key);
      return raw == null ? null : StoredSession.fromJson(jsonDecode(raw));
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> write(StoredSession s) => _s.write(key: _key, value: jsonEncode(s.toJson()));

  @override
  Future<void> clear() => _s.delete(key: _key);

  @override
  Future<String?> lastSite() => _s.read(key: _siteKey);

  @override
  Future<void> rememberSite(String site) => _s.write(key: _siteKey, value: site);
}

/// For tests and previews.
class MemoryTokenStore implements TokenStore {
  StoredSession? session;
  String? site;
  @override
  Future<StoredSession?> read() async => session;
  @override
  Future<void> write(StoredSession s) async => session = s;
  @override
  Future<void> clear() async => session = null;
  @override
  Future<String?> lastSite() async => site;
  @override
  Future<void> rememberSite(String s) async => site = s;
}
