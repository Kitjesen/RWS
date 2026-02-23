import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/tracking_models.dart';
import '../services/tracking_provider.dart';

class ControlPanel extends StatefulWidget {
  const ControlPanel({super.key});

  @override
  State<ControlPanel> createState() => _ControlPanelState();
}

class _ControlPanelState extends State<ControlPanel> {
  final _yawPid = PidParams(kp: 5.0, ki: 0.4, kd: 0.35);
  final _pitchPid = PidParams(kp: 4.0, ki: 0.3, kd: 0.30);
  bool _sending = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadPidFromConfig());
  }

  Future<void> _loadPidFromConfig() async {
    final cfg = await context.read<TrackingProvider>().api.getConfig();
    if (!mounted || cfg == null) return;
    final pid = cfg['pid'] as Map<String, dynamic>?;
    if (pid == null) return;
    setState(() {
      final yaw = pid['yaw'] as Map<String, dynamic>?;
      if (yaw != null) {
        _yawPid.kp = (yaw['kp'] as num).toDouble();
        _yawPid.ki = (yaw['ki'] as num).toDouble();
        _yawPid.kd = (yaw['kd'] as num).toDouble();
      }
      final pitch = pid['pitch'] as Map<String, dynamic>?;
      if (pitch != null) {
        _pitchPid.kp = (pitch['kp'] as num).toDouble();
        _pitchPid.ki = (pitch['ki'] as num).toDouble();
        _pitchPid.kd = (pitch['kd'] as num).toDouble();
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.tune, color: theme.colorScheme.primary),
                const SizedBox(width: 8),
                Text('控制面板', style: theme.textTheme.titleMedium),
              ],
            ),
            const Divider(),
            Expanded(
              child: ListView(
                children: [
                  _TrackingControls(sending: _sending, onToggle: _toggleTracking),
                  const SizedBox(height: 16),
                  _PidSection(
                    title: 'Yaw PID',
                    params: _yawPid,
                    onChanged: () => setState(() {}),
                  ),
                  const SizedBox(height: 12),
                  _PidSection(
                    title: 'Pitch PID',
                    params: _pitchPid,
                    onChanged: () => setState(() {}),
                  ),
                  const SizedBox(height: 16),
                  FilledButton.icon(
                    onPressed: _sending ? null : _applyPid,
                    icon: _sending
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.send),
                    label: const Text('应用 PID 参数'),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _toggleTracking() async {
    setState(() => _sending = true);
    final provider = context.read<TrackingProvider>();
    if (provider.status.running) {
      await provider.stopTracking();
    } else {
      await provider.startTracking();
    }
    setState(() => _sending = false);
  }

  Future<void> _applyPid() async {
    setState(() => _sending = true);
    final provider = context.read<TrackingProvider>();
    await provider.updatePid('yaw', _yawPid);
    await provider.updatePid('pitch', _pitchPid);
    setState(() => _sending = false);

    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('PID 参数已更新'), duration: Duration(seconds: 1)),
      );
    }
  }
}

class _TrackingControls extends StatelessWidget {
  final bool sending;
  final VoidCallback onToggle;

  const _TrackingControls({required this.sending, required this.onToggle});

  @override
  Widget build(BuildContext context) {
    return Consumer<TrackingProvider>(
      builder: (_, p, __) {
        final running = p.status.running;
        return Row(
          children: [
            Expanded(
              child: FilledButton.tonalIcon(
                onPressed: sending ? null : onToggle,
                icon: Icon(running ? Icons.stop : Icons.play_arrow),
                label: Text(running ? '停止跟踪' : '开始跟踪'),
                style: FilledButton.styleFrom(
                  backgroundColor: running
                      ? Colors.red.withValues(alpha: 0.15)
                      : Colors.green.withValues(alpha: 0.15),
                  foregroundColor: running ? Colors.red : Colors.green,
                ),
              ),
            ),
          ],
        );
      },
    );
  }
}

class _PidSection extends StatelessWidget {
  final String title;
  final PidParams params;
  final VoidCallback onChanged;

  const _PidSection({
    required this.title,
    required this.params,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(title,
            style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
        const SizedBox(height: 4),
        _PidSlider(label: 'Kp', value: params.kp, min: 0, max: 20,
            onChanged: (v) { params.kp = v; onChanged(); }),
        _PidSlider(label: 'Ki', value: params.ki, min: 0, max: 5,
            onChanged: (v) { params.ki = v; onChanged(); }),
        _PidSlider(label: 'Kd', value: params.kd, min: 0, max: 5,
            onChanged: (v) { params.kd = v; onChanged(); }),
      ],
    );
  }
}

class _PidSlider extends StatelessWidget {
  final String label;
  final double value;
  final double min;
  final double max;
  final ValueChanged<double> onChanged;

  const _PidSlider({
    required this.label,
    required this.value,
    required this.min,
    required this.max,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        SizedBox(width: 24, child: Text(label, style: const TextStyle(fontSize: 11))),
        Expanded(
          child: Slider(
            value: value,
            min: min,
            max: max,
            divisions: ((max - min) * 20).round(),
            onChanged: onChanged,
          ),
        ),
        SizedBox(
          width: 44,
          child: Text(value.toStringAsFixed(2),
              style: const TextStyle(fontSize: 11, fontFamily: 'monospace')),
        ),
      ],
    );
  }
}
