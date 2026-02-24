import 'dart:math' as math;
import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/tracking_provider.dart';

// ─────────────────────────────────────────────
//  State → background band color mapping
// ─────────────────────────────────────────────
Color _stateColor(String state) {
  switch (state.toUpperCase()) {
    case 'TRACK':
      return Colors.blue.withValues(alpha: 0.12);
    case 'LOCK':
      return Colors.green.withValues(alpha: 0.15);
    case 'LOST':
      return Colors.orange.withValues(alpha: 0.12);
    case 'SEARCH':
    default:
      return Colors.grey.withValues(alpha: 0.12);
  }
}

// ─────────────────────────────────────────────
//  Custom painter: vertical state bands
// ─────────────────────────────────────────────
class _StateBandPainter extends CustomPainter {
  final List<String> stateHistory;

  const _StateBandPainter({required this.stateHistory});

  @override
  void paint(Canvas canvas, Size size) {
    if (stateHistory.isEmpty) return;

    final n = stateHistory.length;
    int runStart = 0;

    while (runStart < n) {
      final runState = stateHistory[runStart];
      int runEnd = runStart + 1;
      while (runEnd < n && stateHistory[runEnd] == runState) {
        runEnd++;
      }

      // Map sample indices to x pixel coordinates
      final x0 = (runStart / n) * size.width;
      final x1 = (runEnd / n) * size.width;

      final paint = Paint()
        ..color = _stateColor(runState)
        ..style = PaintingStyle.fill;

      canvas.drawRect(Rect.fromLTRB(x0, 0, x1, size.height), paint);

      runStart = runEnd;
    }
  }

  @override
  bool shouldRepaint(_StateBandPainter oldDelegate) =>
      oldDelegate.stateHistory != stateHistory;
}

// ─────────────────────────────────────────────
//  Main chart widget (StatefulWidget for smooth Y)
// ─────────────────────────────────────────────
class ErrorChartWidget extends StatefulWidget {
  const ErrorChartWidget({super.key});

  @override
  State<ErrorChartWidget> createState() => _ErrorChartWidgetState();
}

class _ErrorChartWidgetState extends State<ErrorChartWidget> {
  double _smoothedMaxY = 2.0;

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

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Consumer<TrackingProvider>(
      builder: (_, p, __) {
        final yawData = p.yawErrorHistory;
        final pitchData = p.pitchErrorHistory;
        final stateData = p.stateHistory;

        if (yawData.isEmpty) {
          return Card(
            child: Center(
              child: Text('等待数据...', style: theme.textTheme.bodyMedium),
            ),
          );
        }

        // Compute raw max then apply exponential smoothing
        double rawMaxY = 1.0;
        for (final v in yawData) {
          if (v.abs() > rawMaxY) rawMaxY = v.abs();
        }
        for (final v in pitchData) {
          if (v.abs() > rawMaxY) rawMaxY = v.abs();
        }
        rawMaxY = math.max(rawMaxY * 1.2, 2.0);
        _smoothedMaxY = _smoothedMaxY * 0.85 + rawMaxY * 0.15;
        final maxY = _smoothedMaxY;

        final yawSpots = <FlSpot>[];
        final pitchSpots = <FlSpot>[];
        for (int i = 0; i < yawData.length; i++) {
          yawSpots.add(FlSpot(i.toDouble(), yawData[i]));
          pitchSpots.add(FlSpot(i.toDouble(), pitchData[i]));
        }

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
                  child: Stack(
                    children: [
                      // Background state bands drawn behind the chart
                      Positioned.fill(
                        child: CustomPaint(
                          painter: _StateBandPainter(stateHistory: stateData),
                        ),
                      ),
                      LineChart(
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
                            topTitles: const AxisTitles(
                              sideTitles: SideTitles(showTitles: false),
                            ),
                            rightTitles: const AxisTitles(
                              sideTitles: SideTitles(showTitles: false),
                            ),
                            bottomTitles: const AxisTitles(
                              sideTitles: SideTitles(showTitles: false),
                            ),
                            leftTitles: AxisTitles(
                              sideTitles: SideTitles(
                                showTitles: true,
                                reservedSize: 36,
                                getTitlesWidget: (v, _) => Text(
                                  v.toStringAsFixed(1),
                                  style: TextStyle(
                                    fontSize: 10,
                                    color: theme.hintColor,
                                  ),
                                ),
                              ),
                            ),
                          ),
                          borderData: FlBorderData(show: false),
                          extraLinesData: ExtraLinesData(
                            horizontalLines: [
                              HorizontalLine(
                                y: 1.2,
                                color: Colors.greenAccent.withValues(alpha: 0.4),
                                strokeWidth: 0.8,
                                dashArray: [4, 4],
                              ),
                              HorizontalLine(
                                y: -1.2,
                                color: Colors.greenAccent.withValues(alpha: 0.4),
                                strokeWidth: 0.8,
                                dashArray: [4, 4],
                              ),
                            ],
                          ),
                          lineBarsData: [
                            _line(yawSpots, Colors.cyanAccent),
                            _line(pitchSpots, Colors.orangeAccent),
                          ],
                          lineTouchData: const LineTouchData(enabled: false),
                        ),
                        duration: const Duration(milliseconds: 0),
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

// ─────────────────────────────────────────────
//  Legend chip
// ─────────────────────────────────────────────
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
