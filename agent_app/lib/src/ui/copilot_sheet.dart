import 'package:flutter/material.dart';

import '../state/controllers.dart';

/// AI copilot for the open conversation. Everything here is a draft for the agent: "Use" puts text into the
/// composer, where the agent edits and sends it (or not). Only "Add summary note" writes anything, and that is an
/// internal note customers never see.
class CopilotSheet extends StatefulWidget {
  final ConversationController c;
  const CopilotSheet({super.key, required this.c});

  static Future<void> show(BuildContext context, ConversationController c) {
    final wide = MediaQuery.sizeOf(context).width >= 900;
    if (wide) {
      return showDialog(
          context: context,
          builder: (_) => Dialog(
              child: ConstrainedBox(constraints: const BoxConstraints(maxWidth: 560, maxHeight: 640), child: CopilotSheet(c: c))));
    }
    return showModalBottomSheet(
        context: context,
        isScrollControlled: true,
        builder: (_) => SizedBox(height: MediaQuery.sizeOf(context).height * .8, child: CopilotSheet(c: c)));
  }

  @override
  State<CopilotSheet> createState() => _CopilotSheetState();
}

class _CopilotSheetState extends State<CopilotSheet> {
  String? _title;
  Widget? _result;
  bool _busy = false;
  String? _error;

  ConversationController get c => widget.c;

  void _use(String text) {
    c.useDraft(text);
    Navigator.of(context).pop();
  }

  Future<void> _run(String title, String action, Widget Function(Map<String, dynamic>) build,
      {String? text, String? style, String? target}) async {
    setState(() {
      _busy = true;
      _error = null;
      _title = title;
      _result = null;
    });
    final r = await c.copilot(action, text: text, style: style, target: target);
    if (!mounted) return;
    setState(() {
      _busy = false;
      if (r == null) {
        _error = c.actionError ?? 'The AI copilot could not answer.';
      } else {
        _result = build(r);
      }
    });
  }

  Widget _textResult(String text, {bool usable = true}) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        SelectableText(text.isEmpty ? '—' : text),
        if (usable && text.isNotEmpty)
          Align(alignment: Alignment.centerRight, child: FilledButton.tonal(onPressed: () => _use(text), child: const Text('Use in reply'))),
      ]);

  void _suggest() => _run('Suggested replies', 'suggest', (r) {
        final items = [for (final s in (r['suggestions'] as List? ?? const [])) if (s is Map) s];
        final sources = [for (final s in (r['sources'] as List? ?? const [])) if (s is Map) '${s['title']}'];
        if (items.isEmpty) return const Text('No suggestion this time.');
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          for (final s in items)
            Card(
              key: Key('copilot-suggestion-${items.indexOf(s)}'),
              child: Padding(
                padding: const EdgeInsets.all(12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('${s['label']}', style: Theme.of(context).textTheme.labelMedium),
                  const SizedBox(height: 4),
                  SelectableText('${s['text']}'),
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton(onPressed: () => _use('${s['text']}'), child: const Text('Use this')),
                  ),
                ]),
              ),
            ),
          if (sources.isNotEmpty) Text('Based on: ${sources.join(', ')}', style: Theme.of(context).textTheme.bodySmall),
        ]);
      });

  void _rewrite(String style, String label) {
    final draft = c.draft.text.trim();
    if (draft.isEmpty) {
      setState(() => _error = 'Write a draft in the reply box first.');
      return;
    }
    _run(label, 'rewrite', (r) => _textResult('${r['text'] ?? ''}'), text: draft, style: style);
  }

  void _translateDraft() {
    final draft = c.draft.text.trim();
    if (draft.isEmpty) {
      setState(() => _error = 'Write a draft in the reply box first.');
      return;
    }
    final target = c.detail?.language ?? 'ar';
    _run('Draft in the customer\'s language (${target.toUpperCase()})', 'translate', (r) => _textResult('${r['text'] ?? ''}'),
        text: draft, target: target);
  }

  void _translateLast() {
    final last = c.messages.where((m) => m.direction.name == 'inbound').toList();
    if (last.isEmpty) {
      setState(() => _error = 'The customer has not written yet.');
      return;
    }
    final lang = Localizations.maybeLocaleOf(context)?.languageCode ?? 'en';
    _run('Customer\'s last message, translated', 'translate', (r) => _textResult('${r['text'] ?? ''}', usable: false),
        text: last.last.text, target: lang);
  }

  void _summarize() => _run('Summary', 'summarize', (r) => _textResult('${r['summary'] ?? ''}', usable: false));

  void _recommend() => _run('Recommended', 'recommend', (r) {
        final fu = [for (final q in (r['follow_ups'] as List? ?? const [])) '$q'];
        final arts = [for (final a in (r['articles'] as List? ?? const [])) if (a is Map) a];
        final t = Theme.of(context).textTheme;
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          SelectableText('${r['solution'] ?? ''}'.isEmpty ? 'No recommendation from the knowledge base.' : '${r['solution']}'),
          if (fu.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text('Questions to ask', style: t.titleSmall),
            for (final q in fu)
              ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                title: Text(q),
                trailing: TextButton(onPressed: () => _use(q), child: const Text('Ask')),
              ),
          ],
          if (arts.isNotEmpty) ...[
            const SizedBox(height: 12),
            Text('Knowledge base', style: t.titleSmall),
            for (final a in arts)
              ListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                leading: Icon(a['used'] == true ? Icons.check_circle : Icons.article_outlined, size: 18),
                title: Text('${a['title']}'),
                subtitle: Text('${a['excerpt'] ?? ''}', maxLines: 2, overflow: TextOverflow.ellipsis),
              ),
          ],
        ]);
      });

  Future<void> _note() async {
    await _run('Summary note', 'note', (r) => _textResult('Added as an internal note:\n\n${r['summary'] ?? ''}', usable: false));
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    Widget action(String key, IconData icon, String label, VoidCallback onTap) => ActionChip(
          key: Key('copilot-$key'),
          avatar: Icon(icon, size: 18),
          label: Text(label),
          onPressed: _busy ? null : onTap,
        );
    final d = c.detail;
    return Padding(
      padding: const EdgeInsets.all(16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          const Icon(Icons.auto_awesome),
          const SizedBox(width: 8),
          Expanded(child: Text('AI copilot', style: t.titleMedium)),
          IconButton(tooltip: 'Close', icon: const Icon(Icons.close), onPressed: () => Navigator.of(context).pop()),
        ]),
        Text('Drafts only: nothing is sent until you send it.', style: t.bodySmall),
        if (d != null && (d.sentiment != null || d.intent != null))
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              [
                if (d.sentiment != null) 'Mood: ${d.sentiment}',
                if (d.urgency != null) 'Urgency: ${d.urgency}',
                if (d.intent != null) 'Intent: ${d.intent}',
                if (d.language != null) 'Language: ${d.language!.toUpperCase()}',
              ].join(' · '),
              style: t.bodySmall,
            ),
          ),
        const SizedBox(height: 12),
        Wrap(spacing: 8, runSpacing: 8, children: [
          action('suggest', Icons.lightbulb_outline, 'Suggest replies', _suggest),
          action('professional', Icons.work_outline, 'Rewrite: professional', () => _rewrite('professional', 'Professional')),
          action('friendly', Icons.sentiment_satisfied_alt, 'Rewrite: friendly', () => _rewrite('friendly', 'Friendly')),
          action('concise', Icons.short_text, 'Shorter', () => _rewrite('concise', 'Shorter')),
          action('fix', Icons.spellcheck, 'Fix grammar', () => _rewrite('fix', 'Fixed grammar')),
          action('translate-draft', Icons.translate, 'Translate my draft', _translateDraft),
          action('translate-last', Icons.g_translate, 'Translate customer', _translateLast),
          action('recommend', Icons.menu_book_outlined, 'Recommend', _recommend),
          action('summarize', Icons.summarize_outlined, 'Summarise', _summarize),
          action('note', Icons.note_add_outlined, 'Add summary note', _note),
        ]),
        const Divider(height: 24),
        if (_title != null) Text(_title!, style: t.titleSmall),
        const SizedBox(height: 8),
        Expanded(
          child: _busy
              ? const Center(child: CircularProgressIndicator())
              : _error != null
                  ? Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))
                  : SingleChildScrollView(child: _result ?? Text('Pick an action above.', style: t.bodySmall)),
        ),
      ]),
    );
  }
}
