import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../api/api_client.dart';
import '../api/models.dart';
import '../api/staff_api.dart';
import '../auth/oauth.dart';
import '../auth/token_store.dart';

enum SessionPhase { starting, signedOut, signingIn, signedIn, expired }

/// Sign-in state for the whole app. One agent, one site at a time.
class Session extends ChangeNotifier implements TokenProvider {
  final TokenStore store;
  final OAuthService? oauth;
  final http.Client? httpClient;

  SessionPhase phase = SessionPhase.starting;
  StoredSession? _stored;
  Bootstrap? me;
  StaffApi? api;
  String? error;
  String? lastSite;
  Future<bool>? _refreshing;

  Session({required this.store, this.oauth, this.httpClient});

  String? get site => _stored?.site;

  /// Restore the previous session from secure storage, if it is still valid.
  Future<void> restore() async {
    lastSite = await store.lastSite();
    _stored = await store.read();
    if (_stored == null) {
      _set(SessionPhase.signedOut);
      return;
    }
    await _connect();
  }

  Future<void> signIn(String siteInput) async {
    error = null;
    _set(SessionPhase.signingIn);
    try {
      final site = normaliseSite(siteInput);
      _stored = await oauth!.signIn(site);
      await store.write(_stored!);
      await store.rememberSite(site.toString());
      lastSite = site.toString();
      await _connect();
    } catch (e) {
      error = e.toString().replaceFirst('Exception: ', '');
      _set(_stored == null ? SessionPhase.signedOut : SessionPhase.expired);
    }
  }

  /// Use an existing session directly (tests, previews).
  Future<void> adopt(StoredSession s) async {
    _stored = s;
    await store.write(s);
    await _connect();
  }

  Future<void> _connect() async {
    api = StaffApi(ApiClient(site: Uri.parse(_stored!.site), tokens: this, httpClient: httpClient));
    try {
      me = await api!.bootstrap();
      _stored = _stored!.copyWith(user: me!.user);
      await store.write(_stored!);
      error = null;
      _set(SessionPhase.signedIn);
    } on SessionExpired {
      _set(SessionPhase.expired);
    } on AccessDenied catch (e) {
      error = e.message;
      await _wipe();
      _set(SessionPhase.signedOut);
    } on ApiException catch (e) {
      error = e.message;
      _set(me == null ? SessionPhase.expired : SessionPhase.signedIn);
    }
  }

  /// Called by any screen that gets [SessionExpired]: show the sign-in prompt, keep the site.
  void markExpired() {
    if (phase == SessionPhase.signedIn) _set(SessionPhase.expired);
  }

  /// Revoke on the server, stop push to this device, and clear everything stored locally.
  Future<void> signOut({String? pushToken}) async {
    final s = _stored;
    try {
      await api?.signOut(pushToken: pushToken);
    } catch (_) {}
    if (s != null) await oauth?.revoke(s);
    await _wipe();
    _set(SessionPhase.signedOut);
  }

  Future<void> _wipe() async {
    api?.client.close();
    api = null;
    me = null;
    _stored = null;
    await store.clear();
  }

  // ------------------------------------------------------------ TokenProvider
  @override
  Future<String?> accessToken() async => _stored?.accessToken;

  @override
  Future<bool> refresh() {
    // One refresh at a time even if several requests get 401 together.
    return _refreshing ??= _doRefresh().whenComplete(() => _refreshing = null);
  }

  Future<bool> _doRefresh() async {
    final s = _stored;
    if (s == null || oauth == null) return false;
    final n = await oauth!.refresh(s);
    if (n == null) {
      markExpired();
      return false;
    }
    _stored = n;
    await store.write(n);
    return true;
  }

  void _set(SessionPhase p) {
    phase = p;
    notifyListeners();
  }
}
