/// 任务前自检面板 — runs GET /api/selftest and shows a go/no-go checklist.
library;

import 'package:flutter/material.dart';
import '../models/tracking_models.dart';
import '../services/api_client.dart';

/// Maps known selftest check names to their Chinese display labels.
const _nameTranslations = <String, String>{
  'pipeline_imports': '模块导入',
  'shooting_chain': '射击链',
  'audit_logger': '审计日志',
  'health_monitor': '健康监视',
  'lifecycle_manager': '生命周期管理',
  'logs_dir_writable': '日志目录',
  'config_valid': '配置验证',
};

class PreflightWidget extends StatefulWidget {
  final RwsApiClient api;

  const PreflightWidget({super.key, required this.api});

  @override
  State<PreflightWidget> createState() => _PreflightWidgetState();
}

class _PreflightWidgetState extends State<PreflightWidget> {
  bool _running = false;
  bool _go = false;
  List<SelfTestCheck> _checks = [];
  bool _ran = false;

  Future<void> _runSelftest() async {
    setState(() {
      _running = true;
      _ran = false;
      _checks = [];
    });

    try {
      final result = await widget.api.runSelftest();
      if (mounted) {
        setState(() {
          _running = false;
          _ran = true;
          _go = result.go;
          _checks = result.checks;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _running = false;
          _ran = true;
          _go = false;
          _checks = [];
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            // --- Header row ---
            Row(
              children: [
                Icon(Icons.flight_takeoff,
                    color: theme.colorScheme.primary, size: 20),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    '任务前自检',
                    style: theme.textTheme.titleMedium,
                  ),
                ),
                ElevatedButton.icon(
                  onPressed: _running ? null : _runSelftest,
                  icon: _running
                      ? const SizedBox(
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : const Icon(Icons.play_arrow, size: 16),
                  label: Text(
                    _running ? '检测中...' : '运行自检',
                    style: const TextStyle(fontSize: 13),
                  ),
                  style: ElevatedButton.styleFrom(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 14, vertical: 8),
                    visualDensity: VisualDensity.compact,
                  ),
                ),
              ],
            ),

            // --- Progress indicator while running ---
            if (_running) ...[
              const SizedBox(height: 12),
              const LinearProgressIndicator(),
            ],

            // --- Results ---
            if (_ran && !_running) ...[
              const SizedBox(height: 12),
              _GoBanner(go: _go),
              if (_checks.isNotEmpty) ...[
                const SizedBox(height: 10),
                const Divider(height: 1),
                const SizedBox(height: 6),
                ..._checks.map((c) => _CheckRow(check: c)),
              ],
            ],
          ],
        ),
      ),
    );
  }
}

// --- GO / NO-GO colored banner ---

class _GoBanner extends StatelessWidget {
  final bool go;

  const _GoBanner({required this.go});

  @override
  Widget build(BuildContext context) {
    final color = go ? Colors.green : Colors.red;
    final label = go ? '系统就绪  GO' : '系统异常  NO-GO';
    final icon = go ? Icons.check_circle_outline : Icons.cancel_outlined;

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 20),
          const SizedBox(width: 10),
          Text(
            label,
            style: TextStyle(
              color: color,
              fontWeight: FontWeight.w700,
              fontSize: 15,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }
}

// --- Individual check row ---

class _CheckRow extends StatelessWidget {
  final SelfTestCheck check;

  const _CheckRow({required this.check});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final passed = check.passed;
    final color = passed ? Colors.green : Colors.red;
    final icon = passed ? Icons.check_circle : Icons.cancel;
    final displayName = _nameTranslations[check.name] ?? check.name;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 1),
            child: Icon(icon, color: color, size: 18),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  displayName,
                  style: theme.textTheme.bodyMedium?.copyWith(
                    fontWeight: FontWeight.w600,
                    color: color,
                  ),
                ),
                if (check.message.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text(
                      check.message,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: Colors.white60,
                        fontFamily: 'monospace',
                        fontSize: 11,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
