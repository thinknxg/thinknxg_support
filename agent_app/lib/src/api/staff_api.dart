import 'api_client.dart';
import 'models.dart';

/// The staff API v1, typed. One instance per signed-in session.
class StaffApi {
  final ApiClient client;
  StaffApi(this.client);

  Map<String, dynamic> _map(dynamic v) => v is Map ? Map<String, dynamic>.from(v) : <String, dynamic>{};
  List<dynamic> _list(dynamic v) => v is List ? v : const [];

  Future<Bootstrap> bootstrap() async => Bootstrap.fromJson(_map(await client.get('bootstrap')));

  Future<Page<ConversationSummary>> conversations({
    String view = 'all',
    String? channel,
    String status = 'open',
    String? queue,
    String? q,
    String? cursor,
    int limit = 30,
    String? sort,
    String? priority,
    String? tag,
  }) async {
    final r = _map(await client.get('conversations', {
      'view': view,
      'channel': channel,
      'status': status,
      'queue': queue,
      'q': q,
      'cursor': cursor,
      'limit': '$limit',
      'sort': sort,
      'priority': priority,
      'tag': tag,
    }));
    return Page([for (final c in _list(r['items'])) ConversationSummary.fromJson(_map(c))], r['next_cursor'] as String?);
  }

  Future<ConversationSummary> conversation(String id) async =>
      ConversationSummary.fromJson(_map(await client.get('conversation', {'name': id})));

  Future<MessagePage> messages(String id, {String? before, String? after, int limit = 30, String? changedSince}) async =>
      MessagePage.fromJson(_map(await client.get('messages',
          {'name': id, 'before': before, 'after': after, 'limit': '$limit', 'changed_since': changedSince})));

  // 1.14: change messages after sending
  Future<ChatMessage> editMessage(String id, String messageId, String text) async =>
      ChatMessage.fromJson(_map(await client.post('edit_message', {'name': id, 'message': messageId, 'text': text})));

  Future<ChatMessage> removeMessage(String id, String messageId) async =>
      ChatMessage.fromJson(_map(await client.post('remove_message', {'name': id, 'message': messageId})));

  Future<ChatMessage> react(String id, String messageId, String emoji) async =>
      ChatMessage.fromJson(_map(await client.post('react', {'name': id, 'message': messageId, 'emoji': emoji})));

  Future<List<Map<String, dynamic>>> messageHistory(String id, String messageId) async =>
      [for (final h in _list(await client.get('message_history', {'name': id, 'message': messageId}))) _map(h)];

  Future<void> markRead(String id, String messageId) => client.post('mark_read', {'name': id, 'message': messageId});

  Future<ConversationSummary> claim(String id) async => ConversationSummary.fromJson(_map(await client.post('claim', {'name': id})));

  Future<ConversationSummary> transfer(String id, {String? user, String? queue, String? expectedAssignee}) async =>
      ConversationSummary.fromJson(_map(await client.post('transfer', {
        'name': id,
        'user': user,
        'queue': queue,
        'expected_assignee': expectedAssignee ?? '',
      })));

  Future<ConversationSummary> takeOver(String id) async =>
      ConversationSummary.fromJson(_map(await client.post('take_over', {'name': id})));

  Future<ConversationSummary> returnToAssistant(String id) async =>
      ConversationSummary.fromJson(_map(await client.post('return_to_assistant', {'name': id})));

  Future<Map<String, dynamic>> closingForm() async => _map(await client.get('closing_form'));

  Future<ConversationSummary> close(String id,
          {String? reason, String? notes, Map<String, Object?>? answers, bool sendClosingMessage = true, String? expectedStatus}) async =>
      ConversationSummary.fromJson(_map(await client.post('close', {
        'name': id,
        'reason': reason,
        'notes': notes,
        'answers': answers,
        'send_closing_message': sendClosingMessage ? 1 : 0,
        'expected_status': expectedStatus,
      })));

  /// Reply to the customer, or (internal) a staff-only note. Retrying with the same [clientRequestId] never sends twice.
  Future<({ChatMessage message, bool duplicate})> reply(String id, String text,
      {required String clientRequestId, bool internal = false, UploadFile? file, String? replyTo, int? voiceSeconds}) async {
    final fields = {
      'name': id,
      'text': text,
      'client_request_id': clientRequestId,
      'internal': internal ? 1 : 0,
      if (replyTo != null) 'reply_to': replyTo,
      if (voiceSeconds != null) 'voice_seconds': voiceSeconds,
    };
    final r = _map(file == null ? await client.post('reply', fields) : await client.postFile('reply', fields, file));
    return (message: ChatMessage.fromJson(_map(r['message'])), duplicate: r['duplicate'] == true);
  }

  Future<List<CannedResponse>> cannedResponses({String? channel}) async =>
      [for (final c in _list(await client.get('canned_responses', {'channel': channel}))) CannedResponse.fromJson(_map(c))];

  /// Placeholders ({customer_first_name}, {agent_name}, …) filled for this conversation; counts as used.
  Future<String> cannedRender(String cannedId, String conversationId) async =>
      '${_map(await client.post('canned_render', {'name': cannedId, 'conversation': conversationId}))['text'] ?? ''}';

  Future<DownloadedFile> attachment(String messageId) => client.download('attachment', {'message': messageId});

  Future<DownloadedFile> ticketAttachment(String ticketId, String fileId) =>
      client.download('ticket_attachment', {'name': ticketId, 'file': fileId});

  Future<TransferTargets> transferTargets(String id) async =>
      TransferTargets.fromJson(_map(await client.get('transfer_targets', {'name': id})));

  Future<CustomerHistory> customerHistory(String id) async =>
      CustomerHistory.fromJson(_map(await client.get('customer_history', {'name': id})));

  Future<LiveState> live(String id) async => LiveState.fromJson(_map(await client.get('live', {'name': id})));

  Future<void> typing(String id) => client.post('typing', {'name': id});

  /// 1.14: `active` says whether the person used the app since the last heartbeat (drives Away after idle minutes).
  Future<AgentStatus?> heartbeat({bool? active}) async {
    final r = await client.post('heartbeat', {if (active != null) 'active': active ? 1 : 0});
    return r is Map ? AgentStatus.fromJson(r['status']) : null;
  }

  Future<AgentStatus?> setStatus(String status, {String? note}) async =>
      AgentStatus.fromJson(await client.post('set_status', {'status': status, if (note != null) 'note': note}));

  Future<ConversationSummary> setPriority(String id, String priority) async =>
      ConversationSummary.fromJson(_map(await client.post('set_priority', {'name': id, 'priority': priority})));

  Future<ConversationSummary> setTags(String id, {List<String> add = const [], List<String> remove = const []}) async =>
      ConversationSummary.fromJson(_map(await client.post('set_tags', {'name': id, 'add': add, 'remove': remove})));

  Future<ConversationSummary> createLead(String id, {String? name, String? email, String? phone, String? company}) async =>
      ConversationSummary.fromJson(_map(await client.post('create_lead', {
        'name': id,
        if (name != null && name.isNotEmpty) 'person_name': name,
        if (email != null && email.isNotEmpty) 'email': email,
        if (phone != null && phone.isNotEmpty) 'phone': phone,
        if (company != null && company.isNotEmpty) 'company': company,
      })));

  Future<ConversationSummary> collectLeadDetails(String id) async =>
      ConversationSummary.fromJson(_map(await client.post('collect_lead_details', {'name': id})));

  Future<List<String>> tagSuggestions() async => [for (final t in _list(await client.get('tag_suggestions'))) '$t'];

  Future<AlertConfig> alertConfig() async => AlertConfig.fromJson(_map(await client.get('alert_config')));

  // ---------------------------------------------------------------- tickets
  Future<Page<Ticket>> tickets({String view = 'mine', String? status = 'open', String? priority, String? q, String? cursor, int limit = 30}) async {
    final r = _map(await client.get('tickets', {
      'view': view,
      'status': status,
      'priority': priority,
      'q': q,
      'cursor': cursor,
      'limit': '$limit',
    }));
    return Page([for (final t in _list(r['items'])) Ticket.fromJson(_map(t))], r['next_cursor'] as String?);
  }

  Future<Ticket> ticket(String id) async => Ticket.fromJson(_map(await client.get('ticket', {'name': id})));

  Future<Page<TimelineItem>> ticketTimeline(String id, {String? cursor, int limit = 30}) async {
    final r = _map(await client.get('ticket_timeline', {'name': id, 'cursor': cursor, 'limit': '$limit'}));
    return Page([for (final t in _list(r['items'])) TimelineItem.fromJson(_map(t))], r['next_cursor'] as String?);
  }

  Future<bool> ticketReply(String id, String text, {required String clientRequestId, UploadFile? file}) async {
    final fields = {'name': id, 'text': text, 'client_request_id': clientRequestId};
    return _map(file == null ? await client.post('ticket_reply', fields) : await client.postFile('ticket_reply', fields, file))[
            'duplicate'] ==
        true;
  }

  Future<bool> ticketNote(String id, String text, {required String clientRequestId}) async =>
      _map(await client.post('ticket_note', {'name': id, 'text': text, 'client_request_id': clientRequestId}))['duplicate'] == true;

  Future<Ticket> ticketUpdate(String id, {String? status, String? priority, String? team, String? expectedModified}) async =>
      Ticket.fromJson(_map(await client.post('ticket_update', {
        'name': id,
        'status': status,
        'priority': priority,
        'team': team,
        'expected_modified': expectedModified,
      })));

  Future<Ticket> ticketAssign(String id, {String? agent, List<String>? expectedAssignees}) async =>
      Ticket.fromJson(_map(await client.post('ticket_assign', {'name': id, 'agent': agent, 'expected_assignees': expectedAssignees})));

  // ---------------------------------------------------------------- alerts, links, devices
  Future<List<AgentAlert>> alerts() async => (await alertFeed()).items;

  /// Open alerts, plus alerts that are not stored (new messages …) since [since] (the previous poll's cursor).
  Future<({List<AgentAlert> items, List<AgentAlert> events, double? cursor})> alertFeed({double? since}) async {
    final r = _map(await client.get('alerts', {'since': since?.toString()}));
    final c = r['cursor'];
    return (
      items: [for (final a in _list(r['items'])) AgentAlert.fromJson(_map(a))],
      events: [for (final a in _list(r['events'])) AgentAlert.fromJson(_map(a))],
      cursor: c is num ? c.toDouble() : double.tryParse('${c ?? ''}'),
    );
  }

  Future<List<CustomerOption>> customerSearch(String q, {String? conversation}) async => [
        for (final c in _list(await client.get('customer_search', {'q': q, 'conversation': conversation})))
          CustomerOption.fromJson(_map(c)),
      ];

  Future<List<ContactOption>> customerContacts(String customer) async =>
      [for (final c in _list(await client.get('customer_contacts', {'customer': customer}))) ContactOption.fromJson(_map(c))];

  Future<ConversationSummary> linkCustomer(String id, String customer, {String? contact, bool createContact = false}) async =>
      ConversationSummary.fromJson(_map(await client.post('link_customer', {
        'name': id,
        'customer': customer,
        'contact': contact,
        'create_contact': createContact ? 1 : 0,
      })));

  Future<TicketOptions> ticketOptions() async => TicketOptions.fromJson(_map(await client.get('ticket_options')));

  /// Creates a Helpdesk ticket from the chat (retry-safe with [clientRequestId]); returns the ticket id.
  Future<String> createTicket(String id,
          {required String clientRequestId, String? subject, String? priority, String? team, String? ticketType, String? reply}) async =>
      '${_map(await client.post('create_ticket', {
        'name': id,
        'client_request_id': clientRequestId,
        'subject': subject,
        'priority': priority,
        'team': team,
        'ticket_type': ticketType,
        'reply': reply,
      }))['ticket']}';

  Future<List<CannedResponse>> savedReplies({String q = '', String? ticket}) async =>
      [for (final r in _list(await client.get('saved_replies', {'q': q, 'ticket': ticket}))) CannedResponse.savedReply(_map(r))];

  Future<String> savedReplyRender(String name, {String? ticket, String? conversation}) async =>
      '${_map(await client.post('saved_reply_render', {'name': name, 'ticket': ticket, 'conversation': conversation}))['text'] ?? ''}';

  /// AI copilot (drafts only): suggest | rewrite | summarize | recommend | translate | note.
  Future<Map<String, dynamic>> copilot(String id, String action, {String? text, String? style, String? target}) async =>
      _map(await client.post('copilot', {'name': id, 'action': action, 'text': text, 'style': style, 'target': target}));

  Future<String> sendTestAlert() async => '${_map(await client.post('send_test_alert', {}))['message'] ?? ''}';

  Future<List<String>> acknowledgeAlerts(List<String> ids) async =>
      [for (final i in _list(_map(await client.post('acknowledge_alerts', {'ids': ids}))['acknowledged'])) '$i'];

  /// Re-checks access before a notification or alert opens a record.
  Future<({String kind, String id})> openTarget(String doctype, String name) async {
    final r = _map(await client.get('open_target', {'doctype': doctype, 'name': name}));
    return (kind: '${r['kind']}', id: '${r['id'] ?? r['url'] ?? ''}');
  }

  Future<void> registerDevice(String pushToken, String platform, {String? deviceName, String? appVersion}) =>
      client.post('register_device', {'push_token': pushToken, 'platform': platform, 'device_name': deviceName, 'app_version': appVersion});

  Future<void> signOut({String? pushToken}) => client.post('sign_out', {'push_token': pushToken});
}
