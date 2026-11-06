import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:thinknxg_agent/main.dart';
import 'package:thinknxg_agent/src/auth/token_store.dart';
import 'package:thinknxg_agent/src/state/session.dart';

import 'fake_server.dart';

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
  testWidgets('sign-in screen when there is no stored session', (tester) async {
    final session = Session(store: MemoryTokenStore());
    await session.restore();
    await tester.pumpWidget(AgentApp(session: session));
    expect(find.text('thinkNXG Support Agent'), findsOneWidget);
    expect(find.byKey(const Key('site-field')), findsOneWidget);
  });

  testWidgets('Windows-size layout: rail, list and thread side by side; reply reaches the customer', (tester) async {
    final (_, server) = await signedIn(tester, const Size(1440, 900));
    expect(find.byType(NavigationRail), findsOneWidget);
    expect(find.byType(NavigationBar), findsNothing);
    expect(find.text('Visitor Asha'), findsOneWidget);

    await tester.tap(find.byKey(const Key('conv-CONV-100')));
    await tester.pumpAndSettle();
    expect(find.text('My invoice is wrong'), findsWidgets);
    expect(find.text('Reply to customer'), findsOneWidget);
    expect(find.text('Internal note'), findsOneWidget);

    await tester.tap(find.byKey(const Key('claim')));
    await tester.pumpAndSettle();
    expect(find.text('Assigned to you'), findsOneWidget);

    await tester.enterText(find.byKey(const Key('composer-field')), 'Thanks, checking now');
    await tester.tap(find.byKey(const Key('composer-send')));
    await tester.pumpAndSettle();
    expect(server.customerView('CONV-100').where((h) => h.contains('checking now')).length, 1);
    expect(find.text('Sent'), findsOneWidget);
  });

  testWidgets('internal note mode is clearly labelled', (tester) async {
    await signedIn(tester, const Size(1440, 900));
    await tester.tap(find.byKey(const Key('conv-CONV-100')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Internal note'));
    await tester.pumpAndSettle();
    expect(find.text('Only staff can see internal notes.'), findsOneWidget);
    expect(find.text('Add note'), findsOneWidget);
  });

  testWidgets('phone layout: bottom navigation, thread opens full screen', (tester) async {
    await signedIn(tester, const Size(400, 820));
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.byType(NavigationRail), findsNothing);
    await tester.tap(find.byKey(const Key('conv-CONV-100')));
    await tester.pumpAndSettle();
    expect(find.text('Conversation'), findsOneWidget); // pushed route's app bar
    expect(find.byKey(const Key('composer-field')), findsOneWidget);
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.tap(find.text('Tickets'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Invoice wrong'), findsOneWidget);
  });

  testWidgets('composer stays visible with the keyboard open', (tester) async {
    await signedIn(tester, const Size(400, 820));
    await tester.tap(find.byKey(const Key('conv-CONV-100')));
    await tester.pumpAndSettle();
    tester.view.viewInsets = const FakeViewPadding(bottom: 320);
    await tester.pumpAndSettle();
    final field = tester.getRect(find.byKey(const Key('composer-field')));
    expect(field.bottom, lessThanOrEqualTo(820 - 320));
  });

  testWidgets('ticket: reply and status change from the app', (tester) async {
    final (_, server) = await signedIn(tester, const Size(1440, 900));
    await tester.tap(find.text('Tickets'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('ticket-42')));
    await tester.pumpAndSettle();
    expect(find.text('Reply to customer (email)'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('composer-field')), 'Corrected invoice attached');
    await tester.tap(find.byKey(const Key('composer-send')));
    await tester.pumpAndSettle();
    expect(server.ticketTimeline['42']!.single['html'], contains('Corrected invoice'));
    await tester.tap(find.byKey(const Key('ticket-status')));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(CheckedPopupMenuItem<String>, 'Resolved'));
    await tester.pumpAndSettle();
    expect(server.tickets['42']!['status'], 'Resolved');
  });

  testWidgets('sign out clears the stored session', (tester) async {
    final (session, _) = await signedIn(tester, const Size(1440, 900));
    await session.signOut();
    await tester.pumpAndSettle();
    expect(session.phase, SessionPhase.signedOut);
    expect(await session.store.read(), isNull);
    expect(find.byKey(const Key('site-field')), findsOneWidget);
  });
}
