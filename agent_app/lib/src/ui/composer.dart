import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/api_client.dart';
import '../platform/voice.dart';
import '../state/controllers.dart';

/// Reply-or-note composer. The mode is always visible and the field changes colour for internal notes,
/// so a note is never sent to a customer by mistake. Ctrl+Enter (or Cmd+Enter) sends.
class Composer extends StatefulWidget {
  final Draft draft;
  final bool canReply;
  final bool canNote;
  final String? replyDisabledReason;
  final String replyLabel;
  final ValueChanged<ComposerMode> onMode;
  final ValueChanged<String> onChanged;
  final Future<void> Function() onSend;
  final FocusNode? focusNode;
  final VoidCallback? onAttach;
  final VoidCallback? onRemoveFile;
  final VoidCallback? onCanned;
  final String cannedTooltip;
  final VoidCallback? onAi;
  final Future<void> Function(UploadFile file, int seconds)? onVoice;
  final int maxVoiceSeconds;

  const Composer({
    super.key,
    required this.draft,
    required this.onMode,
    required this.onChanged,
    required this.onSend,
    this.canReply = true,
    this.canNote = true,
    this.replyDisabledReason,
    this.replyLabel = 'Reply to customer',
    this.focusNode,
    this.onAttach,
    this.onRemoveFile,
    this.onCanned,
    this.cannedTooltip = 'Canned responses (Ctrl+/)',
    this.onAi,
    this.onVoice,
    this.maxVoiceSeconds = 120,
  });

  @override
  State<Composer> createState() => _ComposerState();
}

class _ComposerState extends State<Composer> {
  late final TextEditingController _text = TextEditingController(text: widget.draft.text);
  VoiceRecorder? _rec;
  DateTime? _recStart;
  Timer? _recTimer;
  String? _recError;

  Future<void> _startRecording() async {
    final rec = VoiceRecorder.factory();
    if (!await rec.start()) {
      rec.dispose();
      setState(() => _recError = 'Allow the microphone to record a voice note.');
      return;
    }
    setState(() {
      _rec = rec;
      _recError = null;
      _recStart = DateTime.now();
    });
    _recTimer = Timer.periodic(const Duration(milliseconds: 250), (_) {
      if (!mounted) return;
      if (_recSeconds >= widget.maxVoiceSeconds) {
        _stopRecording(send: true);
      } else {
        setState(() {});
      }
    });
  }

  int get _recSeconds => _recStart == null ? 0 : DateTime.now().difference(_recStart!).inSeconds;

  Future<void> _stopRecording({required bool send}) async {
    final rec = _rec;
    if (rec == null) return;
    _recTimer?.cancel();
    final seconds = _recSeconds < 1 ? 1 : _recSeconds;
    setState(() => _rec = null);
    if (!send) {
      await rec.cancel();
      rec.dispose();
      return;
    }
    final file = await rec.stop();
    rec.dispose();
    if (file != null && widget.onVoice != null) await widget.onVoice!(file, seconds);
  }

  @override
  void didUpdateWidget(covariant Composer old) {
    super.didUpdateWidget(old);
    if (widget.draft.text != _text.text) {
      // cleared after a successful send, or restored
      _text.value = TextEditingValue(text: widget.draft.text, selection: TextSelection.collapsed(offset: widget.draft.text.length));
    }
  }

  @override
  void dispose() {
    _recTimer?.cancel();
    _rec?.cancel();
    _rec?.dispose();
    _text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final d = widget.draft;
    final s = Theme.of(context).colorScheme;
    final note = d.mode == ComposerMode.note;
    final replyBlocked = !note && !widget.canReply;
    final sending = d.state == SendState.sending;
    final failed = d.state == SendState.failed;
    return Material(
      elevation: 3,
      color: note ? Colors.amber.shade50 : s.surface,
      child: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 8),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              Expanded(
                child: SegmentedButton<ComposerMode>(
                  showSelectedIcon: false,
                  segments: [
                    ButtonSegment(value: ComposerMode.reply, icon: const Icon(Icons.reply, size: 18), label: Text(widget.replyLabel)),
                    ButtonSegment(
                        value: ComposerMode.note,
                        icon: const Icon(Icons.lock_outline, size: 18),
                        label: const Text('Internal note'),
                        enabled: widget.canNote),
                  ],
                  selected: {d.mode},
                  onSelectionChanged: sending ? null : (v) => widget.onMode(v.first),
                ),
              ),
            ]),
            const SizedBox(height: 6),
            if (note)
              Text('Only staff can see internal notes.',
                  style: TextStyle(fontSize: 12, color: Colors.brown.shade700, fontWeight: FontWeight.w600)),
            if (replyBlocked && widget.replyDisabledReason != null)
              Text(widget.replyDisabledReason!, style: TextStyle(fontSize: 12, color: s.error)),
            if (failed && (d.error != null || d.notice != null))
              Semantics(
                liveRegion: true,
                child: Container(
                  margin: const EdgeInsets.only(bottom: 6),
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(color: s.errorContainer, borderRadius: BorderRadius.circular(8)),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(d.error ?? d.notice!, style: TextStyle(color: s.onErrorContainer)),
                    if (d.error != null)
                      Text('Your text is kept. ${d.requestId != null ? 'Retrying will not send it twice.' : ''}',
                          style: TextStyle(fontSize: 12, color: s.onErrorContainer)),
                    for (final a in d.serverActions)
                      Text('• ${a['label'] ?? a['action']}', style: TextStyle(fontSize: 12, color: s.onErrorContainer)),
                  ]),
                ),
              ),
            if (_recError != null) Text(_recError!, style: TextStyle(fontSize: 12, color: s.error)),
            if (_rec != null)
              Padding(
                key: const Key('recording'),
                padding: const EdgeInsets.only(bottom: 6),
                child: Row(children: [
                  Icon(Icons.fiber_manual_record, color: s.error, size: 16),
                  const SizedBox(width: 6),
                  Text('Recording ${_recSeconds ~/ 60}:${(_recSeconds % 60).toString().padLeft(2, '0')}'),
                  const Spacer(),
                  TextButton(onPressed: () => _stopRecording(send: false), child: const Text('Cancel')),
                  FilledButton.icon(
                      key: const Key('recording-send'),
                      onPressed: () => _stopRecording(send: true),
                      icon: const Icon(Icons.send, size: 16),
                      label: const Text('Send')),
                ]),
              ),
            if (d.file != null)
              Align(
                alignment: Alignment.centerLeft,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: InputChip(
                    key: const Key('composer-file'),
                    avatar: const Icon(Icons.attach_file, size: 16),
                    label: Text('${d.file!.name} (${(d.file!.size / 1024).ceil()} KB)'),
                    onDeleted: sending ? null : widget.onRemoveFile,
                    deleteButtonTooltipMessage: 'Remove file',
                  ),
                ),
              ),
            Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              if (widget.onAi != null)
                IconButton(
                  key: const Key('composer-ai'),
                  visualDensity: VisualDensity.compact,
                  tooltip: 'AI copilot (Ctrl+I): suggest, rewrite, translate, summarise',
                  onPressed: sending ? null : widget.onAi,
                  icon: const Icon(Icons.auto_awesome),
                ),
              if (widget.onCanned != null)
                IconButton(
                  key: const Key('composer-canned'),
                  visualDensity: VisualDensity.compact,
                  tooltip: widget.cannedTooltip,
                  onPressed: sending || replyBlocked ? null : widget.onCanned,
                  icon: const Icon(Icons.bolt_outlined),
                ),
              if (widget.onVoice != null && _rec == null)
                IconButton(
                  key: const Key('composer-voice'),
                  visualDensity: VisualDensity.compact,
                  tooltip: 'Record a voice note',
                  onPressed: sending || replyBlocked ? null : _startRecording,
                  icon: const Icon(Icons.mic_none),
                ),
              if (widget.onAttach != null)
                IconButton(
                  key: const Key('composer-attach'),
                  visualDensity: VisualDensity.compact,
                  tooltip: 'Attach a file',
                  onPressed: sending || replyBlocked ? null : widget.onAttach,
                  icon: const Icon(Icons.attach_file),
                ),
              Expanded(
                child: CallbackShortcuts(
                  bindings: {
                    const SingleActivator(LogicalKeyboardKey.enter, control: true): _send,
                    const SingleActivator(LogicalKeyboardKey.enter, meta: true): _send,
                    if (widget.onCanned != null) const SingleActivator(LogicalKeyboardKey.slash, control: true): widget.onCanned!,
                    if (widget.onAi != null) const SingleActivator(LogicalKeyboardKey.keyI, control: true): widget.onAi!,
                  },
                  child: TextField(
                    key: const Key('composer-field'),
                    controller: _text,
                    focusNode: widget.focusNode,
                    enabled: !replyBlocked,
                    minLines: 1,
                    maxLines: 6,
                    textInputAction: TextInputAction.newline,
                    keyboardType: TextInputType.multiline,
                    onChanged: widget.onChanged,
                    decoration: InputDecoration(
                      hintText: note ? 'Write an internal note…' : 'Write a reply…',
                      hintMaxLines: 1,
                      filled: true,
                      fillColor: note ? Colors.amber.shade100 : s.surfaceContainerHighest,
                      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
                      isDense: true,
                    ),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Tooltip(
                message: 'Send (Ctrl+Enter)',
                child: FilledButton.icon(
                  key: const Key('composer-send'),
                  style: note ? FilledButton.styleFrom(backgroundColor: Colors.brown.shade600) : null,
                  onPressed: sending || replyBlocked ? null : _send,
                  icon: sending
                      ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                      : Icon(failed ? Icons.refresh : Icons.send),
                  label: Text(sending ? 'Sending' : failed ? 'Retry' : note ? 'Add note' : 'Send'),
                ),
              ),
            ]),
            if (d.state == SendState.sent)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(note ? 'Note added' : 'Sent', style: TextStyle(fontSize: 12, color: s.primary)),
              ),
          ]),
        ),
      ),
    );
  }

  void _send() {
    widget.onChanged(_text.text);
    widget.onSend();
  }
}
