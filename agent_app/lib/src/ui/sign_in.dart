import 'package:flutter/material.dart';

import '../state/session.dart';

/// First screen, and the prompt shown when a session expires (the site is kept, the agent signs in again).
class SignInScreen extends StatefulWidget {
  final Session session;
  const SignInScreen({super.key, required this.session});
  @override
  State<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<SignInScreen> {
  late final TextEditingController _site =
      TextEditingController(text: widget.session.site ?? widget.session.lastSite ?? '');

  @override
  void dispose() {
    _site.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.session;
    final busy = s.phase == SessionPhase.signingIn;
    final expired = s.phase == SessionPhase.expired;
    final t = Theme.of(context).textTheme;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                const Icon(Icons.support_agent, size: 56),
                const SizedBox(height: 12),
                Text('thinkNXG Support Agent', style: t.headlineSmall, textAlign: TextAlign.center),
                const SizedBox(height: 8),
                Text(
                  expired
                      ? 'Your session has ended. Sign in again to carry on; nothing you were doing is lost on the server.'
                      : 'Sign in with your staff account. Your browser opens your support site\'s sign-in page.',
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 24),
                TextField(
                  key: const Key('site-field'),
                  controller: _site,
                  enabled: !busy,
                  keyboardType: TextInputType.url,
                  autocorrect: false,
                  decoration: const InputDecoration(
                    labelText: 'Support site',
                    hintText: 'support.example.com',
                    prefixIcon: Icon(Icons.public),
                    border: OutlineInputBorder(),
                  ),
                  onSubmitted: busy ? null : (v) => s.signIn(v),
                ),
                const SizedBox(height: 16),
                FilledButton.icon(
                  key: const Key('sign-in'),
                  onPressed: busy ? null : () => s.signIn(_site.text),
                  icon: busy
                      ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.login),
                  label: Text(busy ? 'Waiting for the browser…' : 'Sign in'),
                ),
                if (s.error != null) ...[
                  const SizedBox(height: 16),
                  Semantics(
                    liveRegion: true,
                    child: Text(s.error!, style: TextStyle(color: Theme.of(context).colorScheme.error), textAlign: TextAlign.center),
                  ),
                ],
                if (expired) ...[
                  const SizedBox(height: 8),
                  TextButton(onPressed: busy ? null : () => s.signOut(), child: const Text('Sign out and clear this device')),
                ],
              ]),
            ),
          ),
        ),
      ),
    );
  }
}
