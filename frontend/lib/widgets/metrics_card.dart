import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/tracking_provider.dart';

class MetricsCard extends StatelessWidget {
  const MetricsCard({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Consumer<TrackingProvider>(
      builder: (_, p, __) {
        final s = p.status;

        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.analytics, color: theme.colorScheme.primary),
                    const SizedBox(width: 8),
                    Text('指标', style: theme.textTheme.titleMedium),
                  ],
                ),
                const Divider(),
                Expanded(
                  child: Row(
                    children: [
                      Expanded(
                        child: _MetricTile(
                          label: '平均误差',
                          value: '${s.avgError.toStringAsFixed(2)}°',
                          icon: Icons.gps_fixed,
                          color: s.avgError < 1.0
                              ? Colors.green
                              : s.avgError < 3.0
                                  ? Colors.orange
                                  : Colors.red,
                        ),
                      ),
                      const VerticalDivider(width: 1),
                      Expanded(
                        child: _MetricTile(
                          label: '目标切换',
                          value: '${s.switchesPerMin.toStringAsFixed(1)}/min',
                          icon: Icons.swap_horiz,
                          color: s.switchesPerMin < 5
                              ? Colors.green
                              : s.switchesPerMin < 15
                                  ? Colors.orange
                                  : Colors.red,
                        ),
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
}

class _MetricTile extends StatelessWidget {
  final String label;
  final String value;
  final IconData icon;
  final Color color;

  const _MetricTile({
    required this.label,
    required this.value,
    required this.icon,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Column(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Icon(icon, color: color, size: 24),
        const SizedBox(height: 4),
        Text(value,
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.bold,
              color: color,
            )),
        const SizedBox(height: 2),
        Text(label,
            style: TextStyle(
              fontSize: 11,
              color: Theme.of(context).hintColor,
            )),
      ],
    );
  }
}
