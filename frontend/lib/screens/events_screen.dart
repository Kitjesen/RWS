/// Live event log screen — shows all SSE events received since app launch.
///
/// Keeps the last [_maxEvents] events in memory (ring-buffer semantics).
/// Operators can filter by event type and clear the log.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/event_stream.dart';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const int _maxEvents = 300;

/// Per-type display configuration.
@immutable
class _TypeSpec {
  final Color color;
  final IconData icon;
  final String label;

  const _TypeSpec(this.color, this.icon, this.label);
}

const Map<String, _TypeSpec> _typeSpecs = {
  'fire_executed':    _TypeSpec(Color(0xFFD32F2F), Icons.whatshot,            '开火'),
  'fire_chain_state': _TypeSpec(Color(0xFFF57C00), Icons.security,            '火控链'),
  'operator_timeout': _TypeSpec(Color(0xFF6A1B9A), Icons.timer_off,           '操作员超时'),
  'mission_started':  _TypeSpec(Color(0xFF2E7D32), Icons.play_circle_filled,  '任务开始'),
  'mission_ended':    _TypeSpec(Color(0xFF1565C0), Icons.stop_circle,         '任务结束'),
  'target_designated':_TypeSpec(Color(0xFF00838F), Icons.gps_fixed,           '目标指定'),
  'config_reloaded':  _TypeSpec(Color(0xFF4E342E), Icons.settings_backup_restore, '配置重载'),
  'nfz_added':        _TypeSpec(Color(0xFFAD1457), Icons.block,               'NFZ 添加'),
  'nfz_removed':      _TypeSpec(Color(0xFF558B2F), Icons.check_circle_outline, 'NFZ 移除'),
  'heartbeat':        _TypeSpec(Color(0xFF37474F), Icons.favorite_outline,    '心跳'),
};

_TypeSpec _specFor(String type) =>
    _typeSpecs[type] ?? const _TypeSpec(Color(0xFF455A64), Icons.info_outline, 'EVENT');

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------

class EventsScreen extends StatefulWidget {
  const EventsScreen({super.key});

  @override
  State<EventsScreen> createState() => _EventsScreenState();
}

class _EventsScreenState extends State<EventsScreen> {
  final List<RwsEvent> _events = [];
  StreamSubscription<RwsEvent>? _sub;
  String? _filterType; // null = show all
  final ScrollController _scroll = ScrollController();

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
    _scroll.dispose();
    super.dispose();
  }

  void _onEvent(RwsEvent event) {
    setState(() {
      _events.add(event);
      if (_events.length > _maxEvents) _events.removeAt(0);
    });
    // Auto-scroll only if already near the bottom.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients &&
          _scroll.position.maxScrollExtent - _scroll.offset < 200) {
        _scroll.animateTo(
          _scroll.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
      }
    });
  }

  void _clear() => setState(() => _events.clear());

  List<RwsEvent> get _filtered =>
      _filterType == null ? _events : _events.where((e) => e.type == _filterType).toList();

  @override
  Widget build(BuildContext context) {
    final filtered = _filtered;
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('实时事件日志'),
        actions: [
          // Event-type filter
          _TypeFilterMenu(
            current: _filterType,
            onSelected: (t) => setState(() => _filterType = t),
          ),
          // Event count badge
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Center(
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: theme.colorScheme.primaryContainer,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  '${filtered.length}',
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.bold,
                    color: theme.colorScheme.onPrimaryContainer,
                  ),
                ),
              ),
            ),
          ),
          // Clear button
          IconButton(
            icon: const Icon(Icons.clear_all),
            tooltip: '清除日志',
            onPressed: _events.isEmpty ? null : _clear,
          ),
        ],
      ),
      body: filtered.isEmpty
          ? _EmptyState(connected: context.watch<EventStreamService>().connected)
          : ListView.builder(
              controller: _scroll,
              reverse: false,
              padding: const EdgeInsets.symmetric(vertical: 4),
              itemCount: filtered.length,
              itemBuilder: (_, i) => _EventTile(event: filtered[i]),
            ),
    );
  }
}

// ---------------------------------------------------------------------------
// Sub-widgets
// ---------------------------------------------------------------------------

class _EmptyState extends StatelessWidget {
  final bool connected;

  const _EmptyState({required this.connected});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            connected ? Icons.stream : Icons.wifi_off,
            size: 56,
            color: Colors.white24,
          ),
          const SizedBox(height: 16),
          Text(
            connected ? '等待事件...' : 'SSE 已断开',
            style: const TextStyle(color: Colors.white54, fontSize: 16),
          ),
          if (!connected)
            const Padding(
              padding: EdgeInsets.only(top: 6),
              child: Text(
                '自动重连中...',
                style: TextStyle(color: Colors.white38, fontSize: 13),
              ),
            ),
        ],
      ),
    );
  }
}

class _EventTile extends StatelessWidget {
  final RwsEvent event;

  const _EventTile({required this.event});

  @override
  Widget build(BuildContext context) {
    final spec = _specFor(event.type);
    final timeStr = _formatTime(event.receivedAt);
    final summary = _dataSummary(event);

    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: spec.color.withValues(alpha: 0.07),
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: spec.color.withValues(alpha: 0.2)),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Icon
            Padding(
              padding: const EdgeInsets.only(top: 1),
              child: Icon(spec.icon, size: 16, color: spec.color),
            ),
            const SizedBox(width: 10),
            // Type badge
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: spec.color.withValues(alpha: 0.18),
                borderRadius: BorderRadius.circular(4),
              ),
              child: Text(
                spec.label,
                style: TextStyle(
                  fontSize: 10,
                  fontWeight: FontWeight.bold,
                  color: spec.color,
                  letterSpacing: 0.5,
                ),
              ),
            ),
            const SizedBox(width: 10),
            // Summary
            Expanded(
              child: Text(
                summary,
                style: const TextStyle(fontSize: 12, color: Colors.white70),
                overflow: TextOverflow.ellipsis,
                maxLines: 2,
              ),
            ),
            const SizedBox(width: 8),
            // Timestamp
            Text(
              timeStr,
              style: const TextStyle(
                fontSize: 10,
                color: Colors.white38,
                fontFamily: 'monospace',
              ),
            ),
          ],
        ),
      ),
    );
  }

  static String _formatTime(DateTime t) =>
      '${t.hour.toString().padLeft(2, '0')}:'
      '${t.minute.toString().padLeft(2, '0')}:'
      '${t.second.toString().padLeft(2, '0')}';

  static String _dataSummary(RwsEvent event) {
    final d = event.data;
    return switch (event.type) {
      'fire_executed'     => 'target=${d['target_id'] ?? '?'}  range=${d['distance_m'] ?? '?'}m',
      'fire_chain_state'  => '${d['prev_state'] ?? '?'} → ${d['state'] ?? '?'}',
      'operator_timeout'  => 'elapsed=${d['elapsed_s'] ?? '?'}s',
      'mission_started'   => 'profile=${d['profile'] ?? 'default'}',
      'mission_ended'     => 'elapsed=${d['elapsed_s'] ?? '?'}s',
      'target_designated' => 'track_id=${d['track_id'] ?? '?'}',
      'config_reloaded'   => d['profile'] != null ? 'profile=${d['profile']}' : 'config updated',
      'nfz_added'         => 'zone=${d['zone_id'] ?? '?'}',
      'nfz_removed'       => 'zone=${d['zone_id'] ?? '?'}',
      'heartbeat'         => 'ok',
      _                   => d.entries.take(3).map((e) => '${e.key}=${e.value}').join('  '),
    };
  }
}

class _TypeFilterMenu extends StatelessWidget {
  final String? current;
  final ValueChanged<String?> onSelected;

  const _TypeFilterMenu({required this.current, required this.onSelected});

  @override
  Widget build(BuildContext context) {
    final label = current == null ? '全部' : _specFor(current!).label;

    return PopupMenuButton<String?>(
      tooltip: '按类型筛选',
      initialValue: current,
      onSelected: onSelected,
      itemBuilder: (_) => [
        const PopupMenuItem<String?>(
          value: null,
          child: Text('全部事件'),
        ),
        const PopupMenuDivider(),
        for (final entry in _typeSpecs.entries)
          PopupMenuItem<String?>(
            value: entry.key,
            child: Row(
              children: [
                Icon(entry.value.icon, color: entry.value.color, size: 16),
                const SizedBox(width: 8),
                Text(entry.value.label),
              ],
            ),
          ),
      ],
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(label, style: const TextStyle(fontSize: 13)),
            const SizedBox(width: 4),
            const Icon(Icons.arrow_drop_down, size: 18),
          ],
        ),
      ),
    );
  }
}
