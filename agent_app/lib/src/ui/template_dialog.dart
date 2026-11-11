import 'package:flutter/material.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../state/controllers.dart';

/// 1.17: pick an approved WhatsApp template, fill in its variables, see the message and send it. Works whether the
/// 24-hour reply window is open or closed. A marketing template needs the customer's recorded opt-in.
class TemplateDialog extends StatefulWidget {
  final ConversationController c;
  const TemplateDialog({super.key, required this.c});

  static Future<void> show(BuildContext context, ConversationController c) =>
      showDialog<void>(context: context, builder: (_) => TemplateDialog(c: c));

  @override
  State<TemplateDialog> createState() => _TemplateDialogState();
}

class _TemplateDialogState extends State<TemplateDialog> {
  WhatsAppTemplates? _data;
  WhatsAppTemplate? _tpl;
  final Map<String, TextEditingController> _fields = {};
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    for (final f in _fields.values) {
      f.dispose();
    }
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final d = await widget.c.api.whatsappTemplates(widget.c.id);
      if (!mounted) return;
      setState(() {
        _data = d;
        _error = null;
        _choose(d.templates.isEmpty ? null : d.templates.first);
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  void _choose(WhatsAppTemplate? t) {
    _tpl = t;
    for (final f in _fields.values) {
      f.dispose();
    }
    _fields.clear();
    for (final v in t?.variables ?? const <TemplateVariable>[]) {
      _fields[v.key] = TextEditingController(text: v.value)..addListener(() => setState(() {}));
    }
  }

  Map<String, String> get _values => {for (final e in _fields.entries) e.key: e.value.text};

  Future<void> _send() async {
    final t = _tpl;
    if (t == null || _busy) return;
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await widget.c.sendTemplate(t.id, _values);
      if (mounted) Navigator.of(context).pop();
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _busy = false;
          _error = e.message;
        });
      }
    }
  }

  Future<void> _recordOptIn() async {
    final note = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Record marketing opt-in'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('Only record this when the customer agreed to receive WhatsApp marketing messages. Say how and when.'),
          TextField(key: const Key('optin-note'), controller: note, autofocus: true, decoration: const InputDecoration(labelText: 'How did they agree?')),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Save opt-in')),
        ],
      ),
    );
    final text = note.text.trim();
    note.dispose();
    if (ok != true || text.isEmpty) return;
    try {
      await widget.c.api.whatsappConsent(widget.c.id, 'Opted In', text);
      await _load();
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = Theme.of(context).colorScheme;
    final d = _data;
    final t = _tpl;
    return AlertDialog(
      title: const Text('Send a WhatsApp template'),
      content: SizedBox(
        width: 520,
        child: d == null
            ? (_error != null ? Text(_error!, style: TextStyle(color: s.error)) : const Center(heightFactor: 2, child: CircularProgressIndicator()))
            : d.templates.isEmpty
                ? const Text('No approved templates yet. Create them in WhatsApp Manager, then ask an administrator to sync them.')
                : SingleChildScrollView(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
                      DropdownButtonFormField<String>(
                        key: const Key('template-select'),
                        initialValue: t?.id,
                        isExpanded: true,
                        decoration: const InputDecoration(labelText: 'Template'),
                        items: [
                          for (final x in d.templates)
                            DropdownMenuItem(value: x.id, child: Text('${x.name} (${x.language}) · ${x.category}', overflow: TextOverflow.ellipsis)),
                        ],
                        onChanged: _busy ? null : (v) => setState(() => _choose(d.templates.firstWhere((x) => x.id == v))),
                      ),
                      const SizedBox(height: 8),
                      if (t != null)
                        for (final v in t.variables)
                          Padding(
                            padding: const EdgeInsets.only(bottom: 8),
                            child: TextField(
                              key: Key('var-${v.key}'),
                              controller: _fields[v.key],
                              enabled: !_busy,
                              decoration: InputDecoration(
                                labelText: '${v.component} {{${v.position}}}',
                                helperText: v.example.isEmpty ? null : 'e.g. ${v.example}',
                              ),
                            ),
                          ),
                      if (t != null)
                        Container(
                          key: const Key('template-preview'),
                          padding: const EdgeInsets.all(10),
                          decoration: BoxDecoration(color: s.surfaceContainerHighest, borderRadius: BorderRadius.circular(8)),
                          child: Text(t.preview(_values)),
                        ),
                      if (t?.blocked != null)
                        Padding(
                          padding: const EdgeInsets.only(top: 8),
                          child: Row(children: [
                            Expanded(
                              child: Text(
                                  t!.blocked == 'opted_out'
                                      ? 'This customer asked to stop marketing messages.'
                                      : 'This is a marketing template and this customer has not agreed to receive marketing messages.',
                                  style: TextStyle(color: s.error)),
                            ),
                            TextButton(key: const Key('record-optin'), onPressed: _recordOptIn, child: const Text('Record opt-in')),
                          ]),
                        ),
                      if (_error != null)
                        Padding(padding: const EdgeInsets.only(top: 8), child: Text(_error!, style: TextStyle(color: s.error))),
                    ]),
                  ),
      ),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.of(context).pop(), child: const Text('Cancel')),
        FilledButton(
          key: const Key('template-send'),
          onPressed: t == null || t.blocked != null || t.needsMedia || _busy ? null : _send,
          child: Text(_busy ? 'Sending…' : 'Send template'),
        ),
      ],
    );
  }
}
