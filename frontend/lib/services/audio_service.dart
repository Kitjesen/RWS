// ignore: avoid_web_libraries_in_flutter
import 'dart:js' as js;

/// Plays short alert tones for critical system events.
///
/// Primary implementation uses the browser's Web Audio API (no CDN, no assets).
/// All methods are fire-and-forget; errors are silently swallowed so audio
/// issues never crash the UI.
class AudioService {
  static final AudioService _instance = AudioService._();
  factory AudioService() => _instance;
  AudioService._();

  bool _enabled = true;

  bool get enabled => _enabled;
  void setEnabled(bool v) => _enabled = v;

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /// 开火执行 — 短促双响 (800 Hz × 2, 150 ms gap)
  Future<void> playFireExecuted() async {
    if (!_enabled) return;
    _playBeep(frequency: 800, duration: 0.15, volume: 0.35);
    await Future.delayed(const Duration(milliseconds: 300));
    _playBeep(frequency: 800, duration: 0.15, volume: 0.35);
  }

  /// 操作员超时 — 持续低频警报 (400 Hz, 500 ms)
  Future<void> playOperatorTimeout() async {
    if (!_enabled) return;
    _playBeep(frequency: 400, duration: 0.5, volume: 0.4);
  }

  /// 系统健康异常 — 单响警告 (600 Hz, 200 ms)
  Future<void> playHealthDegraded() async {
    if (!_enabled) return;
    _playBeep(frequency: 600, duration: 0.2, volume: 0.3);
  }

  /// 系统武装 — 上升音 (600 Hz → 900 Hz, 两声)
  Future<void> playArmed() async {
    if (!_enabled) return;
    _playBeep(frequency: 600, duration: 0.12, volume: 0.3);
    await Future.delayed(const Duration(milliseconds: 200));
    _playBeep(frequency: 900, duration: 0.15, volume: 0.3);
  }

  // ---------------------------------------------------------------------------
  // Web Audio API implementation
  // ---------------------------------------------------------------------------

  void _playBeep({
    double frequency = 800,
    double duration = 0.15,
    double volume = 0.3,
  }) {
    try {
      js.context.callMethod('eval', ['''
        (function() {
          try {
            var ctx = new (window.AudioContext || window.webkitAudioContext)();
            var osc = ctx.createOscillator();
            var gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.type = 'sine';
            osc.frequency.value = $frequency;
            gain.gain.setValueAtTime($volume, ctx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + $duration);
            osc.start(ctx.currentTime);
            osc.stop(ctx.currentTime + $duration);
            osc.onended = function() { ctx.close(); };
          } catch(e) { console.warn('[AudioService] beep error:', e); }
        })();
      ''']);
    } catch (_) {
      // Silently ignore — audio is non-critical
    }
  }
}
