import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/controllers.dart';
import 'common.dart';

class AlertsView extends StatelessWidget {
  final AlertsController controller;
  final ValueChanged<AgentAlert> onOpen;
  const AlertsView({super.key, required this.controller, required this.onOpen});

  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: controller,
        builder: (context, _) {
          final c = controller;
          return Column(children: [
            if (c.error != null) ErrorBanner(c.error!, onRetry: c.refresh),
            Align(
              alignment: Alignment.centerLeft,
              child: Padding(
                padding: const EdgeInsets.fromLTRB(8, 8, 8, 0),
                child: OutlinedButton.icon(
                  key: const Key('test-sound'),
                  icon: const Icon(Icons.volume_up_outlined),
                  label: const Text('Test sound'),
                  onPressed: () async {
                    final msg = await c.test();
                    if (context.mounted && msg.isNotEmpty) {
                      ScaffoldMessenger.maybeOf(context)?.showSnackBar(SnackBar(content: Text(msg)));
                    }
                  },
                ),
              ),
            ),
            if (c.items.isNotEmpty)
              Align(
                alignment: Alignment.centerRight,
                child: TextButton.icon(
                  onPressed: () => c.acknowledge([for (final a in c.items) a.id]),
                  icon: const Icon(Icons.done_all),
                  label: const Text('Acknowledge all'),
                ),
              ),
            Expanded(
              child: c.items.isEmpty
                  ? const EmptyState(Icons.notifications_none, 'No open alerts.')
                  : ListView.separated(
                      itemCount: c.items.length,
                      separatorBuilder: (_, __) => const Divider(height: 1),
                      itemBuilder: (context, i) {
                        final a = c.items[i];
                        return ListTile(
                          leading: Icon(a.priority == 'High' || a.priority == 'Urgent' ? Icons.priority_high : Icons.notifications_active_outlined),
                          title: Text(a.title),
                          subtitle: Text(a.body, maxLines: 2, overflow: TextOverflow.ellipsis),
                          onTap: a.referenceDoctype == null ? null : () => onOpen(a),
                          trailing: IconButton(
                            tooltip: 'Acknowledge',
                            icon: const Icon(Icons.check),
                            onPressed: () => c.acknowledge([a.id]),
                          ),
                        );
                      },
                    ),
            ),
          ]);
        },
      );
}
