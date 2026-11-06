import 'dart:convert';

import 'package:http/http.dart' as http;

import '../api/api_client.dart';
import 'browser.dart';
import 'pkce.dart';
import 'token_store.dart';

/// The site's public sign-in details (`auth_config`, no secrets).
class AuthConfig {
  final bool enabled;
  final String clientId;
  final String scopes;
  final Uri authorizeUrl, tokenUrl, revokeUrl;
  final List<String> redirectUris;
  final String siteName;

  const AuthConfig({
    required this.enabled,
    required this.clientId,
    required this.scopes,
    required this.authorizeUrl,
    required this.tokenUrl,
    required this.revokeUrl,
    required this.redirectUris,
    required this.siteName,
  });

  factory AuthConfig.fromJson(Map<String, dynamic> j) => AuthConfig(
        enabled: j['enabled'] == true,
        clientId: '${j['client_id'] ?? ''}',
        scopes: '${j['scopes'] ?? 'all openid'}',
        authorizeUrl: Uri.parse('${j['authorize_url'] ?? ''}'),
        tokenUrl: Uri.parse('${j['token_url'] ?? ''}'),
        revokeUrl: Uri.parse('${j['revoke_url'] ?? ''}'),
        redirectUris: [for (final u in (j['redirect_uris'] as List? ?? const [])) '$u'],
        siteName: '${j['site_name'] ?? ''}',
      );
}

class SignInFailed implements Exception {
  final String message;
  const SignInFailed(this.message);
  @override
  String toString() => message;
}

/// Normalises what the agent types ("support.example.com") into an https origin.
Uri normaliseSite(String input) {
  var s = input.trim();
  if (s.isEmpty) throw const SignInFailed('Enter your support site address.');
  if (!s.contains('://')) s = 'https://$s';
  final u = Uri.tryParse(s);
  if (u == null || u.host.isEmpty) throw const SignInFailed('That does not look like a site address.');
  final local = u.host == 'localhost' || u.host == '127.0.0.1' || u.host.endsWith('.localhost');
  if (u.scheme != 'https' && !local) throw const SignInFailed('Use an https:// address.');
  return Uri(scheme: u.scheme, host: u.host, port: u.hasPort ? u.port : null);
}

/// Authorization code + PKCE in the system browser, token refresh and revocation against Frappe's OAuth provider.
class OAuthService {
  final http.Client _http;
  final BrowserAuthenticator browser;
  OAuthService({required this.browser, http.Client? httpClient}) : _http = httpClient ?? http.Client();

  Future<AuthConfig> config(Uri site) async {
    http.Response r;
    try {
      r = await _http
          .get(site.replace(path: '/api/method/${ApiClient.prefix}auth_config'), headers: {'Accept': 'application/json'})
          .timeout(const Duration(seconds: 15));
    } catch (_) {
      throw const SignInFailed('Could not reach this site. Check the address and your connection.');
    }
    if (r.statusCode == 404 || r.statusCode == 403) {
      throw const SignInFailed('This site does not have thinkNXG Support 1.9 or later with the Agent Apps switched on.');
    }
    final m = ApiClient.decode(r);
    final cfg = AuthConfig.fromJson(m is Map ? Map<String, dynamic>.from(m) : {});
    if (!cfg.enabled || cfg.clientId.isEmpty) {
      throw const SignInFailed('The Agent Apps are not set up on this site yet. Ask your administrator to open '
          'Support Agent App Settings and create the OAuth client.');
    }
    return cfg;
  }

  Future<StoredSession> signIn(Uri site) async {
    final cfg = await config(site);
    final redirect = browser.redirectUri;
    if (!cfg.redirectUris.contains(redirect)) {
      throw SignInFailed('This site does not allow the sign-in address $redirect. Ask your administrator to check '
          'Support Agent App Settings.');
    }
    final pkce = Pkce.generate();
    final state = randomState();
    final authorize = cfg.authorizeUrl.replace(queryParameters: {
      'client_id': cfg.clientId,
      'response_type': 'code',
      'redirect_uri': redirect,
      'scope': cfg.scopes,
      'state': state,
      'code_challenge': pkce.challenge,
      'code_challenge_method': 'S256',
    });
    final callback = await browser.authenticate(authorize);
    final q = callback.queryParameters;
    if (q['error'] != null) {
      throw SignInFailed(q['error'] == 'access_denied' ? 'Sign-in was cancelled.' : 'Sign-in failed: ${q['error_description'] ?? q['error']}');
    }
    if (q['state'] != state) throw const SignInFailed('Sign-in could not be verified. Try again.');
    final code = q['code'];
    if (code == null || code.isEmpty) throw const SignInFailed('Sign-in did not return a code. Try again.');
    final tok = await _token(cfg.tokenUrl, {
      'grant_type': 'authorization_code',
      'code': code,
      'redirect_uri': redirect,
      'client_id': cfg.clientId,
      'code_verifier': pkce.verifier,
    });
    return StoredSession(
      site: site.toString(),
      clientId: cfg.clientId,
      accessToken: tok.access,
      refreshToken: tok.refresh,
      expiresAt: tok.expiresAt,
    );
  }

  Future<StoredSession?> refresh(StoredSession s) async {
    if (s.refreshToken == null) return null;
    final site = Uri.parse(s.site);
    try {
      final tok = await _token(site.replace(path: '/api/method/frappe.integrations.oauth2.get_token'), {
        'grant_type': 'refresh_token',
        'refresh_token': s.refreshToken!,
        'client_id': s.clientId,
      });
      return s.copyWith(accessToken: tok.access, refreshToken: tok.refresh ?? s.refreshToken, expiresAt: tok.expiresAt);
    } on SignInFailed {
      return null;
    }
  }

  /// Best effort: the local copy is cleared whatever the server says.
  Future<void> revoke(StoredSession s) async {
    final url = Uri.parse(s.site).replace(path: '/api/method/frappe.integrations.oauth2.revoke_token');
    for (final t in [s.refreshToken, s.accessToken]) {
      if (t == null) continue;
      try {
        await _http.post(url, body: {'token': t}).timeout(const Duration(seconds: 10));
      } catch (_) {}
    }
  }

  Future<({String access, String? refresh, DateTime? expiresAt})> _token(Uri url, Map<String, String> form) async {
    http.Response r;
    try {
      r = await _http.post(url, body: form, headers: {'Accept': 'application/json'}).timeout(const Duration(seconds: 20));
    } catch (_) {
      throw const SignInFailed('Could not reach the site to finish signing in.');
    }
    Map<String, dynamic> j = {};
    try {
      j = Map<String, dynamic>.from(jsonDecode(r.body) as Map);
    } catch (_) {}
    if (r.statusCode != 200 || j['access_token'] == null) {
      throw SignInFailed('The site did not accept the sign-in (${j['error'] ?? r.statusCode}).');
    }
    final secs = int.tryParse('${j['expires_in'] ?? ''}');
    return (
      access: '${j['access_token']}',
      refresh: j['refresh_token'] as String?,
      expiresAt: secs == null ? null : DateTime.now().add(Duration(seconds: secs)),
    );
  }
}
