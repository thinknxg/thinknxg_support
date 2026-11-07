import 'dart:async';

import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/controllers.dart';
import 'pickers.dart';

/// Link the chat to an existing customer: suggestions from the visitor's e-mail / phone first, then search.
/// Optionally pick one of the customer's contacts, or add the visitor as a new contact.
class LinkCustomerDialog extends StatefulWidget {
  final ConversationController c;
  const LinkCustomerDialog({super.key, required this.c});

  static Future<bool?> show(BuildContext context, ConversationController c) =>
      showDialog<bool>(context: context, builder: (_) => LinkCustomerDialog(c: c));

  @override
  State<LinkCustomerDialog> createState() => _LinkCustomerDialogState();
}

class _LinkCustomerDialogState extends State<LinkCustomerDialog> {
  final _q = TextEditingController();
  Timer? _debounce;
  List<CustomerOption> _results = [];
  bool _loading = true;
  String? _error;
  CustomerOption? _picked;
  List<ContactOption>? _contacts;
  String? _contact; // contact id, or '__new__'
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _search('');
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _q.dispose();
    super.dispose();
  }

  Future<void> _search(String q) async {
    setState(() => _loading = true);
    try {
      final r = await widget.c.api.customerSearch(q, conversation: widget.c.id);
      if (mounted) setState(() => _results = r);
    } catch (e) {
      if (mounted) setState(() => _error = '$e');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _pick(CustomerOption c) async {
    setState(() {
      _picked = c;
      _contacts = null;
      _contact = '__new__';
    });
    try {
      final list = await widget.c.api.customerContacts(c.id);
      final email = widget.c.detail?.contactEmail?.toLowerCase();
      final match = list.where((x) => email != null && (x.email ?? '').toLowerCase() == email);
      if (mounted) {
        setState(() {
          _contacts = list;
          _contact = match.isNotEmpty ? match.first.id : '__new__';
        });
      }
    } catch (_) {
      if (mounted) setState(() => _contacts = const []);
    }
  }

  Future<void> _save() async {
    if (_picked == null) return;
    setState(() => _saving = true);
    final ok = await widget.c.linkCustomer(_picked!.id,
        contact: _contact == '__new__' ? null : _contact, createContact: _contact == '__new__');
    if (!mounted) return;
    setState(() => _saving = false);
    if (ok) {
      Navigator.pop(context, true);
    } else {
      setState(() => _error = widget.c.actionError);
    }
  }

  @override
  Widget build(BuildContext context) {
    final d = widget.c.detail;
    return AlertDialog(
      title: const Text('Link customer'),
      content: SizedBox(
        width: 480,
        height: 460,
        child: _picked == null
            ? Column(children: [
                TextField(
                  key: const Key('customer-search'),
                  controller: _q,
                  autofocus: true,
                  decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Customer name, ID, e-mail or phone'),
                  onChanged: (v) {
                    _debounce?.cancel();
                    _debounce = Timer(const Duration(milliseconds: 350), () => _search(v));
                  },
                ),
                if (_loading) const LinearProgressIndicator(),
                if (_error != null) Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                Expanded(
                  child: _results.isEmpty && !_loading
                      ? const Center(child: Text('No customers found.'))
                      : ListView(children: [
                          for (final c in _results)
                            ListTile(
                              key: Key('customer-${c.id}'),
                              leading: Icon(c.suggested ? Icons.auto_awesome : Icons.business_outlined),
                              title: Text(c.name),
                              subtitle: Text([
                                if (c.suggested) 'Matches the visitor',
                                if (c.id != c.name) c.id,
                                if (c.email != null) c.email!,
                                if (c.phone != null) c.phone!,
                              ].join(' · ')),
                              onTap: () => _pick(c),
                            ),
                        ]),
                ),
              ])
            : ListView(children: [
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.business),
                  title: Text(_picked!.name),
                  subtitle: Text(_picked!.id),
                  trailing: TextButton(onPressed: () => setState(() => _picked = null), child: const Text('Change')),
                ),
                const Divider(),
                const Text('Contact'),
                if (_contacts == null) const LinearProgressIndicator(),
                if (_contacts != null)
                  RadioGroup<String>(
                    groupValue: _contact,
                    onChanged: (v) => setState(() => _contact = v),
                    child: Column(children: [
                      for (final x in _contacts!)
                        RadioListTile<String>(
                          value: x.id,
                          title: Text(x.name),
                          subtitle: Text([x.email, x.phone].whereType<String>().join(' · ')),
                        ),
                      RadioListTile<String>(
                        key: const Key('contact-new'),
                        value: '__new__',
                        title: const Text('Add the visitor as a new contact'),
                        subtitle: Text([d?.contactName, d?.contactEmail, d?.contactPhone].whereType<String>().join(' · ')),
                      ),
                    ]),
                  ),
                if (_error != null) Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
              ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          key: const Key('link-customer-save'),
          onPressed: _picked == null || _saving || _contacts == null ? null : _save,
          child: Text(_saving ? 'Linking…' : 'Link customer'),
        ),
      ],
    );
  }
}

/// Create a Helpdesk ticket from the chat: subject, priority, team, type, and an optional first reply
/// (a Helpdesk saved reply can be inserted). The transcript goes into the ticket.
class CreateTicketDialog extends StatefulWidget {
  final ConversationController c;
  const CreateTicketDialog({super.key, required this.c});

  /// Returns the new ticket's id.
  static Future<String?> show(BuildContext context, ConversationController c) =>
      showDialog<String>(context: context, builder: (_) => CreateTicketDialog(c: c));

  @override
  State<CreateTicketDialog> createState() => _CreateTicketDialogState();
}

class _CreateTicketDialogState extends State<CreateTicketDialog> {
  late final _subject = TextEditingController(text: widget.c.detail?.subject ?? '');
  final _reply = TextEditingController();
  TicketOptions? _opts;
  String? _priority, _team, _type, _error;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    widget.c.api.ticketOptions().then((o) {
      if (mounted) setState(() => _opts = o);
    }).catchError((e) {
      if (mounted) setState(() => _opts = const TicketOptions([], [], []));
    });
  }

  @override
  void dispose() {
    _subject.dispose();
    _reply.dispose();
    super.dispose();
  }

  Future<void> _insertSavedReply() async {
    final picked = await CannedPicker.show(context, () => widget.c.api.savedReplies(), title: 'Saved replies');
    if (picked == null) return;
    try {
      final text = await widget.c.api.savedReplyRender(picked.id, conversation: widget.c.id);
      setState(() => _reply.text = _reply.text.trim().isEmpty ? text : '${_reply.text.trimRight()}\n$text');
    } catch (e) {
      setState(() => _error = '$e');
    }
  }

  Future<void> _save() async {
    if (_subject.text.trim().isEmpty) {
      setState(() => _error = 'Enter a subject.');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    final t = await widget.c.createTicket(
        subject: _subject.text.trim(),
        priority: _priority,
        team: _team,
        ticketType: _type,
        reply: _reply.text.trim().isEmpty ? null : _reply.text.trim());
    if (!mounted) return;
    setState(() => _saving = false);
    if (t != null) {
      Navigator.pop(context, t);
    } else {
      setState(() => _error = widget.c.actionError);
    }
  }

  Widget _drop(String label, List<String> items, String? value, ValueChanged<String?> set) => items.isEmpty
      ? const SizedBox.shrink()
      : DropdownButtonFormField<String>(
          initialValue: value,
          decoration: InputDecoration(labelText: label),
          items: [
            const DropdownMenuItem<String>(value: null, child: Text('Default')),
            for (final x in items) DropdownMenuItem(value: x, child: Text(x)),
          ],
          onChanged: set,
        );

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Create ticket'),
        content: SizedBox(
          width: 480,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              TextField(key: const Key('ticket-subject'), controller: _subject, decoration: const InputDecoration(labelText: 'Subject')),
              if (_opts == null) const Padding(padding: EdgeInsets.all(8), child: LinearProgressIndicator()),
              if (_opts != null) ...[
                _drop('Priority', _opts!.priorities, _priority, (v) => setState(() => _priority = v)),
                _drop('Team', _opts!.teams, _team, (v) => setState(() => _team = v)),
                _drop('Ticket type', _opts!.ticketTypes, _type, (v) => setState(() => _type = v)),
              ],
              const SizedBox(height: 12),
              Row(children: [
                const Expanded(child: Text('First reply to the customer (optional, sent by e-mail)')),
                TextButton.icon(
                  key: const Key('ticket-saved-reply'),
                  onPressed: _insertSavedReply,
                  icon: const Icon(Icons.bolt_outlined, size: 18),
                  label: const Text('Saved reply'),
                ),
              ]),
              TextField(
                key: const Key('ticket-first-reply'),
                controller: _reply,
                minLines: 3,
                maxLines: 8,
                decoration: const InputDecoration(border: OutlineInputBorder(), hintText: 'Leave empty to only create the ticket'),
              ),
              const SizedBox(height: 8),
              Text('The chat transcript is added to the ticket, and the chat is linked to it. The ticket is assigned to you.',
                  style: Theme.of(context).textTheme.bodySmall),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ),
            ]),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(
            key: const Key('create-ticket-save'),
            onPressed: _saving ? null : _save,
            child: Text(_saving ? 'Creating…' : 'Create ticket'),
          ),
        ],
      );
}
