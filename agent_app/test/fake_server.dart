import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

/// A small in-memory stand-in for the staff API v1 that behaves like the server on the points the app relies on:
/// bearer auth, per-agent identity, claim conflicts, reply de-duplication by client_request_id, internal notes,
/// and Helpdesk ticket replies / status changes. Contract: docs/agent-api.md.
class FakeServer {
  String validToken = 'token-1';
  String user = 'agent1@example.com';
  final List<Map<String, dynamic>> conversations = [];
  final Map<String, List<Map<String, dynamic>>> messages = {};
  final Map<String, Map<String, dynamic>> tickets = {};
  final Map<String, List<Map<String, dynamic>>> ticketTimeline = {};
  final Set<String> seenRequestIds = {};
  final List<String> calls = [];
  int failNextWithTimeout = 0; // the server processes the request but the answer is "lost"
  bool offline = false; // no answer at all
  final Map<String, List<int>> files = {}; // message id -> bytes
  final List<Map<String, dynamic>> alertItems = [];
  final List<Map<String, dynamic>> feed = []; // unstored alerts with 'seq'

  void message(String conv) => feed.add({
        'id': 'e:msg:$conv:${feed.length}',
        'kind': 'Chat Message',
        'title': 'New message',
        'body': '',
        'reference_doctype': 'Support Conversation Link',
        'reference_name': conv,
        'seq': 2.0 + feed.length,
      });
  final List<String> acknowledged = [];
  int typingCalls = 0;
  final Map<String, Map<String, dynamic>> closed = {};
  final Map<String, Map<String, dynamic>> linked = {};
  final List<Map<String, dynamic>> createdTickets = [];
  final List<Map<String, dynamic>> copilotCalls = [];
  int heartbeats = 0;
  bool customerTyping = false;
  int _seq = 0;

  FakeServer() {
    for (var i = 0; i < 45; i++) {
      conversations.add({
        'id': 'CONV-${(100 - i).toString().padLeft(3, '0')}',
        'subject': 'Chat $i',
        'display_name': i == 0 ? 'Visitor Asha' : 'Customer $i',
        'channel': i % 3 == 0 ? 'Live Chat' : (i % 3 == 1 ? 'Portal' : 'WhatsApp'),
        'status': 'Open',
        'handling': i == 0 ? 'Queued' : 'Agent',
        'queue': 'Billing',
        'assignee': i == 0 ? null : {'user': 'other@example.com', 'name': 'Other Agent'},
        'ticket': i == 0 ? '42' : null,
        'last_activity_at': DateTime.utc(2026, 11, 6, 12).subtract(Duration(minutes: i)).toIso8601String(),
        'unread': i == 0 ? 1 : 0,
        'sentiment': i == 0 ? 'Negative' : null,
        'urgency': i == 0 ? 'High' : null,
        'preview': i == 0 ? 'My invoice is wrong' : 'Hello',
        'whatsapp_window_open': i % 3 == 2 ? (i != 2) : null,
      });
      messages['CONV-${(100 - i).toString().padLeft(3, '0')}'] = [
        _msg('inbound', i == 0 ? 'My invoice is wrong' : 'Hello', author: 'Customer'),
      ];
    }
    tickets['42'] = {
      'id': '42',
      'subject': 'Invoice wrong',
      'status': 'Open',
      'priority': 'Medium',
      'raised_by': 'asha@example.com',
      'assignees': [],
      'sla': {'response_by': '2026-11-06T14:00:00', 'status': 'First Response Due'},
      'modified': '2026-11-06 12:00:00.000000',
      'description': '<p>The amount is wrong</p>',
      'linked_conversation': 'CONV-100',
      'can_write': true,
      'statuses': [
        {'name': 'Open', 'label': 'Open', 'category': 'Open'},
        {'name': 'Replied', 'label': 'Replied', 'category': 'Paused'},
        {'name': 'Resolved', 'label': 'Resolved', 'category': 'Resolved'},
      ],
      'priorities': ['Urgent', 'High', 'Medium', 'Low'],
    };
    ticketTimeline['42'] = [];
  }

  Map<String, dynamic> _msg(String direction, String text, {String author = 'Agent', bool internal = false, String? rid}) => {
        'id': 'MSG-${++_seq}',
        'direction': direction,
        'internal': internal,
        'sender_type': direction == 'inbound' ? 'Customer' : 'Agent',
        'author': author,
        'html': '<p>$text</p>',
        'created_at': DateTime.utc(2026, 11, 6, 12, 0, _seq).toIso8601String(),
        'client_request_id': rid,
        'can_edit': direction != 'inbound',
        'can_remove': direction != 'inbound',
        'reactions': <Map<String, dynamic>>[],
        '_changed': 0,
      };

  /// 1.14: a message changed by someone else (another agent, the customer); the next poll returns it in `updated`.
  void changeMessage(String conv, String id, String text) {
    final m = messages[conv]!.firstWhere((x) => x['id'] == id);
    m['html'] = '<p>$text</p>';
    m['edited'] = true;
    m['_changed'] = ++_changeSeq;
  }

  int _changeSeq = 0;
  final List<Map<String, dynamic>> messageCalls = [];

  Map<String, dynamic> _find(String conv, String id) => messages[conv]!.firstWhere((x) => x['id'] == id);

  Map<String, dynamic> _conv(String id) => conversations.firstWhere((c) => c['id'] == id);

  Map<String, dynamic> _detail(String id) {
    final c = _conv(id);
    final open = c['status'] != 'Closed';
    return {
      ...c,
      'actions': {
        'claim': open && (c['assignee']?['user'] != user),
        'transfer': open,
        'reply': open && c['whatsapp_window_open'] != false,
        'note': true,
        'close': open,
        'take_over': open && c['handling'] == 'Bot',
        'return_to_assistant': false,
        'link_customer': true,
        'create_ticket': c['ticket'] == null,
        'whatsapp_window_open': c['whatsapp_window_open'],
      },
      'customer_name': c['customer_name'],
      'insight': {'sentiment': c['sentiment'], 'urgency': c['urgency'], 'intent': c['sentiment'] == null ? null : 'late delivery',
                  'language': c['sentiment'] == null ? null : 'ar', 'summary': c['summary']},
      'contact': {'name': c['display_name'], 'email': 'asha@example.com'},
    };
  }

  /// What a customer sees in the portal for a conversation (never internal notes).
  List<String> customerView(String id) => [for (final m in messages[id]!) if (m['internal'] != true) '${m['html']}'];

  http.Response _ok(Object? message) => http.Response(jsonEncode({'message': message}), 200, headers: {'content-type': 'application/json'});
  http.Response _err(int code, String msg, [Map<String, Object?> extra = const {}]) =>
      http.Response(jsonEncode({'exc_type': 'Error', 'error_message': msg, ...extra}), code);

  late final MockClient client = MockClient((req) async {
    final path = req.url.path;
    const p = '/api/method/thinknxg_support.api.staff.v1.';
    if (!path.startsWith(p)) return http.Response('not found', 404);
    final method = path.substring(p.length);
    calls.add(method);
    if (offline) throw http.ClientException('Network is unreachable');
    if (req.headers['Authorization'] != 'Bearer $validToken') return _err(401, 'Sign in with your staff account.');
    final q = req.url.queryParameters;
    final type = req.headers['content-type'] ?? '';
    final b = type.startsWith('multipart/form-data')
        ? _multipart(req.bodyBytes, type)
        : (req.body.isEmpty ? <String, dynamic>{} : Map<String, dynamic>.from(jsonDecode(req.body) as Map));
    if (b['internal'] is String) b['internal'] = int.parse(b['internal'] as String);
    final res = download(method, q) ?? _handle(method, q, b);
    if (failNextWithTimeout > 0 && !const {'typing', 'live', 'heartbeat'}.contains(method)) {
      failNextWithTimeout--;
      throw http.ClientException('Connection closed before full header was received');
    }
    return res;
  });

  /// Just enough multipart parsing for the tests: text fields, and one file as `__file` (name, bytes).
  static Map<String, dynamic> _multipart(List<int> body, String type) {
    final boundary = type.split('boundary=').last;
    final text = latin1.decode(body);
    final out = <String, dynamic>{};
    for (final part in text.split('--$boundary')) {
      final i = part.indexOf('\r\n\r\n');
      if (i < 0) continue;
      final head = part.substring(0, i);
      var value = part.substring(i + 4);
      if (value.endsWith('\r\n')) value = value.substring(0, value.length - 2);
      final name = RegExp(r'name="([^"]+)"').firstMatch(head)?.group(1);
      final filename = RegExp(r'filename="([^"]+)"').firstMatch(head)?.group(1);
      if (filename != null) {
        out['__file'] = (filename, latin1.encode(value));
      } else if (name != null) {
        out[name] = value;
      }
    }
    return out;
  }

  http.Response _handle(String method, Map<String, String> q, Map<String, dynamic> b) {
    switch (method) {
      case 'bootstrap':
        return _ok({
          'api_version': 1,
          'site': {'url': 'https://support.example.com', 'name': 'support.example.com', 'app_version': '1.9.0'},
          'agent': {'user': user, 'full_name': 'Agent One', 'email': user, 'is_manager': false, 'helpdesk_agent': true},
          'capabilities': {
            'conversations': true, 'helpdesk': true, 'live_chat': true, 'whatsapp': true, 'copilot': true,
            'messaging': {'reactions': ['👍', '❤️', '🙏'], 'voice': true, 'max_voice_seconds': 120, 'edit': true},
          },
          'queues': [
            {'name': 'Billing', 'member': true},
          ],
          'poll': {'inbox_seconds': 10, 'thread_seconds': 4, 'alerts_seconds': 5},
        });
      case 'conversations':
        var list = conversations.where((c) => c['status'] != 'Closed').toList();
        if (q['view'] == 'mine') list = list.where((c) => c['assignee']?['user'] == user).toList();
        if (q['view'] == 'unassigned') list = list.where((c) => c['assignee'] == null).toList();
        if (q['channel'] != null) list = list.where((c) => c['channel'] == q['channel']).toList();
        final limit = int.parse(q['limit'] ?? '30');
        final start = q['cursor'] == null ? 0 : int.parse(q['cursor']!);
        final page = list.skip(start).take(limit).toList();
        return _ok({'items': page, 'next_cursor': start + limit < list.length ? '${start + limit}' : null});
      case 'conversation':
        return _ok(_detail(q['name']!));
      case 'messages':
        final all = messages[q['name']]!;
        final now = '$_changeSeq';
        if (q['after'] != null) {
          final i = all.indexWhere((m) => m['id'] == q['after']);
          final newer = all.skip(i + 1).toList();
          final since = int.tryParse(q['changed_since'] ?? '');
          return _ok({
            'items': newer,
            'latest_cursor': newer.isEmpty ? q['after'] : newer.last['id'],
            'has_more_before': false,
            'server_time': now,
            if (since != null) 'updated': all.take(i + 1).where((m) => (m['_changed'] as int) > since).toList(),
          });
        }
        return _ok({'items': all, 'latest_cursor': all.isEmpty ? null : all.last['id'], 'has_more_before': false, 'server_time': now});
      case 'edit_message':
        messageCalls.add({'action': 'edit', ...b});
        final m = _find(b['name'], b['message']);
        m['html'] = '<p>${b['text']}</p>';
        m['edited'] = true;
        return _ok(m);
      case 'remove_message':
        messageCalls.add({'action': 'remove', ...b});
        final m = _find(b['name'], b['message']);
        m['removed'] = true;
        m['removed_by'] = 'Agent One';
        m['can_edit'] = false;
        m['can_remove'] = false;
        return _ok(m);
      case 'react':
        messageCalls.add({'action': 'react', ...b});
        final m = _find(b['name'], b['message']);
        final list = (m['reactions'] as List).cast<Map<String, dynamic>>();
        final r = list.where((x) => x['emoji'] == b['emoji']).toList();
        if (r.isEmpty) {
          list.add({'emoji': b['emoji'], 'count': 1, 'mine': true});
        } else {
          list.remove(r.first);
        }
        return _ok(m);
      case 'message_history':
        return _ok([
          {'text': 'first version', 'edited_by': 'Agent One', 'edited_on': '2026-11-06 12:00:00'},
        ]);
      case 'mark_read':
        _conv(b['name'])['unread'] = 0;
        return _ok({'read_up_to': '2026-11-06T12:00:00'});
      case 'claim':
        final c = _conv(b['name']);
        if (c['assignee'] != null && c['assignee']['user'] != user) {
          return _err(409, '${c['assignee']['name']} already has this conversation.', {'error_code': 'conflict', 'conflict': _detail(b['name'])});
        }
        c['assignee'] = {'user': user, 'name': 'Agent One'};
        c['handling'] = 'Agent';
        return _ok(_detail(b['name']));
      case 'reply':
        final id = b['name'] as String;
        final rid = b['client_request_id'] as String;
        final existing = messages[id]!.where((m) => m['client_request_id'] == rid);
        if (existing.isNotEmpty) return _ok({'message': existing.first, 'duplicate': true});
        final c = _conv(id);
        if (b['internal'] != 1 && c['whatsapp_window_open'] == false) {
          return _err(422, 'WhatsApp only allows free replies within 24 hours of the customer\'s last message.',
              {'error_code': 'whatsapp_window_closed', 'actions': [{'action': 'open_web_console', 'label': 'Open in the web console'}]});
        }
        final m = _msg(b['internal'] == 1 ? 'internal' : 'outbound', b['text'] as String, internal: b['internal'] == 1, rid: rid);
        if (b['reply_to'] != null) {
          final target = _find(id, '${b['reply_to']}');
          m['reply_to'] = {'id': target['id'], 'author': target['author'], 'excerpt': '${target['html']}'.replaceAll(RegExp('<[^>]+>'), '')};
        }
        if (b['__file'] != null) {
          final f = b['__file'] as (String, List<int>);
          m['attachment'] = {'name': f.$1};
          files[m['id'] as String] = f.$2;
          if (b['voice_seconds'] != null) {
            m['attachment_kind'] = 'audio';
            m['voice_seconds'] = int.parse('${b['voice_seconds']}');
          }
        }
        messages[id]!.add(m);
        return _ok({'message': m, 'duplicate': false});
      case 'closing_form':
        return _ok({
          'reasons': ['Resolved'],
          'require_reason': 0,
          'questions': [
            {'idx': 1, 'question': "Was the customer's issue resolved?", 'answer_type': 'Yes/No', 'required': 1,
             'report_as': 'Issue Resolved', 'options': ['Yes', 'No']},
            {'idx': 2, 'question': 'Does the customer need a follow-up?', 'answer_type': 'Yes/No', 'required': 1,
             'report_as': 'Follow-up Needed', 'options': []}, // an older server sends no options for Yes/No
          ],
          'closing_message': '',
        });
      case 'close':
        final c = _conv(b['name']);
        final ans = Map<String, dynamic>.from(b['answers'] as Map? ?? {});
        if (ans['1'] == null || ans['2'] == null) return _err(417, 'Answer: Does the customer need a follow-up?');
        closed[b['name'] as String] = ans;
        c['status'] = 'Closed';
        return _ok(_detail(b['name']));
      case 'copilot':
        copilotCalls.add(Map<String, dynamic>.from(b));
        switch (b['action']) {
          case 'suggest':
            return _ok({
              'suggestions': [
                {'label': 'Apologise', 'text': 'Sorry about the delay with your order.'},
                {'label': 'Ask', 'text': 'Could you share your order number?'},
              ],
              'sources': [{'title': 'Delivery times'}],
            });
          case 'rewrite':
            return _ok({'text': 'Thank you for your patience. ${b['text']}'});
          case 'translate':
            return _ok({'text': 'نص مترجم', 'language': b['target']});
          case 'summarize':
            _conv(b['name'])['summary'] = '- Late order';
            return _ok({'summary': '- Late order'});
          case 'recommend':
            return _ok({'solution': 'Check the courier.', 'follow_ups': ['Is the address right?'], 'articles': []});
          case 'note':
            messages[b['name']]!.add(_msg('internal', 'AI summary: Late order', internal: true));
            return _ok({'summary': '- Late order', 'message': 'X'});
        }
        return _err(417, 'Unknown copilot action.');
      case 'customer_search':
        return _ok([
          {'name': 'CUST-ASHA', 'customer_name': 'Asha Trading LLC', 'email_id': 'asha@example.com', 'suggested': true},
          {'name': 'CUST-002', 'customer_name': 'Muscat Motors', 'suggested': false},
        ].where((x) => (q['q'] ?? '').isEmpty || '${x['customer_name']}'.toLowerCase().contains(q['q']!.toLowerCase())).toList());
      case 'customer_contacts':
        return _ok([
          {'name': 'CONT-1', 'full_name': 'Asha', 'email': 'asha@example.com'},
        ]);
      case 'link_customer':
        final c = _conv(b['name']);
        c['customer_name'] = b['customer'] == 'CUST-ASHA' ? 'Asha Trading LLC' : b['customer'];
        linked[b['name'] as String] = {'customer': b['customer'], 'contact': b['contact'], 'create_contact': b['create_contact']};
        return _ok(_detail(b['name']));
      case 'ticket_options':
        return _ok({'priorities': ['High', 'Medium'], 'teams': ['Billing'], 'ticket_types': ['Question']});
      case 'create_ticket':
        final c = _conv(b['name']);
        c['ticket'] = '77';
        tickets['77'] = {...tickets['42']!, 'id': '77', 'subject': b['subject'], 'priority': b['priority'], 'linked_conversation': b['name']};
        ticketTimeline['77'] = [];
        createdTickets.add(Map<String, dynamic>.from(b));
        return _ok({'ticket': '77', 'duplicate': false});
      case 'saved_replies':
        return _ok([
          {'name': 'SR-1', 'title': 'Invoice corrected', 'scope': 'Global', 'preview': 'We have corrected your invoice'},
        ]);
      case 'saved_reply_render':
        return _ok({'text': b['ticket'] != null ? 'Ticket #${b['ticket']}: we have corrected your invoice' : 'We have corrected your invoice', 'html': ''});
      case 'tickets':
        return _ok({'items': tickets.values.toList(), 'next_cursor': null});
      case 'ticket':
        return _ok(tickets[q['name']]);
      case 'ticket_timeline':
        return _ok({'items': ticketTimeline[q['name']], 'next_cursor': null});
      case 'ticket_reply':
      case 'ticket_note':
        final rid = '${b['client_request_id']}';
        if (!seenRequestIds.add(rid)) return _ok({'duplicate': true});
        ticketTimeline[b['name']]!.add({
          'id': 'C-${++_seq}',
          'kind': method == 'ticket_reply' ? 'email' : 'note',
          'internal': method == 'ticket_note',
          'direction': method == 'ticket_reply' ? 'outbound' : 'internal',
          'author': 'Agent One',
          'html': '<p>${b['text']}</p>',
          'created_at': '2026-11-06T12:30:00',
        });
        return _ok({'id': 'C-$_seq', 'duplicate': false});
      case 'ticket_update':
        final t = tickets[b['name']]!;
        if (b['expected_modified'] != null && b['expected_modified'] != t['modified']) {
          return _err(409, 'Someone else changed this ticket. Reload to see the latest.', {'error_code': 'conflict', 'conflict': t});
        }
        if (b['status'] != null) t['status'] = b['status'];
        if (b['priority'] != null) t['priority'] = b['priority'];
        t['modified'] = '2026-11-06 12:31:00.000000';
        return _ok(t);
      case 'ticket_assign':
        tickets[b['name']]!['assignees'] = [
          {'user': b['agent'], 'name': 'Agent One'},
        ];
        return _ok(tickets[b['name']]);
      case 'alerts':
        final since = double.tryParse(q['since'] ?? '');
        final cursor = feed.isEmpty ? 1.0 : feed.map((e) => e['seq'] as double).reduce((a, b) => a > b ? a : b);
        return _ok({
          'items': alertItems,
          'events': since == null ? [] : feed.where((e) => (e['seq'] as double) > since).toList(),
          'cursor': cursor,
        });
      case 'send_test_alert':
        return _ok({'message': 'Test alert sent.'});
      case 'acknowledge_alerts':
        final ids = [for (final i in b['ids'] as List) '$i'];
        acknowledged.addAll(ids);
        alertItems.removeWhere((a) => ids.contains(a['id']));
        return _ok({'acknowledged': ids});
      case 'alert_config':
        return _ok({
          'enabled': true,
          'rules': {
            'New Chat': {'enabled': 1, 'popup': 1, 'sound': 'Ring', 'repeat_until_ack': 1, 'repeat_seconds': 10, 'max_repeats': 0, 'volume': 90},
            'Chat Message': {'enabled': 1, 'popup': 1, 'sound': 'Ping', 'repeat_until_ack': 0, 'repeat_seconds': 15, 'max_repeats': 0, 'volume': 70},
          },
          'prefs': {'mute_all': 0, 'volume': 80, 'items': {}},
        });
      case 'canned_responses':
        return _ok([
          {'name': 'CR-1', 'title': 'Greeting', 'shortcut': 'hi', 'content': '<p>Hi {customer_first_name}</p>'},
          {'name': 'CR-2', 'title': 'Refunds', 'shortcut': 'refund', 'content': '<p>Refunds take 5 days.</p>'},
        ]);
      case 'canned_render':
        return _ok({'text': b['name'] == 'CR-1' ? 'Hi Asha' : 'Refunds take 5 days.', 'html': ''});
      case 'transfer_targets':
        return _ok({
          'agents': [
            {'user': 'agent2@example.com', 'name': 'Agent Two', 'online': true, 'open_chats': 1, 'in_queue': true},
            {'user': 'agent3@example.com', 'name': 'Agent Three', 'online': false, 'open_chats': 0, 'in_queue': false},
          ],
          'queues': ['Billing', 'Technical'],
          'current': {'user': null, 'queue': 'Billing'},
        });
      case 'transfer':
        final c = _conv(b['name']);
        c['assignee'] = b['user'] == null ? null : {'user': b['user'], 'name': 'Agent Two'};
        if (b['queue'] != null) c['queue'] = b['queue'];
        return _ok(_detail(b['name']));
      case 'customer_history':
        return _ok({
          'conversations': [conversations[5]],
          'tickets': [tickets['42']],
        });
      case 'live':
        return _ok({'customer_typing': customerTyping, 'visitor_online': true, 'ai_drafting': false});
      case 'typing':
        typingCalls++;
        return _ok({'ok': true});
      case 'heartbeat':
        heartbeats++;
        return _ok({'ok': true});
      case 'register_device':
        return _ok({'device': 'D1'});
      case 'open_target':
        if (q['name'] == 'SECRET') return _err(403, 'This conversation is in a queue you are not part of.');
        return _ok({'kind': q['doctype'] == 'HD Ticket' ? 'ticket' : 'conversation', 'id': q['name']});
      case 'sign_out':
        return _ok({'ok': true});
    }
    return _err(404, 'Unknown method $method');
  }

  /// Files are served raw (like Frappe's download response), errors as JSON.
  http.Response? download(String method, Map<String, String> q) {
    if (method != 'attachment') return null;
    final bytes = files[q['message']];
    if (bytes == null) return _err(404, 'Attachment not found.');
    final m = messages.values.expand((x) => x).firstWhere((x) => x['id'] == q['message']);
    return http.Response.bytes(bytes, 200,
        headers: {'content-type': 'application/pdf', 'content-disposition': 'attachment; filename="${m['attachment']['name']}"'});
  }
}
