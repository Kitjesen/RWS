import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/tracking_models.dart';
import '../services/tracking_provider.dart';

class FireControlWidget extends StatefulWidget {
  const FireControlWidget({super.key});

  @override
  State<FireControlWidget> createState() => _FireControlWidgetState();
}

class _FireControlWidgetState extends State<FireControlWidget> {
  late TextEditingController _opIdCtrl;
  final TextEditingController _secondOpCtrl = TextEditingController();

  @override
  void initState() {
    super.initState();
    final p = context.read<TrackingProvider>();
    _opIdCtrl = TextEditingController(text: p.operatorId);
  }

  @override
  void dispose() {
    _opIdCtrl.dispose();
    _secondOpCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Consumer<TrackingProvider>(
      builder: (_, p, __) {
        final fire = p.fireStatus;

        if (_opIdCtrl.text != p.operatorId) {
          _opIdCtrl.text = p.operatorId;
        }

        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(Icons.gps_fixed, color: theme.colorScheme.primary),
                    const SizedBox(width: 8),
                    Text('火控系统', style: theme.textTheme.titleMedium),
                    const Spacer(),
                    _StateChip(state: fire.state),
                  ],
                ),
                const Divider(),

                if (!fire.isConfigured) ...[
                  const Expanded(
                    child: Center(
                      child: Padding(
                        padding: EdgeInsets.all(16),
                        child: Text('火控模块未启用',
                            style: TextStyle(color: Colors.grey, fontSize: 14)),
                      ),
                    ),
                  ),
                ] else ...[
                  // 操作员 ID（仅 SAFE 状态可编辑）
                  if (fire.state == 'safe') ...[
                    TextField(
                      controller: _opIdCtrl,
                      decoration: InputDecoration(
                        labelText: '操作员编号',
                        labelStyle: const TextStyle(fontSize: 12),
                        prefixIcon: const Icon(Icons.badge, size: 18),
                        contentPadding: const EdgeInsets.symmetric(
                            horizontal: 12, vertical: 8),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(8),
                        ),
                        isDense: true,
                      ),
                      style: const TextStyle(fontSize: 13),
                      onChanged: p.setOperatorId,
                    ),
                    const SizedBox(height: 10),
                  ] else if (fire.operatorId != null) ...[
                    Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Row(
                        children: [
                          const Icon(Icons.badge, size: 14, color: Colors.white54),
                          const SizedBox(width: 6),
                          Text(
                            '操作员: ${fire.operatorId}',
                            style: TextStyle(
                                fontSize: 12,
                                color: theme.colorScheme.onSurface
                                    .withValues(alpha: 0.7)),
                          ),
                        ],
                      ),
                    ),
                  ],

                  // 双人规则挂起提示 (two-man arming rule)
                  if (p.armPendingStatus.pending)
                    _TwoManArmBanner(
                      pending: p.armPendingStatus,
                      secondOpCtrl: _secondOpCtrl,
                      onConfirm: () => _confirmSecondOperator(context, p),
                    ),

                  // 按钮行: SAFE / ARM
                  Row(
                    children: [
                      Expanded(
                        child: FilledButton.tonalIcon(
                          onPressed: () => p.safeSystem(),
                          icon: const Icon(Icons.shield, size: 18),
                          label: const Text('解除武装'),
                          style: FilledButton.styleFrom(
                            backgroundColor:
                                Colors.grey.withValues(alpha: 0.15),
                            foregroundColor: Colors.grey.shade300,
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      if (fire.state == 'safe')
                        Expanded(
                          child: Tooltip(
                            message: '武装系统后，安全联锁授权时可发送开火请求',
                            child: FilledButton.tonalIcon(
                              // ARM requires operator ID and confirmation dialog
                              onPressed: p.operatorId.isEmpty
                                  ? null
                                  : () => _confirmArm(context, p),
                              icon: const Icon(Icons.lock_open, size: 18),
                              label: const Text('武装'),
                              style: FilledButton.styleFrom(
                                backgroundColor:
                                    Colors.amber.withValues(alpha: 0.15),
                                foregroundColor: Colors.amber,
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                  const SizedBox(height: 12),

                  // 开火请求按钮
                  SizedBox(
                    width: double.infinity,
                    height: 48,
                    child: FilledButton.icon(
                      onPressed: fire.state == 'fire_authorized'
                          ? () => _confirmFire(context, p)
                          : null,
                      icon: const Icon(Icons.local_fire_department),
                      label: const Text('请求开火'),
                      style: FilledButton.styleFrom(
                        backgroundColor: fire.state == 'fire_authorized'
                            ? Colors.red
                            : Colors.grey.shade800,
                        foregroundColor: Colors.white,
                        disabledBackgroundColor: Colors.grey.shade800,
                        disabledForegroundColor: Colors.grey.shade500,
                      ),
                    ),
                  ),

                  if (fire.state != 'fire_authorized')
                    Padding(
                      padding: const EdgeInsets.only(top: 4),
                      child: Text(
                        _disabledReason(fire.state),
                        style:
                            TextStyle(fontSize: 11, color: Colors.grey.shade500),
                      ),
                    ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }

  String _disabledReason(String state) {
    return switch (state) {
      'safe' => '需要先武装系统',
      'armed' => '等待安全联锁授权',
      'fire_requested' => '开火请求已发送，等待执行',
      'fired' => '已开火',
      'cooldown' => '冷却中...',
      _ => '',
    };
  }

  /// ARM 确认对话框 — 武装是高风险操作，需要二次确认
  void _confirmArm(BuildContext context, TrackingProvider provider) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.warning_amber, color: Colors.amber),
            SizedBox(width: 8),
            Text('确认武装系统'),
          ],
        ),
        content: Text(
          '操作员「${provider.operatorId}」确认武装火控系统？\n\n'
          '武装后，当安全联锁条件满足时系统将进入火控授权状态。\n'
          '请确保周边安全。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () async {
              Navigator.of(ctx).pop();
              final armed = await provider.armSystem();
              if (!armed && provider.armPendingStatus.pending && context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                    content: Text('双人规则已启用：等待第二操作员确认武装'),
                    backgroundColor: Colors.amber,
                    duration: Duration(seconds: 5),
                  ),
                );
              }
            },
            style: FilledButton.styleFrom(backgroundColor: Colors.amber),
            child: const Text('确认武装'),
          ),
        ],
      ),
    );
  }

  /// 第二操作员确认对话框 (双人规则)
  void _confirmSecondOperator(BuildContext context, TrackingProvider provider) {
    _secondOpCtrl.clear();
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.people, color: Colors.orange),
            SizedBox(width: 8),
            Text('双人规则 — 第二操作员确认'),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '操作员「${provider.armPendingStatus.initiatedBy ?? "?"}」已发起武装请求。\n'
              '请第二操作员输入编号以确认武装。',
              style: const TextStyle(fontSize: 13),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _secondOpCtrl,
              decoration: InputDecoration(
                labelText: '第二操作员编号',
                prefixIcon: const Icon(Icons.badge, size: 18),
                border: OutlineInputBorder(
                  borderRadius: BorderRadius.circular(8),
                ),
                isDense: true,
              ),
              autofocus: true,
              style: const TextStyle(fontSize: 13),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () async {
              final secondId = _secondOpCtrl.text.trim();
              if (secondId.isEmpty) return;
              Navigator.of(ctx).pop();
              final ok = await provider.armConfirm(secondId);
              if (context.mounted) {
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(ok ? '武装成功（双人规则已满足）' : '确认失败，请检查操作员编号'),
                    backgroundColor: ok ? Colors.green : Colors.red,
                  ),
                );
              }
            },
            style: FilledButton.styleFrom(backgroundColor: Colors.orange),
            child: const Text('确认武装'),
          ),
        ],
      ),
    );
  }

  /// 开火确认对话框 — 最高级别确认
  void _confirmFire(BuildContext context, TrackingProvider provider) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Row(
          children: [
            Icon(Icons.warning_amber, color: Colors.red),
            SizedBox(width: 8),
            Text('确认开火'),
          ],
        ),
        content: Text(
          '操作员「${provider.operatorId}」确认发送开火请求？\n\n'
          '此操作不可撤销，请再次确认目标已正确识别。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () {
              Navigator.of(ctx).pop();
              provider.requestFire();
            },
            style: FilledButton.styleFrom(backgroundColor: Colors.red),
            child: const Text('确认开火'),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Two-Man Arm Pending Banner
// ---------------------------------------------------------------------------

class _TwoManArmBanner extends StatelessWidget {
  final ArmPendingStatus pending;
  final TextEditingController secondOpCtrl;
  final VoidCallback onConfirm;

  const _TwoManArmBanner({
    required this.pending,
    required this.secondOpCtrl,
    required this.onConfirm,
  });

  @override
  Widget build(BuildContext context) {
    final expires = pending.expiresInS;
    final expiresText = expires != null ? '（剩余 ${expires.toStringAsFixed(0)}s）' : '';

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: Colors.orange.withValues(alpha: 0.12),
        border: Border.all(color: Colors.orange.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.people, color: Colors.orange, size: 16),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  '等待第二操作员确认$expiresText',
                  style: const TextStyle(
                      color: Colors.orange,
                      fontSize: 12,
                      fontWeight: FontWeight.w600),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            '操作员「${pending.initiatedBy ?? "?"}」已发起武装请求，'
            '需要另一名操作员确认。',
            style: TextStyle(fontSize: 11, color: Colors.orange.shade200),
          ),
          const SizedBox(height: 8),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: onConfirm,
              icon: const Icon(Icons.how_to_reg, size: 16),
              label: const Text('第二操作员确认'),
              style: OutlinedButton.styleFrom(
                foregroundColor: Colors.orange,
                side: const BorderSide(color: Colors.orange),
                padding: const EdgeInsets.symmetric(vertical: 6),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _StateChip extends StatelessWidget {
  final String state;

  const _StateChip({required this.state});

  @override
  Widget build(BuildContext context) {
    final (color, label) = _stateStyle(state);

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
          Text(label,
              style: TextStyle(
                  color: color, fontWeight: FontWeight.w600, fontSize: 12)),
        ],
      ),
    );
  }

  (Color, String) _stateStyle(String state) {
    return switch (state) {
      'safe' => (Colors.grey, '安全'),
      'armed' => (Colors.amber, '已武装'),
      'fire_authorized' => (Colors.green, '已授权'),
      'fire_requested' => (Colors.orange, '请求中'),
      'fired' => (Colors.red, '已开火'),
      'cooldown' => (Colors.blue, '冷却中'),
      _ => (Colors.grey, '未配置'),
    };
  }
}
