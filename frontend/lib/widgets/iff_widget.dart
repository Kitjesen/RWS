/// 友军识别 (IFF) 白名单管理面板 — mark/unmark track IDs as friendly.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import '../services/api_client.dart';
import '../services/tracking_provider.dart';

class IffWidget extends StatefulWidget {
  const IffWidget({super.key});

  @override
  State<IffWidget> createState() => _IffWidgetState();
}

class _IffWidgetState extends State<IffWidget> {
  List<int> _friendlyIds = [];
  bool _loading = false;
  bool _adding = false;

  final _trackIdCtrl = TextEditingController();
  final _formKey = GlobalKey<FormState>();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _loadStatus();
    });
  }

  @override
  void dispose() {
    _trackIdCtrl.dispose();
    super.dispose();
  }

  RwsApiClient get _api =>
      context.read<TrackingProvider>().api;

  Future<void> _loadStatus() async {
    setState(() => _loading = true);
    try {
      final ids = await _api.getIffFriendlyIds();
      if (mounted) {
        setState(() {
          _friendlyIds = ids;
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _markFriendly() async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    final trackId = int.tryParse(_trackIdCtrl.text.trim());
    if (trackId == null) return;

    // Optimistic: add immediately if not already present
    if (!_friendlyIds.contains(trackId)) {
      setState(() {
        _friendlyIds = [..._friendlyIds, trackId]..sort();
      });
    }

    setState(() => _adding = true);
    try {
      final ok = await _api.markFriendly(trackId);
      if (mounted) {
        setState(() => _adding = false);
        if (ok) {
          _trackIdCtrl.clear();
          // Refresh from server to ensure consistency
          await _loadStatus();
        } else {
          // Revert optimistic update
          setState(() {
            _friendlyIds =
                _friendlyIds.where((id) => id != trackId).toList();
          });
          _showSnack('标记失败', isError: true);
        }
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _adding = false;
          _friendlyIds =
              _friendlyIds.where((id) => id != trackId).toList();
        });
        _showSnack('标记失败', isError: true);
      }
    }
  }

  Future<void> _unmarkFriendly(int trackId) async {
    // Optimistic removal
    setState(() {
      _friendlyIds = _friendlyIds.where((id) => id != trackId).toList();
    });

    try {
      final ok = await _api.unmarkFriendly(trackId);
      if (mounted && !ok) {
        // Revert: put it back
        setState(() {
          _friendlyIds = [..._friendlyIds, trackId]..sort();
        });
        _showSnack('取消标记失败', isError: true);
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _friendlyIds = [..._friendlyIds, trackId]..sort();
        });
        _showSnack('取消标记失败', isError: true);
      }
    }
  }

  void _showSnack(String msg, {bool isError = false}) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(msg),
        backgroundColor: isError ? Colors.red : Colors.green,
        duration: const Duration(seconds: 2),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // --- 标题行 ---
            Row(
              children: [
                Icon(Icons.verified_user, color: Colors.green.shade400),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    '友军识别 IFF',
                    style: theme.textTheme.titleMedium,
                  ),
                ),
                if (_friendlyIds.isNotEmpty)
                  Container(
                    padding: const EdgeInsets.symmetric(
                        horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(
                      color: Colors.green.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(10),
                    ),
                    child: Text(
                      '${_friendlyIds.length}',
                      style: const TextStyle(
                        color: Colors.green,
                        fontWeight: FontWeight.w600,
                        fontSize: 12,
                      ),
                    ),
                  ),
                const SizedBox(width: 8),
                Tooltip(
                  message: '刷新',
                  child: IconButton(
                    icon: _loading
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white54),
                          )
                        : const Icon(Icons.refresh,
                            size: 18, color: Colors.white54),
                    onPressed: _loading ? null : _loadStatus,
                    padding: EdgeInsets.zero,
                    constraints: const BoxConstraints(),
                  ),
                ),
              ],
            ),
            const Divider(),

            // --- 友军列表 ---
            if (_friendlyIds.isEmpty && !_loading)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: Center(
                  child: Text(
                    '无友军记录',
                    style: TextStyle(color: Colors.grey, fontSize: 13),
                  ),
                ),
              )
            else
              Expanded(
                child: ListView.separated(
                  itemCount: _friendlyIds.length,
                  separatorBuilder: (_, __) => const SizedBox(height: 4),
                  itemBuilder: (_, i) => _IffRow(
                    trackId: _friendlyIds[i],
                    onUnmark: () => _unmarkFriendly(_friendlyIds[i]),
                  ),
                ),
              ),

            // --- 添加输入行 ---
            const SizedBox(height: 8),
            Form(
              key: _formKey,
              child: Row(
                children: [
                  Expanded(
                    child: TextFormField(
                      controller: _trackIdCtrl,
                      keyboardType: TextInputType.number,
                      inputFormatters: [
                        FilteringTextInputFormatter.digitsOnly,
                      ],
                      decoration: const InputDecoration(
                        labelText: 'Track ID',
                        hintText: '输入目标编号',
                        isDense: true,
                        contentPadding: EdgeInsets.symmetric(
                            horizontal: 8, vertical: 8),
                        border: OutlineInputBorder(),
                      ),
                      style: const TextStyle(fontSize: 12),
                      validator: (v) {
                        if (v == null || v.trim().isEmpty) return '必填';
                        final id = int.tryParse(v.trim());
                        if (id == null || id < 0) return '正整数';
                        if (_friendlyIds.contains(id)) return '已存在';
                        return null;
                      },
                      onFieldSubmitted: (_) => _adding ? null : _markFriendly(),
                    ),
                  ),
                  const SizedBox(width: 8),
                  ElevatedButton(
                    onPressed: _adding ? null : _markFriendly,
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.green.shade700,
                      padding: const EdgeInsets.symmetric(
                          horizontal: 12, vertical: 12),
                    ),
                    child: _adding
                        ? const SizedBox(
                            width: 14,
                            height: 14,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text(
                            '标记友军',
                            style: TextStyle(fontSize: 12),
                          ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _IffRow extends StatelessWidget {
  final int trackId;
  final VoidCallback onUnmark;

  const _IffRow({required this.trackId, required this.onUnmark});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: Colors.green.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: Colors.green.withValues(alpha: 0.2)),
      ),
      child: Row(
        children: [
          const Icon(Icons.shield, size: 14, color: Colors.green),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              'Track #$trackId',
              style: const TextStyle(
                fontSize: 13,
                fontFamily: 'monospace',
                color: Colors.white,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
          Chip(
            label: const Text(
              '友军',
              style: TextStyle(fontSize: 10, color: Colors.green),
            ),
            backgroundColor: Colors.green.withValues(alpha: 0.12),
            side: BorderSide(color: Colors.green.withValues(alpha: 0.3)),
            padding: EdgeInsets.zero,
            labelPadding:
                const EdgeInsets.symmetric(horizontal: 6, vertical: -2),
            visualDensity: VisualDensity.compact,
          ),
          const SizedBox(width: 6),
          Tooltip(
            message: '取消友军标记',
            child: InkWell(
              onTap: onUnmark,
              borderRadius: BorderRadius.circular(4),
              child: Padding(
                padding: const EdgeInsets.all(4),
                child: Icon(Icons.close,
                    size: 16, color: Colors.red.shade300),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
