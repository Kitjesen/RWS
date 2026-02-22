import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/tracking_models.dart';
import '../services/tracking_provider.dart';

class ThreatQueueWidget extends StatelessWidget {
  const ThreatQueueWidget({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Consumer<TrackingProvider>(
      builder: (_, p, __) {
        final threats = p.threats;

        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 标题行
                Row(
                  children: [
                    Icon(Icons.warning_amber,
                        color: theme.colorScheme.primary),
                    const SizedBox(width: 8),
                    Text('威胁队列 Threats',
                        style: theme.textTheme.titleMedium),
                    const SizedBox(width: 8),
                    if (threats.isNotEmpty)
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: Colors.red.withValues(alpha: 0.15),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Text(
                          '${threats.length}',
                          style: const TextStyle(
                              color: Colors.red,
                              fontWeight: FontWeight.w600,
                              fontSize: 12),
                        ),
                      ),
                  ],
                ),
                const Divider(),

                if (threats.isEmpty)
                  const Expanded(
                    child: Center(
                      child: Text('未检测到威胁目标',
                          style: TextStyle(color: Colors.grey, fontSize: 14)),
                    ),
                  )
                else
                  Expanded(
                    child: ListView.separated(
                      itemCount: threats.length,
                      separatorBuilder: (_, __) =>
                          const SizedBox(height: 6),
                      itemBuilder: (_, i) =>
                          _ThreatTile(threat: threats[i]),
                    ),
                  ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _ThreatTile extends StatelessWidget {
  final ThreatEntry threat;

  const _ThreatTile({required this.threat});

  @override
  Widget build(BuildContext context) {
    final rankColor = switch (threat.priorityRank) {
      1 => Colors.red,
      2 => Colors.orange,
      3 => Colors.yellow,
      _ => Colors.grey,
    };

    final classIcon = switch (threat.classId) {
      'person' => Icons.person,
      'car' => Icons.directions_car,
      'truck' => Icons.local_shipping,
      _ => Icons.help_outline,
    };

    final pct = (threat.threatScore * 100).toStringAsFixed(0);

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: rankColor.withValues(alpha: 0.06),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: rankColor.withValues(alpha: 0.2)),
      ),
      child: Row(
        children: [
          // 优先级
          SizedBox(
            width: 28,
            child: Text(
              '#${threat.priorityRank}',
              style: TextStyle(
                  fontWeight: FontWeight.bold,
                  fontSize: 15,
                  color: rankColor),
            ),
          ),
          const SizedBox(width: 6),

          // 类型图标 + 名称
          Icon(classIcon, size: 18, color: Colors.white70),
          const SizedBox(width: 4),
          SizedBox(
            width: 50,
            child: Text(threat.classId,
                style: const TextStyle(fontSize: 12),
                overflow: TextOverflow.ellipsis),
          ),
          const SizedBox(width: 8),

          // 威胁分数条
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                ClipRRect(
                  borderRadius: BorderRadius.circular(3),
                  child: LinearProgressIndicator(
                    value: threat.threatScore.clamp(0.0, 1.0),
                    minHeight: 6,
                    backgroundColor: Colors.grey.shade800,
                    valueColor:
                        AlwaysStoppedAnimation<Color>(_threatBarColor(threat.threatScore)),
                  ),
                ),
                const SizedBox(height: 2),
                Text('$pct%',
                    style: const TextStyle(fontSize: 10, color: Colors.white54)),
              ],
            ),
          ),
          const SizedBox(width: 8),

          // 距离
          if (threat.distanceM > 0)
            Text('${threat.distanceM.toStringAsFixed(0)}m',
                style: const TextStyle(
                    fontSize: 12,
                    fontFamily: 'monospace',
                    color: Colors.white70)),
        ],
      ),
    );
  }

  Color _threatBarColor(double score) {
    if (score >= 0.7) return Colors.red;
    if (score >= 0.4) return Colors.orange;
    return Colors.amber;
  }
}
