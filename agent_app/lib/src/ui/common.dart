import 'package:flutter/material.dart';

import '../api/models.dart';

const wideBreakpoint = 900.0;
const extraWideBreakpoint = 1280.0;

IconData channelIcon(String channel) => switch (channel) {
      'WhatsApp' => Icons.chat_outlined,
      'Live Chat' => Icons.forum_outlined,
      _ => Icons.language_outlined,
    };

String timeAgo(DateTime? t, [DateTime? now]) {
  if (t == null) return '';
  final d = (now ?? DateTime.now()).difference(t.toLocal());
  if (d.inSeconds < 60) return 'now';
  if (d.inMinutes < 60) return '${d.inMinutes}m';
  if (d.inHours < 24) return '${d.inHours}h';
  if (d.inDays < 7) return '${d.inDays}d';
  final l = t.toLocal();
  return '${l.day}/${l.month}/${l.year}';
}

String clock(DateTime? t) {
  if (t == null) return '';
  final l = t.toLocal();
  return '${l.hour.toString().padLeft(2, '0')}:${l.minute.toString().padLeft(2, '0')}';
}

class StatusPill extends StatelessWidget {
  final String label;
  final Color? color;
  const StatusPill(this.label, {super.key, this.color});
  @override
  Widget build(BuildContext context) {
    final c = color ?? Theme.of(context).colorScheme.secondary;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(color: c.withValues(alpha: .12), borderRadius: BorderRadius.circular(20)),
      child: Text(label, style: TextStyle(color: c, fontSize: 12, fontWeight: FontWeight.w600)),
    );
  }
}

Color conversationStatusColor(BuildContext context, ConversationSummary c) {
  final s = Theme.of(context).colorScheme;
  if (c.isClosed) return s.outline;
  if (c.handling == 'Queued' && c.assignee == null) return Colors.orange.shade800;
  if (c.handling == 'Bot') return s.tertiary;
  return s.primary;
}

String conversationStatusLabel(ConversationSummary c) {
  if (c.isClosed) return 'Closed';
  if (c.handling == 'Bot') return 'Assistant';
  if (c.handling == 'Queued' && c.assignee == null) return 'Waiting for agent';
  return c.status == 'Waiting' ? 'Replied' : 'Open';
}

class EmptyState extends StatelessWidget {
  final IconData icon;
  final String text;
  final Widget? action;
  const EmptyState(this.icon, this.text, {super.key, this.action});
  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon, size: 40, color: Theme.of(context).colorScheme.outline),
            const SizedBox(height: 12),
            Text(text, textAlign: TextAlign.center, style: Theme.of(context).textTheme.bodyMedium),
            if (action != null) ...[const SizedBox(height: 12), action!],
          ]),
        ),
      );
}

class ErrorBanner extends StatelessWidget {
  final String message;
  final VoidCallback? onRetry;
  const ErrorBanner(this.message, {super.key, this.onRetry});
  @override
  Widget build(BuildContext context) {
    final s = Theme.of(context).colorScheme;
    return Semantics(
      liveRegion: true,
      child: Container(
        width: double.infinity,
        color: s.errorContainer,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(children: [
          Icon(Icons.error_outline, color: s.onErrorContainer, size: 18),
          const SizedBox(width: 8),
          Expanded(child: Text(message, style: TextStyle(color: s.onErrorContainer))),
          if (onRetry != null) TextButton(onPressed: onRetry, child: const Text('Retry')),
        ]),
      ),
    );
  }
}

/// A message bubble. Customer on the left; agent replies on the right; internal notes full width and amber.
class Bubble extends StatelessWidget {
  final MessageDirection direction;
  final String author;
  final String text;
  final DateTime? at;
  final String? footer;
  final bool failed;
  final List<String> files;
  final void Function(int index)? onOpenFile;
  // 1.14
  final ReplyRef? quote;
  final bool edited;
  final bool removed;
  final String? removedBy;
  final List<Reaction> reactions;
  final void Function(String emoji)? onReact;
  final Widget? media;
  final VoidCallback? onMenu;
  final Key? menuKey;
  const Bubble(
      {super.key,
      required this.direction,
      required this.author,
      required this.text,
      this.at,
      this.footer,
      this.failed = false,
      this.files = const [],
      this.onOpenFile,
      this.quote,
      this.edited = false,
      this.removed = false,
      this.removedBy,
      this.reactions = const [],
      this.onReact,
      this.media,
      this.onMenu,
      this.menuKey});

  @override
  Widget build(BuildContext context) {
    final s = Theme.of(context).colorScheme;
    final note = direction == MessageDirection.internal;
    final mine = direction == MessageDirection.outbound;
    final bg = note ? Colors.amber.shade100 : (mine ? s.primaryContainer : s.surfaceContainerHighest);
    final fg = note ? Colors.brown.shade900 : (mine ? s.onPrimaryContainer : s.onSurface);
    final bubble = Align(
      alignment: note ? Alignment.center : (mine ? Alignment.centerRight : Alignment.centerLeft),
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: note ? 720 : 560),
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 4, horizontal: 12),
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
          decoration: BoxDecoration(
            color: bg,
            borderRadius: BorderRadius.circular(12),
            border: note ? Border.all(color: Colors.amber.shade700) : (failed ? Border.all(color: s.error) : null),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(mainAxisSize: MainAxisSize.min, children: [
              if (note) Icon(Icons.lock_outline, size: 14, color: fg),
              if (note) const SizedBox(width: 4),
              Flexible(
                child: Text(note ? 'Internal note · $author' : author,
                    style: TextStyle(fontSize: 12, fontWeight: FontWeight.w600, color: fg), overflow: TextOverflow.ellipsis),
              ),
              const SizedBox(width: 8),
              Text(clock(at), style: TextStyle(fontSize: 11, color: fg.withValues(alpha: .7))),
              if (edited) Text(' · edited', style: TextStyle(fontSize: 11, color: fg.withValues(alpha: .7))),
              if (onMenu != null)
                InkWell(
                  key: menuKey,
                  onTap: onMenu,
                  customBorder: const CircleBorder(),
                  child: Padding(
                      padding: const EdgeInsets.only(left: 6),
                      child: Icon(Icons.more_horiz, size: 16, color: fg.withValues(alpha: .7), semanticLabel: 'Message actions')),
                ),
            ]),
            const SizedBox(height: 4),
            if (quote != null)
              Container(
                margin: const EdgeInsets.only(bottom: 4),
                padding: const EdgeInsets.fromLTRB(8, 2, 8, 2),
                decoration: BoxDecoration(
                    border: Border(left: BorderSide(color: s.primary, width: 3)),
                    color: fg.withValues(alpha: .06),
                    borderRadius: BorderRadius.circular(4)),
                child: Text('${quote!.author}: ${quote!.excerpt}',
                    maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, color: fg.withValues(alpha: .8))),
              ),
            if (text.isNotEmpty)
              SelectableText(text,
                  style: TextStyle(
                      color: removed ? fg.withValues(alpha: .5) : fg, decoration: removed ? TextDecoration.lineThrough : null)),
            if (removed)
              Text('Removed${removedBy == null ? '' : ' by $removedBy'}: the customer sees "Message removed"',
                  key: const Key('removed-label'), style: TextStyle(fontSize: 11, color: s.error)),
            if (media != null) Padding(padding: const EdgeInsets.only(top: 4), child: media!),
            for (var i = 0; i < files.length; i++)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: ActionChip(
                  avatar: const Icon(Icons.description_outlined, size: 16),
                  label: Text(files[i], overflow: TextOverflow.ellipsis),
                  tooltip: 'Open ${files[i]}',
                  onPressed: onOpenFile == null ? null : () => onOpenFile!(i),
                ),
              ),
            if (reactions.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Wrap(spacing: 4, runSpacing: 4, children: [
                  for (final r in reactions)
                    InkWell(
                      onTap: onReact == null ? null : () => onReact!(r.emoji),
                      borderRadius: BorderRadius.circular(999),
                      child: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                        decoration: BoxDecoration(
                            borderRadius: BorderRadius.circular(999),
                            border: Border.all(color: r.mine ? s.primary : fg.withValues(alpha: .25))),
                        child: Text('${r.emoji} ${r.count}', style: const TextStyle(fontSize: 12)),
                      ),
                    ),
                ]),
              ),
            if (footer != null) ...[
              const SizedBox(height: 4),
              Text(footer!, style: TextStyle(fontSize: 11, color: failed ? s.error : fg.withValues(alpha: .7))),
            ],
          ]),
        ),
      ),
    );
    if (onMenu == null) return bubble;
    return GestureDetector(onLongPress: onMenu, onSecondaryTap: onMenu, child: bubble);
  }
}
