import 'dart:async';
import 'dart:io';

import 'package:flutter_web_auth_2/flutter_web_auth_2.dart';
import 'package:url_launcher/url_launcher.dart';

/// Opens the site's sign-in page in the system browser and returns the callback URL.
abstract class BrowserAuthenticator {
  String get redirectUri;
  Future<Uri> authenticate(Uri authorizeUrl);

  factory BrowserAuthenticator.forPlatform() =>
      Platform.isWindows || Platform.isLinux || Platform.isMacOS ? LoopbackAuthenticator() : MobileAuthenticator();
}

/// Android (Custom Tabs) and iOS (ASWebAuthenticationSession) via flutter_web_auth_2, app scheme callback.
class MobileAuthenticator implements BrowserAuthenticator {
  static const scheme = 'com.thinknxg.agent';
  @override
  String get redirectUri => '$scheme://oauth2redirect';

  @override
  Future<Uri> authenticate(Uri authorizeUrl) async {
    final result = await FlutterWebAuth2.authenticate(url: authorizeUrl.toString(), callbackUrlScheme: scheme);
    return Uri.parse(result);
  }
}

/// Windows: RFC 8252 loopback redirect. Listens on 127.0.0.1 only, for one request, for a few minutes.
class LoopbackAuthenticator implements BrowserAuthenticator {
  final int port;
  final Duration wait;
  final Future<bool> Function(Uri) open;
  LoopbackAuthenticator({this.port = 43823, this.wait = const Duration(minutes: 5), Future<bool> Function(Uri)? open})
      : open = open ?? ((u) => launchUrl(u, mode: LaunchMode.externalApplication));

  @override
  String get redirectUri => 'http://127.0.0.1:$port/callback';

  @override
  Future<Uri> authenticate(Uri authorizeUrl) async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, port);
    try {
      if (!await open(authorizeUrl)) throw Exception('Could not open the browser.');
      await for (final req in server.timeout(wait)) {
        if (req.uri.path != '/callback') {
          req.response.statusCode = 404;
          await req.response.close();
          continue;
        }
        req.response.headers.contentType = ContentType.html;
        req.response.write('<!doctype html><meta charset="utf-8"><title>thinkNXG Support</title>'
            '<body style="font-family:system-ui;padding:40px;text-align:center">'
            '<h2>You can close this tab</h2><p>Return to the thinkNXG Support Agent app.</p></body>');
        await req.response.close();
        return Uri.parse(redirectUri).replace(queryParameters: req.uri.queryParameters);
      }
      throw Exception('Sign-in was not completed.');
    } on TimeoutException {
      throw Exception('Sign-in timed out. Try again.');
    } finally {
      await server.close(force: true);
    }
  }
}
