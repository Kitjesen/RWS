/// 任务前自检面板 — Pre-flight Go/No-Go check.
library;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_client.dart';
import '../services/tracking_provider.dart';

class PreflightWidget extends StatefulWidget {
  const PreflightWidget({super.key});

  @override
  State<PreflightWidget> createState() => _PreflightWidgetState();
}

class _PreflightWidgetState extends State<PreflightWidget> {
  Map<String, dynamic>? _result;
  bool _loading = false;

  RwsApiClient get _api => context.read<TrackingProvider>().api;

  Future<void> _runSelfTest() async {
    setState(() {
      _loading = true;
      _result = null;
    });
    try {
      final r = await _api.runSelfTest();
      if (mounted) setState(() => _result = r);
    } catch (e) {
      if (mounted) setState(() => _result = {'ok': false, 'error': e.toString()});
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final checks = _result?['checks'] as Map<String, dynamic>?;
    final allOk = _result?['ok'] == true;

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // --- 标题行 ---
            Row(
              children: [
                Icon(
                  _result == null
                      ? Icons.checklist
                      : (allOk ? Icons.check_circle : Icons.cancel),
                  color: _result == null
                      ? theme.colorScheme.primary
                      : (allOk ? Colors.green : Colors.red),
                  size: 20,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text('任务前自检 Pre-flight',
                      style: theme.textTheme.titleMedium),
                ),
                if (_result != null)
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(
                      color: (allOk ? Colors.green : Colors.red)
                          .withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text(
                      allOk ? 'GO' : 'NO-GO',
                      style: TextStyle(
                        color: allOk ? Colors.green : Colors.red,
                        fontWeight: FontWeight.bold,
                        fontSize: 12,
                        letterSpacing: 1,
                      ),
                    ),
                  ),
              ],
            ),
            const Divider(),

            // --- 自检结果列表 ---
            if (_result == null && !_loading)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 8),
                child: Text(
                  '点击运行以检查各子系统状态',
                  style: TextStyle(color: Colors.grey, fontSize: 13),
                ),
              )
            else if (checks != null)
              ...checks.entries.map((e) => _CheckRow(
                    name: e.key,
                    entry: e.value as Map<String, dynamic>,
                  ))
            else if (_loading)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 8),
                child: Row(
                  children: [
                    SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                    SizedBox(width: 10),
                    Text('自检中...', style: TextStyle(fontSize: 13)),
                  ],
                ),
              ),

            const SizedBox(height: 8),
            SizedBox(
              width: double.infinity,
              child: OutlinedButton.icon(
                onPressed: _loading ? null : _runSelfTest,
                icon: _loading
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : const Icon(Icons.play_circle_outline, size: 18),
                label: Text(_result == null ? '运行自检' : '重新运行'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _CheckRow extends StatelessWidget {
  final String name;
  final Map<String, dynamic> entry;

  const _CheckRow({required this.name, required this.entry});

  @override
  Widget build(BuildContext context) {
    final ok = entry['ok'] == true;
    final message = entry['message'] as String? ?? '';
    final icon = ok ? Icons.check_circle_outline : Icons.error_outline;
    final color = ok ? Colors.green : Colors.red;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Icon(icon, size: 14, color: color),
          const SizedBox(width: 8),
          SizedBox(
            width: 140,
            child: Text(
              name,
              style: TextStyle(
                  fontSize: 11,
                  fontFamily: 'monospace',
                  color: color.withValues(alpha: 0.9)),
              overflow: TextOverflow.ellipsis,
            ),
          ),
          Expanded(
            child: Text(
              message,
              style: const TextStyle(fontSize: 11, color: Colors.white54),
              overflow: TextOverflow.ellipsis,
            ),
          ),
        ],
      ),
    );
  }
}
