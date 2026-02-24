import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/tracking_provider.dart';
import '../models/tracking_models.dart';
import '../utils/launch_url.dart';

/// Fallback profile list used when the server is unreachable.
const _kFallbackProfiles = ['urban_cqb', 'open_field', 'surveillance', 'drill'];

class MissionControlWidget extends StatefulWidget {
  const MissionControlWidget({super.key});

  @override
  State<MissionControlWidget> createState() => _MissionControlWidgetState();
}

class _MissionControlWidgetState extends State<MissionControlWidget> {
  List<String> _profiles = _kFallbackProfiles;
  String _selectedProfile = _kFallbackProfiles.first;
  bool _busy = false; // guards start/end button during async call

  // Selftest gate: tracks whether the operator has run a passing selftest
  // before attempting to start a mission this session.
  bool _selftestPassed = false;
  bool _selftestRunning = false;

  // Duration counter — ticks every second while a mission is active.
  Timer? _durationTimer;
  int _localElapsedS = 0; // local counter; reset on mission start

  @override
  void initState() {
    super.initState();
    // Load profiles after the first frame so the provider is available.
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadProfiles());
  }

  @override
  void dispose() {
    _durationTimer?.cancel();
    super.dispose();
  }

  Future<void> _loadProfiles() async {
    final api = context.read<TrackingProvider>().api;
    final fetched = await api.fetchProfiles();
    if (!mounted || fetched.isEmpty) return;
    setState(() {
      _profiles = fetched;
      // Keep current selection if still valid; else reset to first.
      if (!_profiles.contains(_selectedProfile)) {
        _selectedProfile = _profiles.first;
      }
    });
  }

  /// Start the 1-second local elapsed-time counter.
  void _startDurationTimer(int initialElapsedS) {
    _durationTimer?.cancel();
    _localElapsedS = initialElapsedS;
    _durationTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() => _localElapsedS++);
    });
  }

  void _stopDurationTimer() {
    _durationTimer?.cancel();
    _durationTimer = null;
    _localElapsedS = 0;
  }

  Future<void> _runSelftest(TrackingProvider provider) async {
    setState(() => _selftestRunning = true);
    try {
      final result = await provider.api.runSelftest();
      if (!mounted) return;
      setState(() {
        _selftestPassed = result.go;
        _selftestRunning = false;
      });
      if (!result.go) {
        final failedNames = result.checks
            .where((c) => !c.passed)
            .map((c) => c.name)
            .join(', ');
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('Pre-flight failed: $failedNames'),
            backgroundColor: Colors.red.shade800,
            duration: const Duration(seconds: 5),
          ),
        );
      }
    } catch (e) {
      if (!mounted) return;
      setState(() => _selftestRunning = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Consumer<TrackingProvider>(
      builder: (_, provider, __) {
        final mission = provider.missionStatus;
        final lastReport = provider.lastReportPath;

        // Sync duration timer with mission state.
        if (mission.active && _durationTimer == null) {
          // Mission just became active — start timer from server's elapsed_s.
          WidgetsBinding.instance.addPostFrameCallback(
            (_) => _startDurationTimer(mission.elapsedS.toInt()),
          );
        } else if (!mission.active && _durationTimer != null) {
          // Mission ended — stop timer.
          WidgetsBinding.instance.addPostFrameCallback(
            (_) => _stopDurationTimer(),
          );
        }

        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // ── Header ────────────────────────────────────────────────
                Row(
                  children: [
                    Icon(Icons.my_location, color: theme.colorScheme.primary),
                    const SizedBox(width: 8),
                    Text(
                      'Mission Control',
                      style: theme.textTheme.titleMedium,
                    ),
                    const Spacer(),
                    // ROE profile chip (shown when mission active or profile selected)
                    _RoeProfileChip(
                      profile: mission.active
                          ? (mission.roeProfile ?? mission.profile)
                          : _selectedProfile,
                    ),
                    const SizedBox(width: 8),
                    _MissionStatusChip(active: mission.active),
                  ],
                ),
                const Divider(),

                // ── Active mission status ─────────────────────────────────
                if (mission.active) ...[
                  _ActiveStatusSection(
                    mission: mission,
                    dwell: provider.dwellStatus,
                    localElapsedS: _localElapsedS,
                  ),
                  const SizedBox(height: 12),
                ],

                // ── Profile selector (only when idle) ────────────────────
                if (!mission.active) ...[
                  _ProfileDropdown(
                    profiles: _profiles,
                    selected: _selectedProfile,
                    onChanged: (val) {
                      if (val != null) {
                        setState(() {
                          _selectedProfile = val;
                          // Profile change invalidates previous selftest pass.
                          _selftestPassed = false;
                        });
                      }
                    },
                  ),
                  const SizedBox(height: 8),

                  // ── Pre-flight gate ──────────────────────────────────────
                  _PreflightGate(
                    passed: _selftestPassed,
                    running: _selftestRunning,
                    onRunSelftest: () => _runSelftest(provider),
                  ),
                  const SizedBox(height: 8),
                ],

                // ── Start / End buttons ───────────────────────────────────
                if (!mission.active)
                  _StartButton(
                    busy: _busy,
                    preflightPassed: _selftestPassed,
                    onPressed: () => _startMission(provider),
                  )
                else
                  _EndButton(
                    busy: _busy,
                    onPressed: () => _confirmEnd(context, provider),
                  ),

                // ── Last report download link ─────────────────────────────
                if (lastReport != null && !mission.active) ...[
                  const SizedBox(height: 10),
                  _ReportLink(reportPath: lastReport, baseUrl: _baseUrl(provider)),
                ],
              ],
            ),
          ),
        );
      },
    );
  }

  /// Derive the base URL by stripping any path suffix from the snapshot URL.
  String _baseUrl(TrackingProvider provider) {
    final snap = provider.snapshotUrl;
    // snapshotUrl is like "http://host:port/api/video/snapshot"
    final uri = Uri.tryParse(snap);
    if (uri == null) return '';
    return '${uri.scheme}://${uri.host}:${uri.port}';
  }

  Future<void> _startMission(TrackingProvider provider) async {
    setState(() => _busy = true);
    try {
      await provider.startMission(_selectedProfile);
      // Reset selftest gate so next mission requires a new check.
      if (mounted) setState(() => _selftestPassed = false);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _confirmEnd(BuildContext context, TrackingProvider provider) {
    showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.stop_circle_outlined, color: Colors.orange),
            SizedBox(width: 8),
            Text('End Mission'),
          ],
        ),
        content: const Text(
          'End the current mission session?\n'
          'A report will be generated.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            style: FilledButton.styleFrom(backgroundColor: Colors.orange),
            child: const Text('End Mission'),
          ),
        ],
      ),
    ).then((confirmed) async {
      if (confirmed != true) return;
      setState(() => _busy = true);
      try {
        await provider.endMission();
      } finally {
        if (mounted) setState(() => _busy = false);
      }
    });
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-widgets
// ─────────────────────────────────────────────────────────────────────────────

class _MissionStatusChip extends StatelessWidget {
  final bool active;

  const _MissionStatusChip({required this.active});

  @override
  Widget build(BuildContext context) {
    final color = active ? Colors.green : Colors.grey;
    final label = active ? 'ACTIVE' : 'IDLE';

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
          Text(
            label,
            style: TextStyle(
              color: color,
              fontWeight: FontWeight.w600,
              fontSize: 12,
            ),
          ),
        ],
      ),
    );
  }
}

class _ActiveStatusSection extends StatelessWidget {
  final MissionStatus mission;
  final EngagementDwellStatus dwell;
  /// Local elapsed seconds maintained by a 1-second Timer in the parent widget.
  /// Falls back to server-reported elapsed_s when 0.
  final int localElapsedS;

  const _ActiveStatusSection({
    required this.mission,
    required this.dwell,
    this.localElapsedS = 0,
  });

  String _formatElapsed(int totalS) {
    final mm = (totalS ~/ 60).toString().padLeft(2, '0');
    final ss = (totalS % 60).toString().padLeft(2, '0');
    return '$mm:$ss';
  }

  @override
  Widget build(BuildContext context) {
    // Prefer local counter (ticks every second) over server-reported value.
    final displayElapsed = localElapsedS > 0
        ? _formatElapsed(localElapsedS)
        : mission.elapsedFormatted;

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.green.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.green.withValues(alpha: 0.2)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Elapsed time + profile row
          Row(
            children: [
              const Icon(Icons.timer_outlined, size: 16, color: Colors.green),
              const SizedBox(width: 6),
              Text(
                displayElapsed,
                style: const TextStyle(
                  fontFamily: 'monospace',
                  fontSize: 20,
                  fontWeight: FontWeight.bold,
                  color: Colors.green,
                  letterSpacing: 2,
                ),
              ),
              const Spacer(),
              if (mission.profile != null)
                Text(
                  mission.profile!,
                  style: const TextStyle(
                    fontSize: 13,
                    color: Colors.white70,
                    fontWeight: FontWeight.w500,
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),

          // Targets engaged + fire chain state
          Row(
            children: [
              if (mission.targetsEngaged != null) ...[
                const Icon(Icons.radar, size: 14, color: Colors.white54),
                const SizedBox(width: 4),
                Text(
                  '${mission.targetsEngaged} 个目标已交战',
                  style: const TextStyle(fontSize: 12, color: Colors.white70),
                ),
                const SizedBox(width: 12),
              ],
              if (mission.fireChainState != null)
                _FireChainChip(state: mission.fireChainState!),
            ],
          ),

          // Engagement dwell timer — only visible when pipeline is dwelling
          if (dwell.active) ...[
            const SizedBox(height: 10),
            _DwellTimerBar(dwell: dwell),
          ],

          // Lifecycle breakdown row (shown only when data is available)
          if (mission.lifecycleByState.isNotEmpty) ...[
            const SizedBox(height: 8),
            _LifecycleStatsRow(lifecycleByState: mission.lifecycleByState),
          ],
        ],
      ),
    );
  }
}

/// Countdown progress bar shown while the pipeline dwells on a locked target.
///
/// Counts from 0 → [dwell.totalS] seconds before auto-advancing to the next
/// engagement target.  The bar fills amber → green as the dwell completes.
class _DwellTimerBar extends StatelessWidget {
  final EngagementDwellStatus dwell;

  const _DwellTimerBar({required this.dwell});

  @override
  Widget build(BuildContext context) {
    // Color ramps from amber (just started) → green (nearly complete)
    final color = dwell.fraction >= 0.8
        ? Colors.green
        : dwell.fraction >= 0.4
            ? Colors.amber
            : Colors.orange;

    final elapsed = dwell.elapsedS.toStringAsFixed(1);
    final total = dwell.totalS.toStringAsFixed(1);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(Icons.hourglass_bottom, size: 13, color: color),
            const SizedBox(width: 5),
            Text(
              '交战驻留  $elapsed s / $total s',
              style: TextStyle(
                fontSize: 11,
                color: color,
                fontFamily: 'monospace',
              ),
            ),
            const Spacer(),
            if (dwell.trackId != null)
              Text(
                '目标 #${dwell.trackId}',
                style: const TextStyle(fontSize: 11, color: Colors.white54),
              ),
          ],
        ),
        const SizedBox(height: 4),
        ClipRRect(
          borderRadius: BorderRadius.circular(3),
          child: LinearProgressIndicator(
            value: dwell.fraction.clamp(0.0, 1.0),
            minHeight: 6,
            backgroundColor: Colors.white10,
            valueColor: AlwaysStoppedAnimation<Color>(color),
          ),
        ),
      ],
    );
  }
}

class _FireChainChip extends StatelessWidget {
  final String state;

  const _FireChainChip({required this.state});

  @override
  Widget build(BuildContext context) {
    final color = switch (state) {
      'fire_authorized' => Colors.amber,
      'armed' => Colors.orange,
      'safe' => Colors.grey,
      'fired' => Colors.red,
      'cooldown' => Colors.blue,
      _ => Colors.grey,
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Text(
        state.toUpperCase().replaceAll('_', ' '),
        style: TextStyle(
          color: color,
          fontSize: 11,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

class _ProfileDropdown extends StatelessWidget {
  final List<String> profiles;
  final String selected;
  final ValueChanged<String?> onChanged;

  const _ProfileDropdown({
    required this.profiles,
    required this.selected,
    required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        const Text(
          'Profile:',
          style: TextStyle(fontSize: 13, color: Colors.white70),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: DropdownButtonFormField<String>(
            initialValue: profiles.contains(selected) ? selected : profiles.first,
            isExpanded: true,
            decoration: InputDecoration(
              contentPadding:
                  const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(8),
              ),
              isDense: true,
            ),
            items: profiles
                .map(
                  (p) => DropdownMenuItem(
                    value: p,
                    child: Text(
                      p,
                      style: const TextStyle(fontSize: 13),
                    ),
                  ),
                )
                .toList(),
            onChanged: onChanged,
          ),
        ),
      ],
    );
  }
}

class _StartButton extends StatelessWidget {
  final bool busy;
  /// Whether the operator has passed the preflight selftest.
  /// When false, the button is shown in a warning style to discourage use
  /// but is NOT disabled — the backend enforces the gate via HTTP 424.
  final bool preflightPassed;
  final VoidCallback onPressed;

  const _StartButton({
    required this.busy,
    required this.onPressed,
    this.preflightPassed = false,
  });

  @override
  Widget build(BuildContext context) {
    final bgColor = preflightPassed ? Colors.green.shade700 : Colors.orange.shade800;

    return SizedBox(
      width: double.infinity,
      height: 44,
      child: FilledButton.icon(
        onPressed: busy ? null : onPressed,
        icon: busy
            ? const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Colors.white,
                ),
              )
            : Icon(preflightPassed ? Icons.play_arrow : Icons.warning_amber_rounded),
        label: Text(preflightPassed ? 'START MISSION' : 'START WITHOUT PREFLIGHT'),
        style: FilledButton.styleFrom(
          backgroundColor: bgColor,
          foregroundColor: Colors.white,
          disabledBackgroundColor: Colors.grey.shade800,
          disabledForegroundColor: Colors.grey.shade500,
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// ROE Profile chip
// ─────────────────────────────────────────────────────────────────────────────

/// A small coloured chip that shows the active Rules of Engagement profile.
///
/// Colour coding:
///   training  → grey   (safe, no live fire)
///   exercise  → orange (simulated engagement)
///   live      → red    (live fire authorised) with warning icon
///
/// Any unrecognised profile name renders as a neutral blue-grey chip.
class _RoeProfileChip extends StatelessWidget {
  final String? profile;

  const _RoeProfileChip({this.profile});

  @override
  Widget build(BuildContext context) {
    if (profile == null || profile!.isEmpty) return const SizedBox.shrink();

    final lower = profile!.toLowerCase();

    final (Color color, IconData? icon) = switch (lower) {
      'training' => (Colors.grey, null),
      'exercise' => (Colors.orange, null),
      'live'     => (Colors.red, Icons.warning_amber_rounded),
      _          => (Colors.blueGrey, null),
    };

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 12, color: color),
            const SizedBox(width: 4),
          ],
          Text(
            profile!.toUpperCase(),
            style: TextStyle(
              color: color,
              fontSize: 10,
              fontWeight: FontWeight.w700,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Pre-flight gate
// ─────────────────────────────────────────────────────────────────────────────

/// Shows the preflight status and a button to run the selftest.
///
/// When [passed] is false, a "PRE-FLIGHT REQUIRED" warning banner is shown
/// so the operator knows they should complete the selftest before starting.
class _PreflightGate extends StatelessWidget {
  final bool passed;
  final bool running;
  final VoidCallback onRunSelftest;

  const _PreflightGate({
    required this.passed,
    required this.running,
    required this.onRunSelftest,
  });

  @override
  Widget build(BuildContext context) {
    if (passed) {
      // Compact "GO" indicator once passed.
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: Colors.green.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: Colors.green.withValues(alpha: 0.25)),
        ),
        child: const Row(
          children: [
            Icon(Icons.check_circle_outline, size: 14, color: Colors.green),
            SizedBox(width: 6),
            Text(
              'Pre-flight passed — GO',
              style: TextStyle(fontSize: 12, color: Colors.green),
            ),
          ],
        ),
      );
    }

    // Warning banner + run button.
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.amber.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: Colors.amber.withValues(alpha: 0.30)),
      ),
      child: Row(
        children: [
          const Icon(Icons.warning_amber_rounded, size: 15, color: Colors.amber),
          const SizedBox(width: 6),
          const Expanded(
            child: Text(
              'PRE-FLIGHT REQUIRED before mission start',
              style: TextStyle(fontSize: 11, color: Colors.amber),
            ),
          ),
          const SizedBox(width: 8),
          SizedBox(
            height: 28,
            child: FilledButton(
              onPressed: running ? null : onRunSelftest,
              style: FilledButton.styleFrom(
                backgroundColor: Colors.amber.shade800,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(horizontal: 10),
                disabledBackgroundColor: Colors.grey.shade800,
              ),
              child: running
                  ? const SizedBox(
                      width: 12,
                      height: 12,
                      child: CircularProgressIndicator(
                        strokeWidth: 1.5,
                        color: Colors.white,
                      ),
                    )
                  : const Text('RUN', style: TextStyle(fontSize: 11)),
            ),
          ),
        ],
      ),
    );
  }
}

class _EndButton extends StatelessWidget {
  final bool busy;
  final VoidCallback onPressed;

  const _EndButton({required this.busy, required this.onPressed});

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 44,
      child: FilledButton.icon(
        onPressed: busy ? null : onPressed,
        icon: busy
            ? const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  color: Colors.white,
                ),
              )
            : const Icon(Icons.stop),
        label: const Text('END MISSION'),
        style: FilledButton.styleFrom(
          backgroundColor: Colors.orange.shade800,
          foregroundColor: Colors.white,
          disabledBackgroundColor: Colors.grey.shade800,
          disabledForegroundColor: Colors.grey.shade500,
        ),
      ),
    );
  }
}

class _ReportLink extends StatelessWidget {
  final String reportPath;
  final String baseUrl;

  const _ReportLink({required this.reportPath, required this.baseUrl});

  @override
  Widget build(BuildContext context) {
    // Build a full URL if the path is relative (starts with /)
    final fullUrl = reportPath.startsWith('http')
        ? reportPath
        : '$baseUrl$reportPath';

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(
        color: Colors.blueGrey.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: Colors.blueGrey.withValues(alpha: 0.25)),
      ),
      child: Row(
        children: [
          const Icon(Icons.description_outlined, size: 16, color: Colors.blueGrey),
          const SizedBox(width: 8),
          const Text(
            'Last report:',
            style: TextStyle(fontSize: 12, color: Colors.white60),
          ),
          const SizedBox(width: 6),
          Expanded(
            child: GestureDetector(
              onTap: () => _launchUrl(fullUrl),
              child: Text(
                _shortPath(reportPath),
                style: const TextStyle(
                  fontSize: 12,
                  color: Colors.lightBlue,
                  decoration: TextDecoration.underline,
                  decorationColor: Colors.lightBlue,
                  overflow: TextOverflow.ellipsis,
                ),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ),
          const SizedBox(width: 4),
          GestureDetector(
            onTap: () => _launchUrl(fullUrl),
            child: const Icon(Icons.open_in_new, size: 14, color: Colors.lightBlue),
          ),
        ],
      ),
    );
  }

  /// Show only the last path segment as the visible label.
  String _shortPath(String path) {
    final parts = path.split(RegExp(r'[/\\]'));
    return parts.lastWhere((s) => s.isNotEmpty, orElse: () => path);
  }

  void _launchUrl(String url) => launchExternalUrl(url);
}

// ─────────────────────────────────────────────────────────────────────────────
// Lifecycle breakdown
// ─────────────────────────────────────────────────────────────────────────────

/// Maps a normalised (lower-case) lifecycle state key to a human-readable
/// Chinese label and a display colour.
const _kLifecycleConfig = <String, (String, Color)>{
  'detected':    ('发现',   Colors.blue),
  'tracked':     ('跟踪中', Colors.cyan),
  'archived':    ('已归档', Colors.grey),
  'neutralized': ('已中和', Colors.green),
};

/// Ordered display sequence for the chips.
const _kLifecycleOrder = ['detected', 'tracked', 'neutralized', 'archived'];

class _LifecycleStatsRow extends StatelessWidget {
  final Map<String, int> lifecycleByState;

  const _LifecycleStatsRow({required this.lifecycleByState});

  @override
  Widget build(BuildContext context) {
    // Normalise keys to lower-case so the widget works regardless of whether
    // the server sends 'DETECTED' or 'detected'.
    final normalised = {
      for (final e in lifecycleByState.entries)
        e.key.toLowerCase(): e.value,
    };

    final chips = _kLifecycleOrder
        .where((key) => normalised.containsKey(key))
        .map((key) {
          final (label, color) = _kLifecycleConfig[key]!;
          return _StatChip(
            label: label,
            count: normalised[key]!,
            color: color,
          );
        })
        .toList();

    // Also render any keys returned by the server that are not in our known
    // list, so new states from the backend are not silently dropped.
    for (final key in normalised.keys) {
      if (!_kLifecycleOrder.contains(key)) {
        chips.add(_StatChip(
          label: key,
          count: normalised[key]!,
          color: Colors.blueGrey,
        ));
      }
    }

    if (chips.isEmpty) return const SizedBox.shrink();

    return Wrap(
      spacing: 6,
      runSpacing: 4,
      children: chips,
    );
  }
}

/// Small coloured pill showing a state label and its count.
class _StatChip extends StatelessWidget {
  final String label;
  final int count;
  final Color color;

  const _StatChip({
    required this.label,
    required this.count,
    required this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            label,
            style: TextStyle(
              fontSize: 11,
              color: color.withValues(alpha: 0.85),
            ),
          ),
          const SizedBox(width: 5),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 5, vertical: 1),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.22),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Text(
              '$count',
              style: TextStyle(
                fontSize: 11,
                fontWeight: FontWeight.bold,
                color: color,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
