/// Real-time alert banner driven by SSE events.
///
/// Displays a sliding notification at the top of the screen whenever a
/// critical event arrives over the SSE stream.  Critical events are those
/// that require immediate operator attention:
///
///   • fire_executed       — round was fired
///   • fire_chain_state    — FSM entered FIRE_AUTHORIZED or ARMED
///   • operator_timeout    — deadman switch triggered
///   • mission_started     — new mission began
///   • mission_ended       — mission concluded
///
/// The banner auto-dismisses after [_autoDismissSeconds] seconds.
/// Non-critical events (heartbeat, connected) are silently ignored.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/event_stream.dart';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const int _autoDismissSeconds = 6;

@immutable
class _AlertSpec {
  final Color color;
  final IconData icon;
  final String Function(Map<String, dynamic> data) message;

  const _AlertSpec({
    required this.color,
    required this.icon,
    required this.message,
  });
}

const Map<String, _AlertSpec> _specs = {
  'fire_executed': _AlertSpec(
    color: Color(0xFFD32F2F), // red
    icon: Icons.whatshot,
    message: _fireFiredMsg,
  ),
  'fire_chain_state': _AlertSpec(
    color: Color(0xFFF57C00), // deep orange
    icon: Icons.security,
    message: _chainStateMsg,
  ),
  'operator_timeout': _AlertSpec(
    color: Color(0xFF6A1B9A), // purple
    icon: Icons.timer_off,
    message: _timeoutMsg,
  ),
  'mission_started': _AlertSpec(
    color: Color(0xFF2E7D32), // green
    icon: Icons.play_circle_filled,
    message: _missionStartMsg,
  ),
  'mission_ended': _AlertSpec(
    color: Color(0xFF1565C0), // blue
    icon: Icons.stop_circle,
    message: _missionEndMsg,
  ),
};

// ---------------------------------------------------------------------------
// Message builders
// ---------------------------------------------------------------------------

String _fireFiredMsg(Map<String, dynamic> d) {
  final id = d['target_id'] ?? '?';
  final dist = d['distance_m'] ?? 0;
  return 'FIRE EXECUTED  target=$id  range=${dist}m';
}

String _chainStateMsg(Map<String, dynamic> d) {
  final state = (d['state'] as String? ?? '').toUpperCase();
  final prev = (d['prev_state'] as String? ?? '').toUpperCase();
  // Only surface notable transitions.
  if (state == 'FIRE_AUTHORIZED') {
    return 'FIRE AUTHORIZED — target ${d['target_id'] ?? '?'}';
  }
  if (state == 'SAFE' && prev == 'ARMED') {
    return 'Fire chain returned to SAFE';
  }
  return 'Chain: $prev → $state';
}

String _timeoutMsg(Map<String, dynamic> d) {
  final elapsed = d['elapsed_s'] ?? '?';
  return 'OPERATOR TIMEOUT  (${elapsed}s)  — auto-SAFE engaged';
}

String _missionStartMsg(Map<String, dynamic> d) {
  final profile = d['profile'] ?? 'default';
  return 'Mission STARTED  profile=$profile';
}

String _missionEndMsg(Map<String, dynamic> d) {
  final elapsed = d['elapsed_s'] ?? 0;
  return 'Mission ENDED  (${elapsed}s elapsed)';
}

// ---------------------------------------------------------------------------
// Widget
// ---------------------------------------------------------------------------

/// Wraps [child] and overlays a sliding alert banner on critical SSE events.
///
/// Place this at the root of your scaffold body:
/// ```dart
/// AlertBannerOverlay(child: Scaffold(...))
/// ```
class AlertBannerOverlay extends StatefulWidget {
  final Widget child;

  const AlertBannerOverlay({super.key, required this.child});

  @override
  State<AlertBannerOverlay> createState() => _AlertBannerOverlayState();
}

class _AlertBannerOverlayState extends State<AlertBannerOverlay>
    with SingleTickerProviderStateMixin {
  late final AnimationController _animCtrl;
  late final Animation<Offset> _slideAnim;

  StreamSubscription<RwsEvent>? _sub;
  Timer? _dismissTimer;

  String _message = '';
  Color _color = Colors.red;
  IconData _icon = Icons.info;
  bool _visible = false;

  @override
  void initState() {
    super.initState();
    _animCtrl = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 280),
    );
    _slideAnim = Tween<Offset>(
      begin: const Offset(0, -1),
      end: Offset.zero,
    ).animate(CurvedAnimation(parent: _animCtrl, curve: Curves.easeOut));
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _sub?.cancel();
    final es = context.read<EventStreamService>();
    _sub = es.events.listen(_onEvent);
  }

  @override
  void dispose() {
    _sub?.cancel();
    _dismissTimer?.cancel();
    _animCtrl.dispose();
    super.dispose();
  }

  void _onEvent(RwsEvent event) {
    final spec = _specs[event.type];
    if (spec == null) return; // ignore non-critical events

    // Filter fire_chain_state to only the notable states.
    if (event.type == 'fire_chain_state') {
      final state = event.data['state'] as String? ?? '';
      final prev = event.data['prev_state'] as String? ?? '';
      final notable = {'fire_authorized', 'safe'};
      if (!notable.contains(state) && !notable.contains(prev)) return;
    }

    final msg = spec.message(event.data);

    setState(() {
      _message = msg;
      _color = spec.color;
      _icon = spec.icon;
      _visible = true;
    });

    _animCtrl.forward(from: 0);
    _dismissTimer?.cancel();
    _dismissTimer = Timer(
      const Duration(seconds: _autoDismissSeconds),
      _dismiss,
    );
  }

  void _dismiss() {
    _animCtrl.reverse().then((_) {
      if (mounted) setState(() => _visible = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    return Stack(
      children: [
        widget.child,
        if (_visible)
          Positioned(
            top: 0,
            left: 0,
            right: 0,
            child: SlideTransition(
              position: _slideAnim,
              child: Material(
                color: _color,
                elevation: 8,
                child: InkWell(
                  onTap: _dismiss,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 16, vertical: 10),
                    child: Row(
                      children: [
                        Icon(_icon, color: Colors.white, size: 20),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Text(
                            _message,
                            style: const TextStyle(
                              color: Colors.white,
                              fontWeight: FontWeight.bold,
                              fontSize: 13,
                              letterSpacing: 0.3,
                            ),
                          ),
                        ),
                        const Icon(Icons.close, color: Colors.white70, size: 18),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }
}
