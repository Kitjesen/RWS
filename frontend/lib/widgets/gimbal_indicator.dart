import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/tracking_provider.dart';

const int _kTrailLength = 60; // positions to remember (~12 s at 200 ms polling)

class GimbalIndicator extends StatefulWidget {
  const GimbalIndicator({super.key});

  @override
  State<GimbalIndicator> createState() => _GimbalIndicatorState();
}

class _GimbalIndicatorState extends State<GimbalIndicator> {
  // Ring buffer of (yawDeg, pitchDeg) pairs — oldest first.
  final List<(double, double)> _trail = [];

  void _addToTrail(double yaw, double pitch) {
    if (_trail.isNotEmpty) {
      final (lastY, lastP) = _trail.last;
      // Skip if position hasn't meaningfully changed (reduces clutter).
      if ((yaw - lastY).abs() < 0.05 && (pitch - lastP).abs() < 0.05) return;
    }
    _trail.add((yaw, pitch));
    if (_trail.length > _kTrailLength) _trail.removeAt(0);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Consumer<TrackingProvider>(
      builder: (_, p, __) {
        final s = p.status;
        _addToTrail(s.yawDeg, s.pitchDeg);

        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.control_camera, color: theme.colorScheme.primary),
                    const SizedBox(width: 8),
                    Text('云台姿态', style: theme.textTheme.titleMedium),
                  ],
                ),
                const SizedBox(height: 8),
                Expanded(
                  child: LayoutBuilder(
                    builder: (context, constraints) {
                      final size = math.min(constraints.maxWidth, constraints.maxHeight);
                      return Center(
                        child: SizedBox(
                          width: size,
                          height: size,
                          child: CustomPaint(
                            painter: _GimbalPainter(
                              yawDeg: s.yawDeg,
                              pitchDeg: s.pitchDeg,
                              yawErrorDeg: s.yawErrorDeg,
                              pitchErrorDeg: s.pitchErrorDeg,
                              trail: List.unmodifiable(_trail),
                              primaryColor: theme.colorScheme.primary,
                            ),
                          ),
                        ),
                      );
                    },
                  ),
                ),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceAround,
                  children: [
                    _AngleLabel(label: 'Yaw', valueDeg: s.yawDeg, errorDeg: s.yawErrorDeg),
                    _AngleLabel(label: 'Pitch', valueDeg: s.pitchDeg, errorDeg: s.pitchErrorDeg),
                  ],
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _AngleLabel extends StatelessWidget {
  final String label;
  final double valueDeg;
  final double errorDeg;

  const _AngleLabel({required this.label, required this.valueDeg, required this.errorDeg});

  @override
  Widget build(BuildContext context) {
    final errColor = errorDeg.abs() < 1.0
        ? Colors.green
        : errorDeg.abs() < 3.0
            ? Colors.orange
            : Colors.red;

    return Column(
      children: [
        Text(label, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w500)),
        Text('${valueDeg.toStringAsFixed(1)}°',
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.bold)),
        Text('err ${errorDeg.toStringAsFixed(2)}°',
            style: TextStyle(fontSize: 11, color: errColor)),
      ],
    );
  }
}

class _GimbalPainter extends CustomPainter {
  final double yawDeg;
  final double pitchDeg;
  final double yawErrorDeg;
  final double pitchErrorDeg;
  final List<(double, double)> trail;
  final Color primaryColor;

  _GimbalPainter({
    required this.yawDeg,
    required this.pitchDeg,
    required this.yawErrorDeg,
    required this.pitchErrorDeg,
    required this.trail,
    required this.primaryColor,
  });

  static const double maxDeg = 90.0;

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = math.min(size.width, size.height) / 2 - 8;

    // Background circles
    final bgPaint = Paint()
      ..color = primaryColor.withValues(alpha: 0.08)
      ..style = PaintingStyle.fill;
    canvas.drawCircle(center, radius, bgPaint);

    final ringPaint = Paint()
      ..color = primaryColor.withValues(alpha: 0.25)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 0.8;
    for (final f in [0.33, 0.66, 1.0]) {
      canvas.drawCircle(center, radius * f, ringPaint);
    }

    // Crosshair
    final crossPaint = Paint()
      ..color = primaryColor.withValues(alpha: 0.15)
      ..strokeWidth = 0.5;
    canvas.drawLine(Offset(center.dx - radius, center.dy),
        Offset(center.dx + radius, center.dy), crossPaint);
    canvas.drawLine(Offset(center.dx, center.dy - radius),
        Offset(center.dx, center.dy + radius), crossPaint);

    // Trail — faded dots, oldest most transparent
    final trailLen = trail.length;
    for (int i = 0; i < trailLen; i++) {
      final (ty, tp) = trail[i];
      final age = (trailLen - i) / trailLen; // 1.0 = oldest, 0.0 = newest
      final alpha = (1.0 - age) * 0.55; // newest ~0.55, oldest ~0.0
      final dotRadius = 2.0 + (1.0 - age) * 1.5;
      final tx = (ty / maxDeg).clamp(-1.0, 1.0);
      final tpy = (-tp / maxDeg).clamp(-1.0, 1.0);
      final tPos = Offset(center.dx + tx * radius, center.dy + tpy * radius);
      canvas.drawCircle(
        tPos,
        dotRadius,
        Paint()..color = Colors.cyanAccent.withValues(alpha: alpha),
      );
    }

    // Current position dot
    final nx = (yawDeg / maxDeg).clamp(-1.0, 1.0);
    final ny = (-pitchDeg / maxDeg).clamp(-1.0, 1.0);
    final pos = Offset(center.dx + nx * radius, center.dy + ny * radius);

    final dotPaint = Paint()..color = Colors.cyanAccent;
    canvas.drawCircle(pos, 5, dotPaint);

    // Error ring around dot
    final errMag = math.sqrt(yawErrorDeg * yawErrorDeg + pitchErrorDeg * pitchErrorDeg);
    final errRadius = (errMag / maxDeg * radius).clamp(2.0, radius * 0.5);
    final errColor = errMag < 1.0 ? Colors.green : errMag < 3.0 ? Colors.orange : Colors.red;
    final errPaint = Paint()
      ..color = errColor.withValues(alpha: 0.4)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.5;
    canvas.drawCircle(pos, errRadius, errPaint);
  }

  @override
  bool shouldRepaint(covariant _GimbalPainter old) => true; // trail changes every poll
}
