import 'package:flutter/material.dart';

import '../api/models.dart';
import '../state/controllers.dart';
import '../platform/services.dart';
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
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 6, 12, 0),
              child: Text(AppServices.pushStatus(), key: const Key('push-status'), style: Theme.of(context).textTheme.bodySmall),
            ),
            const DeviceAlertSettings(),
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


/// This device's part in getting alerts through: desktop background mode and start at sign-in; on phones, anything
/// in the system settings that holds notifications back.
class DeviceAlertSettings extends StatefulWidget {
  const DeviceAlertSettings({super.key});
  @override
  State<DeviceAlertSettings> createState() => _DeviceAlertSettingsState();
}

class _DeviceAlertSettingsState extends State<DeviceAlertSettings> with WidgetsBindingObserver {
  String? _note;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _check();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _check(); // back from the system settings
  }

  Future<void> _check() async {
    final note = await AppServices.deliveryNote?.call().catchError((_) => null);
    if (mounted && note != _note) setState(() => _note = note);
  }

  Future<void> _set(Future<void> Function() change) async {
    try {
      await change();
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.maybeOf(context)?.showSnackBar(SnackBar(content: Text('This computer did not allow it: $e')));
      }
    }
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final d = AppServices.desktop;
    final open = AppServices.openSystemSettings;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (d != null) ...[
        SwitchListTile(
          key: const Key('start-at-login'),
          dense: true,
          title: const Text('Start when I sign in to this computer'),
          subtitle: const Text('Opens in the background, so alerts arrive without opening the app'),
          value: d.startAtLogin,
          onChanged: (v) => _set(() => d.setStartAtLogin(v)),
        ),
        SwitchListTile(
          key: const Key('keep-running'),
          dense: true,
          title: const Text('Keep running when the window is closed'),
          subtitle: const Text('Stays near the clock; use its menu to open or quit'),
          value: d.keepRunning,
          onChanged: (v) => _set(() => d.setKeepRunning(v)),
        ),
      ],
      if (_note != null)
        Padding(
          padding: const EdgeInsets.fromLTRB(12, 6, 12, 0),
          child: Text(_note!, key: const Key('delivery-note'), style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ),
      if (open != null)
        Padding(
          padding: const EdgeInsets.fromLTRB(8, 4, 8, 0),
          child: TextButton.icon(
            key: const Key('system-settings'),
            icon: const Icon(Icons.settings_outlined),
            label: const Text('Notification and battery settings'),
            onPressed: () => open(),
          ),
        ),
    ]);
  }
}
