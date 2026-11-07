import 'package:flutter/material.dart';

import '../api/models.dart';

/// Canned responses: type to filter by title, shortcut or text; Enter picks the first match.
class CannedPicker extends StatefulWidget {
  final Future<List<CannedResponse>> Function() load;
  final String title;
  const CannedPicker({super.key, required this.load, this.title = 'Canned responses'});

  static Future<CannedResponse?> show(BuildContext context, Future<List<CannedResponse>> Function() load,
          {String title = 'Canned responses'}) =>
      showDialog<CannedResponse>(context: context, builder: (_) => CannedPicker(load: load, title: title));

  @override
  State<CannedPicker> createState() => _CannedPickerState();
}

class _CannedPickerState extends State<CannedPicker> {
  late final Future<List<CannedResponse>> _items = widget.load();
  String _q = '';

  List<CannedResponse> _filter(List<CannedResponse> all) {
    final q = _q.trim().toLowerCase().replaceFirst(RegExp(r'^/'), '');
    if (q.isEmpty) return all;
    return all
        .where((c) =>
            c.title.toLowerCase().contains(q) ||
            (c.shortcut ?? '').toLowerCase().startsWith(q) ||
            c.preview.toLowerCase().contains(q))
        .toList();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Text(widget.title),
        content: SizedBox(
          width: 480,
          height: 420,
          child: FutureBuilder<List<CannedResponse>>(
            future: _items,
            builder: (context, snap) {
              if (snap.hasError) return Center(child: Text('${snap.error}'));
              if (!snap.hasData) return const Center(child: CircularProgressIndicator());
              final list = _filter(snap.data!);
              final empty = snap.data!.isEmpty ? 'None set up yet.' : 'Nothing matches.';
              return Column(children: [
                TextField(
                  key: const Key('canned-search'),
                  autofocus: true,
                  decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Search or type a /shortcut'),
                  onChanged: (v) => setState(() => _q = v),
                  onSubmitted: (_) {
                    if (list.isNotEmpty) Navigator.pop(context, list.first);
                  },
                ),
                const SizedBox(height: 8),
                Expanded(
                  child: list.isEmpty
                      ? Center(child: Text(empty))
                      : ListView.separated(
                          itemCount: list.length,
                          separatorBuilder: (_, __) => const Divider(height: 1),
                          itemBuilder: (context, i) {
                            final c = list[i];
                            return ListTile(
                              key: Key('canned-${c.id}'),
                              title: Text(c.title),
                              subtitle: Text(c.preview, maxLines: 2, overflow: TextOverflow.ellipsis),
                              trailing: c.shortcut == null || c.shortcut!.isEmpty
                                  ? (c.category == null ? null : Text(c.category!, style: Theme.of(context).textTheme.bodySmall))
                                  : Text('/${c.shortcut}'),
                              onTap: () => Navigator.pop(context, c),
                            );
                          },
                        ),
                ),
              ]);
            },
          ),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel'))],
      );
}

/// Transfer to an agent (online first, with their open chats) or to a queue.
class TransferPicker extends StatefulWidget {
  final Future<TransferTargets?> Function() load;
  const TransferPicker({super.key, required this.load});

  static Future<({String? user, String? queue})?> show(BuildContext context, Future<TransferTargets?> Function() load) =>
      showDialog<({String? user, String? queue})>(context: context, builder: (_) => TransferPicker(load: load));

  @override
  State<TransferPicker> createState() => _TransferPickerState();
}

class _TransferPickerState extends State<TransferPicker> {
  late final Future<TransferTargets?> _t = widget.load();
  String _q = '';

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Transfer conversation'),
        content: SizedBox(
          width: 460,
          height: 460,
          child: FutureBuilder<TransferTargets?>(
            future: _t,
            builder: (context, snap) {
              if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
              final t = snap.data;
              if (t == null) return const Center(child: Text('Could not load agents and queues.'));
              final q = _q.trim().toLowerCase();
              final agents = t.agents.where((a) => q.isEmpty || a.name.toLowerCase().contains(q) || a.user.contains(q)).toList();
              final queues = t.queues.where((x) => q.isEmpty || x.toLowerCase().contains(q)).toList();
              return Column(children: [
                TextField(
                  autofocus: true,
                  decoration: const InputDecoration(prefixIcon: Icon(Icons.search), hintText: 'Find an agent or queue'),
                  onChanged: (v) => setState(() => _q = v),
                ),
                const SizedBox(height: 8),
                Expanded(
                  child: ListView(children: [
                    if (queues.isNotEmpty) const ListTile(dense: true, title: Text('Queues')),
                    for (final x in queues)
                      ListTile(
                        leading: const Icon(Icons.groups_outlined),
                        title: Text(x),
                        trailing: x == t.currentQueue ? const Text('current') : null,
                        onTap: () => Navigator.pop(context, (user: null, queue: x)),
                      ),
                    if (agents.isNotEmpty) const ListTile(dense: true, title: Text('Agents')),
                    for (final a in agents)
                      ListTile(
                        key: Key('transfer-${a.user}'),
                        leading: Icon(Icons.circle, size: 12, color: a.online ? Colors.green : Colors.grey),
                        title: Text(a.name),
                        subtitle: Text('${a.online ? 'Online' : 'Offline'} · ${a.openChats} open'
                            '${a.inQueue ? ' · in this queue' : ''}'),
                        onTap: () => Navigator.pop(context, (user: a.user, queue: null)),
                      ),
                  ]),
                ),
              ]);
            },
          ),
        ),
        actions: [TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel'))],
      );
}
