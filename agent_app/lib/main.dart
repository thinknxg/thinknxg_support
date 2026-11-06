import 'package:flutter/material.dart';

import 'src/alerts/device.dart';
import 'src/auth/browser.dart';
import 'src/auth/oauth.dart';
import 'src/auth/token_store.dart';
import 'src/platform/services.dart';
import 'src/state/session.dart';
import 'src/ui/sign_in.dart';
import 'src/ui/workspace.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final sink = DeviceAlertSink();
  sink.init();
  AppServices.alertSink = sink;
  AppServices.startPush = PushService.start;
  AppServices.stopPush = PushService.stop;
  AppServices.pushToken = () => PushService.token;
  final session = Session(store: SecureTokenStore(), oauth: OAuthService(browser: BrowserAuthenticator.forPlatform()));
  runApp(AgentApp(session: session));
  session.restore();
}

class AgentApp extends StatelessWidget {
  final Session session;
  const AgentApp({super.key, required this.session});

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFF0F766E);
    return MaterialApp(
      title: 'thinkNXG Support Agent',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: seed, useMaterial3: true),
      darkTheme: ThemeData(colorSchemeSeed: seed, useMaterial3: true, brightness: Brightness.dark),
      home: ListenableBuilder(
        listenable: session,
        builder: (context, _) {
          if (session.phase == SessionPhase.starting) return const Scaffold(body: Center(child: CircularProgressIndicator()));
          final me = session.me;
          if (me == null) return SignInScreen(session: session);
          // Expired mid-work: the workspace (and any unsent draft) stays underneath; sign in again on top.
          return Stack(children: [
            Workspace(key: ValueKey(me.user), session: session),
            if (session.phase != SessionPhase.signedIn)
              Positioned.fill(child: ColoredBox(color: Colors.black54, child: SignInScreen(session: session))),
          ]);
        },
      ),
    );
  }
}
