/// 禁射区管理面板 — list, add, and remove no-fire zones at runtime.
library;

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../models/tracking_models.dart';
import '../services/tracking_provider.dart';

class SafetyZonesWidget extends StatefulWidget {
  const SafetyZonesWidget({super.key});

  @override
  State<SafetyZonesWidget> createState() => _SafetyZonesWidgetState();
}

class _SafetyZonesWidgetState extends State<SafetyZonesWidget> {
  bool _showAddForm = false;

  // Add-form controllers
  final _yawCtrl = TextEditingController();
  final _pitchCtrl = TextEditingController();
  final _radiusCtrl = TextEditingController();
  final _idCtrl = TextEditingController();
  final _formKey = GlobalKey<FormState>();
  bool _adding = false;

  @override
  void initState() {
    super.initState();
    // Load zones on first mount.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<TrackingProvider>().loadNfzZones();
    });
  }

  @override
  void dispose() {
    _yawCtrl.dispose();
    _pitchCtrl.dispose();
    _radiusCtrl.dispose();
    _idCtrl.dispose();
    super.dispose();
  }

  void _toggleForm() {
    setState(() {
      _showAddForm = !_showAddForm;
      if (!_showAddForm) {
        _yawCtrl.clear();
        _pitchCtrl.clear();
        _radiusCtrl.clear();
        _idCtrl.clear();
      }
    });
  }

  Future<void> _submit(TrackingProvider p) async {
    if (!(_formKey.currentState?.validate() ?? false)) return;
    setState(() => _adding = true);

    final zone = SafetyZoneModel(
      zoneId: _idCtrl.text.trim(),
      centerYawDeg: double.parse(_yawCtrl.text),
      centerPitchDeg: double.parse(_pitchCtrl.text),
      radiusDeg: double.parse(_radiusCtrl.text),
    );

    final ok = await p.addNfzZone(zone);
    if (mounted) {
      setState(() {
        _adding = false;
        if (ok) {
          _showAddForm = false;
          _yawCtrl.clear();
          _pitchCtrl.clear();
          _radiusCtrl.clear();
          _idCtrl.clear();
        }
      });
      if (!ok) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('添加失败'), backgroundColor: Colors.red),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Consumer<TrackingProvider>(
      builder: (_, p, __) {
        final zones = p.nfzZones;

        return Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // 标题行
                Row(
                  children: [
                    Icon(Icons.block, color: Colors.red.shade400),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text('禁射区 No-Fire Zones',
                          style: theme.textTheme.titleMedium),
                    ),
                    if (zones.isNotEmpty)
                      Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 2),
                        decoration: BoxDecoration(
                          color: Colors.red.withValues(alpha: 0.15),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Text('${zones.length}',
                            style: const TextStyle(
                                color: Colors.red,
                                fontWeight: FontWeight.w600,
                                fontSize: 12)),
                      ),
                    const SizedBox(width: 8),
                    Tooltip(
                      message: _showAddForm ? '取消' : '添加禁射区',
                      child: IconButton(
                        icon: Icon(
                            _showAddForm ? Icons.close : Icons.add_circle,
                            color: _showAddForm ? Colors.grey : Colors.green,
                            size: 20),
                        onPressed: _toggleForm,
                        padding: EdgeInsets.zero,
                        constraints: const BoxConstraints(),
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.refresh, size: 18,
                          color: Colors.white54),
                      onPressed: () => p.loadNfzZones(),
                      padding: EdgeInsets.zero,
                      constraints: const BoxConstraints(),
                    ),
                  ],
                ),
                const Divider(),

                // Zone list
                if (zones.isEmpty && !_showAddForm)
                  const Padding(
                    padding: EdgeInsets.symmetric(vertical: 12),
                    child: Center(
                      child: Text('无禁射区',
                          style:
                              TextStyle(color: Colors.grey, fontSize: 13)),
                    ),
                  )
                else
                  Expanded(
                    child: ListView.separated(
                      itemCount: zones.length,
                      separatorBuilder: (_, __) =>
                          const SizedBox(height: 4),
                      itemBuilder: (_, i) => _ZoneRow(
                        zone: zones[i],
                        onDelete: () => p.deleteNfzZone(zones[i].zoneId),
                      ),
                    ),
                  ),

                // Add form
                if (_showAddForm) ...[
                  const SizedBox(height: 8),
                  _AddZoneForm(
                    formKey: _formKey,
                    yawCtrl: _yawCtrl,
                    pitchCtrl: _pitchCtrl,
                    radiusCtrl: _radiusCtrl,
                    idCtrl: _idCtrl,
                    adding: _adding,
                    onSubmit: () => _submit(p),
                    onCancel: _toggleForm,
                  ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }
}

class _ZoneRow extends StatelessWidget {
  final SafetyZoneModel zone;
  final VoidCallback onDelete;

  const _ZoneRow({required this.zone, required this.onDelete});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: Colors.red.withValues(alpha: 0.05),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: Colors.red.withValues(alpha: 0.2)),
      ),
      child: Row(
        children: [
          const Icon(Icons.not_interested, size: 14, color: Colors.red),
          const SizedBox(width: 6),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  zone.zoneId.isEmpty ? '(auto)' : zone.zoneId,
                  style: const TextStyle(
                      fontSize: 11, color: Colors.white70),
                  overflow: TextOverflow.ellipsis,
                ),
                Text(
                  'Y:${zone.centerYawDeg.toStringAsFixed(1)}° '
                  'P:${zone.centerPitchDeg.toStringAsFixed(1)}° '
                  'R:${zone.radiusDeg.toStringAsFixed(1)}°',
                  style: const TextStyle(
                      fontSize: 12,
                      fontFamily: 'monospace',
                      color: Colors.white),
                ),
              ],
            ),
          ),
          const SizedBox(width: 6),
          InkWell(
            onTap: onDelete,
            borderRadius: BorderRadius.circular(4),
            child: Padding(
              padding: const EdgeInsets.all(4),
              child: Icon(Icons.delete_outline,
                  size: 16, color: Colors.red.shade300),
            ),
          ),
        ],
      ),
    );
  }
}

class _AddZoneForm extends StatelessWidget {
  final GlobalKey<FormState> formKey;
  final TextEditingController yawCtrl, pitchCtrl, radiusCtrl, idCtrl;
  final bool adding;
  final VoidCallback onSubmit, onCancel;

  const _AddZoneForm({
    required this.formKey,
    required this.yawCtrl,
    required this.pitchCtrl,
    required this.radiusCtrl,
    required this.idCtrl,
    required this.adding,
    required this.onSubmit,
    required this.onCancel,
  });

  @override
  Widget build(BuildContext context) {
    return Form(
      key: formKey,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text('添加禁射区',
              style: TextStyle(
                  fontSize: 12,
                  color: Colors.white70,
                  fontWeight: FontWeight.w600)),
          const SizedBox(height: 8),
          // ID field (optional)
          TextFormField(
            controller: idCtrl,
            decoration: const InputDecoration(
              labelText: 'ID (可选)',
              isDense: true,
              contentPadding:
                  EdgeInsets.symmetric(horizontal: 8, vertical: 6),
              border: OutlineInputBorder(),
            ),
            style: const TextStyle(fontSize: 12),
          ),
          const SizedBox(height: 8),
          // Yaw / Pitch / Radius row
          Row(
            children: [
              Expanded(
                  child: _NumField(
                      ctrl: yawCtrl, label: 'Yaw (°)', allowNeg: true)),
              const SizedBox(width: 8),
              Expanded(
                  child: _NumField(
                      ctrl: pitchCtrl, label: 'Pitch (°)', allowNeg: true)),
              const SizedBox(width: 8),
              Expanded(
                  child: _NumField(
                      ctrl: radiusCtrl,
                      label: '半径 (°)',
                      allowNeg: false)),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              TextButton(
                  onPressed: onCancel,
                  child: const Text('取消',
                      style: TextStyle(color: Colors.grey))),
              const SizedBox(width: 8),
              ElevatedButton(
                onPressed: adding ? null : onSubmit,
                style: ElevatedButton.styleFrom(
                    backgroundColor: Colors.red.shade700),
                child: adding
                    ? const SizedBox(
                        width: 14,
                        height: 14,
                        child: CircularProgressIndicator(strokeWidth: 2))
                    : const Text('添加', style: TextStyle(fontSize: 12)),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _NumField extends StatelessWidget {
  final TextEditingController ctrl;
  final String label;
  final bool allowNeg;

  const _NumField(
      {required this.ctrl, required this.label, required this.allowNeg});

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: ctrl,
      keyboardType: const TextInputType.numberWithOptions(
          signed: true, decimal: true),
      decoration: InputDecoration(
        labelText: label,
        isDense: true,
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        border: const OutlineInputBorder(),
      ),
      style: const TextStyle(fontSize: 12),
      validator: (v) {
        if (v == null || v.isEmpty) return '必填';
        final d = double.tryParse(v);
        if (d == null) return '数字';
        if (!allowNeg && d <= 0) return '>0';
        return null;
      },
    );
  }
}
