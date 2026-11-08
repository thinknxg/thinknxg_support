import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/models.dart';
import '../state/controllers.dart';

/// 1.14: what an agent can do with one message: reply, react, edit, remove, see earlier versions, copy.
/// Opened by a long press (touch) or right-click (desktop). The server checks every action again.
Future<void> showMessageActions(BuildContext context, ConversationController c, ChatMessage m, MessagingCaps caps) async {
  if (m.senderType == 'System' && m.direction != MessageDirection.internal) return;
  final choice = await showModalBottomSheet<String>(
    context: context,
    showDragHandle: true,
    builder: (ctx) => SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (caps.reactions.isNotEmpty && !m.removed)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
            child: Wrap(spacing: 8, children: [
              for (final e in caps.reactions)
                ActionChip(
                  key: Key('react-$e'),
                  label: Text(e, style: const TextStyle(fontSize: 20)),
                  onPressed: () => Navigator.pop(ctx, 'react:$e'),
                ),
            ]),
          ),
        if (!m.removed)
          ListTile(
              key: const Key('msg-reply'),
              leading: const Icon(Icons.reply),
              title: const Text('Reply'),
              onTap: () => Navigator.pop(ctx, 'reply')),
        if (m.canEdit)
          ListTile(
              key: const Key('msg-edit'),
              leading: const Icon(Icons.edit_outlined),
              title: const Text('Edit'),
              onTap: () => Navigator.pop(ctx, 'edit')),
        if (m.canRemove)
          ListTile(
              key: const Key('msg-remove'),
              leading: const Icon(Icons.delete_outline),
              title: const Text('Remove'),
              subtitle: const Text('The customer sees "Message removed"; the text is kept for staff'),
              onTap: () => Navigator.pop(ctx, 'remove')),
        if (m.edited)
          ListTile(
              key: const Key('msg-history'),
              leading: const Icon(Icons.history),
              title: const Text('Earlier versions'),
              onTap: () => Navigator.pop(ctx, 'history')),
        if (m.text.isNotEmpty)
          ListTile(leading: const Icon(Icons.copy), title: const Text('Copy text'), onTap: () => Navigator.pop(ctx, 'copy')),
      ]),
    ),
  );
  if (choice == null || !context.mounted) return;
  if (choice.startsWith('react:')) {
    await c.react(m, choice.substring(6));
  } else if (choice == 'reply') {
    c.startReply(m);
  } else if (choice == 'edit') {
    final text = await _editDialog(context, m.text);
    if (text != null && text.trim().isNotEmpty && text.trim() != m.text.trim()) await c.editMessage(m, text);
  } else if (choice == 'remove') {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Remove this message?'),
        content: const Text('The customer will see "Message removed". You and other staff keep the text.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(key: const Key('confirm-remove'), onPressed: () => Navigator.pop(ctx, true), child: const Text('Remove')),
        ],
      ),
    );
    if (ok == true) await c.removeMessage(m);
  } else if (choice == 'history') {
    final rows = await c.messageHistory(m);
    if (!context.mounted) return;
    await showDialog<void>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Earlier versions'),
        content: SizedBox(
          width: 420,
          child: ListView(shrinkWrap: true, children: [
            for (final h in rows)
              ListTile(title: Text('${h['text'] ?? ''}'), subtitle: Text('${h['edited_by'] ?? ''} · ${h['edited_on'] ?? ''}')),
            if (rows.isEmpty) const Text('No earlier versions.'),
          ]),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Close'))],
      ),
    );
  } else if (choice == 'copy') {
    await Clipboard.setData(ClipboardData(text: m.text));
  }
}

Future<String?> _editDialog(BuildContext context, String current) {
  final ctl = TextEditingController(text: current);
  return showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: const Text('Edit message'),
      content: SizedBox(
        width: 480,
        child: TextField(key: const Key('edit-field'), controller: ctl, autofocus: true, minLines: 2, maxLines: 8),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
        FilledButton(key: const Key('edit-save'), onPressed: () => Navigator.pop(ctx, ctl.text), child: const Text('Save')),
      ],
    ),
  );
}
