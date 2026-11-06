import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../alerts/alert_center.dart';
import '../api/api_client.dart';
import '../api/models.dart';
import '../platform/files.dart';
import '../platform/services.dart';
import '../state/controllers.dart';
import '../state/session.dart';
import 'alerts_view.dart';
import 'common.dart';
import 'conversation_view.dart';
import 'inbox_view.dart';
import 'tickets_view.dart';

enum Section { inbox, tickets, alerts }

/// The signed-in workspace. Wide windows (Windows, tablets): navigation rail + resizable list + thread (+ details).
/// Narrow (phones): bottom navigation, threads open full screen.
class Workspace extends StatefulWidget {
  final Session session;
  const Workspace({super.key, required this.session});
  @override
  State<Workspace> createState() => WorkspaceState();
}

class WorkspaceState extends State<Workspace> {
  late final InboxController inbox;
  late final TicketsController tickets;
  late final AlertsController alerts;
  ConversationController? conversation;
  TicketController? ticket;
  Section section = Section.inbox;
  double listWidth = 380;
  final searchFocus = FocusNode(debugLabel: 'search');
  final composerFocus = FocusNode(debugLabel: 'composer');
  late final AppLifecycleListener _life;
  late final AlertCenter alertCenter;
  final List<Timer> _timers = [];
  bool _foreground = true;

  Bootstrap get me => widget.session.me!;

  @override
  void initState() {
    super.initState();
    final api = widget.session.api!;
    void expired() => widget.session.markExpired();
    inbox = InboxController(api, onExpired: expired)..onReconnect = _refreshAll;
    tickets = TicketsController(api, onExpired: expired);
    alertCenter = AlertCenter(AppServices.alertSink, appInForeground: () => _foreground)..start();
    alerts = AlertsController(api, onExpired: expired, center: alertCenter);
    alerts.loadConfig().then((_) => alerts.refresh());
    _startPolling();
    _refreshAll();
    api.heartbeat().catchError((_) {});
    // Polling keeps running while the window is hidden or minimised so alerts still ring (desktop) and show a
    // notification; a resume refreshes everything at once.
    _life = AppLifecycleListener(
      onResume: () {
        _foreground = true;
        _startPolling();
        _refreshAll();
      },
      onInactive: () => _foreground = false,
      onHide: () => _foreground = false,
      onShow: () => _foreground = true,
    );
    AppServices.pendingLink.addListener(_openPending);
    WidgetsBinding.instance.addPostFrameCallback((_) => _openPending());
    _startPush();
  }

  void _openPending() {
    final l = AppServices.pendingLink.value;
    if (l == null || !mounted) return;
    AppServices.pendingLink.value = null;
    openLink(l.doctype, l.name); // access is checked by the server before anything opens
  }

  Future<void> _startPush() async {
    final start = AppServices.startPush;
    if (start == null) return;
    await start(
      onToken: (t) => widget.session.api
          ?.registerDevice(t, AppServices.platform, deviceName: AppServices.platform, appVersion: AppServices.appVersion)
          .catchError((_) {}),
      onForeground: () => alerts.refresh(),
    );
  }

  void _refreshAll() {
    inbox.refresh();
    if (me.can('helpdesk')) tickets.refresh();
    alerts.refresh();
    conversation?.poll();
  }

  void _startPolling() {
    _stopPolling();
    _timers.add(Timer.periodic(Duration(seconds: me.inboxPollSeconds), (_) {
      inbox.refresh();
      if (section == Section.tickets && me.can('helpdesk')) tickets.refresh();
    }));
    _timers.add(Timer.periodic(Duration(seconds: me.threadPollSeconds), (_) => conversation?.poll()));
    _timers.add(Timer.periodic(Duration(seconds: me.alertsPollSeconds), (_) => alerts.refresh()));
    _timers.add(Timer.periodic(const Duration(seconds: 45), (_) => widget.session.api?.heartbeat().catchError((_) {})));
  }

  void _stopPolling() {
    for (final t in _timers) {
      t.cancel();
    }
    _timers.clear();
  }

  @override
  void dispose() {
    _stopPolling();
    _life.dispose();
    AppServices.pendingLink.removeListener(_openPending);
    alertCenter.dispose();
    inbox.dispose();
    tickets.dispose();
    alerts.dispose();
    conversation?.dispose();
    ticket?.dispose();
    searchFocus.dispose();
    composerFocus.dispose();
    super.dispose();
  }

  bool get _wide => MediaQuery.sizeOf(context).width >= wideBreakpoint;

  void openConversation(String id) {
    if (conversation?.id != id) {
      conversation?.dispose();
      conversation = ConversationController(widget.session.api!, id,
          onExpired: widget.session.markExpired, onChanged: inbox.upsert)
        ..load();
    }
    setState(() => section = Section.inbox);
    if (!_wide) {
      _push(ConversationView(controller: conversation!, me: me.user, onOpenTicket: openTicket, onOpenConversation: openConversation),
          'Conversation');
    }
  }

  void openTicket(String id) {
    if (ticket?.id != id) {
      ticket?.dispose();
      ticket = TicketController(widget.session.api!, id, onExpired: widget.session.markExpired)..load();
    }
    setState(() => section = Section.tickets);
    if (!_wide) _push(TicketView(controller: ticket!, me: me.user, onOpenConversation: openConversation), 'Ticket #$id');
  }

  /// Notification and alert links: the server checks access again before anything opens.
  Future<void> openLink(String doctype, String name) async {
    try {
      final t = await widget.session.api!.openTarget(doctype, name);
      if (!mounted) return;
      if (t.kind == 'conversation') {
        openConversation(t.id);
      } else if (t.kind == 'ticket') {
        openTicket(t.id);
      } else {
        _snack('This item opens in the web console.');
      }
    } on SessionExpired {
      widget.session.markExpired();
    } on ApiException catch (e) {
      _snack(e is AccessDenied || e is NotFound ? 'You do not have access to this item.' : e.message);
    }
  }

  void _snack(String m) => ScaffoldMessenger.maybeOf(context)?.showSnackBar(SnackBar(content: Text(m)));

  void _push(Widget body, String title) {
    Navigator.of(context).push(MaterialPageRoute(
      builder: (_) => Scaffold(appBar: AppBar(title: Text(title)), body: body),
    ));
  }

  void _move(int delta) {
    if (section != Section.inbox || inbox.items.isEmpty) return;
    final i = inbox.items.indexWhere((c) => c.id == conversation?.id);
    final n = (i + delta).clamp(0, inbox.items.length - 1);
    openConversation(inbox.items[n].id);
  }

  Map<ShortcutActivator, VoidCallback> get _shortcuts => {
        const SingleActivator(LogicalKeyboardKey.digit1, control: true): () => setState(() => section = Section.inbox),
        const SingleActivator(LogicalKeyboardKey.digit2, control: true): () => setState(() => section = Section.tickets),
        const SingleActivator(LogicalKeyboardKey.digit3, control: true): () => setState(() => section = Section.alerts),
        const SingleActivator(LogicalKeyboardKey.keyK, control: true): () => searchFocus.requestFocus(),
        const SingleActivator(LogicalKeyboardKey.keyR, control: true): _refreshAll,
        const SingleActivator(LogicalKeyboardKey.arrowDown, alt: true): () => _move(1),
        const SingleActivator(LogicalKeyboardKey.arrowUp, alt: true): () => _move(-1),
        const SingleActivator(LogicalKeyboardKey.keyN, control: true, shift: true): () => conversation?.setMode(ComposerMode.note),
        const SingleActivator(LogicalKeyboardKey.keyE, control: true): () => composerFocus.requestFocus(),
      };

  Widget _list() => switch (section) {
        Section.inbox => InboxView(
            controller: inbox,
            queues: me.queues,
            selectedId: conversation?.id,
            searchFocus: searchFocus,
            onOpen: (c) => openConversation(c.id)),
        Section.tickets => me.can('helpdesk')
            ? TicketListView(controller: tickets, selectedId: ticket?.id, onOpen: (t) => openTicket(t.id))
            : const EmptyState(Icons.confirmation_number_outlined, 'Helpdesk is not installed on this site.'),
        Section.alerts => AlertsView(
            controller: alerts,
            onOpen: (a) {
              alerts.acknowledge([a.id]);
              openLink(a.referenceDoctype!, a.referenceName!);
            }),
      };

  Widget _detail(bool extraWide) {
    if (section == Section.tickets && ticket != null) {
      return TicketView(
          key: ValueKey('t-${ticket!.id}'), controller: ticket!, me: me.user, onOpenConversation: openConversation, composerFocus: composerFocus);
    }
    if (conversation != null && section != Section.tickets) {
      return ConversationView(
          key: ValueKey('c-${conversation!.id}'),
          controller: conversation!,
          me: me.user,
          onOpenTicket: openTicket,
          onOpenConversation: openConversation,
          showDetailsPanel: extraWide,
          composerFocus: composerFocus);
    }
    return const EmptyState(Icons.forum_outlined, 'Select a conversation or ticket.');
  }

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final wide = width >= wideBreakpoint;
    final destinations = [
      (Section.inbox, Icons.inbox_outlined, Icons.inbox, 'Inbox'),
      (Section.tickets, Icons.confirmation_number_outlined, Icons.confirmation_number, 'Tickets'),
      (Section.alerts, Icons.notifications_none, Icons.notifications, 'Alerts'),
    ];
    return CallbackShortcuts(
      bindings: _shortcuts,
      child: FocusTraversalGroup(
        child: ListenableBuilder(
          listenable: Listenable.merge([inbox, alerts]),
          builder: (context, _) {
            Widget badge(Section s, Widget icon) {
              final n = s == Section.inbox ? inbox.unreadTotal : (s == Section.alerts ? alerts.items.length : 0);
              return n == 0 ? icon : Badge(label: Text('$n'), child: icon);
            }

            final account = _AccountButton(session: widget.session);
            if (!wide) {
              return Scaffold(
                appBar: AppBar(title: Text(destinations[section.index].$4), actions: [account]),
                body: Column(children: [if (inbox.offline) const _OfflineBanner(), Expanded(child: _list())]),
                bottomNavigationBar: NavigationBar(
                  selectedIndex: section.index,
                  onDestinationSelected: (i) => setState(() => section = Section.values[i]),
                  destinations: [
                    for (final d in destinations)
                      NavigationDestination(icon: badge(d.$1, Icon(d.$2)), selectedIcon: badge(d.$1, Icon(d.$3)), label: d.$4),
                  ],
                ),
              );
            }
            return Scaffold(
              body: Column(children: [
                if (inbox.offline) const _OfflineBanner(),
                Expanded(child: Row(children: [
                NavigationRail(
                  selectedIndex: section.index,
                  onDestinationSelected: (i) => setState(() => section = Section.values[i]),
                  labelType: NavigationRailLabelType.all,
                  leading: Padding(
                    padding: const EdgeInsets.only(bottom: 8),
                    child: Tooltip(message: me.siteUrl, child: const Icon(Icons.support_agent, size: 32)),
                  ),
                  trailing: Expanded(child: Align(alignment: Alignment.bottomCenter, child: Padding(padding: const EdgeInsets.all(8), child: account))),
                  destinations: [
                    for (final d in destinations)
                      NavigationRailDestination(icon: badge(d.$1, Icon(d.$2)), selectedIcon: badge(d.$1, Icon(d.$3)), label: Text(d.$4)),
                  ],
                ),
                const VerticalDivider(width: 1),
                SizedBox(width: listWidth, child: _list()),
                _Splitter(onDrag: (dx) => setState(() => listWidth = (listWidth + dx).clamp(280.0, (width * .45).clamp(300.0, 640.0)))),
                Expanded(child: _detail(width >= extraWideBreakpoint)),
                ])),
              ]),
            );
          },
        ),
      ),
    );
  }
}

class _Splitter extends StatelessWidget {
  final ValueChanged<double> onDrag;
  const _Splitter({required this.onDrag});
  @override
  Widget build(BuildContext context) => Semantics(
        label: 'Resize list',
        child: MouseRegion(
          cursor: SystemMouseCursors.resizeColumn,
          child: GestureDetector(
            behavior: HitTestBehavior.translucent,
            onHorizontalDragUpdate: (d) => onDrag(d.delta.dx),
            child: Container(width: 6, color: Theme.of(context).dividerColor.withValues(alpha: .3)),
          ),
        ),
      );
}

class _AccountButton extends StatelessWidget {
  final Session session;
  const _AccountButton({required this.session});
  @override
  Widget build(BuildContext context) {
    final me = session.me!;
    return PopupMenuButton<String>(
      tooltip: 'Account',
      icon: CircleAvatar(radius: 16, child: Text(me.fullName.isEmpty ? '?' : me.fullName[0].toUpperCase())),
      onSelected: (v) async {
        if (v == 'signout') {
          final token = AppServices.pushToken();
          await session.signOut(pushToken: token); // server stops push to this device first
          await AppServices.stopPush?.call();
          await clearDownloadedFiles();
        }
      },
      itemBuilder: (_) => [
        PopupMenuItem(
          enabled: false,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(me.fullName, style: const TextStyle(fontWeight: FontWeight.w600)),
            Text(me.email),
            Text(me.siteUrl, style: Theme.of(context).textTheme.bodySmall),
            Text('Signed in${me.isManager ? ' · Manager' : ''}', style: Theme.of(context).textTheme.bodySmall),
          ]),
        ),
        const PopupMenuDivider(),
        const PopupMenuItem(value: 'signout', child: Text('Sign out')),
      ],
    );
  }
}

class _OfflineBanner extends StatelessWidget {
  const _OfflineBanner();
  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    return Semantics(
      liveRegion: true,
      child: Container(
        key: const Key('offline'),
        width: double.infinity,
        color: c.tertiaryContainer,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        child: Text('Offline: reconnecting… Messages you send now will fail and stay in the composer to retry.',
            style: TextStyle(color: c.onTertiaryContainer)),
      ),
    );
  }
}
