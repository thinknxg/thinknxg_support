import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:thinknxg_agent/main.dart';
import 'package:thinknxg_agent/src/alerts/alert_center.dart';
import 'package:thinknxg_agent/src/alerts/sounds.dart';
import 'package:thinknxg_agent/src/api/api_client.dart';
import 'package:thinknxg_agent/src/api/models.dart';
import 'package:thinknxg_agent/src/api/staff_api.dart';
import 'package:thinknxg_agent/src/auth/token_store.dart';
import 'package:thinknxg_agent/src/platform/files.dart';
import 'package:thinknxg_agent/src/platform/services.dart';
import 'package:thinknxg_agent/src/state/controllers.dart';
import 'package:thinknxg_agent/src/state/session.dart';

import 'fake_server.dart';

class Tokens implements TokenProvider {
  @override
  Future<String?> accessToken() async => 'token-1';
  @override
  Future<bool> refresh() async => false;
}

class FakeFiles implements FileService {
  UploadFile? next = const UploadFile('invoice.pdf', [37, 80, 68, 70]);
  DownloadedFile? opened;
  @override
  Future<UploadFile?> pick({int maxBytes = 10 * 1024 * 1024}) async => next;
  @override
  Future<void> open(DownloadedFile file) async => opened = file;
}

StaffApi apiFor(FakeServer s) =>
    StaffApi(ApiClient(site: Uri.parse('https://support.example.com'), tokens: Tokens(), httpClient: s.client));

Future<(Session, FakeServer)> signedIn(WidgetTester tester, Size size) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final server = FakeServer();
  final session = Session(store: MemoryTokenStore(), httpClient: server.client);
  await session.adopt(const StoredSession(site: 'https://support.example.com', clientId: 'cid', accessToken: 'token-1'));
  await tester.pumpWidget(AgentApp(session: session));
  await tester.pumpAndSettle();
  return (session, server);
}

void main() {
  late FakeFiles files;
  late SilentAlertSink sink;
  setUp(() {
    files = FakeFiles();
    FileService.instance = files;
    sink = SilentAlertSink();
    AppServices.alertSink = sink;
  });

  group('attachments', () {
    test('a file goes with the reply and opens through the authorised download', () async {
      final s = FakeServer();
      final c = ConversationController(apiFor(s), 'CONV-100', onExpired: () {});
      await c.load();
      c.attach(const UploadFile('invoice.pdf', [37, 80, 68, 70]));
      c.setText('Your invoice');
      await c.send();
      expect(c.draft.state, SendState.sent);
      expect(c.draft.file, isNull);
      final sent = c.messages.last;
      expect(sent.attachmentName, 'invoice.pdf');
      final f = await apiFor(s).attachment(sent.id);
      expect(f.name, 'invoice.pdf');
      expect(f.bytes, [37, 80, 68, 70]);
      c.dispose();
    });

    test('a missing file is an error, not an empty download', () async {
      final s = FakeServer();
      expect(apiFor(s).attachment('NOPE'), throwsA(isA<NotFound>()));
    });
  });

  group('canned responses and typing', () {
    test('placeholders come back filled and are added to the draft', () async {
      final s = FakeServer();
      final c = ConversationController(apiFor(s), 'CONV-100', onExpired: () {});
      await c.load();
      final list = await apiFor(s).cannedResponses();
      expect(list.map((x) => x.title), ['Greeting', 'Refunds']);
      await c.insertCanned(list.first);
      expect(c.draft.text, 'Hi Asha');
      await c.insertCanned(list.last);
      expect(c.draft.text, 'Hi Asha\nRefunds take 5 days.');
      c.dispose();
    });

    test('typing is sent at most every few seconds; customer typing shows', () async {
      final s = FakeServer()..customerTyping = true;
      final c = ConversationController(apiFor(s), 'CONV-100', onExpired: () {});
      await c.load();
      c.setText('H');
      c.setText('He');
      c.setText('Hel');
      await Future<void>.delayed(Duration.zero);
      expect(s.typingCalls, 1);
      await c.poll();
      expect(c.live.customerTyping, isTrue);
      c.dispose();
    });
  });

  group('alerts', () {
    AgentAlert alert(String id, String kind) => AgentAlert(id, kind, 'New chat', '', 'Support Conversation Link', 'CONV-100', null, null);
    AlertConfig config() => AlertConfig.fromJson({
          'enabled': true,
          'rules': {
            'New Chat': {'enabled': 1, 'popup': 1, 'sound': 'Ring', 'repeat_until_ack': 1, 'repeat_seconds': 10, 'max_repeats': 3, 'volume': 90},
            'Chat Message': {'enabled': 1, 'popup': 1, 'sound': 'Ping', 'repeat_until_ack': 0, 'repeat_seconds': 15, 'volume': 70},
            'Escalation': {'enabled': 0, 'sound': 'Siren'},
          },
          'prefs': {
            'mute_all': 0,
            'volume': 50,
            'items': {
              'Chat Message': {'sound': 'Pop', 'popup': 'Team Default', 'repeat': 'Team Default'},
            },
          },
        });

    test('rules merge with the agent\'s preferences like the web alert centre', () {
      final c = config();
      expect(c.rules['Chat Message']!.sound, 'Pop'); // own choice wins
      expect(c.rules['New Chat']!.sound, 'Ring'); // team default
      expect(c.rules['New Chat']!.volume, 45); // 90 % rule x 50 % agent
      expect(c.rules['New Chat']!.repeat, isTrue);
    });

    test('new alerts ring once; repeating ones until acknowledged; disabled stay silent', () async {
      var now = DateTime(2026, 11, 6, 12);
      final center = AlertCenter(sink, appInForeground: () => false, clock: () => now)..config = config();
      await center.update([]); // first load primes
      await center.update([alert('A1', 'New Chat'), alert('A2', 'Chat Message'), alert('A3', 'Escalation')]);
      expect(sink.played, ['Ring', 'Pop']);
      expect(sink.notified, ['New chat waiting', 'New chat message']); // generic text only
      now = now.add(const Duration(seconds: 10));
      await center.tick();
      expect(sink.played.last, 'Ring');
      expect(sink.played.length, 3);
      center.acknowledged(['A1']);
      now = now.add(const Duration(seconds: 10));
      await center.tick();
      expect(sink.played.length, 3);
      center.dispose();
    });

    test('alerts acknowledged elsewhere stop ringing on the next poll', () async {
      var now = DateTime(2026, 11, 6, 12);
      final center = AlertCenter(sink, appInForeground: () => true, clock: () => now)..config = config();
      await center.update([]);
      await center.update([alert('A1', 'New Chat')]);
      expect(center.ringingCount, 1);
      expect(sink.notified, isEmpty); // app in front: sound, no notification
      await center.update([]); // acknowledged on the web
      expect(center.ringingCount, 0);
      center.dispose();
    });

    test('mute silences everything', () async {
      final center = AlertCenter(sink, appInForeground: () => true)
        ..config = AlertConfig.fromJson({
          'enabled': true,
          'rules': {'New Chat': {'enabled': 1, 'sound': 'Ring', 'repeat_until_ack': 1, 'repeat_seconds': 10}},
          'prefs': {'mute_all': 1},
        });
      await center.update([]);
      await center.update([alert('A1', 'New Chat')]);
      expect(sink.played, isEmpty);
      center.dispose();
    });

    test('every sound synthesises to a valid WAV', () {
      for (final n in alertSoundNames) {
        final w = synthesizeWav(n);
        expect(String.fromCharCodes(w.sublist(0, 4)), 'RIFF', reason: n);
        expect(String.fromCharCodes(w.sublist(8, 12)), 'WAVE', reason: n);
        expect(w.length, greaterThan(44 + 1000), reason: n);
      }
      expect(synthesizeWav('None'), isEmpty);
    });
  });

  group('workspace', () {
    testWidgets('canned picker, attach, transfer picker and customer history', (tester) async {
      final (_, server) = await signedIn(tester, const Size(1440, 900));
      await tester.tap(find.byKey(const Key('conv-CONV-100')));
      await tester.pumpAndSettle();
      expect(find.text('Customer history'), findsOneWidget);
      expect(find.byKey(const Key('history-CONV-095')), findsOneWidget);

      await tester.tap(find.byKey(const Key('composer-canned')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('canned-search')), '/hi');
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('canned-CR-1')));
      await tester.pumpAndSettle();
      expect(find.text('Hi Asha'), findsWidgets);

      await tester.tap(find.byKey(const Key('composer-attach')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('composer-file')), findsOneWidget);
      await tester.tap(find.byKey(const Key('composer-send')));
      await tester.pumpAndSettle();
      expect(server.files.length, 1);
      expect(find.text('invoice.pdf'), findsOneWidget); // in the thread

      await tester.tap(find.text('invoice.pdf'));
      await tester.pumpAndSettle();
      expect(files.opened?.name, 'invoice.pdf');

      await tester.tap(find.byTooltip('More actions'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Transfer…'));
      await tester.pumpAndSettle();
      expect(find.text('Agent Two'), findsOneWidget);
      expect(find.textContaining('Online · 1 open'), findsOneWidget);
      await tester.tap(find.byKey(const Key('transfer-agent2@example.com')));
      await tester.pumpAndSettle();
      expect(server.conversations.first['assignee']['user'], 'agent2@example.com');
    });

    testWidgets('link customer: suggested customer, visitor added as a contact', (tester) async {
      final (_, server) = await signedIn(tester, const Size(1440, 900));
      await tester.tap(find.byKey(const Key('conv-CONV-100')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('link-customer')));
      await tester.pumpAndSettle();
      expect(find.text('Matches the visitor · CUST-ASHA · asha@example.com'), findsOneWidget);
      await tester.tap(find.byKey(const Key('customer-CUST-ASHA')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('contact-new')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('link-customer-save')));
      await tester.pumpAndSettle();
      expect(server.linked['CONV-100'], {'customer': 'CUST-ASHA', 'contact': null, 'create_contact': 1});
      expect(find.text('Asha Trading LLC'), findsWidgets);
      expect(find.byKey(const Key('link-customer')), findsNothing);
    });

    testWidgets('create ticket from a chat with a saved reply, then the ticket opens', (tester) async {
      final (_, server) = await signedIn(tester, const Size(1440, 900));
      await tester.tap(find.byKey(const Key('conv-CONV-099')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('create-ticket')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('ticket-subject')), 'Invoice is wrong');
      await tester.tap(find.byKey(const Key('ticket-saved-reply')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('canned-SR-1')));
      await tester.pumpAndSettle();
      expect(find.text('We have corrected your invoice'), findsWidgets);
      await tester.tap(find.byKey(const Key('create-ticket-save')));
      await tester.pumpAndSettle();
      expect(server.createdTickets.single['subject'], 'Invoice is wrong');
      expect(server.createdTickets.single['reply'], 'We have corrected your invoice');
      expect(server.createdTickets.single['client_request_id'], isNotEmpty);
      expect(find.textContaining('#77 Invoice is wrong'), findsWidgets); // the ticket view
    });

    testWidgets('ticket reply: insert a Helpdesk saved reply', (tester) async {
      await signedIn(tester, const Size(1440, 900));
      await tester.tap(find.text('Tickets'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('ticket-42')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('composer-canned')));
      await tester.pumpAndSettle();
      expect(find.text('Saved replies'), findsOneWidget);
      await tester.tap(find.byKey(const Key('canned-SR-1')));
      await tester.pumpAndSettle();
      expect(find.text('Ticket #42: we have corrected your invoice'), findsWidgets);
    });

    testWidgets('end chat asks: issue resolved? follow-up needed? (Yes/No, both required)', (tester) async {
      final (_, server) = await signedIn(tester, const Size(1440, 900));
      await tester.tap(find.byKey(const Key('conv-CONV-100')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('End chat'));
      await tester.pumpAndSettle();
      expect(find.text("Was the customer's issue resolved? *"), findsOneWidget);
      expect(find.text('Does the customer need a follow-up? *'), findsOneWidget);
      await tester.tap(find.widgetWithText(FilledButton, 'End chat'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Answer "Was the customer'), findsOneWidget); // required
      await tester.tap(find.text("Was the customer's issue resolved? *"));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Yes').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Does the customer need a follow-up? *'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('No').last);
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, 'End chat'));
      await tester.pumpAndSettle();
      expect(server.closed['CONV-100'], {'1': 'Yes', '2': 'No'});
    });

    testWidgets('live chat messages ring while the agent is in another section', (tester) async {
      final (_, server) = await signedIn(tester, const Size(1440, 900));
      await tester.tap(find.text('Tickets'));
      await tester.pumpAndSettle();
      await tester.pump(const Duration(seconds: 6)); // cursor
      server.message('CONV-097');
      await tester.pump(const Duration(seconds: 6));
      await tester.pumpAndSettle();
      expect(sink.played, ['Ping']);
    });

    testWidgets('offline banner, then everything refreshes on reconnect', (tester) async {
      final (_, server) = await signedIn(tester, const Size(1440, 900));
      server.offline = true;
      await tester.pump(const Duration(seconds: 11)); // next inbox poll fails
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('offline')), findsOneWidget);
      server.offline = false;
      server.calls.clear();
      await tester.pump(const Duration(seconds: 10));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('offline')), findsNothing);
      expect(server.calls, containsAll(['conversations', 'alerts']));
    });

    testWidgets('a notification tap opens the record only after the server allows it', (tester) async {
      await signedIn(tester, const Size(1440, 900));
      AppServices.pendingLink.value = (doctype: 'Support Conversation Link', name: 'SECRET');
      await tester.pumpAndSettle();
      expect(find.text('You do not have access to this item.'), findsOneWidget);
      AppServices.pendingLink.value = (doctype: 'Support Conversation Link', name: 'CONV-100');
      await tester.pumpAndSettle();
      expect(find.text('Reply to customer'), findsOneWidget);
    });

    testWidgets('new-message alerts (not stored on the server) ring once; Test sound plays', (tester) async {
      final (_, server) = await signedIn(tester, const Size(1440, 900));
      await tester.pump(const Duration(seconds: 16)); // a poll establishes the cursor
      server.message('CONV-100');
      await tester.pump(const Duration(seconds: 16));
      await tester.pumpAndSettle();
      expect(sink.played, ['Ping']);
      await tester.pump(const Duration(seconds: 16));
      expect(sink.played, ['Ping'], reason: 'each event once');
      await tester.tap(find.text('Alerts'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('test-sound')));
      await tester.pumpAndSettle();
      expect(sink.played.last, 'Ring');
      expect(find.text('Test alert sent.'), findsOneWidget);
    });

    testWidgets('alerts ring in the app and acknowledging clears them on the server', (tester) async {
      final (_, server) = await signedIn(tester, const Size(1440, 900));
      server.alertItems.add({
        'id': 'AL-1',
        'kind': 'New Chat',
        'title': 'New chat: Asha',
        'body': '',
        'reference_doctype': 'Support Conversation Link',
        'reference_name': 'CONV-100',
      });
      await tester.pump(const Duration(seconds: 16));
      await tester.pumpAndSettle();
      expect(sink.played, contains('Ring'));
      await tester.tap(find.text('Alerts'));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Acknowledge'));
      await tester.pumpAndSettle();
      expect(server.acknowledged, ['AL-1']);
    });
  });
}
