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

  @override
  void initState() {
    super.initState();
    // Load profiles after the first frame so the provider is available.
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadProfiles());
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

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Consumer<TrackingProvider>(
      builder: (_, provider, __) {
        final mission = provider.missionStatus;
        final lastReport = provider.lastReportPath;

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
                    _MissionStatusChip(active: mission.active),
                  ],
                ),
                const Divider(),

                // ── Active mission status ─────────────────────────────────
                if (mission.active) ...[
                  _ActiveStatusSection(mission: mission),
                  const SizedBox(height: 12),
                ],

                // ── Profile selector (only when idle) ────────────────────
                if (!mission.active) ...[
                  _ProfileDropdown(
                    profiles: _profiles,
                    selected: _selectedProfile,
                    onChanged: (val) {
                      if (val != null) setState(() => _selectedProfile = val);
                    },
                  ),
                  const SizedBox(height: 12),
                ],

                // ── Start / End buttons ───────────────────────────────────
                if (!mission.active)
                  _StartButton(
                    busy: _busy,
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

  const _ActiveStatusSection({required this.mission});

  @override
  Widget build(BuildContext context) {
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
                mission.elapsedFormatted,
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
                  '${mission.targetsEngaged} target${mission.targetsEngaged == 1 ? '' : 's'} engaged',
                  style: const TextStyle(fontSize: 12, color: Colors.white70),
                ),
                const SizedBox(width: 12),
              ],
              if (mission.fireChainState != null)
                _FireChainChip(state: mission.fireChainState!),
            ],
          ),
        ],
      ),
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
            value: profiles.contains(selected) ? selected : profiles.first,
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
  final VoidCallback onPressed;

  const _StartButton({required this.busy, required this.onPressed});

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
            : const Icon(Icons.play_arrow),
        label: const Text('START MISSION'),
        style: FilledButton.styleFrom(
          backgroundColor: Colors.green.shade700,
          foregroundColor: Colors.white,
          disabledBackgroundColor: Colors.grey.shade800,
          disabledForegroundColor: Colors.grey.shade500,
        ),
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
