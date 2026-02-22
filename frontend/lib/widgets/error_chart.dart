import 'dart:math' as math;
import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/tracking_provider.dart';

class ErrorChartWidget extends StatelessWidget {
  const ErrorChartWidget({super.key});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Consumer<TrackingProvider>(
      builder: (_, p, __) {
        final yawData = p.yawErrorHistory;
        final pitchData = p.pitchErrorHistory;
        if (yawData.isEmpty) {
          return Card(
            child: Center(
              child: Text('等待数据...', style: theme.textTheme.bodyMedium),
            ),
          );
        }

        final yawSpots = <FlSpot>[];
        final pitchSpots = <FlSpot>[];
        for (int i = 0; i < yawData.length; i++) {
          yawSpots.add(FlSpot(i.toDouble(), yawData[i]));
          pitchSpots.add(FlSpot(i.toDouble(), pitchData[i]));
        }

        double maxY = 1.0;
        for (final v in yawData) {
          if (v.abs() > maxY) maxY = v.abs();
        }
        for (final v in pitchData) {
          if (v.abs() > maxY) maxY = v.abs();
        }
        maxY = (maxY * 1.2).ceilToDouble();
        maxY = math.max(maxY, 2.0);

        return Card(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.show_chart, color: theme.colorScheme.primary),
                    const SizedBox(width: 8),
                    Text('跟踪误差 (°)', style: theme.textTheme.titleMedium),
                    const Spacer(),
                    _Legend(color: Colors.cyanAccent, label: 'Yaw'),
                    const SizedBox(width: 12),
                    _Legend(color: Colors.orangeAccent, label: 'Pitch'),
                  ],
                ),
                const SizedBox(height: 12),
                Expanded(
                  child: LineChart(
                    LineChartData(
                      minY: -maxY,
                      maxY: maxY,
                      clipData: const FlClipData.all(),
                      gridData: FlGridData(
                        show: true,
                        drawVerticalLine: false,
                        horizontalInterval: maxY / 2,
                        getDrawingHorizontalLine: (_) => FlLine(
                          color: theme.dividerColor.withValues(alpha: 0.2),
                          strokeWidth: 0.5,
                        ),
                      ),
                      titlesData: FlTitlesData(
                        topTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                        rightTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                        bottomTitles: const AxisTitles(sideTitles: SideTitles(showTitles: false)),
                        leftTitles: AxisTitles(
                          sideTitles: SideTitles(
                            showTitles: true,
                            reservedSize: 36,
                            getTitlesWidget: (v, _) => Text(
                              v.toStringAsFixed(1),
                              style: TextStyle(fontSize: 10, color: theme.hintColor),
                            ),
                          ),
                        ),
                      ),
                      borderData: FlBorderData(show: false),
                      lineBarsData: [
                        _line(yawSpots, Colors.cyanAccent),
                        _line(pitchSpots, Colors.orangeAccent),
                      ],
                      lineTouchData: const LineTouchData(enabled: false),
                    ),
                    duration: const Duration(milliseconds: 0),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  LineChartBarData _line(List<FlSpot> spots, Color color) {
    return LineChartBarData(
      spots: spots,
      isCurved: true,
      curveSmoothness: 0.2,
      color: color,
      barWidth: 1.5,
      dotData: const FlDotData(show: false),
      belowBarData: BarAreaData(
        show: true,
        color: color.withValues(alpha: 0.08),
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  final Color color;
  final String label;

  const _Legend({required this.color, required this.label});

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(width: 12, height: 3, color: color),
        const SizedBox(width: 4),
        Text(label, style: TextStyle(fontSize: 11, color: color)),
      ],
    );
  }
}
