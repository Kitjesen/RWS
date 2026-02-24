import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/tracking_provider.dart';

class StatusCard extends StatelessWidget {
  const StatusCard({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Consumer<TrackingProvider>(
      builder: (_, p, __) {
        final s = p.status;
        final stateColor = _stateColor(s.state);
        final connected = p.connected;

        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.monitor_heart,
                        color: connected
                            ? theme.colorScheme.primary
                            : Colors.red.shade300),
                    const SizedBox(width: 8),
                    Text('系统状态', style: theme.textTheme.titleMedium),
                    const Spacer(),
                    if (!connected)
                      _StatusChip(label: '离线', color: Colors.red)
                    else
                      _StatusChip(
                        label: s.running ? '运行中' : '已停止',
                        color: s.running ? Colors.green : Colors.grey,
                      ),
                  ],
                ),
                if (!connected)
                  Padding(
                    padding: const EdgeInsets.only(top: 6, bottom: 2),
                    child: Row(
                      children: [
                        Icon(Icons.wifi_off, size: 14, color: Colors.red.shade300),
                        const SizedBox(width: 6),
                        Text(
                          '后端无响应，显示最后已知状态',
                          style: TextStyle(
                            fontSize: 11,
                            color: Colors.red.shade300,
                            fontStyle: FontStyle.italic,
                          ),
                        ),
                      ],
                    ),
                  ),
                const Divider(),
                Expanded(
                  child: Wrap(
                    spacing: 24,
                    runSpacing: 8,
                    children: [
                      _Metric(
                        icon: Icons.flag,
                        label: '决策状态',
                        value: s.state,
                        color: stateColor,
                      ),
                      _Metric(
                        icon: Icons.videocam,
                        label: '帧数',
                        value: '${s.frameCount}',
                      ),
                      _Metric(
                        icon: s.errorCount > 0
                            ? Icons.error_outline
                            : Icons.check_circle_outline,
                        label: '错误',
                        value: '${s.errorCount}',
                        color: s.errorCount > 0 ? Colors.red : Colors.green,
                      ),
                      _Metric(
                        icon: Icons.lock,
                        label: '锁定率',
                        value: '${(s.lockRate * 100).toStringAsFixed(1)}%',
                        color: s.lockRate > 0.7
                            ? Colors.green
                            : s.lockRate > 0.3
                                ? Colors.orange
                                : Colors.red,
                      ),
                      if (s.fps > 0)
                        _Metric(
                          icon: Icons.speed,
                          label: 'FPS',
                          value: s.fps.toStringAsFixed(1),
                          color: s.fps >= 25
                              ? Colors.green
                              : s.fps >= 15
                                  ? Colors.orange
                                  : Colors.red,
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  Color _stateColor(String state) {
    // Color semantics: green=success/locked, cyan=active/tracking,
    // grey=idle/normal, orange=attention-needed, red=error
    return switch (state) {
      'LOCK' => Colors.green,       // 目标锁定 = 成功 (绿)
      'TRACK' => Colors.cyan,       // 正在跟踪 = 活跃 (青)
      'LOST' => Colors.orange,      // 目标丢失 = 需要注意 (橙)
      'SEARCH' => Colors.blueGrey,  // 扫描搜索 = 正常待机 (灰蓝)
      _ => Colors.grey,
    };
  }
}

class _StatusChip extends StatelessWidget {
  final String label;
  final Color color;

  const _StatusChip({required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(width: 6),
          Text(label, style: TextStyle(color: color, fontWeight: FontWeight.w600, fontSize: 12)),
        ],
      ),
    );
  }
}

class _Metric extends StatelessWidget {
  final IconData icon;
  final String label;
  final String value;
  final Color? color;

  const _Metric({required this.icon, required this.label, required this.value, this.color});

  @override
  Widget build(BuildContext context) {
    final effectiveColor = color ?? Theme.of(context).colorScheme.onSurface;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 16, color: effectiveColor.withValues(alpha: 0.6)),
        const SizedBox(width: 4),
        Text('$label: ', style: TextStyle(fontSize: 12, color: effectiveColor.withValues(alpha: 0.7))),
        Text(value, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: effectiveColor)),
      ],
    );
  }
}
