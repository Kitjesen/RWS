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
      if (mounted) setState(() => _result = {'go': false, 'error': e.toString()});
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final checks = _result?['checks'] as List<dynamic>?;
    final allOk = _result?['go'] == true;
    final errorMsg = _result?['error'] as String?;

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
            if (_loading)
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
              )
            else if (_result == null)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 8),
                child: Text(
                  '点击运行以检查各子系统状态',
                  style: TextStyle(color: Colors.grey, fontSize: 13),
                ),
              )
            else if (errorMsg != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(
                  '自检失败: $errorMsg',
                  style: const TextStyle(color: Colors.red, fontSize: 12),
                ),
              )
            else if (checks != null)
              ...checks.map((e) => _CheckRow(
                    entry: e as Map<String, dynamic>,
                  )),

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
  final Map<String, dynamic> entry;

  const _CheckRow({required this.entry});

  @override
  Widget build(BuildContext context) {
    final ok = entry['status'] == 'pass';
    final name = entry['name'] as String? ?? '?';
    final message = entry['message'] as String? ?? '';
    final elapsedMs = entry['elapsed_ms'];
    final icon = ok ? Icons.check_circle_outline : Icons.error_outline;
    final color = ok ? Colors.green : Colors.red;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Icon(icon, size: 14, color: color),
          const SizedBox(width: 8),
          SizedBox(
            width: 130,
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
          if (elapsedMs != null)
            Text(
              '${elapsedMs}ms',
              style: const TextStyle(fontSize: 10, color: Colors.white38),
            ),
        ],
      ),
    );
  }
}
