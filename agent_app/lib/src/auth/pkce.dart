import 'dart:convert';
import 'dart:math';

import 'package:crypto/crypto.dart';

/// RFC 7636 PKCE pair (S256). The verifier never leaves the device except in the token request.
class Pkce {
  final String verifier;
  final String challenge;
  const Pkce._(this.verifier, this.challenge);

  factory Pkce.generate([Random? rng]) {
    final r = rng ?? Random.secure();
    final verifier = base64UrlEncode(List<int>.generate(48, (_) => r.nextInt(256))).replaceAll('=', '');
    return Pkce._(verifier, challengeFor(verifier));
  }

  static String challengeFor(String verifier) =>
      base64UrlEncode(sha256.convert(ascii.encode(verifier)).bytes).replaceAll('=', '');
}

String randomState([Random? rng]) {
  final r = rng ?? Random.secure();
  return base64UrlEncode(List<int>.generate(24, (_) => r.nextInt(256))).replaceAll('=', '');
}
