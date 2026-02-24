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
        final designatedId = p.designatedTrackId;
        final pipelineActive = p.pipelineActive;

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
                    const Spacer(),
                    // Clear designation button (shown only when active)
                    if (designatedId != null)
                      TextButton.icon(
                        icon: const Icon(Icons.cancel, size: 14),
                        label: Text('取消指定 #$designatedId',
                            style: const TextStyle(fontSize: 11)),
                        style: TextButton.styleFrom(
                          foregroundColor: Colors.orange,
                          padding: const EdgeInsets.symmetric(
                              horizontal: 8, vertical: 4),
                          tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        ),
                        onPressed: () => p.clearDesignation(),
                      ),
                  ],
                ),
                const Divider(),

                if (threats.isEmpty)
                  Expanded(
                    child: Center(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(
                            pipelineActive
                                ? Icons.shield_outlined
                                : Icons.videocam_off,
                            color: pipelineActive
                                ? Colors.green.shade400
                                : Colors.grey.shade700,
                            size: 40,
                          ),
                          const SizedBox(height: 8),
                          Text(
                            pipelineActive ? '区域清洁 — 无威胁目标' : '跟踪未启动',
                            style: TextStyle(
                              color: pipelineActive
                                  ? Colors.green.shade400
                                  : Colors.grey.shade600,
                              fontWeight: FontWeight.w500,
                              fontSize: 14,
                            ),
                          ),
                          if (!pipelineActive)
                            Padding(
                              padding: const EdgeInsets.only(top: 4),
                              child: Text(
                                '请先启动任务',
                                style: TextStyle(
                                    color: Colors.grey.shade700,
                                    fontSize: 12),
                              ),
                            ),
                        ],
                      ),
                    ),
                  )
                else
                  Expanded(
                    child: ListView.separated(
                      itemCount: threats.length,
                      separatorBuilder: (_, __) =>
                          const SizedBox(height: 6),
                      itemBuilder: (_, i) => _ThreatTile(
                        threat: threats[i],
                        isDesignated: threats[i].trackId == designatedId,
                        onDesignate: () =>
                            p.designateTarget(threats[i].trackId),
                        onClear: () => p.clearDesignation(),
                      ),
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
  final bool isDesignated;
  final VoidCallback onDesignate;
  final VoidCallback onClear;

  const _ThreatTile({
    required this.threat,
    required this.isDesignated,
    required this.onDesignate,
    required this.onClear,
  });

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

    // Designated tiles get a bright cyan border
    final borderColor = isDesignated
        ? Colors.cyanAccent.withValues(alpha: 0.9)
        : rankColor.withValues(alpha: 0.2);
    final bgColor = isDesignated
        ? Colors.cyan.withValues(alpha: 0.08)
        : rankColor.withValues(alpha: 0.06);

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: bgColor,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
            color: borderColor, width: isDesignated ? 1.5 : 1.0),
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
                    valueColor: AlwaysStoppedAnimation<Color>(
                        _threatBarColor(threat.threatScore)),
                  ),
                ),
                const SizedBox(height: 2),
                Text('$pct%',
                    style:
                        const TextStyle(fontSize: 10, color: Colors.white54)),
              ],
            ),
          ),
          const SizedBox(width: 8),

          // 距离
          if (threat.distanceM > 0)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Text('${threat.distanceM.toStringAsFixed(0)}m',
                  style: const TextStyle(
                      fontSize: 12,
                      fontFamily: 'monospace',
                      color: Colors.white70)),
            ),

          // 指定按钮
          _DesignateButton(
            isDesignated: isDesignated,
            onDesignate: onDesignate,
            onClear: onClear,
          ),
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

class _DesignateButton extends StatelessWidget {
  final bool isDesignated;
  final VoidCallback onDesignate;
  final VoidCallback onClear;

  const _DesignateButton({
    required this.isDesignated,
    required this.onDesignate,
    required this.onClear,
  });

  @override
  Widget build(BuildContext context) {
    if (isDesignated) {
      return Tooltip(
        message: '取消指定',
        child: InkWell(
          onTap: onClear,
          borderRadius: BorderRadius.circular(4),
          child: Container(
            padding:
                const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
            decoration: BoxDecoration(
              color: Colors.cyan.withValues(alpha: 0.2),
              border: Border.all(color: Colors.cyanAccent),
              borderRadius: BorderRadius.circular(4),
            ),
            child: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(Icons.my_location, size: 12, color: Colors.cyanAccent),
                SizedBox(width: 3),
                Text('LOCK',
                    style: TextStyle(
                        fontSize: 10,
                        color: Colors.cyanAccent,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 0.5)),
              ],
            ),
          ),
        ),
      );
    }

    return Tooltip(
      message: '指定此目标',
      child: InkWell(
        onTap: onDesignate,
        borderRadius: BorderRadius.circular(4),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
          decoration: BoxDecoration(
            border: Border.all(color: Colors.white24),
            borderRadius: BorderRadius.circular(4),
          ),
          child: const Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.gps_fixed, size: 12, color: Colors.white54),
              SizedBox(width: 3),
              Text('指定',
                  style: TextStyle(fontSize: 10, color: Colors.white54)),
            ],
          ),
        ),
      ),
    );
  }
}
