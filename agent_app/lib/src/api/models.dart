// Typed contracts for the staff API v1 (docs/agent-api.md). Parsing is lenient: unknown fields are ignored,
// missing optional fields become null, so a newer server does not break an older app.

DateTime? _dt(Object? v) => v is String && v.isNotEmpty ? DateTime.tryParse(v) : null;
String _s(Object? v) => v == null ? '' : v.toString();
bool _b(Object? v) => v == true || v == 1 || v == '1';
int _i(Object? v) => v is int ? v : int.tryParse(_s(v)) ?? 0;
Map<String, dynamic> _m(Object? v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
List<dynamic> _l(Object? v) => v is List ? v : const [];

class Person {
  final String user;
  final String name;
  const Person(this.user, this.name);
  static Person? fromJson(Object? j) {
    if (j is! Map) return null;
    final user = _s(j['user']);
    return user.isEmpty ? null : Person(user, _s(j['name']).isEmpty ? user : _s(j['name']));
  }
}

class Page<T> {
  final List<T> items;
  final String? nextCursor;
  const Page(this.items, this.nextCursor);
}

class Bootstrap {
  final int apiVersion;
  final String siteUrl;
  final String siteName;
  final String serverAppVersion;
  final String user;
  final String fullName;
  final String email;
  final bool isManager;
  final bool helpdeskAgent;
  final Map<String, dynamic> capabilities;
  final List<({String name, bool member})> queues;
  final int inboxPollSeconds;
  final int threadPollSeconds;
  final int alertsPollSeconds;

  const Bootstrap({
    required this.apiVersion,
    required this.siteUrl,
    required this.siteName,
    required this.serverAppVersion,
    required this.user,
    required this.fullName,
    required this.email,
    required this.isManager,
    required this.helpdeskAgent,
    required this.capabilities,
    required this.queues,
    required this.inboxPollSeconds,
    required this.threadPollSeconds,
    required this.alertsPollSeconds,
  });

  bool can(String capability) => _b(capabilities[capability]);

  factory Bootstrap.fromJson(Map<String, dynamic> j) {
    final site = _m(j['site']);
    final agent = _m(j['agent']);
    final poll = _m(j['poll']);
    return Bootstrap(
      apiVersion: _i(j['api_version']),
      siteUrl: _s(site['url']),
      siteName: _s(site['name']),
      serverAppVersion: _s(site['app_version']),
      user: _s(agent['user']),
      fullName: _s(agent['full_name']),
      email: _s(agent['email']),
      isManager: _b(agent['is_manager']),
      helpdeskAgent: _b(agent['helpdesk_agent']),
      capabilities: _m(j['capabilities']),
      queues: [for (final q in _l(j['queues'])) (name: _s(_m(q)['name']), member: _b(_m(q)['member']))],
      inboxPollSeconds: _i(poll['inbox_seconds']).clamp(2, 300),
      threadPollSeconds: _i(poll['thread_seconds']).clamp(2, 300),
      alertsPollSeconds: _i(poll['alerts_seconds']).clamp(2, 300),
    );
  }
}

class ConversationActions {
  final bool claim, transfer, reply, note, close, takeOver, returnToAssistant;
  final bool? whatsappWindowOpen;
  const ConversationActions({
    this.claim = false,
    this.transfer = false,
    this.reply = false,
    this.note = true,
    this.close = false,
    this.takeOver = false,
    this.returnToAssistant = false,
    this.whatsappWindowOpen,
  });
  factory ConversationActions.fromJson(Map<String, dynamic> j) => ConversationActions(
        claim: _b(j['claim']),
        transfer: _b(j['transfer']),
        reply: _b(j['reply']),
        note: j['note'] == null ? true : _b(j['note']),
        close: _b(j['close']),
        takeOver: _b(j['take_over']),
        returnToAssistant: _b(j['return_to_assistant']),
        whatsappWindowOpen: j['whatsapp_window_open'] == null ? null : _b(j['whatsapp_window_open']),
      );
}

class ConversationSummary {
  final String id;
  final String subject;
  final String displayName;
  final String channel; // Portal | Live Chat | WhatsApp
  final String status; // Open | Waiting | Closed
  final String? handling; // Bot | Queued | Agent
  final String? queue;
  final Person? assignee;
  final String? ticket;
  final DateTime? lastActivityAt;
  final int unread;
  final String preview;
  final bool? whatsappWindowOpen;
  // detail only
  final ConversationActions actions;
  final String? contactName, contactEmail, contactPhone, customerName, handoffReason;

  const ConversationSummary({
    required this.id,
    required this.subject,
    required this.displayName,
    required this.channel,
    required this.status,
    this.handling,
    this.queue,
    this.assignee,
    this.ticket,
    this.lastActivityAt,
    this.unread = 0,
    this.preview = '',
    this.whatsappWindowOpen,
    this.actions = const ConversationActions(),
    this.contactName,
    this.contactEmail,
    this.contactPhone,
    this.customerName,
    this.handoffReason,
  });

  bool get isClosed => status == 'Closed';

  factory ConversationSummary.fromJson(Map<String, dynamic> j) {
    final contact = _m(j['contact']);
    String? n(Object? v) => v == null || _s(v).isEmpty ? null : _s(v);
    return ConversationSummary(
      id: _s(j['id']),
      subject: _s(j['subject']),
      displayName: _s(j['display_name']).isEmpty ? _s(j['subject']) : _s(j['display_name']),
      channel: _s(j['channel']).isEmpty ? 'Portal' : _s(j['channel']),
      status: _s(j['status']),
      handling: n(j['handling']),
      queue: n(j['queue']),
      assignee: Person.fromJson(j['assignee']),
      ticket: n(j['ticket']),
      lastActivityAt: _dt(j['last_activity_at']),
      unread: _i(j['unread']),
      preview: _s(j['preview']),
      whatsappWindowOpen: j['whatsapp_window_open'] == null ? null : _b(j['whatsapp_window_open']),
      actions: ConversationActions.fromJson(_m(j['actions'])),
      contactName: n(contact['name']),
      contactEmail: n(contact['email']),
      contactPhone: n(contact['phone']),
      customerName: n(j['customer_name']),
      handoffReason: n(j['handoff_reason']),
    );
  }
}

enum MessageDirection { inbound, outbound, internal }

class ChatMessage {
  final String id;
  final MessageDirection direction;
  final bool internal;
  final String senderType;
  final String author;
  final String html;
  final DateTime? createdAt;
  final String? deliveryStatus;
  final String? deliveryError;
  final String? clientRequestId;

  const ChatMessage({
    required this.id,
    required this.direction,
    required this.internal,
    required this.senderType,
    required this.author,
    required this.html,
    this.createdAt,
    this.deliveryStatus,
    this.deliveryError,
    this.clientRequestId,
  });

  String get text => htmlToText(html);

  factory ChatMessage.fromJson(Map<String, dynamic> j) {
    final d = _s(j['direction']);
    final delivery = _m(j['delivery']);
    return ChatMessage(
      id: _s(j['id']),
      direction: d == 'inbound'
          ? MessageDirection.inbound
          : d == 'internal'
              ? MessageDirection.internal
              : MessageDirection.outbound,
      internal: _b(j['internal']),
      senderType: _s(j['sender_type']),
      author: _s(j['author']),
      html: _s(j['html']),
      createdAt: _dt(j['created_at']),
      deliveryStatus: delivery['status'] == null ? null : _s(delivery['status']),
      deliveryError: delivery['error'] == null ? null : _s(delivery['error']),
      clientRequestId: j['client_request_id'] == null ? null : _s(j['client_request_id']),
    );
  }
}

class MessagePage {
  final List<ChatMessage> items;
  final String? beforeCursor;
  final bool hasMoreBefore;
  final String? latestCursor;
  const MessagePage(this.items, this.beforeCursor, this.hasMoreBefore, this.latestCursor);
  factory MessagePage.fromJson(Map<String, dynamic> j) => MessagePage(
        [for (final m in _l(j['items'])) ChatMessage.fromJson(_m(m))],
        j['before_cursor'] as String?,
        _b(j['has_more_before']),
        j['latest_cursor'] as String?,
      );
}

class TicketStatus {
  final String name, label;
  final String? category;
  const TicketStatus(this.name, this.label, this.category);
}

class Ticket {
  final String id;
  final String subject;
  final String status;
  final String? statusCategory;
  final String? priority;
  final String? raisedBy;
  final String? customer;
  final String? team;
  final List<Person> assignees;
  final DateTime? responseBy, resolutionBy, createdAt;
  final String? slaStatus;
  final String modified;
  final bool unread;
  // detail only
  final String description;
  final String? linkedConversation;
  final bool canWrite;
  final List<TicketStatus> statuses;
  final List<String> priorities;

  const Ticket({
    required this.id,
    required this.subject,
    required this.status,
    this.statusCategory,
    this.priority,
    this.raisedBy,
    this.customer,
    this.team,
    this.assignees = const [],
    this.responseBy,
    this.resolutionBy,
    this.createdAt,
    this.slaStatus,
    this.modified = '',
    this.unread = false,
    this.description = '',
    this.linkedConversation,
    this.canWrite = false,
    this.statuses = const [],
    this.priorities = const [],
  });

  factory Ticket.fromJson(Map<String, dynamic> j) {
    final sla = _m(j['sla']);
    String? n(Object? v) => v == null || _s(v).isEmpty ? null : _s(v);
    return Ticket(
      id: _s(j['id']),
      subject: _s(j['subject']),
      status: _s(j['status']),
      statusCategory: n(j['status_category']),
      priority: n(j['priority']),
      raisedBy: n(j['raised_by']),
      customer: n(j['customer']),
      team: n(j['team']),
      assignees: [for (final a in _l(j['assignees'])) if (Person.fromJson(a) != null) Person.fromJson(a)!],
      responseBy: _dt(sla['response_by']),
      resolutionBy: _dt(sla['resolution_by']),
      createdAt: _dt(j['created_at']),
      slaStatus: n(sla['status']),
      modified: _s(j['modified']),
      unread: _b(j['unread']),
      description: _s(j['description']),
      linkedConversation: n(j['linked_conversation']),
      canWrite: _b(j['can_write']),
      statuses: [
        for (final s in _l(j['statuses']))
          TicketStatus(_s(_m(s)['name']), _s(_m(s)['label']).isEmpty ? _s(_m(s)['name']) : _s(_m(s)['label']),
              n(_m(s)['category'])),
      ],
      priorities: [for (final p in _l(j['priorities'])) _s(p)],
    );
  }
}

class TimelineItem {
  final String id;
  final String kind; // email | note
  final bool internal;
  final MessageDirection direction;
  final String author;
  final String html;
  final DateTime? createdAt;
  const TimelineItem(this.id, this.kind, this.internal, this.direction, this.author, this.html, this.createdAt);
  String get text => htmlToText(html);
  factory TimelineItem.fromJson(Map<String, dynamic> j) {
    final d = _s(j['direction']);
    return TimelineItem(
      _s(j['id']),
      _s(j['kind']),
      _b(j['internal']),
      d == 'inbound'
          ? MessageDirection.inbound
          : d == 'internal'
              ? MessageDirection.internal
              : MessageDirection.outbound,
      _s(j['author']),
      _s(j['html']),
      _dt(j['created_at']),
    );
  }
}

class AgentAlert {
  final String id, kind, title, body;
  final String? referenceDoctype, referenceName, priority;
  final DateTime? alertedOn;
  const AgentAlert(this.id, this.kind, this.title, this.body, this.referenceDoctype, this.referenceName, this.priority,
      this.alertedOn);
  factory AgentAlert.fromJson(Map<String, dynamic> j) => AgentAlert(
        _s(j['id']),
        _s(j['kind']),
        _s(j['title']),
        htmlToText(_s(j['body'])),
        j['reference_doctype'] as String?,
        j['reference_name'] as String?,
        j['priority'] as String?,
        _dt(j['alerted_on']),
      );
}

/// Plain text for display. Message bodies are rendered as text (never as live HTML) in the app.
String htmlToText(String html) {
  var s = html
      .replaceAll(RegExp(r'<br\s*/?>', caseSensitive: false), '\n')
      .replaceAll(RegExp(r'</(p|div|li|h[1-6])>', caseSensitive: false), '\n')
      .replaceAll(RegExp(r'<li[^>]*>', caseSensitive: false), '• ')
      .replaceAll(RegExp(r'<[^>]+>'), '');
  const entities = {'&nbsp;': ' ', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'", '&#x27;': "'", '&amp;': '&'};
  entities.forEach((k, v) => s = s.replaceAll(k, v));
  return s.replaceAll(RegExp(r'\n{3,}'), '\n\n').trim();
}
