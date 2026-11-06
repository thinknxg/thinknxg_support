import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/controllers.dart';
import 'common.dart';
import 'composer.dart';
import 'conversation_view.dart' show openDownload, pickInto;

class TicketListView extends StatefulWidget {
  final TicketsController controller;
  final String? selectedId;
  final ValueChanged<Ticket> onOpen;
  const TicketListView({super.key, required this.controller, required this.onOpen, this.selectedId});
  @override
  State<TicketListView> createState() => _TicketListViewState();
}

class _TicketListViewState extends State<TicketListView> {
  final _search = TextEditingController();
  final _scroll = ScrollController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels > _scroll.position.maxScrollExtent - 300) widget.controller.loadMore();
    });
  }

  @override
  void dispose() {
    _search.dispose();
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    return ListenableBuilder(
      listenable: c,
      builder: (context, _) => Column(children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: TextField(
            controller: _search,
            decoration: InputDecoration(
              prefixIcon: const Icon(Icons.search),
              hintText: 'Search tickets',
              isDense: true,
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(24)),
            ),
            textInputAction: TextInputAction.search,
            onSubmitted: (v) => c.setView(q: v),
          ),
        ),
        SizedBox(
          height: 44,
          child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 8), children: [
            for (final v in const [('mine', 'Mine'), ('unassigned', 'Unassigned'), ('all', 'All I can see')])
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 3),
                child: ChoiceChip(label: Text(v.$2), selected: c.view == v.$1, onSelected: (_) => c.setView(view: v.$1)),
              ),
            const SizedBox(width: 8),
            for (final v in const [('open', 'Open'), ('closed', 'Resolved'), ('', 'Any status')])
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 3),
                child: ChoiceChip(label: Text(v.$2), selected: c.status == v.$1, onSelected: (_) => c.setView(status: v.$1)),
              ),
          ]),
        ),
        if (c.error != null) ErrorBanner(c.error!, onRetry: c.refresh),
        Expanded(
          child: c.loading
              ? const Center(child: CircularProgressIndicator())
              : c.items.isEmpty
                  ? const EmptyState(Icons.confirmation_number_outlined, 'No tickets here.')
                  : RefreshIndicator(
                      onRefresh: c.refresh,
                      child: ListView.separated(
                        controller: _scroll,
                        itemCount: c.items.length,
                        separatorBuilder: (_, __) => const Divider(height: 1),
                        itemBuilder: (context, i) {
                          final t = c.items[i];
                          return ListTile(
                            key: Key('ticket-${t.id}'),
                            selected: t.id == widget.selectedId,
                            onTap: () => widget.onOpen(t),
                            title: Text('#${t.id} ${t.subject}',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: TextStyle(fontWeight: t.unread ? FontWeight.w700 : FontWeight.w500)),
                            subtitle: Wrap(spacing: 8, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
                              StatusPill(t.status),
                              if (t.priority != null) Text(t.priority!, style: Theme.of(context).textTheme.bodySmall),
                              Text(t.raisedBy ?? '', style: Theme.of(context).textTheme.bodySmall),
                              if (t.slaStatus != null) Text('SLA: ${t.slaStatus}', style: Theme.of(context).textTheme.bodySmall),
                            ]),
                            trailing: Text(timeAgo(DateTime.tryParse(t.modified)), style: Theme.of(context).textTheme.bodySmall),
                          );
                        },
                      ),
                    ),
        ),
      ]),
    );
  }
}

/// One Helpdesk ticket.
class TicketView extends StatelessWidget {
  final TicketController controller;
  final String me;
  final void Function(String conversationId)? onOpenConversation;
  final FocusNode? composerFocus;
  const TicketView({super.key, required this.controller, required this.me, this.onOpenConversation, this.composerFocus});

  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: controller,
        builder: (context, _) {
          final c = controller;
          if (c.loading && c.ticket == null) return const Center(child: CircularProgressIndicator());
          final t = c.ticket;
          if (t == null) {
            return EmptyState(Icons.lock_outline, c.error ?? 'This ticket could not be opened.',
                action: TextButton(onPressed: c.load, child: const Text('Try again')));
          }
          final tt = Theme.of(context).textTheme;
          final assigned = t.assignees.map((a) => a.user == me ? 'You' : a.name).join(', ');
          return Column(children: [
            Material(
              color: Theme.of(context).colorScheme.surfaceContainerLow,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('#${t.id} ${t.subject}', style: tt.titleMedium, maxLines: 2, overflow: TextOverflow.ellipsis),
                  const SizedBox(height: 6),
                  Wrap(spacing: 8, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
                    PopupMenuButton<String>(
                      key: const Key('ticket-status'),
                      tooltip: 'Change status',
                      enabled: t.canWrite && !c.busy,
                      onSelected: (s) => c.update(status: s),
                      itemBuilder: (_) => [
                        for (final s in t.statuses) CheckedPopupMenuItem(value: s.name, checked: s.name == t.status, child: Text(s.label)),
                      ],
                      child: Chip(avatar: const Icon(Icons.arrow_drop_down, size: 18), label: Text('Status: ${t.status}')),
                    ),
                    PopupMenuButton<String>(
                      tooltip: 'Change priority',
                      enabled: t.canWrite && !c.busy && t.priorities.isNotEmpty,
                      onSelected: (p) => c.update(priority: p),
                      itemBuilder: (_) => [
                        for (final p in t.priorities) CheckedPopupMenuItem(value: p, checked: p == t.priority, child: Text(p)),
                      ],
                      child: Chip(avatar: const Icon(Icons.arrow_drop_down, size: 18), label: Text('Priority: ${t.priority ?? '-'}')),
                    ),
                    if (t.teams.isNotEmpty)
                      PopupMenuButton<String>(
                        key: const Key('ticket-team'),
                        tooltip: 'Change team',
                        enabled: t.canWrite && !c.busy,
                        onSelected: (x) => c.update(team: x),
                        itemBuilder: (_) => [
                          for (final x in t.teams) CheckedPopupMenuItem(value: x, checked: x == t.team, child: Text(x)),
                        ],
                        child: Chip(avatar: const Icon(Icons.arrow_drop_down, size: 18), label: Text('Team: ${t.team ?? '-'}')),
                      ),
                    Text(assigned.isEmpty ? 'Unassigned' : 'Owner: $assigned', style: tt.bodySmall),
                    if (t.canWrite && !t.assignees.any((a) => a.user == me))
                      TextButton(onPressed: c.busy ? null : () => c.assignToMe(me), child: const Text('Assign to me')),
                    if (t.linkedConversation != null && onOpenConversation != null)
                      ActionChip(
                        avatar: const Icon(Icons.forum_outlined, size: 16),
                        label: const Text('Open conversation'),
                        onPressed: () => onOpenConversation!(t.linkedConversation!),
                      ),
                    if (c.busy) const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)),
                  ]),
                  const SizedBox(height: 4),
                  Wrap(spacing: 12, children: [
                    if (t.raisedBy != null) Text('From ${t.raisedBy}', style: tt.bodySmall),
                    if (t.responseBy != null) Text('Respond by ${_fmt(t.responseBy!)}', style: tt.bodySmall),
                    if (t.resolutionBy != null) Text('Resolve by ${_fmt(t.resolutionBy!)}', style: tt.bodySmall),
                    if (t.slaStatus != null) Text('SLA ${t.slaStatus}', style: tt.bodySmall),
                  ]),
                ]),
              ),
            ),
            if (c.actionError != null) ErrorBanner(c.actionError!),
            Expanded(
              child: ListView(padding: const EdgeInsets.symmetric(vertical: 8), children: [
                if (t.description.isNotEmpty)
                  Bubble(direction: MessageDirection.inbound, author: t.raisedBy ?? 'Customer', text: htmlToText(t.description), at: t.createdAt),
                for (final i in c.timeline)
                  Bubble(
                    direction: i.internal ? MessageDirection.internal : i.direction,
                    author: i.author,
                    text: i.text,
                    at: i.createdAt,
                    files: [for (final f in i.attachments) f.name],
                    onOpenFile: (n) => openDownload(context, () => c.api.ticketAttachment(t.id, i.attachments[n].id)),
                  ),
              ]),
            ),
            Composer(
              draft: c.draft,
              focusNode: composerFocus,
              canReply: t.canWrite,
              replyLabel: 'Reply to customer (email)',
              replyDisabledReason: t.canWrite ? null : 'You can read this ticket but not reply to it.',
              onMode: c.setMode,
              onChanged: (v) => c.draft.text = v,
              onSend: c.send,
              onAttach: c.draft.mode == ComposerMode.reply ? () => pickInto(context, c.attach) : null,
              onRemoveFile: () => c.attach(null),
            ),
          ]);
        },
      );

  static String _fmt(DateTime d) {
    final l = d.toLocal();
    return '${l.day}/${l.month} ${clock(l)}';
  }
}
