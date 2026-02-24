// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/api_client.dart';
import '../services/tracking_provider.dart';

class ReplayScreen extends StatefulWidget {
  const ReplayScreen({super.key});

  @override
  State<ReplayScreen> createState() => _ReplayScreenState();
}

class _ReplayScreenState extends State<ReplayScreen> {
  List<Map<String, dynamic>> _sessions = [];
  Map<String, dynamic>? _selectedSession;
  List<Map<String, dynamic>> _selectedEvents = [];
  Set<String> _activeFilters = {};
  bool _loading = false;

  List<Map<String, dynamic>> _clips = [];
  bool _clipsLoading = false;
  bool _clipsExpanded = false;

  @override
  void initState() {
    super.initState();
    _loadSessions();
  }

  RwsApiClient get _api =>
      context.read<TrackingProvider>().api;

  Future<void> _loadSessions() async {
    setState(() => _loading = true);
    final sessions = await _api.getReplaySessions();
    setState(() {
      _sessions = sessions;
      _loading = false;
    });
  }

  Future<void> _loadSession(String filename) async {
    setState(() => _loading = true);
    final session = await _api.getReplaySession(filename);
    if (session != null) {
      final rawEvents = (session['events'] as List<dynamic>? ?? [])
          .cast<Map<String, dynamic>>();
      setState(() {
        _selectedSession = session;
        _activeFilters = {};
        _selectedEvents = rawEvents;
        _loading = false;
      });
    } else {
      setState(() => _loading = false);
    }
  }

  List<Map<String, dynamic>> get _allEvents {
    final raw = (_selectedSession?['events'] as List<dynamic>? ?? [])
        .cast<Map<String, dynamic>>();
    return raw;
  }

  Set<String> get _allEventTypes {
    return _allEvents
        .map((e) => e['event_type'] as String? ?? '')
        .where((t) => t.isNotEmpty)
        .toSet();
  }

  void _toggleFilter(String type) {
    setState(() {
      if (_activeFilters.contains(type)) {
        _activeFilters.remove(type);
      } else {
        _activeFilters.add(type);
      }
      _applyFilter();
    });
  }

  void _applyFilter() {
    final all = _allEvents;
    if (_activeFilters.isEmpty) {
      _selectedEvents = all;
    } else {
      _selectedEvents = all
          .where((e) =>
              _activeFilters.contains(e['event_type'] as String? ?? ''))
          .toList();
    }
  }

  void _clearSelection() {
    setState(() {
      _selectedSession = null;
      _selectedEvents = [];
      _activeFilters = {};
    });
  }

  Future<void> _loadClips() async {
    setState(() => _clipsLoading = true);
    final clips = await _api.getClips();
    setState(() {
      _clips = clips;
      _clipsLoading = false;
      _clipsExpanded = true;
    });
  }

  @override
  Widget build(BuildContext context) {
    if (_selectedSession != null) {
      return _buildSessionDetailView();
    }
    return _buildSessionListView();
  }

  // ---------------------------------------------------------------------------
  // Session list view
  // ---------------------------------------------------------------------------

  Widget _buildSessionListView() {
    return Scaffold(
      appBar: AppBar(
        title: const Text('任务回放'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: '刷新列表',
            onPressed: _loadSessions,
          ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '历史任务',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const Divider(),
            Flexible(flex: 3, child: _buildSessionListBody()),
            _buildClipsSection(),
          ],
        ),
      ),
    );
  }

  Widget _buildClipsSection() {
    final baseUrl = _api.baseUrl;
    return Card(
      margin: const EdgeInsets.only(top: 12),
      child: ExpansionTile(
        initiallyExpanded: _clipsExpanded,
        leading: const Icon(Icons.videocam, color: Colors.red),
        title: Row(
          children: [
            const Text('火控视频片段'),
            const SizedBox(width: 8),
            if (_clips.isNotEmpty)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color: Colors.red.withValues(alpha: 0.2),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Text(
                  '${_clips.length}',
                  style: const TextStyle(
                    fontSize: 11,
                    color: Colors.red,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
          ],
        ),
        onExpansionChanged: (open) {
          if (open && _clips.isEmpty) _loadClips();
          setState(() => _clipsExpanded = open);
        },
        children: [
          if (_clipsLoading)
            const Padding(
              padding: EdgeInsets.all(16),
              child: Center(child: CircularProgressIndicator()),
            )
          else if (_clips.isEmpty)
            const Padding(
              padding: EdgeInsets.all(16),
              child: Text(
                '暂无视频片段',
                style: TextStyle(color: Colors.grey),
              ),
            )
          else
            ListView.builder(
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              itemCount: _clips.length,
              itemBuilder: (context, index) {
                return _ClipTile(clip: _clips[index], baseUrl: baseUrl);
              },
            ),
        ],
      ),
    );
  }

  Widget _buildSessionListBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_sessions.isEmpty) {
      return const Center(
        child: Text(
          '暂无历史任务',
          style: TextStyle(color: Colors.grey),
        ),
      );
    }
    return ListView.builder(
      itemCount: _sessions.length,
      itemBuilder: (context, index) {
        final s = _sessions[index];
        final filename = s['filename'] as String? ?? s['session_id'] as String? ?? 'unknown';
        final eventCount = (s['event_count'] as num?)?.toInt() ?? 0;
        final durationS = (s['duration_s'] as num?)?.toDouble() ?? 0.0;
        final fireCount = (s['fire_count'] as num?)?.toInt() ?? 0;

        return Card(
          child: ListTile(
            leading: const Icon(Icons.history),
            title: Text(filename),
            subtitle: Text(
              '$eventCount events · ${durationS.toStringAsFixed(1)}s',
            ),
            trailing: Text(
              'fired: $fireCount',
              style: TextStyle(
                color: fireCount > 0 ? Colors.red : null,
                fontWeight:
                    fireCount > 0 ? FontWeight.bold : FontWeight.normal,
              ),
            ),
            onTap: () => _loadSession(filename),
          ),
        );
      },
    );
  }

  // ---------------------------------------------------------------------------
  // Session detail view
  // ---------------------------------------------------------------------------

  Widget _buildSessionDetailView() {
    final allTypes = _allEventTypes.toList()..sort();
    final events = _selectedEvents;

    return Scaffold(
      appBar: AppBar(
        title: const Text('任务回放'),
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          tooltip: '返回列表',
          onPressed: _clearSelection,
        ),
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : Column(
              children: [
                // Filter chips
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  padding:
                      const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  child: Row(
                    children: allTypes.map((type) {
                      final isSelected = _activeFilters.contains(type);
                      return Padding(
                        padding: const EdgeInsets.only(right: 8),
                        child: FilterChip(
                          label: Text(type),
                          selected: isSelected,
                          selectedColor:
                              _eventTypeColor(type).withValues(alpha: 0.3),
                          onSelected: (_) => _toggleFilter(type),
                        ),
                      );
                    }).toList(),
                  ),
                ),
                const Divider(height: 1),
                // Event list
                Expanded(
                  child: events.isEmpty
                      ? const Center(
                          child: Text(
                            '暂无符合筛选条件的事件',
                            style: TextStyle(color: Colors.grey),
                          ),
                        )
                      : ListView.builder(
                          itemCount: events.length,
                          itemBuilder: (context, index) {
                            return _EventTile(event: events[index]);
                          },
                        ),
                ),
              ],
            ),
    );
  }

  Color _eventTypeColor(String type) {
    switch (type) {
      case 'fired':
        return Colors.red;
      case 'fire_chain_state':
        return Colors.orange;
      case 'mission_start':
      case 'mission_end':
        return Colors.green;
      case 'operator_timeout':
        return Colors.purple;
      default:
        return Colors.blue.shade300;
    }
  }
}

// ---------------------------------------------------------------------------
// Event tile
// ---------------------------------------------------------------------------

class _EventTile extends StatelessWidget {
  final Map<String, dynamic> event;

  const _EventTile({required this.event});

  Color _eventTypeColor(String type) {
    switch (type) {
      case 'fired':
        return Colors.red;
      case 'fire_chain_state':
        return Colors.orange;
      case 'mission_start':
      case 'mission_end':
        return Colors.green;
      case 'operator_timeout':
        return Colors.purple;
      default:
        return Colors.blue.shade300;
    }
  }

  @override
  Widget build(BuildContext context) {
    final eventType = event['event_type'] as String? ?? 'unknown';
    final timestamp = event['timestamp'] as String? ??
        event['ts'] as String? ??
        '';
    final data = event['data'] ?? event['payload'] ?? {};
    final dataSummary = data.toString();
    final displaySummary = dataSummary.length > 80
        ? '${dataSummary.substring(0, 80)}...'
        : dataSummary;

    final color = _eventTypeColor(eventType);

    return Container(
      decoration: BoxDecoration(
        border: Border(
          left: BorderSide(color: color, width: 4),
        ),
      ),
      margin: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Timestamp
            SizedBox(
              width: 160,
              child: Text(
                timestamp,
                style: const TextStyle(
                  fontSize: 11,
                  fontFamily: 'monospace',
                  color: Colors.grey,
                ),
              ),
            ),
            const SizedBox(width: 8),
            // Event type badge
            Container(
              padding:
                  const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
              decoration: BoxDecoration(
                color: color.withValues(alpha: 0.2),
                borderRadius: BorderRadius.circular(4),
                border: Border.all(color: color.withValues(alpha: 0.6)),
              ),
              child: Text(
                eventType,
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                  color: color,
                ),
              ),
            ),
            const SizedBox(width: 8),
            // Data summary
            Expanded(
              child: Text(
                displaySummary,
                style: const TextStyle(fontSize: 11, color: Colors.grey),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Clip tile
// ---------------------------------------------------------------------------

class _ClipTile extends StatelessWidget {
  final Map<String, dynamic> clip;
  final String baseUrl;

  const _ClipTile({required this.clip, required this.baseUrl});

  @override
  Widget build(BuildContext context) {
    final filename = clip['filename'] as String? ?? '';
    final sizeBytes = (clip['size_bytes'] as num?)?.toInt() ?? 0;
    final timestamp = (clip['timestamp'] as num?)?.toDouble() ?? 0.0;
    final sizeKb = (sizeBytes / 1024).round();

    final dt = timestamp > 0
        ? DateTime.fromMillisecondsSinceEpoch((timestamp * 1000).toInt())
        : null;
    final timeStr = dt != null
        ? '${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')} '
            '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}:${dt.second.toString().padLeft(2, '0')}'
        : filename;

    return ListTile(
      dense: true,
      leading: const Icon(Icons.movie_outlined, color: Colors.red),
      title: Text(timeStr, style: const TextStyle(fontSize: 13)),
      subtitle: Text(
        '$sizeKb KB · $filename',
        style: const TextStyle(fontSize: 11, color: Colors.grey),
      ),
      trailing: IconButton(
        icon: const Icon(Icons.download, size: 20),
        tooltip: '下载片段',
        onPressed: () {
          final url = '$baseUrl/api/fire/clips/${Uri.encodeComponent(filename)}';
          html.window.open(url, '_blank');
        },
      ),
    );
  }
}
