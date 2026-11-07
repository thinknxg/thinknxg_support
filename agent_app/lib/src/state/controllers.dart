import 'dart:async';

import 'package:flutter/foundation.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../alerts/alert_center.dart';
import '../api/staff_api.dart';

/// Called with errors no screen can fix itself (session expired): the shell shows the sign-in prompt.
typedef ExpiredHandler = void Function();

mixin _Polling on ChangeNotifier {
  Timer? _timer;
  bool _disposed = false;

  void startPolling(Duration every, Future<void> Function() tick) {
    _timer?.cancel();
    _timer = Timer.periodic(every, (_) {
      if (!_disposed) tick();
    });
  }

  void stopPolling() => _timer?.cancel();

  void safeNotify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _timer?.cancel();
    super.dispose();
  }
}

class InboxFilter {
  final String view; // all | mine | unassigned | waiting
  final String? channel; // Portal | Live Chat | WhatsApp
  final String status; // open | closed | all
  final String? queue;
  final String q;
  const InboxFilter({this.view = 'all', this.channel, this.status = 'open', this.queue, this.q = ''});
  InboxFilter copyWith({String? view, String? channel, bool clearChannel = false, String? status, String? queue,
          bool clearQueue = false, String? q}) =>
      InboxFilter(
        view: view ?? this.view,
        channel: clearChannel ? null : (channel ?? this.channel),
        status: status ?? this.status,
        queue: clearQueue ? null : (queue ?? this.queue),
        q: q ?? this.q,
      );
}

/// The conversation list: filters, cursor pagination, polling the first page.
class InboxController extends ChangeNotifier with _Polling {
  final StaffApi api;
  final ExpiredHandler onExpired;
  InboxFilter filter = const InboxFilter();
  List<ConversationSummary> items = [];
  String? nextCursor;
  bool loading = false;
  bool loadingMore = false;
  String? error;
  int _generation = 0;
  bool offline = false;
  VoidCallback? onReconnect;

  InboxController(this.api, {required this.onExpired});

  int get unreadTotal => items.fold(0, (a, c) => a + (c.unread > 0 ? 1 : 0));

  Future<void> setFilter(InboxFilter f) {
    filter = f;
    items = [];
    nextCursor = null;
    return refresh();
  }

  /// Reloads the first page and merges it in (keeps pages already loaded below it).
  Future<void> refresh() async {
    final gen = ++_generation;
    loading = items.isEmpty;
    safeNotify();
    try {
      final page = await _fetch(null);
      if (gen != _generation) return;
      final fresh = {for (final c in page.items) c.id};
      if (offline) {
        offline = false;
        onReconnect?.call(); // back online: refresh everything that may have changed meanwhile
      }
      if (items.length > page.items.length) {
        // more pages were loaded: keep them under the refreshed first page
        items = [...page.items, ...items.skip(page.items.length).where((c) => !fresh.contains(c.id))];
      } else {
        items = page.items;
        nextCursor = page.nextCursor;
      }
      error = null;
    } on SessionExpired {
      onExpired();
    } on NetworkError {
      offline = true;
      error = null; // the workspace shows one offline banner instead
    } on ApiException catch (e) {
      error = e.message;
    } finally {
      if (gen == _generation) {
        loading = false;
        safeNotify();
      }
    }
  }

  Future<void> loadMore() async {
    if (nextCursor == null || loadingMore) return;
    loadingMore = true;
    safeNotify();
    try {
      final page = await _fetch(nextCursor);
      final have = {for (final c in items) c.id};
      items = [...items, ...page.items.where((c) => !have.contains(c.id))];
      nextCursor = page.nextCursor;
    } on SessionExpired {
      onExpired();
    } on ApiException catch (e) {
      error = e.message;
    } finally {
      loadingMore = false;
      safeNotify();
    }
  }

  Future<Page<ConversationSummary>> _fetch(String? cursor) => api.conversations(
        view: filter.view,
        channel: filter.channel,
        status: filter.status,
        queue: filter.queue,
        q: filter.q.trim().isEmpty ? null : filter.q.trim(),
        cursor: cursor,
      );

  /// Reflect a change made in the open conversation right away (claim, read, close).
  void upsert(ConversationSummary c) {
    final i = items.indexWhere((x) => x.id == c.id);
    if (i >= 0) {
      items = [...items]..[i] = c;
      safeNotify();
    }
  }
}

enum ComposerMode { reply, note }

enum SendState { idle, sending, sent, failed }

/// The composer's draft. A failed send keeps the text and its request id, so "Retry" can never send twice.
class Draft {
  String text = '';
  ComposerMode mode = ComposerMode.reply;
  String? requestId;
  SendState state = SendState.idle;
  String? error;
  List<Map<String, dynamic>> serverActions = const [];
  String? notice;
  UploadFile? file;
}

/// One open conversation: detail, timeline (paged back, polled forward), read acknowledgement, actions, composer.
class ConversationController extends ChangeNotifier with _Polling {
  final StaffApi api;
  final String id;
  final ExpiredHandler onExpired;
  final void Function(ConversationSummary)? onChanged;
  final String Function() requestIdFactory;

  ConversationSummary? detail;
  List<ChatMessage> messages = [];
  String? beforeCursor;
  bool hasMoreBefore = false;
  String? latestCursor;
  bool loading = true;
  String? error;
  String? actionError;
  bool busy = false;
  final Draft draft = Draft();
  String? _readUpTo;
  int _ticks = 0;

  ConversationController(this.api, this.id, {required this.onExpired, this.onChanged, String Function()? requestIdFactory})
      : requestIdFactory = requestIdFactory ?? newRequestId;

  Future<void> load() async {
    loading = true;
    safeNotify();
    try {
      final results = await Future.wait([api.conversation(id), api.messages(id)]);
      detail = results[0] as ConversationSummary;
      final page = results[1] as MessagePage;
      messages = page.items;
      beforeCursor = page.beforeCursor;
      hasMoreBefore = page.hasMoreBefore;
      latestCursor = page.latestCursor;
      error = null;
      await _acknowledge();
    } on SessionExpired {
      onExpired();
    } on ApiException catch (e) {
      error = e.message;
    } finally {
      loading = false;
      safeNotify();
    }
  }

  Future<void> loadEarlier() async {
    if (!hasMoreBefore || beforeCursor == null) return;
    try {
      final page = await api.messages(id, before: beforeCursor);
      final have = {for (final m in messages) m.id};
      messages = [...page.items.where((m) => !have.contains(m.id)), ...messages];
      beforeCursor = page.beforeCursor;
      hasMoreBefore = page.hasMoreBefore;
      safeNotify();
    } on SessionExpired {
      onExpired();
    } on ApiException catch (e) {
      actionError = e.message;
      safeNotify();
    }
  }

  /// Polling tick: new messages since the latest one, and the detail every few ticks.
  Future<void> poll() async {
    try {
      final page = await api.messages(id, after: latestCursor);
      if (page.items.isNotEmpty) {
        _merge(page.items);
        latestCursor = page.latestCursor ?? latestCursor;
        await _acknowledge();
        safeNotify();
      }
      if (++_ticks % 3 == 0 || page.items.isNotEmpty) {
        detail = await api.conversation(id);
        safeNotify();
      }
      if (detail != null && !detail!.isClosed && detail!.channel != 'WhatsApp') {
        final l = await api.live(id);
        if (l.customerTyping != live.customerTyping || l.visitorOnline != live.visitorOnline || l.aiDrafting != live.aiDrafting) {
          live = l;
          safeNotify();
        }
      }
    } on SessionExpired {
      onExpired();
    } on ApiException {
      // keep showing what we have; the next tick tries again
    }
  }

  void _merge(List<ChatMessage> incoming) {
    final byId = {for (final m in messages) m.id: m};
    for (final m in incoming) {
      byId[m.id] = m;
    }
    messages = byId.values.toList()
      ..sort((a, b) => (a.createdAt ?? DateTime(0)).compareTo(b.createdAt ?? DateTime(0)));
  }

  Future<void> _acknowledge() async {
    if (messages.isEmpty) return;
    final last = messages.last.id;
    if (last == _readUpTo) return;
    try {
      await api.markRead(id, last);
      _readUpTo = last;
      if (detail != null && detail!.unread > 0) {
        detail = detail!.withUnread(0);
        onChanged?.call(detail!);
      }
    } on ApiException {
      // read state is retried on the next tick
    }
  }

  Future<bool> _act(Future<ConversationSummary> Function() fn) async {
    busy = true;
    actionError = null;
    safeNotify();
    try {
      detail = await fn();
      onChanged?.call(detail!);
      return true;
    } on SessionExpired {
      onExpired();
    } on ConflictError catch (e) {
      actionError = e.message;
      if (e.current.isNotEmpty) detail = ConversationSummary.fromJson(e.current);
    } on ApiException catch (e) {
      actionError = e.message;
    } finally {
      busy = false;
      safeNotify();
    }
    return false;
  }

  Future<bool> claim() => _act(() => api.claim(id));
  Future<bool> takeOver() => _act(() => api.takeOver(id));
  Future<bool> returnToAssistant() => _act(() => api.returnToAssistant(id));
  Future<bool> transfer({String? user, String? queue}) =>
      _act(() => api.transfer(id, user: user, queue: queue, expectedAssignee: detail?.assignee?.user ?? ''));
  Future<bool> close({String? reason, String? notes, Map<String, Object?>? answers, bool sendClosingMessage = true}) => _act(() =>
      api.close(id, reason: reason, notes: notes, answers: answers, sendClosingMessage: sendClosingMessage, expectedStatus: detail?.status));

  void setMode(ComposerMode m) {
    if (draft.mode == m) return;
    draft.mode = m;
    draft.requestId = null;
    draft.state = SendState.idle;
    draft.error = null;
    safeNotify();
  }

  void setText(String t) {
    draft.text = t;
    if (draft.state == SendState.sent) draft.state = SendState.idle;
    final now = DateTime.now();
    if (t.isNotEmpty && draft.mode == ComposerMode.reply && now.difference(_lastTyping) > const Duration(seconds: 3)) {
      _lastTyping = now;
      api.typing(id).catchError((_) {}); // best effort: shows "agent is typing" to the customer
    }
  }

  DateTime _lastTyping = DateTime(2000);
  LiveState live = const LiveState();
  CustomerHistory? history;
  bool historyLoading = false;

  void attach(UploadFile? f) {
    draft.file = f;
    if (draft.state == SendState.sent) draft.state = SendState.idle;
    safeNotify();
  }

  Future<void> loadHistory() async {
    if (historyLoading) return;
    historyLoading = true;
    safeNotify();
    try {
      history = await api.customerHistory(id);
    } on SessionExpired {
      onExpired();
    } on ApiException catch (e) {
      actionError = e.message;
    } finally {
      historyLoading = false;
      safeNotify();
    }
  }

  Future<TransferTargets?> transferTargets() async {
    try {
      return await api.transferTargets(id);
    } on SessionExpired {
      onExpired();
    } on ApiException catch (e) {
      actionError = e.message;
      safeNotify();
    }
    return null;
  }

  Future<bool> linkCustomer(String customer, {String? contact, bool createContact = false}) =>
      _act(() => api.linkCustomer(id, customer, contact: contact, createContact: createContact));

  /// Create a Helpdesk ticket from this chat; returns its id (null on error, shown in [actionError]).
  Future<String?> createTicket({String? subject, String? priority, String? team, String? ticketType, String? reply}) async {
    busy = true;
    actionError = null;
    safeNotify();
    final rid = requestIdFactory();
    try {
      final t = await api.createTicket(id,
          clientRequestId: rid, subject: subject, priority: priority, team: team, ticketType: ticketType, reply: reply);
      detail = await api.conversation(id);
      onChanged?.call(detail!);
      return t;
    } on SessionExpired {
      onExpired();
    } on ApiException catch (e) {
      actionError = e.message;
    } finally {
      busy = false;
      safeNotify();
    }
    return null;
  }

  /// Insert a canned response (placeholders filled by the server) at the end of the draft.
  Future<void> insertCanned(CannedResponse c) async {
    try {
      final text = await api.cannedRender(c.id, id);
      draft.text = draft.text.trim().isEmpty ? text : '${draft.text.trimRight()}\n$text';
      if (draft.state == SendState.sent) draft.state = SendState.idle;
      safeNotify();
    } on SessionExpired {
      onExpired();
    } on ApiException catch (e) {
      actionError = e.message;
      safeNotify();
    }
  }

  /// Send (or retry) the draft. Online only: failures keep the draft for a manual retry.
  Future<void> send() async {
    final text = draft.text.trim();
    if ((text.isEmpty && draft.file == null) || draft.state == SendState.sending) return;
    draft.requestId ??= requestIdFactory();
    draft.state = SendState.sending;
    draft.error = null;
    draft.notice = null;
    draft.serverActions = const [];
    safeNotify();
    try {
      final r = await api.reply(id, text,
          clientRequestId: draft.requestId!, internal: draft.mode == ComposerMode.note, file: draft.file);
      _merge([r.message]);
      if (r.duplicate && r.message.text.trim() != text) {
        draft.notice = 'Your earlier message had already been sent. Edit and send again if you need to add more.';
        draft.requestId = null;
        draft.state = SendState.failed;
      } else {
        draft.text = '';
        draft.file = null;
        draft.requestId = null;
        draft.state = SendState.sent;
      }
      await _acknowledge();
    } on SessionExpired {
      draft.state = SendState.failed;
      draft.error = 'Your session has expired. Sign in again, then retry; your message is kept.';
      onExpired();
    } on ActionRequired catch (e) {
      draft.state = SendState.failed;
      draft.error = e.message;
      draft.serverActions = e.actions;
      draft.requestId = null;
    } on NetworkError catch (e) {
      draft.state = SendState.failed;
      draft.error = e.message; // keep requestId: the first attempt may have arrived
    } on ApiException catch (e) {
      draft.state = SendState.failed;
      draft.error = e.message;
    }
    safeNotify();
  }
}

/// Helpdesk tickets list.
class TicketsController extends ChangeNotifier with _Polling {
  final StaffApi api;
  final ExpiredHandler onExpired;
  String view = 'mine';
  String status = 'open';
  String q = '';
  List<Ticket> items = [];
  String? nextCursor;
  bool loading = false;
  String? error;
  int _gen = 0;

  TicketsController(this.api, {required this.onExpired});

  Future<void> setView({String? view, String? status, String? q}) {
    this.view = view ?? this.view;
    this.status = status ?? this.status;
    this.q = q ?? this.q;
    items = [];
    nextCursor = null;
    return refresh();
  }

  Future<void> refresh() async {
    final gen = ++_gen;
    loading = items.isEmpty;
    safeNotify();
    try {
      final p = await api.tickets(view: view, status: status, q: q.trim().isEmpty ? null : q.trim());
      if (gen != _gen) return;
      items = p.items;
      nextCursor = p.nextCursor;
      error = null;
    } on SessionExpired {
      onExpired();
    } on ApiException catch (e) {
      error = e.message;
    } finally {
      if (gen == _gen) {
        loading = false;
        safeNotify();
      }
    }
  }

  Future<void> loadMore() async {
    if (nextCursor == null) return;
    try {
      final p = await api.tickets(view: view, status: status, q: q.trim().isEmpty ? null : q.trim(), cursor: nextCursor);
      final have = {for (final t in items) t.id};
      items = [...items, ...p.items.where((t) => !have.contains(t.id))];
      nextCursor = p.nextCursor;
      safeNotify();
    } on SessionExpired {
      onExpired();
    } on ApiException catch (e) {
      error = e.message;
      safeNotify();
    }
  }
}

/// One Helpdesk ticket: detail, timeline, reply / internal note (idempotent), status, priority, owner.
class TicketController extends ChangeNotifier with _Polling {
  final StaffApi api;
  final String id;
  final ExpiredHandler onExpired;
  final String Function() requestIdFactory;
  Ticket? ticket;
  List<TimelineItem> timeline = [];
  bool loading = true;
  bool busy = false;
  String? error;
  String? actionError;
  final Draft draft = Draft();

  TicketController(this.api, this.id, {required this.onExpired, String Function()? requestIdFactory})
      : requestIdFactory = requestIdFactory ?? newRequestId;

  Future<void> load({bool quiet = false}) async {
    if (!quiet) {
      loading = true;
      safeNotify();
    }
    try {
      final r = await Future.wait([api.ticket(id), api.ticketTimeline(id)]);
      ticket = r[0] as Ticket;
      timeline = (r[1] as Page<TimelineItem>).items;
      error = null;
    } on SessionExpired {
      onExpired();
    } on ApiException catch (e) {
      error = e.message;
    } finally {
      loading = false;
      safeNotify();
    }
  }

  void setMode(ComposerMode m) {
    if (draft.mode == m) return;
    draft.mode = m;
    draft.requestId = null;
    draft.state = SendState.idle;
    draft.error = null;
    safeNotify();
  }

  void attach(UploadFile? f) {
    draft.file = f;
    safeNotify();
  }

  /// Insert a Helpdesk saved reply, rendered for this ticket by the server.
  Future<void> insertSavedReply(CannedResponse r) async {
    try {
      final text = await api.savedReplyRender(r.id, ticket: id);
      draft.text = draft.text.trim().isEmpty ? text : '${draft.text.trimRight()}\n$text';
      if (draft.state == SendState.sent) draft.state = SendState.idle;
      safeNotify();
    } on SessionExpired {
      onExpired();
    } on ApiException catch (e) {
      actionError = e.message;
      safeNotify();
    }
  }

  Future<void> send() async {
    final text = draft.text.trim();
    if (text.isEmpty || draft.state == SendState.sending) return;
    draft.requestId ??= requestIdFactory();
    draft.state = SendState.sending;
    draft.error = null;
    safeNotify();
    try {
      if (draft.mode == ComposerMode.reply) {
        await api.ticketReply(id, text, clientRequestId: draft.requestId!, file: draft.file);
      } else {
        await api.ticketNote(id, text, clientRequestId: draft.requestId!);
      }
      draft.text = '';
      draft.file = null;
      draft.requestId = null;
      draft.state = SendState.sent;
      await load(quiet: true);
    } on SessionExpired {
      draft.state = SendState.failed;
      draft.error = 'Your session has expired. Sign in again, then retry; your message is kept.';
      onExpired();
    } on NetworkError catch (e) {
      draft.state = SendState.failed;
      draft.error = e.message;
    } on ApiException catch (e) {
      draft.state = SendState.failed;
      draft.error = e.message;
    }
    safeNotify();
  }

  Future<bool> update({String? status, String? priority, String? team}) async {
    busy = true;
    actionError = null;
    safeNotify();
    try {
      final t = await api.ticketUpdate(id, status: status, priority: priority, team: team, expectedModified: ticket?.modified);
      await load(quiet: true);
      ticket ??= t;
      return true;
    } on SessionExpired {
      onExpired();
    } on ConflictError catch (e) {
      actionError = e.message;
      await load(quiet: true);
    } on ApiException catch (e) {
      actionError = e.message;
    } finally {
      busy = false;
      safeNotify();
    }
    return false;
  }

  Future<bool> assignToMe(String me) async {
    busy = true;
    actionError = null;
    safeNotify();
    try {
      await api.ticketAssign(id, agent: me, expectedAssignees: [for (final a in ticket?.assignees ?? <Person>[]) a.user]);
      await load(quiet: true);
      return true;
    } on SessionExpired {
      onExpired();
    } on ConflictError catch (e) {
      actionError = e.message;
      await load(quiet: true);
    } on ApiException catch (e) {
      actionError = e.message;
    } finally {
      busy = false;
      safeNotify();
    }
    return false;
  }
}

/// Server-backed alerts: acknowledging here clears them on the web console and other devices too.
class AlertsController extends ChangeNotifier with _Polling {
  final StaffApi api;
  final ExpiredHandler onExpired;
  final AlertCenter? center;
  List<AgentAlert> items = [];
  String? error;
  AlertsController(this.api, {required this.onExpired, this.center});

  /// Team rules and this agent's sound preferences.
  Future<void> loadConfig() async {
    if (center == null) return;
    try {
      center!.config = await api.alertConfig();
    } on ApiException {
      // keep the defaults; the next start tries again
    }
  }

  double? _cursor;

  Future<void> refresh() async {
    try {
      final f = await api.alertFeed(since: _cursor);
      final first = _cursor == null;
      _cursor = f.cursor ?? _cursor;
      items = f.items;
      error = null;
      await center?.update(items);
      if (!first) await center?.events(f.events);
    } on SessionExpired {
      onExpired();
    } on ApiException catch (e) {
      error = e.message;
    }
    safeNotify();
  }

  /// Play this PC's alert sound now, then ask the server for a real test alert (arrives on the next poll).
  Future<String> test() async {
    await center?.testSound();
    try {
      return await api.sendTestAlert();
    } on ApiException catch (e) {
      return e.message;
    }
  }

  Future<void> acknowledge(List<String> ids) async {
    try {
      center?.acknowledged(ids);
      final done = await api.acknowledgeAlerts(ids);
      items = items.where((a) => !done.contains(a.id)).toList();
      safeNotify();
    } on SessionExpired {
      onExpired();
    } on ApiException catch (e) {
      error = e.message;
      safeNotify();
    }
  }
}
