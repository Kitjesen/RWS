import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/tracking_provider.dart';

class FireControlWidget extends StatelessWidget {
  const FireControlWidget({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Consumer<TrackingProvider>(
      builder: (_, p, __) {
        final fire = p.fireStatus;

        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 标题行
                Row(
                  children: [
                    Icon(Icons.gps_fixed, color: theme.colorScheme.primary),
                    const SizedBox(width: 8),
                    Text('火控系统 Fire Control',
                        style: theme.textTheme.titleMedium),
                    const Spacer(),
                    _StateChip(state: fire.state),
                  ],
                ),
                const Divider(),

                if (!fire.isConfigured) ...[
                  const Center(
                    child: Padding(
                      padding: EdgeInsets.all(16),
                      child: Text('火控模块未启用',
                          style: TextStyle(color: Colors.grey, fontSize: 14)),
                    ),
                  ),
                ] else ...[
                  // 操作员信息
                  if (fire.isArmed && fire.operatorId != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Text(
                        '操作员 Operator: ${fire.operatorId}',
                        style: TextStyle(
                            fontSize: 12,
                            color: theme.colorScheme.onSurface
                                .withValues(alpha: 0.7)),
                      ),
                    ),

                  // 按钮行: SAFE / ARM
                  Row(
                    children: [
                      Expanded(
                        child: FilledButton.tonalIcon(
                          onPressed: () => p.safeSystem(),
                          icon: const Icon(Icons.shield, size: 18),
                          label: const Text('解除武装 SAFE'),
                          style: FilledButton.styleFrom(
                            backgroundColor:
                                Colors.grey.withValues(alpha: 0.15),
                            foregroundColor: Colors.grey.shade300,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      if (fire.state == 'safe')
                        Expanded(
                          child: FilledButton.tonalIcon(
                            onPressed: () => p.armSystem(),
                            icon: const Icon(Icons.lock_open, size: 18),
                            label: const Text('武装 ARM'),
                            style: FilledButton.styleFrom(
                              backgroundColor:
                                  Colors.amber.withValues(alpha: 0.15),
                              foregroundColor: Colors.amber,
                            ),
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 12),

                  // 开火请求按钮
                  SizedBox(
                    width: double.infinity,
                    height: 48,
                    child: FilledButton.icon(
                      onPressed: fire.state == 'fire_authorized'
                          ? () => _confirmFire(context, p)
                          : null,
                      icon: const Icon(Icons.local_fire_department),
                      label: const Text('请求开火 REQUEST FIRE'),
                      style: FilledButton.styleFrom(
                        backgroundColor: fire.state == 'fire_authorized'
                            ? Colors.red
                            : Colors.grey.shade800,
                        foregroundColor: Colors.white,
                        disabledBackgroundColor: Colors.grey.shade800,
                        disabledForegroundColor: Colors.grey.shade500,
                      ),
                    ),
                  ),

                  if (fire.state != 'fire_authorized')
                    Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(
                        _disabledReason(fire.state),
                        style: TextStyle(
                            fontSize: 11, color: Colors.grey.shade500),
                      ),
                    ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }

  String _disabledReason(String state) {
    return switch (state) {
      'safe' => '需要先武装系统',
      'armed' => '等待火控授权',
      'fire_requested' => '开火请求已发送',
      'fired' => '已开火',
      'cooldown' => '冷却中...',
      _ => '',
    };
  }

  void _confirmFire(BuildContext context, TrackingProvider provider) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.warning_amber, color: Colors.red),
            SizedBox(width: 8),
            Text('确认开火 Confirm Fire'),
          ],
        ),
        content: const Text('确认发送开火请求？此操作不可撤销。\n'
            'Confirm fire request? This action cannot be undone.'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('取消 Cancel'),
          ),
          FilledButton(
            onPressed: () {
              Navigator.of(ctx).pop();
              provider.requestFire();
            },
            style: FilledButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('确认开火 FIRE'),
          ),
        ],
      ),
    );
  }
}

class _StateChip extends StatelessWidget {
  final String state;

  const _StateChip({required this.state});

  @override
  Widget build(BuildContext context) {
    final (color, label) = _stateStyle(state);

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
          Text(label,
              style: TextStyle(
                  color: color, fontWeight: FontWeight.w600, fontSize: 12)),
        ],
      ),
    );
  }

  (Color, String) _stateStyle(String state) {
    return switch (state) {
      'safe' => (Colors.grey, 'SAFE'),
      'armed' => (Colors.amber, 'ARMED'),
      'fire_authorized' => (Colors.green, 'AUTHORIZED'),
      'fire_requested' => (Colors.orange, 'REQUESTED'),
      'fired' => (Colors.red, 'FIRED'),
      'cooldown' => (Colors.blue, 'COOLDOWN'),
      _ => (Colors.grey, '未配置'),
    };
  }
}
