import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/tracking_models.dart';
import '../services/tracking_provider.dart';

class SystemHealthWidget extends StatelessWidget {
  const SystemHealthWidget({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Consumer<TrackingProvider>(
      builder: (_, p, __) {
        final healthMap = p.health;
        final entries = healthMap.values.toList();
        final overall = _overallStatus(entries);

        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 标题行
                Row(
                  children: [
                    Icon(Icons.monitor_heart,
                        color: theme.colorScheme.primary),
                    const SizedBox(width: 8),
                    Text('系统健康 System Health',
                        style: theme.textTheme.titleMedium),
                    const Spacer(),
                    _OverallChip(status: overall),
                  ],
                ),
                const Divider(),

                if (entries.isEmpty)
                  const Center(
                    child: Padding(
                      padding: EdgeInsets.all(12),
                      child: Text('等待健康数据...',
                          style:
                              TextStyle(color: Colors.grey, fontSize: 13)),
                    ),
                  )
                else
                  Expanded(
                    child: GridView.builder(
                      gridDelegate:
                          const SliverGridDelegateWithFixedCrossAxisCount(
                        crossAxisCount: 2,
                        childAspectRatio: 3.0,
                        crossAxisSpacing: 8,
                        mainAxisSpacing: 8,
                      ),
                      itemCount: entries.length,
                      itemBuilder: (ctx, i) =>
                          _SubsystemChip(sub: entries[i]),
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }

  String _overallStatus(List<SubsystemHealth> entries) {
    if (entries.isEmpty) return 'unknown';
    if (entries.any((e) => e.status == 'failed')) return 'failed';
    if (entries.any((e) => e.status == 'degraded')) return 'degraded';
    if (entries.every((e) => e.status == 'ok')) return 'ok';
    return 'unknown';
  }
}

class _OverallChip extends StatelessWidget {
  final String status;

  const _OverallChip({required this.status});

  @override
  Widget build(BuildContext context) {
    final (color, label) = switch (status) {
      'ok' => (Colors.green, 'OK'),
      'degraded' => (Colors.orange, 'DEGRADED'),
      'failed' => (Colors.red, 'FAILED'),
      _ => (Colors.grey, 'UNKNOWN'),
    };

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
                  color: color,
                  fontWeight: FontWeight.w600,
                  fontSize: 12)),
        ],
      ),
    );
  }
}

class _SubsystemChip extends StatelessWidget {
  final SubsystemHealth sub;

  const _SubsystemChip({required this.sub});

  @override
  Widget build(BuildContext context) {
    final dotColor = switch (sub.status) {
      'ok' => Colors.green,
      'degraded' => Colors.orange,
      'failed' => Colors.red,
      _ => Colors.grey,
    };

    final icon = _subsystemIcon(sub.name);

    return InkWell(
      borderRadius: BorderRadius.circular(8),
      onTap: sub.error != null
          ? () {
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text('${sub.name}: ${sub.error}'),
                  duration: const Duration(seconds: 3),
                ),
              );
            }
          : null,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
        decoration: BoxDecoration(
          color: dotColor.withValues(alpha: 0.06),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: dotColor.withValues(alpha: 0.2)),
        ),
        child: Row(
          children: [
            Icon(icon, size: 16, color: Colors.white70),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                _displayName(sub.name),
                style: const TextStyle(fontSize: 12),
                overflow: TextOverflow.ellipsis,
              ),
            ),
            Container(
              width: 10,
              height: 10,
              decoration:
                  BoxDecoration(color: dotColor, shape: BoxShape.circle),
            ),
          ],
        ),
      ),
    );
  }

  IconData _subsystemIcon(String name) {
    return switch (name) {
      'camera' => Icons.videocam,
      'gimbal_driver' => Icons.open_with,
      'imu' => Icons.screen_rotation,
      'rangefinder' => Icons.straighten,
      'safety' => Icons.shield,
      'api' => Icons.cloud,
      _ => Icons.memory,
    };
  }

  String _displayName(String name) {
    return switch (name) {
      'camera' => 'Camera',
      'gimbal_driver' => 'Gimbal',
      'imu' => 'IMU',
      'rangefinder' => 'Rangefinder',
      'safety' => 'Safety',
      'api' => 'API',
      _ => name,
    };
  }
}
