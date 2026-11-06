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
  }) async {
    final r = _map(await client.get('conversations', {
      'view': view,
      'channel': channel,
      'status': status,
      'queue': queue,
      'q': q,
      'cursor': cursor,
      'limit': '$limit',
    }));
    return Page([for (final c in _list(r['items'])) ConversationSummary.fromJson(_map(c))], r['next_cursor'] as String?);
  }

  Future<ConversationSummary> conversation(String id) async =>
      ConversationSummary.fromJson(_map(await client.get('conversation', {'name': id})));

  Future<MessagePage> messages(String id, {String? before, String? after, int limit = 30}) async =>
      MessagePage.fromJson(_map(await client.get('messages', {'name': id, 'before': before, 'after': after, 'limit': '$limit'})));

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
      {required String clientRequestId, bool internal = false}) async {
    final r = _map(await client.post('reply', {
      'name': id,
      'text': text,
      'client_request_id': clientRequestId,
      'internal': internal ? 1 : 0,
    }));
    return (message: ChatMessage.fromJson(_map(r['message'])), duplicate: r['duplicate'] == true);
  }

  Future<List<Map<String, dynamic>>> cannedResponses({String? channel}) async =>
      [for (final c in _list(await client.get('canned_responses', {'channel': channel}))) _map(c)];

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

  Future<bool> ticketReply(String id, String text, {required String clientRequestId}) async =>
      _map(await client.post('ticket_reply', {'name': id, 'text': text, 'client_request_id': clientRequestId}))['duplicate'] == true;

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
  Future<List<AgentAlert>> alerts() async =>
      [for (final a in _list(_map(await client.get('alerts'))['items'])) AgentAlert.fromJson(_map(a))];

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
