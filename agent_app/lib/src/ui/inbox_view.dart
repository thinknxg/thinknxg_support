import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/controllers.dart';
import 'common.dart';

/// Conversation list with view, channel, status, queue filters and search.
class InboxView extends StatefulWidget {
  final InboxController controller;
  final List<({String name, bool member})> queues;
  final String? selectedId;
  final ValueChanged<ConversationSummary> onOpen;
  final FocusNode? searchFocus;

  const InboxView({super.key, required this.controller, required this.onOpen, this.queues = const [], this.selectedId, this.searchFocus});

  @override
  State<InboxView> createState() => _InboxViewState();
}

class _InboxViewState extends State<InboxView> {
  final _scroll = ScrollController();
  final _search = TextEditingController();

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      if (_scroll.position.pixels > _scroll.position.maxScrollExtent - 300) widget.controller.loadMore();
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    _search.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    return ListenableBuilder(
      listenable: c,
      builder: (context, _) {
        final f = c.filter;
        return Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
            child: TextField(
              controller: _search,
              focusNode: widget.searchFocus,
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.search),
                hintText: 'Search name, email, number, subject',
                isDense: true,
                border: OutlineInputBorder(borderRadius: BorderRadius.circular(24)),
                suffixIcon: _search.text.isEmpty
                    ? null
                    : IconButton(
                        tooltip: 'Clear search',
                        icon: const Icon(Icons.close),
                        onPressed: () {
                          _search.clear();
                          c.setFilter(f.copyWith(q: ''));
                        }),
              ),
              textInputAction: TextInputAction.search,
              onSubmitted: (v) => c.setFilter(f.copyWith(q: v)),
            ),
          ),
          SizedBox(
            height: 44,
            child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 8), children: [
              for (final v in const [('all', 'All'), ('mine', 'Mine'), ('unassigned', 'Unassigned'), ('waiting', 'Waiting')])
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 3),
                  child: ChoiceChip(
                    label: Text(v.$2),
                    selected: f.view == v.$1,
                    onSelected: (_) => c.setFilter(f.copyWith(view: v.$1)),
                  ),
                ),
            ]),
          ),
          SizedBox(
            height: 44,
            child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 8), children: [
              for (final ch in const ['Portal', 'Live Chat', 'WhatsApp'])
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 3),
                  child: FilterChip(
                    avatar: Icon(channelIcon(ch), size: 16),
                    label: Text(ch),
                    selected: f.channel == ch,
                    onSelected: (on) => c.setFilter(on ? f.copyWith(channel: ch) : f.copyWith(clearChannel: true)),
                  ),
                ),
              const SizedBox(width: 6),
              _Drop<String>(
                label: 'Status',
                value: f.status,
                items: const {'open': 'Open', 'closed': 'Closed', 'all': 'All'},
                onChanged: (v) => c.setFilter(f.copyWith(status: v)),
              ),
              _Drop<String>(
                label: 'Sort',
                value: f.sort,
                items: const {'recent': 'Newest first', 'priority': 'Priority first'},
                onChanged: (v) => c.setFilter(f.copyWith(sort: v)),
              ),
              if (widget.queues.isNotEmpty)
                _Drop<String?>(
                  label: 'Queue',
                  value: f.queue,
                  items: {null: 'All queues', for (final q in widget.queues) q.name: q.member ? '${q.name} (mine)' : q.name},
                  onChanged: (v) => c.setFilter(v == null ? f.copyWith(clearQueue: true) : f.copyWith(queue: v)),
                ),
            ]),
          ),
          if (c.error != null) ErrorBanner(c.error!, onRetry: c.refresh),
          Expanded(
            child: c.loading
                ? const Center(child: CircularProgressIndicator())
                : c.items.isEmpty
                    ? const EmptyState(Icons.inbox_outlined, 'No conversations match these filters.')
                    : RefreshIndicator(
                        onRefresh: c.refresh,
                        child: ListView.separated(
                          controller: _scroll,
                          itemCount: c.items.length + (c.nextCursor != null ? 1 : 0),
                          separatorBuilder: (_, __) => const Divider(height: 1),
                          itemBuilder: (context, i) {
                            if (i >= c.items.length) {
                              return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
                            }
                            final item = c.items[i];
                            return ConversationTile(item, selected: item.id == widget.selectedId, onTap: () => widget.onOpen(item));
                          },
                        ),
                      ),
          ),
        ]);
      },
    );
  }
}

class _Drop<T> extends StatelessWidget {
  final String label;
  final T value;
  final Map<T, String> items;
  final ValueChanged<T> onChanged;
  const _Drop({required this.label, required this.value, required this.items, required this.onChanged});
  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 3),
        child: PopupMenuButton<T>(
          tooltip: label,
          onSelected: onChanged,
          itemBuilder: (_) => [for (final e in items.entries) CheckedPopupMenuItem(value: e.key, checked: e.key == value, child: Text(e.value))],
          child: Chip(label: Text('$label: ${items[value] ?? ''}'), avatar: const Icon(Icons.arrow_drop_down, size: 18)),
        ),
      );
}

class ConversationTile extends StatelessWidget {
  final ConversationSummary c;
  final bool selected;
  final VoidCallback onTap;
  const ConversationTile(this.c, {super.key, required this.onTap, this.selected = false});

  @override
  Widget build(BuildContext context) {
    final s = Theme.of(context).colorScheme;
    final unread = c.unread > 0;
    return Semantics(
      label: '${c.displayName}, ${c.channel}, ${conversationStatusLabel(c)}${unread ? ', ${c.unread} unread' : ''}',
      selected: selected,
      button: true,
      child: ListTile(
        key: Key('conv-${c.id}'),
        selected: selected,
        selectedTileColor: s.primaryContainer.withValues(alpha: .4),
        onTap: onTap,
        leading: CircleAvatar(child: Icon(channelIcon(c.channel), size: 20)),
        title: Row(children: [
          Expanded(
            child: Text(c.displayName,
                maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontWeight: unread ? FontWeight.w700 : FontWeight.w500)),
          ),
          Text(timeAgo(c.lastActivityAt), style: Theme.of(context).textTheme.bodySmall),
        ]),
        subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(c.preview.isEmpty ? c.subject : c.preview, maxLines: 1, overflow: TextOverflow.ellipsis),
          const SizedBox(height: 4),
          Wrap(spacing: 6, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
            StatusPill(conversationStatusLabel(c), color: conversationStatusColor(context, c)),
            if (c.needsAttention)
              StatusPill(c.urgency == 'High' ? 'Urgent' : 'Unhappy', color: Theme.of(context).colorScheme.error),
            if (c.highPriority) StatusPill(c.priority, color: Theme.of(context).colorScheme.error),
            for (final t in c.tags.take(3)) Text('#$t', style: Theme.of(context).textTheme.bodySmall),
            if (c.assignee != null) Text(c.assignee!.name, style: Theme.of(context).textTheme.bodySmall),
            if (c.queue != null) Text('· ${c.queue}', style: Theme.of(context).textTheme.bodySmall),
          ]),
        ]),
        trailing: unread
            ? Badge(label: Text('${c.unread}'), backgroundColor: s.primary, textColor: s.onPrimary)
            : null,
        isThreeLine: true,
      ),
    );
  }
}
