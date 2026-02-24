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

  // 云台角度指令
  double _targetYaw = 0.0;
  double _targetPitch = 0.0;
  bool _sendingAngle = false;

  // 云台速率指令
  double _rateYaw = 0.0;
  double _ratePitch = 0.0;
  bool _sendingRate = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadPidFromConfig();
      context.read<TrackingProvider>().fetchControllerMode();
    });
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
              child: Consumer<TrackingProvider>(
                builder: (_, p, __) => ListView(
                  children: [
                    _TrackingControls(sending: _sending, onToggle: _toggleTracking),
                    const SizedBox(height: 12),

                    // ---- 控制器模式切换 ----
                    _ControllerModeToggle(
                      mode: p.controllerMode,
                      onChanged: (m) => p.setControllerMode(m),
                    ),
                    const SizedBox(height: 12),
                    const Divider(),

                    // ---- PID 参数 ----
                    const SizedBox(height: 4),
                    Text('偏航 PID',
                        style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    const SizedBox(height: 4),
                    _PidSection(
                      title: '',
                      params: _yawPid,
                      onChanged: () => setState(() {}),
                    ),
                    const SizedBox(height: 8),
                    Text('俯仰 PID',
                        style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    const SizedBox(height: 4),
                    _PidSection(
                      title: '',
                      params: _pitchPid,
                      onChanged: () => setState(() {}),
                    ),
                    const SizedBox(height: 12),
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
                    const SizedBox(height: 16),
                    const Divider(),

                    // ---- 云台角度控制 ----
                    const SizedBox(height: 4),
                    const Text('云台角度控制',
                        style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    const SizedBox(height: 8),
                    _AngleSlider(
                      label: '偏航',
                      unit: '°',
                      value: _targetYaw,
                      min: -160,
                      max: 160,
                      onChanged: (v) => setState(() => _targetYaw = v),
                    ),
                    const SizedBox(height: 4),
                    _AngleSlider(
                      label: '俯仰',
                      unit: '°',
                      value: _targetPitch,
                      min: -45,
                      max: 75,
                      onChanged: (v) => setState(() => _targetPitch = v),
                    ),
                    const SizedBox(height: 8),
                    FilledButton.icon(
                      onPressed: _sendingAngle ? null : _sendAngle,
                      icon: _sendingAngle
                          ? const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.control_camera),
                      label: const Text('发送角度指令'),
                    ),
                    const SizedBox(height: 16),
                    const Divider(),

                    // ---- 云台速率控制 ----
                    const SizedBox(height: 4),
                    const Text('手动速率控制',
                        style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                    const SizedBox(height: 2),
                    const Text('直接注入速率指令（deg/s），绕过视觉跟踪',
                        style: TextStyle(fontSize: 10, color: Colors.grey)),
                    const SizedBox(height: 8),
                    _AngleSlider(
                      label: '偏航',
                      unit: '°/s',
                      value: _rateYaw,
                      min: -90,
                      max: 90,
                      onChanged: (v) => setState(() => _rateYaw = v),
                    ),
                    const SizedBox(height: 4),
                    _AngleSlider(
                      label: '俯仰',
                      unit: '°/s',
                      value: _ratePitch,
                      min: -45,
                      max: 45,
                      onChanged: (v) => setState(() => _ratePitch = v),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      children: [
                        Expanded(
                          child: FilledButton.icon(
                            onPressed: _sendingRate ? null : _sendRate,
                            icon: _sendingRate
                                ? const SizedBox(
                                    width: 16,
                                    height: 16,
                                    child: CircularProgressIndicator(strokeWidth: 2),
                                  )
                                : const Icon(Icons.speed),
                            label: const Text('发送速率'),
                          ),
                        ),
                        const SizedBox(width: 8),
                        OutlinedButton(
                          onPressed: () {
                            setState(() {
                              _rateYaw = 0;
                              _ratePitch = 0;
                            });
                            p.setGimbalRate(0, 0);
                          },
                          child: const Text('归零'),
                        ),
                      ],
                    ),
                  ],
                ),
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

  Future<void> _sendAngle() async {
    setState(() => _sendingAngle = true);
    final provider = context.read<TrackingProvider>();
    final ok = await provider.setGimbalPosition(_targetYaw, _targetPitch);
    setState(() => _sendingAngle = false);
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(ok
              ? '角度指令已发送  偏航 ${_targetYaw.toStringAsFixed(1)}°  俯仰 ${_targetPitch.toStringAsFixed(1)}°'
              : '发送失败（请检查 pipeline 是否已启动）'),
          duration: const Duration(seconds: 2),
        ),
      );
    }
  }

  Future<void> _sendRate() async {
    setState(() => _sendingRate = true);
    final provider = context.read<TrackingProvider>();
    final ok = await provider.setGimbalRate(_rateYaw, _ratePitch);
    setState(() => _sendingRate = false);
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(ok
              ? '速率指令已发送  偏航 ${_rateYaw.toStringAsFixed(1)}°/s  俯仰 ${_ratePitch.toStringAsFixed(1)}°/s'
              : '发送失败（请检查 pipeline 是否已启动）'),
          duration: const Duration(seconds: 2),
        ),
      );
    }
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
        return Tooltip(
          message: running
              ? '停止视觉检测与云台跟踪 pipeline'
              : '启动视觉检测与云台跟踪 pipeline（独立于任务，可在任务开始前先行测试）',
          child: Row(
            children: [
              Expanded(
                child: FilledButton.tonalIcon(
                  onPressed: sending ? null : onToggle,
                  icon: sending
                      ? const SizedBox(
                          width: 16,
                          height: 16,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Icon(running ? Icons.stop : Icons.play_arrow),
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
          ),
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
        _PidField(label: 'Kp', value: params.kp, min: 0, max: 20,
            onChanged: (v) { params.kp = v; onChanged(); }),
        _PidField(label: 'Ki', value: params.ki, min: 0, max: 5,
            onChanged: (v) { params.ki = v; onChanged(); }),
        _PidField(label: 'Kd', value: params.kd, min: 0, max: 5,
            onChanged: (v) { params.kd = v; onChanged(); }),
      ],
    );
  }
}

/// PID 参数行：滑块粗调 + 文本框精确输入
/// 两者联动：拖动滑块自动更新文本框，文本框回车更新滑块
class _PidField extends StatefulWidget {
  final String label;
  final double value;
  final double min;
  final double max;
  final ValueChanged<double> onChanged;

  const _PidField({
    required this.label,
    required this.value,
    required this.min,
    required this.max,
    required this.onChanged,
  });

  @override
  State<_PidField> createState() => _PidFieldState();
}

class _PidFieldState extends State<_PidField> {
  late TextEditingController _ctrl;
  bool _hasFocus = false;

  @override
  void initState() {
    super.initState();
    _ctrl = TextEditingController(text: widget.value.toStringAsFixed(3));
  }

  @override
  void didUpdateWidget(_PidField old) {
    super.didUpdateWidget(old);
    if (!_hasFocus && old.value != widget.value) {
      _ctrl.text = widget.value.toStringAsFixed(3);
    }
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  void _commitText(String s) {
    final v = double.tryParse(s);
    if (v != null) {
      final clamped = v.clamp(widget.min, widget.max);
      widget.onChanged(clamped);
      _ctrl.text = clamped.toStringAsFixed(3);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        SizedBox(
          width: 24,
          child: Text(widget.label,
              style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
        ),
        Expanded(
          child: Slider(
            value: widget.value.clamp(widget.min, widget.max),
            min: widget.min,
            max: widget.max,
            divisions: ((widget.max - widget.min) * 20).round(),
            onChanged: (v) {
              widget.onChanged(v);
              if (!_hasFocus) _ctrl.text = v.toStringAsFixed(3);
            },
          ),
        ),
        // 精确数值输入框 (按回车或失焦时生效)
        SizedBox(
          width: 72,
          child: Focus(
            onFocusChange: (f) => setState(() => _hasFocus = f),
            child: TextField(
              controller: _ctrl,
              keyboardType: const TextInputType.numberWithOptions(decimal: true),
              style: const TextStyle(fontSize: 11, fontFamily: 'monospace'),
              decoration: const InputDecoration(
                isDense: true,
                contentPadding: EdgeInsets.symmetric(horizontal: 6, vertical: 6),
                border: OutlineInputBorder(),
              ),
              onSubmitted: _commitText,
              onEditingComplete: () => _commitText(_ctrl.text),
            ),
          ),
        ),
      ],
    );
  }
}

/// 控制器模式切换 (PID ↔ MPC)
class _ControllerModeToggle extends StatelessWidget {
  final String mode;
  final ValueChanged<String> onChanged;

  const _ControllerModeToggle({required this.mode, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isMpc = mode == 'mpc';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Text('控制器',
                style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
            const Spacer(),
            Tooltip(
              message: '切换轴控制器算法。更改在下次 Pipeline 启动时生效。',
              child: ToggleButtons(
                isSelected: [!isMpc, isMpc],
                onPressed: (i) => onChanged(i == 0 ? 'pid' : 'mpc'),
                borderRadius: BorderRadius.circular(8),
                selectedColor: theme.colorScheme.onPrimary,
                fillColor: theme.colorScheme.primary,
                textStyle: const TextStyle(fontSize: 12),
                constraints: const BoxConstraints(minWidth: 48, minHeight: 32),
                children: const [Text('PID'), Text('MPC')],
              ),
            ),
          ],
        ),
        if (isMpc)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(
              'MPC 模式：预计算最优增益 K，可通过 q/r 比值调节激进程度',
              style: TextStyle(fontSize: 10, color: theme.colorScheme.primary.withValues(alpha: 0.8)),
            ),
          ),
      ],
    );
  }
}

/// 角度滑块组件（用于云台角度控制）
class _AngleSlider extends StatelessWidget {
  final String label;
  final String unit;
  final double value;
  final double min;
  final double max;
  final ValueChanged<double> onChanged;

  const _AngleSlider({
    required this.label,
    required this.unit,
    required this.value,
    required this.min,
    required this.max,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        SizedBox(
          width: 32,
          child: Text(label, style: const TextStyle(fontSize: 11)),
        ),
        Expanded(
          child: Slider(
            value: value,
            min: min,
            max: max,
            divisions: ((max - min) * 2).round(),
            onChanged: onChanged,
          ),
        ),
        SizedBox(
          width: 52,
          child: Text('${value.toStringAsFixed(1)}$unit',
              style: const TextStyle(fontSize: 11, fontFamily: 'monospace')),
        ),
      ],
    );
  }
}
