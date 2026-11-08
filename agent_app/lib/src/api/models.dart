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
  final AgentStatus? status;

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
    this.status,
  });

  bool can(String capability) => _b(capabilities[capability]);
  MessagingCaps get messaging => MessagingCaps.fromJson(capabilities['messaging']);

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
      status: AgentStatus.fromJson(agent['status']),
    );
  }
}

class ConversationActions {
  final bool claim, transfer, reply, note, close, takeOver, returnToAssistant, linkCustomer, createTicket;
  final bool? whatsappWindowOpen;
  const ConversationActions({
    this.claim = false,
    this.transfer = false,
    this.reply = false,
    this.note = true,
    this.close = false,
    this.takeOver = false,
    this.returnToAssistant = false,
    this.linkCustomer = false,
    this.createTicket = false,
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
        linkCustomer: j['link_customer'] == null ? true : _b(j['link_customer']),
        createTicket: _b(j['create_ticket']),
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
  // AI insight (1.10): from the customer's latest message
  final String? sentiment, urgency, intent, language, summary;
  // 1.14: set by people
  final String priority; // Low | Normal | High | Urgent
  final List<String> tags;
  final LeadRef? lead; // 1.14 increment 3, detail only

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
    this.sentiment,
    this.urgency,
    this.intent,
    this.language,
    this.summary,
    this.priority = 'Normal',
    this.tags = const [],
    this.lead,
  });

  bool get isClosed => status == 'Closed';
  bool get highPriority => priority == 'High' || priority == 'Urgent';
  bool get needsAttention => sentiment == 'Negative' || urgency == 'High';

  ConversationSummary withUnread(int n) => ConversationSummary(
        id: id,
        subject: subject,
        displayName: displayName,
        channel: channel,
        status: status,
        handling: handling,
        queue: queue,
        assignee: assignee,
        ticket: ticket,
        lastActivityAt: lastActivityAt,
        unread: n,
        preview: preview,
        whatsappWindowOpen: whatsappWindowOpen,
        actions: actions,
        contactName: contactName,
        contactEmail: contactEmail,
        contactPhone: contactPhone,
        customerName: customerName,
        handoffReason: handoffReason,
        sentiment: sentiment,
        urgency: urgency,
        intent: intent,
        language: language,
        summary: summary,
        priority: priority,
        tags: tags,
        lead: lead,
      );

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
      sentiment: n(j['sentiment'] ?? _m(j['insight'])['sentiment']),
      urgency: n(j['urgency'] ?? _m(j['insight'])['urgency']),
      intent: n(_m(j['insight'])['intent']),
      language: n(_m(j['insight'])['language']),
      summary: n(_m(j['insight'])['summary']),
      priority: n(j['priority']) ?? 'Normal',
      tags: [for (final t in _l(j['tags'])) '$t'],
      lead: j['lead'] is Map ? LeadRef.fromJson(_m(j['lead'])) : null,
    );
  }
}

/// 1.14: the lead created or linked from a chat (CRM Lead in thinkNXG CRM, or ERPNext Lead).
class LeadRef {
  final String doctype, name, title, url;
  final int? score;
  final String? reasons;
  const LeadRef(this.doctype, this.name, this.title, this.url, {this.score, this.reasons});
  factory LeadRef.fromJson(Map<String, dynamic> j) => LeadRef(_s(j['doctype']), _s(j['name']), _s(j['title']), _s(j['url']),
      score: j['score'] == null ? null : _i(j['score']), reasons: j['reasons'] == null ? null : _s(j['reasons']));
}

/// 1.14: an agent's status now. `status` is what routing uses (Offline off shift, Away when idle); `setStatus` is
/// what the agent chose.
class AgentStatus {
  final String status, setStatus;
  final String? reason, note;
  const AgentStatus(this.status, {String? setStatus, this.reason, this.note}) : setStatus = setStatus ?? status;
  static AgentStatus? fromJson(Object? raw) {
    if (raw is! Map) return null;
    final j = Map<String, dynamic>.from(raw);
    final s = _s(j['status']);
    if (s.isEmpty) return null;
    return AgentStatus(s,
        setStatus: _s(j['set_status']).isEmpty ? s : _s(j['set_status']),
        reason: j['reason'] == null ? null : _s(j['reason']),
        note: j['note'] == null ? null : _s(j['note']));
  }

  String get label => reason == null ? status : '$status ($reason)';
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
  final String? attachmentName;
  // 1.14
  final ReplyRef? replyTo;
  final bool edited;
  final bool removed;
  final String? removedBy;
  final List<Reaction> reactions;
  final String? attachmentKind; // image | audio | file
  final int? voiceSeconds;
  final bool canEdit;
  final bool canRemove;

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
    this.attachmentName,
    this.replyTo,
    this.edited = false,
    this.removed = false,
    this.removedBy,
    this.reactions = const [],
    this.attachmentKind,
    this.voiceSeconds,
    this.canEdit = false,
    this.canRemove = false,
  });

  String get text => htmlToText(html);
  bool get isVoice => attachmentKind == 'audio';
  bool get isImage => attachmentKind == 'image';

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
      attachmentName: j['attachment'] is Map ? _s((j['attachment'] as Map)['name']) : null,
      replyTo: j['reply_to'] is Map ? ReplyRef.fromJson(_m(j['reply_to'])) : null,
      edited: _b(j['edited']),
      removed: _b(j['removed']),
      removedBy: j['removed_by'] == null ? null : _s(j['removed_by']),
      reactions: [for (final r in _l(j['reactions'])) Reaction.fromJson(_m(r))],
      attachmentKind: j['attachment_kind'] == null ? null : _s(j['attachment_kind']),
      voiceSeconds: j['voice_seconds'] == null ? null : _i(j['voice_seconds']),
      canEdit: _b(j['can_edit']),
      canRemove: _b(j['can_remove']),
    );
  }
}

class ReplyRef {
  final String id, author, excerpt;
  const ReplyRef(this.id, this.author, this.excerpt);
  factory ReplyRef.fromJson(Map<String, dynamic> j) => ReplyRef(_s(j['id']), _s(j['author']), _s(j['excerpt']));
}

class Reaction {
  final String emoji;
  final int count;
  final bool mine;
  const Reaction(this.emoji, this.count, this.mine);
  factory Reaction.fromJson(Map<String, dynamic> j) => Reaction(_s(j['emoji']), _i(j['count']), _b(j['mine']));
}

/// 1.14: what the site allows (reactions, voice notes); empty on older servers, which hides those actions.
class MessagingCaps {
  final List<String> reactions;
  final bool voice;
  final int maxVoiceSeconds;
  final bool edit;
  const MessagingCaps({this.reactions = const [], this.voice = false, this.maxVoiceSeconds = 120, this.edit = false});
  factory MessagingCaps.fromJson(Object? raw) {
    final j = raw is Map ? Map<String, dynamic>.from(raw) : <String, dynamic>{};
    return MessagingCaps(
      reactions: [for (final r in _l(j['reactions'])) '$r'],
      voice: _b(j['voice']),
      maxVoiceSeconds: j['max_voice_seconds'] == null ? 120 : _i(j['max_voice_seconds']),
      edit: _b(j['edit']),
    );
  }
}

class MessagePage {
  final List<ChatMessage> items;
  final String? beforeCursor;
  final bool hasMoreBefore;
  final String? latestCursor;
  final List<ChatMessage> updated;
  final String? serverTime;
  const MessagePage(this.items, this.beforeCursor, this.hasMoreBefore, this.latestCursor,
      {this.updated = const [], this.serverTime});
  factory MessagePage.fromJson(Map<String, dynamic> j) => MessagePage(
        [for (final m in _l(j['items'])) ChatMessage.fromJson(_m(m))],
        j['before_cursor'] as String?,
        _b(j['has_more_before']),
        j['latest_cursor'] as String?,
        updated: [for (final m in _l(j['updated'])) ChatMessage.fromJson(_m(m))],
        serverTime: j['server_time'] as String?,
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
  final List<String> teams;
  final List<FileRef> attachments;

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
    this.teams = const [],
    this.attachments = const [],
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
      teams: [for (final t in _l(j['teams'])) _s(t)],
      attachments: [for (final f in _l(j['attachments'])) FileRef.fromJson(_m(f))],
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
  final List<FileRef> attachments;
  const TimelineItem(this.id, this.kind, this.internal, this.direction, this.author, this.html, this.createdAt,
      [this.attachments = const []]);
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
      [for (final f in _l(j['attachments'])) FileRef.fromJson(_m(f))],
    );
  }
}

class FileRef {
  final String id, name;
  final int size;
  const FileRef(this.id, this.name, this.size);
  factory FileRef.fromJson(Map<String, dynamic> j) => FileRef(_s(j['id']), _s(j['name']), _i(j['size']));
}

class TransferAgent {
  final String user, name;
  final bool online, inQueue;
  final int openChats;
  const TransferAgent(this.user, this.name, this.online, this.inQueue, this.openChats);
}

class TransferTargets {
  final List<TransferAgent> agents;
  final List<String> queues;
  final String? currentUser, currentQueue;
  const TransferTargets(this.agents, this.queues, this.currentUser, this.currentQueue);
  factory TransferTargets.fromJson(Map<String, dynamic> j) {
    final cur = _m(j['current']);
    return TransferTargets(
      [
        for (final a in _l(j['agents']))
          TransferAgent(_s(_m(a)['user']), _s(_m(a)['name']).isEmpty ? _s(_m(a)['user']) : _s(_m(a)['name']),
              _b(_m(a)['online']), _b(_m(a)['in_queue']), _i(_m(a)['open_chats'])),
      ],
      [for (final q in _l(j['queues'])) _s(q)],
      cur['user'] as String?,
      cur['queue'] as String?,
    );
  }
}

class CustomerHistory {
  final List<ConversationSummary> conversations;
  final List<Ticket> tickets;
  const CustomerHistory(this.conversations, this.tickets);
  factory CustomerHistory.fromJson(Map<String, dynamic> j) => CustomerHistory(
        [for (final c in _l(j['conversations'])) ConversationSummary.fromJson(_m(c))],
        [for (final t in _l(j['tickets'])) Ticket.fromJson(_m(t))],
      );
}

class LiveState {
  final bool customerTyping, visitorOnline, aiDrafting;
  const LiveState({this.customerTyping = false, this.visitorOnline = false, this.aiDrafting = false});
  factory LiveState.fromJson(Map<String, dynamic> j) =>
      LiveState(customerTyping: _b(j['customer_typing']), visitorOnline: _b(j['visitor_online']), aiDrafting: _b(j['ai_drafting']));
}

class CustomerOption {
  final String id, name;
  final String? email, phone;
  final bool suggested;
  const CustomerOption(this.id, this.name, this.email, this.phone, this.suggested);
  factory CustomerOption.fromJson(Map<String, dynamic> j) => CustomerOption(_s(j['name']),
      _s(j['customer_name']).isEmpty ? _s(j['name']) : _s(j['customer_name']), j['email_id'] as String?, j['mobile_no'] as String?,
      _b(j['suggested']));
}

class ContactOption {
  final String id, name;
  final String? email, phone;
  const ContactOption(this.id, this.name, this.email, this.phone);
  factory ContactOption.fromJson(Map<String, dynamic> j) =>
      ContactOption(_s(j['name']), _s(j['full_name']), j['email'] as String?, j['phone'] as String?);
}

class TicketOptions {
  final List<String> priorities, teams, ticketTypes;
  const TicketOptions(this.priorities, this.teams, this.ticketTypes);
  factory TicketOptions.fromJson(Map<String, dynamic> j) => TicketOptions([for (final x in _l(j['priorities'])) _s(x)],
      [for (final x in _l(j['teams'])) _s(x)], [for (final x in _l(j['ticket_types'])) _s(x)]);
}

class CannedResponse {
  final String id, title;
  final String? shortcut, category;
  final String preview;
  const CannedResponse(this.id, this.title, this.shortcut, this.category, this.preview);
  factory CannedResponse.fromJson(Map<String, dynamic> j) => CannedResponse(_s(j['name']), _s(j['title']),
      j['shortcut'] as String?, j['category'] as String?, htmlToText(_s(j['content'])));

  /// Helpdesk saved replies use the same picker.
  factory CannedResponse.savedReply(Map<String, dynamic> j) =>
      CannedResponse(_s(j['name']), _s(j['title']), null, j['scope'] as String?, _s(j['preview']));
}

/// A team alert rule merged with this agent's preferences (from `alert_config`).
class AlertRule {
  final String kind, sound;
  final bool enabled, repeat, popup;
  final int repeatSeconds, maxRepeats, volume;
  const AlertRule(this.kind, this.sound, this.enabled, this.repeat, this.popup, this.repeatSeconds, this.maxRepeats, this.volume);
}

class AlertConfig {
  final bool enabled, muteAll;
  final int volume;
  final Map<String, AlertRule> rules;
  const AlertConfig({this.enabled = false, this.muteAll = false, this.volume = 80, this.rules = const {}});

  /// Same rules as the web alert centre: the agent's own choice wins over "Team Default"; mute silences all.
  factory AlertConfig.fromJson(Map<String, dynamic> j) {
    final prefs = _m(j['prefs']);
    final items = _m(prefs['items']);
    final mute = _b(prefs['mute_all']);
    final prefVol = prefs['volume'] == null ? 80 : _i(prefs['volume']);
    final rules = <String, AlertRule>{};
    _m(j['rules']).forEach((kind, v) {
      final r = _m(v);
      final it = _m(items[kind]);
      final ownSound = _s(it['sound']);
      final sound = mute ? 'None' : (ownSound.isNotEmpty && ownSound != 'Team Default' ? ownSound : _s(r['sound']));
      final popup = _s(it['popup']) == 'Show' ? true : (_s(it['popup']) == 'Hide' ? false : _b(r['popup']));
      final rep = _s(it['repeat']) == 'Until acknowledged' ? true : (_s(it['repeat']) == 'Once' ? false : _b(r['repeat_until_ack']));
      final ruleVol = r['volume'] == null ? 80 : _i(r['volume']);
      rules[kind] = AlertRule(kind, sound.isEmpty ? 'None' : sound, _b(r['enabled']), rep, popup,
          _i(r['repeat_seconds']) < 5 ? 15 : _i(r['repeat_seconds']), _i(r['max_repeats']), (ruleVol * prefVol / 100).round());
    });
    return AlertConfig(enabled: _b(j['enabled']), muteAll: mute, volume: prefVol, rules: rules);
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
