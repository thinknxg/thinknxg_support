import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../platform/files.dart';
import '../state/controllers.dart';
import 'common.dart';
import 'composer.dart';
import 'pickers.dart';

/// Pick a file for the composer and report problems inline (size, cancelled picker).
Future<void> pickInto(BuildContext context, void Function(UploadFile) attach) async {
  try {
    final f = await FileService.instance.pick();
    if (f != null) attach(f);
  } catch (e) {
    if (context.mounted) ScaffoldMessenger.maybeOf(context)?.showSnackBar(SnackBar(content: Text('$e')));
  }
}

/// Download (access checked by the server) and open with the system viewer.
Future<void> openDownload(BuildContext context, Future<DownloadedFile> Function() fetch) async {
  final messenger = ScaffoldMessenger.maybeOf(context);
  messenger?.showSnackBar(const SnackBar(content: Text('Opening…'), duration: Duration(seconds: 1)));
  try {
    await FileService.instance.open(await fetch());
  } on ApiException catch (e) {
    messenger?.showSnackBar(SnackBar(content: Text(e.message)));
  } catch (e) {
    messenger?.showSnackBar(SnackBar(content: Text('Could not open the file: $e')));
  }
}

/// Timeline, header actions and composer for one conversation.
class ConversationView extends StatefulWidget {
  final ConversationController controller;
  final String me;
  final void Function(String ticketId)? onOpenTicket;
  final void Function(String conversationId)? onOpenConversation;
  final bool showDetailsPanel;
  final FocusNode? composerFocus;

  const ConversationView({
    super.key,
    required this.controller,
    required this.me,
    this.onOpenTicket,
    this.onOpenConversation,
    this.showDetailsPanel = false,
    this.composerFocus,
  });

  @override
  State<ConversationView> createState() => _ConversationViewState();
}

class _ConversationViewState extends State<ConversationView> {
  final _scroll = ScrollController();
  int _lastCount = 0;

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  void _scrollToEndIfNew(int count) {
    if (count == _lastCount) return;
    final first = _lastCount == 0;
    _lastCount = count;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scroll.hasClients) return;
      final nearEnd = _scroll.position.maxScrollExtent - _scroll.position.pixels < 240;
      if (first || nearEnd) _scroll.jumpTo(_scroll.position.maxScrollExtent);
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    return ListenableBuilder(
      listenable: c,
      builder: (context, _) {
        if (c.loading && c.detail == null) return const Center(child: CircularProgressIndicator());
        if (c.detail == null) {
          return EmptyState(Icons.lock_outline, c.error ?? 'This conversation could not be opened.',
              action: TextButton(onPressed: c.load, child: const Text('Try again')));
        }
        final d = c.detail!;
        _scrollToEndIfNew(c.messages.length);
        final thread = Column(children: [
          _Header(
              d: d,
              c: c,
              me: widget.me,
              onOpenTicket: widget.onOpenTicket,
              onDetails: widget.showDetailsPanel
                  ? null
                  : () => showModalBottomSheet(
                        context: context,
                        isScrollControlled: true,
                        builder: (_) => SizedBox(
                          height: MediaQuery.sizeOf(context).height * .75,
                          child: _Details(
                              d: d, c: c, onOpenTicket: widget.onOpenTicket, onOpenConversation: widget.onOpenConversation),
                        ),
                      )),
          if (c.actionError != null) ErrorBanner(c.actionError!),
          Expanded(
            child: ListView.builder(
              controller: _scroll,
              padding: const EdgeInsets.symmetric(vertical: 8),
              itemCount: c.messages.length + 1,
              itemBuilder: (context, i) {
                if (i == 0) {
                  return c.hasMoreBefore
                      ? Center(child: TextButton(onPressed: c.loadEarlier, child: const Text('Load earlier messages')))
                      : const SizedBox(height: 4);
                }
                final m = c.messages[i - 1];
                final failed = m.deliveryStatus == 'Failed';
                return Bubble(
                  direction: m.internal ? MessageDirection.internal : m.direction,
                  author: m.author.isEmpty ? (m.senderType == 'System' ? 'System' : '') : m.author,
                  text: m.text,
                  at: m.createdAt,
                  failed: failed,
                  files: [if (m.attachmentName != null) m.attachmentName!],
                  onOpenFile: (_) => openDownload(context, () => c.api.attachment(m.id)),
                  footer: failed
                      ? 'Not delivered: ${m.deliveryError ?? 'unknown error'}'
                      : (m.deliveryStatus != null && !m.internal ? m.deliveryStatus : null),
                );
              },
            ),
          ),
          Composer(
            draft: c.draft,
            focusNode: widget.composerFocus,
            canReply: d.actions.reply,
            replyDisabledReason: d.isClosed
                ? 'This conversation is closed.'
                : d.whatsappWindowOpen == false
                    ? 'The WhatsApp 24-hour window has closed. Send a template from the web console, or add an internal note.'
                    : null,
            onMode: c.setMode,
            onChanged: c.setText,
            onSend: c.send,
            onAttach: () => pickInto(context, c.attach),
            onRemoveFile: () => c.attach(null),
            onCanned: () async {
              final picked = await CannedPicker.show(context, () => c.api.cannedResponses(channel: d.channel));
              if (picked != null) await c.insertCanned(picked);
            },
          ),
        ]);
        if (!widget.showDetailsPanel) return thread;
        return Row(children: [
          Expanded(child: thread),
          const VerticalDivider(width: 1),
          SizedBox(
              width: 300,
              child: _Details(d: d, c: c, onOpenTicket: widget.onOpenTicket, onOpenConversation: widget.onOpenConversation)),
        ]);
      },
    );
  }
}

class _Header extends StatelessWidget {
  final ConversationSummary d;
  final ConversationController c;
  final String me;
  final void Function(String)? onOpenTicket;
  final VoidCallback? onDetails;
  const _Header({required this.d, required this.c, required this.me, this.onOpenTicket, this.onDetails});

  @override
  Widget build(BuildContext context) {
    final a = d.actions;
    final mine = d.assignee?.user == me;
    return Material(
      color: Theme.of(context).colorScheme.surfaceContainerLow,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 8, 10),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(channelIcon(d.channel), size: 20),
            const SizedBox(width: 8),
            Expanded(
              child: Text(d.displayName,
                  style: Theme.of(context).textTheme.titleMedium, maxLines: 1, overflow: TextOverflow.ellipsis),
            ),
            if (c.busy) const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
            PopupMenuButton<String>(
              tooltip: 'More actions',
              enabled: !c.busy,
              onSelected: (v) => _menu(context, v),
              itemBuilder: (_) => [
                if (a.transfer) const PopupMenuItem(value: 'transfer', child: Text('Transfer…')),
                if (a.takeOver) const PopupMenuItem(value: 'take_over', child: Text('Take over from assistant')),
                if (a.returnToAssistant) const PopupMenuItem(value: 'return', child: Text('Return to assistant')),
                if (d.ticket != null && onOpenTicket != null) PopupMenuItem(value: 'ticket', child: Text('Open ticket #${d.ticket}')),
                if (onDetails != null) const PopupMenuItem(value: 'details', child: Text('Details and history')),
              ],
            ),
          ]),
          const SizedBox(height: 6),
          Wrap(spacing: 8, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
            StatusPill(conversationStatusLabel(d), color: conversationStatusColor(context, d)),
            if (c.live.customerTyping)
              Text('Customer is typing…', key: const Key('typing'), style: TextStyle(color: Theme.of(context).colorScheme.primary))
            else if (c.live.aiDrafting)
              Text('Assistant is writing…', style: Theme.of(context).textTheme.bodySmall)
            else if (d.channel == 'Live Chat')
              Text(c.live.visitorOnline ? '● Visitor online' : '○ Visitor away',
                  style: TextStyle(fontSize: 12, color: c.live.visitorOnline ? Colors.green.shade700 : Theme.of(context).colorScheme.outline)),
            Text(d.channel, style: Theme.of(context).textTheme.bodySmall),
            Text(d.assignee == null ? 'Unassigned' : (mine ? 'Assigned to you' : 'Assigned to ${d.assignee!.name}'),
                style: Theme.of(context).textTheme.bodySmall),
            if (d.ticket != null)
              ActionChip(
                avatar: const Icon(Icons.confirmation_number_outlined, size: 16),
                label: Text('Ticket #${d.ticket}'),
                onPressed: onOpenTicket == null ? null : () => onOpenTicket!(d.ticket!),
              ),
            if (a.claim)
              FilledButton.tonalIcon(
                key: const Key('claim'),
                onPressed: c.busy ? null : c.claim,
                icon: const Icon(Icons.pan_tool_alt_outlined, size: 18),
                label: Text(d.assignee == null ? 'Claim' : 'Claim from ${d.assignee!.name}'),
              ),
            if (a.close)
              OutlinedButton.icon(
                onPressed: c.busy ? null : () => _close(context),
                icon: const Icon(Icons.check_circle_outline, size: 18),
                label: const Text('End chat'),
              ),
          ]),
        ]),
      ),
    );
  }

  Future<void> _menu(BuildContext context, String v) async {
    switch (v) {
      case 'take_over':
        await c.takeOver();
      case 'return':
        await c.returnToAssistant();
      case 'ticket':
        onOpenTicket?.call(d.ticket!);
      case 'details':
        onDetails?.call();
      case 'transfer':
        final r = await TransferPicker.show(context, c.transferTargets);
        if (r != null) await c.transfer(user: r.user, queue: r.queue);
    }
  }

  Future<void> _close(BuildContext context) async {
    Map<String, dynamic> form = {};
    try {
      form = await c.api.closingForm();
    } catch (_) {}
    if (!context.mounted) return;
    final r = await showDialog<Map<String, Object?>>(context: context, builder: (_) => _CloseDialog(form: form));
    if (r != null) {
      await c.close(
          reason: r['reason'] as String?,
          notes: r['notes'] as String?,
          answers: (r['answers'] as Map?)?.cast<String, Object?>(),
          sendClosingMessage: r['send'] != false);
    }
  }
}

/// Wrap-up: closing reason, notes and the site's closing questions (Support Chat Closing Question).
class _CloseDialog extends StatefulWidget {
  final Map<String, dynamic> form;
  const _CloseDialog({required this.form});
  @override
  State<_CloseDialog> createState() => _CloseDialogState();
}

class _CloseDialogState extends State<_CloseDialog> {
  String? _reason;
  final _notes = TextEditingController();
  final Map<String, Object?> _answers = {};
  bool _send = true;
  String? _error;

  List<Map<String, dynamic>> get _questions =>
      [for (final q in (widget.form['questions'] as List? ?? const [])) if (q is Map) Map<String, dynamic>.from(q)];
  List<String> get _reasons => [for (final r in (widget.form['reasons'] as List? ?? const [])) '$r'];

  @override
  void dispose() {
    _notes.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('End chat'),
        content: SizedBox(
          width: 420,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              if (_reasons.isNotEmpty)
                DropdownButtonFormField<String>(
                  initialValue: _reason,
                  decoration: const InputDecoration(labelText: 'Closing reason'),
                  items: [for (final r in _reasons) DropdownMenuItem(value: r, child: Text(r))],
                  onChanged: (v) => setState(() => _reason = v),
                ),
              for (final q in _questions) _question(q),
              TextField(controller: _notes, decoration: const InputDecoration(labelText: 'Notes (staff only)'), maxLines: 3),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                value: _send,
                onChanged: (v) => setState(() => _send = v ?? true),
                title: const Text('Send the closing message to the customer'),
              ),
              if (_error != null) Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ]),
          ),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(onPressed: _submit, child: const Text('End chat')),
        ],
      );

  Widget _question(Map<String, dynamic> q) {
    final key = '${q['idx'] ?? q['question']}';
    final label = '${q['question'] ?? key}${q['required'] == 1 || q['required'] == true ? ' *' : ''}';
    final options = [for (final o in (q['options'] as List? ?? const [])) '$o'];
    if (options.isNotEmpty) {
      return DropdownButtonFormField<String>(
        initialValue: _answers[key] as String?,
        decoration: InputDecoration(labelText: label),
        items: [for (final o in options) DropdownMenuItem(value: o, child: Text(o))],
        onChanged: (v) => setState(() => _answers[key] = v),
      );
    }
    return TextField(decoration: InputDecoration(labelText: label), onChanged: (v) => _answers[key] = v);
  }

  void _submit() {
    if ((widget.form['require_reason'] == 1 || widget.form['require_reason'] == true) && _reasons.isNotEmpty && _reason == null) {
      setState(() => _error = 'Choose a closing reason.');
      return;
    }
    for (final q in _questions) {
      final key = '${q['idx'] ?? q['question']}';
      if ((q['required'] == 1 || q['required'] == true) && '${_answers[key] ?? ''}'.trim().isEmpty) {
        setState(() => _error = 'Answer "${q['question']}".');
        return;
      }
    }
    Navigator.pop(context, {'reason': _reason, 'notes': _notes.text.trim(), 'answers': _answers, 'send': _send});
  }
}

class _Details extends StatefulWidget {
  final ConversationSummary d;
  final ConversationController c;
  final void Function(String)? onOpenTicket;
  final void Function(String)? onOpenConversation;
  const _Details({required this.d, required this.c, this.onOpenTicket, this.onOpenConversation});
  @override
  State<_Details> createState() => _DetailsState();
}

class _DetailsState extends State<_Details> {
  @override
  void initState() {
    super.initState();
    if (widget.c.history == null) widget.c.loadHistory();
  }

  @override
  Widget build(BuildContext context) {
    final d = widget.d;
    final t = Theme.of(context).textTheme;
    Widget row(String k, String? v) => v == null || v.isEmpty
        ? const SizedBox.shrink()
        : Padding(
            padding: const EdgeInsets.only(bottom: 10),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(k, style: t.labelSmall),
              SelectableText(v, style: t.bodyMedium),
            ]),
          );
    return ListenableBuilder(
      listenable: widget.c,
      builder: (context, _) {
        final h = widget.c.history;
        return ListView(padding: const EdgeInsets.all(16), children: [
          Text('Details', style: t.titleSmall),
          const SizedBox(height: 12),
          row('Contact', d.contactName),
          row('Email', d.contactEmail),
          row('Phone', d.contactPhone),
          row('Customer', d.customerName),
          row('Channel', d.channel),
          row('Queue', d.queue),
          row('Assigned to', d.assignee?.name),
          row('Handed over because', d.handoffReason),
          row('Subject', d.subject),
          if (d.ticket != null)
            OutlinedButton.icon(
              onPressed: widget.onOpenTicket == null ? null : () => widget.onOpenTicket!(d.ticket!),
              icon: const Icon(Icons.confirmation_number_outlined),
              label: Text('Ticket #${d.ticket}'),
            ),
          const Divider(height: 32),
          Text('Customer history', style: t.titleSmall),
          const SizedBox(height: 8),
          if (widget.c.historyLoading) const LinearProgressIndicator(),
          if (h != null && h.conversations.isEmpty && h.tickets.isEmpty)
            Text('No earlier conversations or tickets.', style: t.bodySmall),
          if (h != null)
            for (final x in h.conversations)
              ListTile(
                key: Key('history-${x.id}'),
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: Icon(channelIcon(x.channel), size: 18),
                title: Text(x.subject.isEmpty ? x.displayName : x.subject, maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: Text('${conversationStatusLabel(x)} · ${timeAgo(x.lastActivityAt)}'),
                onTap: widget.onOpenConversation == null ? null : () => widget.onOpenConversation!(x.id),
              ),
          if (h != null)
            for (final tk in h.tickets)
              ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: const Icon(Icons.confirmation_number_outlined, size: 18),
                title: Text('#${tk.id} ${tk.subject}', maxLines: 1, overflow: TextOverflow.ellipsis),
                subtitle: Text(tk.status),
                onTap: widget.onOpenTicket == null ? null : () => widget.onOpenTicket!(tk.id),
              ),
        ]);
      },
    );
  }
}
