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
  const Bubble({super.key, required this.direction, required this.author, required this.text, this.at, this.footer, this.failed = false});

  @override
  Widget build(BuildContext context) {
    final s = Theme.of(context).colorScheme;
    final note = direction == MessageDirection.internal;
    final mine = direction == MessageDirection.outbound;
    final bg = note ? Colors.amber.shade100 : (mine ? s.primaryContainer : s.surfaceContainerHighest);
    final fg = note ? Colors.brown.shade900 : (mine ? s.onPrimaryContainer : s.onSurface);
    return Align(
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
            ]),
            const SizedBox(height: 4),
            SelectableText(text, style: TextStyle(color: fg)),
            if (footer != null) ...[
              const SizedBox(height: 4),
              Text(footer!, style: TextStyle(fontSize: 11, color: failed ? s.error : fg.withValues(alpha: .7))),
            ],
          ]),
        ),
      ),
    );
  }
}
