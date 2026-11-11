import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:thinknxg_agent/src/api/api_client.dart';
import 'package:thinknxg_agent/src/api/models.dart';
import 'package:thinknxg_agent/src/api/staff_api.dart';
import 'package:thinknxg_agent/src/auth/oauth.dart';
import 'package:thinknxg_agent/src/auth/pkce.dart';
import 'package:thinknxg_agent/src/state/controllers.dart';

import 'fake_server.dart';

class Tokens implements TokenProvider {
  String? token;
  String? next;
  int refreshes = 0;
  Tokens(this.token, {this.next});
  @override
  Future<String?> accessToken() async => token;
  @override
  Future<bool> refresh() async {
    refreshes++;
    if (next == null) return false;
    token = next;
    next = null;
    return true;
  }
}

StaffApi apiFor(FakeServer s, Tokens t) =>
    StaffApi(ApiClient(site: Uri.parse('https://support.example.com'), tokens: t, httpClient: s.client));

void main() {
  group('PKCE', () {
    test('S256 challenge is base64url(sha256(verifier)) without padding', () {
      // reference value computed independently: python3 hashlib.sha256 + base64.urlsafe_b64encode
      expect(Pkce.challengeFor('dBjftJeZ4CVP-mJ92K9DXCdHl1CGvvn6cqyDkB9H5Bk'), 'GpvbgcWzXQfBXxJT7NV8bvauWD9D6AdWuZ1oTL6uhTQ');
    });
    test('verifier is 43..128 unreserved characters', () {
      final p = Pkce.generate();
      expect(p.verifier.length, inInclusiveRange(43, 128));
      expect(RegExp(r'^[A-Za-z0-9\-._~]+$').hasMatch(p.verifier), isTrue);
    });
  });

  group('site address', () {
    test('adds https and strips paths', () => expect(normaliseSite('support.example.com/app').toString(), 'https://support.example.com'));
    test('refuses plain http except localhost', () {
      expect(() => normaliseSite('http://support.example.com'), throwsA(isA<SignInFailed>()));
      expect(normaliseSite('http://localhost:8000').toString(), 'http://localhost:8000');
    });
  });

  group('ApiClient', () {
    test('sends the bearer token and unwraps message', () async {
      final s = FakeServer();
      final b = await apiFor(s, Tokens('token-1')).bootstrap();
      expect(b.user, 'agent1@example.com');
      expect(b.can('helpdesk'), isTrue);
    });

    test('refreshes once on 401 and retries', () async {
      final s = FakeServer();
      final t = Tokens('old', next: 'token-1');
      final b = await apiFor(s, t).bootstrap();
      expect(b.fullName, 'Agent One');
      expect(t.refreshes, 1);
    });

    test('expired session when refresh fails', () async {
      final s = FakeServer();
      expect(apiFor(s, Tokens('old')).bootstrap(), throwsA(isA<SessionExpired>()));
    });

    test('maps Frappe _server_messages and status codes', () async {
      final api = ApiClient(
        site: Uri.parse('https://x.example.com'),
        tokens: Tokens('t'),
        httpClient: MockClient((_) async => http.Response(
            jsonEncode({'exc_type': 'PermissionError', '_server_messages': jsonEncode([jsonEncode({'message': 'Not <b>allowed</b>'})])}),
            403)),
      );
      await expectLater(api.get('bootstrap'), throwsA(isA<AccessDenied>().having((e) => e.message, 'message', 'Not allowed')));
    });

    test('an endpoint missing on an older site says to update the site', () async {
      final api = ApiClient(
        site: Uri.parse('https://x.example.com'),
        tokens: Tokens('t'),
        httpClient: MockClient((_) async => http.Response(
            jsonEncode({
              'exc_type': 'AttributeError',
              'exception': "Failed to get method for command thinknxg_support.api.staff.v1.send_test_alert with module "
                  "'thinknxg_support.api.staff.v1' has no attribute 'send_test_alert'",
            }),
            404)),
      );
      await expectLater(api.post('send_test_alert', {}), throwsA(isA<NotFound>().having((e) => e.message, 'message', contains('newer thinkNXG Support'))));
    });

    test('a lost response is a NetworkError', () async {
      final s = FakeServer()..failNextWithTimeout = 1;
      expect(apiFor(s, Tokens('token-1')).bootstrap(), throwsA(isA<NetworkError>()));
    });
  });

  group('conversations', () {
    test('cursor pagination returns each conversation once', () async {
      final s = FakeServer();
      final inbox = InboxController(apiFor(s, Tokens('token-1')), onExpired: () {});
      await inbox.refresh();
      expect(inbox.items.length, 30);
      await inbox.loadMore();
      expect(inbox.items.length, 45);
      expect(inbox.items.map((c) => c.id).toSet().length, 45);
      expect(inbox.nextCursor, isNull);
      inbox.dispose();
    });

    test('second agent claiming gets a conflict and sees the winner', () async {
      final s = FakeServer();
      final c = ConversationController(apiFor(s, Tokens('token-1')), 'CONV-100', onExpired: () {});
      await c.load();
      expect(c.detail!.actions.claim, isTrue);
      expect(await c.claim(), isTrue);
      expect(c.detail!.assignee!.user, 'agent1@example.com');
      s.user = 'agent2@example.com';
      final c2 = ConversationController(apiFor(s, Tokens('token-1')), 'CONV-100', onExpired: () {});
      await c2.load();
      expect(await c2.claim(), isFalse);
      expect(c2.actionError, contains('already has this conversation'));
      expect(c2.detail!.assignee!.user, 'agent1@example.com');
      c.dispose();
      c2.dispose();
    });

    test('retrying after a lost response creates one customer-visible message', () async {
      final s = FakeServer();
      final c = ConversationController(apiFor(s, Tokens('token-1')), 'CONV-100', onExpired: () {});
      await c.load();
      c.setText('We are fixing your invoice');
      s.failNextWithTimeout = 1;
      await c.send();
      expect(c.draft.state, SendState.failed);
      expect(c.draft.text, 'We are fixing your invoice', reason: 'draft kept on failure');
      final rid = c.draft.requestId;
      expect(rid, isNotNull);
      await c.send(); // manual retry
      expect(c.draft.state, SendState.sent);
      expect(c.draft.text, isEmpty);
      final visible = s.customerView('CONV-100').where((h) => h.contains('fixing your invoice'));
      expect(visible.length, 1);
      expect(c.messages.where((m) => m.text == 'We are fixing your invoice').length, 1);
      c.dispose();
    });

    test('internal notes never reach the customer view', () async {
      final s = FakeServer();
      final c = ConversationController(apiFor(s, Tokens('token-1')), 'CONV-100', onExpired: () {});
      await c.load();
      c.setMode(ComposerMode.note);
      c.setText('Customer is a VIP');
      await c.send();
      expect(c.messages.last.internal, isTrue);
      expect(s.customerView('CONV-100').any((h) => h.contains('VIP')), isFalse);
      c.dispose();
    });

    test('closed WhatsApp window: server says why, draft kept', () async {
      final s = FakeServer();
      final id = s.conversations[2]['id'] as String; // WhatsApp, window closed
      final c = ConversationController(apiFor(s, Tokens('token-1')), id, onExpired: () {});
      await c.load();
      expect(c.detail!.actions.reply, isFalse);
      c.setText('Hello?');
      await c.send();
      expect(c.draft.state, SendState.failed);
      expect(c.draft.error, contains('24 hours'));
      expect(c.draft.serverActions.single['action'], 'open_web_console');
      expect(c.draft.text, 'Hello?');
      c.dispose();
    });

    test('WhatsApp templates: listed, blocked without opt-in, sent once, shown in the thread', () async {
      final s = FakeServer();
      final id = s.conversations[2]['id'] as String; // WhatsApp, window closed
      final c = ConversationController(apiFor(s, Tokens('token-1')), id, onExpired: () {});
      await c.load();
      expect(c.detail!.actions.reply, isFalse);
      expect(c.detail!.actions.sendTemplate, isTrue);
      final t = await c.api.whatsappTemplates(id);
      expect(t.templates.map((x) => x.id), ['order_update-en', 'summer_offer-en']);
      final order = t.templates.first;
      expect(order.preview({'body.1': 'Salim', 'body.2': 'A100'}), contains('Hi Salim, your order A100 is on its way.'));
      expect(order.preview({'body.1': 'Salim'}), contains('{{2}}')); // an unfilled variable stays visible
      expect(t.templates.last.blocked, 'no_optin');
      // a missing variable is refused by the server and nothing is sent
      await expectLater(c.sendTemplate('order_update-en', {'body.1': 'Salim', 'body.2': ''}), throwsA(isA<ApiException>()));
      final before = c.messages.length;
      await c.sendTemplate('order_update-en', {'body.1': 'Salim', 'body.2': 'A100'});
      expect(c.messages.length, before + 1);
      expect(c.messages.last.text, contains('order_update-en'));
      await c.api.whatsappConsent(id, 'Opted In', 'Asked on the phone');
      expect((await c.api.whatsappTemplates(id)).templates.last.blocked, isNull);
      c.dispose();
    });

    test('opening the thread acknowledges it as read', () async {
      final s = FakeServer();
      final c = ConversationController(apiFor(s, Tokens('token-1')), 'CONV-100', onExpired: () {});
      await c.load();
      expect(s.calls, contains('mark_read'));
      expect(s.conversations.first['unread'], 0);
      c.dispose();
    });

    test('session expiry is reported, not swallowed', () async {
      final s = FakeServer();
      var expired = false;
      final c = ConversationController(apiFor(s, Tokens('stale')), 'CONV-100', onExpired: () => expired = true);
      await c.load();
      expect(expired, isTrue);
      c.dispose();
    });
  });

  group('tickets', () {
    test('reply, internal note and status change', () async {
      final s = FakeServer();
      final t = TicketController(apiFor(s, Tokens('token-1')), '42', onExpired: () {});
      await t.load();
      expect(t.ticket!.subject, 'Invoice wrong');
      expect(t.ticket!.linkedConversation, 'CONV-100');
      t.draft.text = 'We have corrected the invoice';
      await t.send();
      t.setMode(ComposerMode.note);
      t.draft.text = 'Credit note raised';
      await t.send();
      expect(t.timeline.where((i) => !i.internal).single.text, 'We have corrected the invoice');
      expect(t.timeline.where((i) => i.internal).single.text, 'Credit note raised');
      expect(await t.update(status: 'Resolved'), isTrue);
      expect(t.ticket!.status, 'Resolved');
      t.dispose();
    });

    test('stale status change is a conflict', () async {
      final s = FakeServer();
      final t = TicketController(apiFor(s, Tokens('token-1')), '42', onExpired: () {});
      await t.load();
      s.tickets['42']!['modified'] = '2026-11-06 12:10:00.000000'; // someone else saved
      expect(await t.update(status: 'Replied'), isFalse);
      expect(t.actionError, contains('Someone else changed'));
      t.dispose();
    });
  });

  test('notification links are re-checked by the server', () async {
    final s = FakeServer();
    final api = apiFor(s, Tokens('token-1'));
    expect((await api.openTarget('Support Conversation Link', 'CONV-100')).kind, 'conversation');
    expect(api.openTarget('Support Conversation Link', 'SECRET'), throwsA(isA<AccessDenied>()));
  });

  test('htmlToText', () {
    expect(htmlToText('<p>Hi &amp; welcome</p><p>Line&nbsp;2</p>'), 'Hi & welcome\nLine 2');
  });
}
