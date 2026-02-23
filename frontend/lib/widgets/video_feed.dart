import 'dart:async';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/tracking_provider.dart';

class VideoFeedWidget extends StatefulWidget {
  const VideoFeedWidget({super.key});

  @override
  State<VideoFeedWidget> createState() => _VideoFeedWidgetState();
}

class _VideoFeedWidgetState extends State<VideoFeedWidget> {
  int _refreshKey = 0;
  Timer? _refreshTimer;

  @override
  void initState() {
    super.initState();
    _refreshTimer = Timer.periodic(const Duration(milliseconds: 200), (_) {
      if (mounted) setState(() => _refreshKey++);
    });
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Consumer<TrackingProvider>(
      builder: (_, p, __) {
        final connected = p.connected;
        final videoUrl = '${p.snapshotUrl}?t=$_refreshKey';

        return Card(
          clipBehavior: Clip.antiAlias,
          child: Stack(
            fit: StackFit.expand,
            children: [
              if (connected)
                Image.network(
                  videoUrl,
                  fit: BoxFit.contain,
                  errorBuilder: (_, __, ___) => _placeholder(theme, '视频流不可用'),
                  loadingBuilder: (_, child, progress) {
                    if (progress == null) return child;
                    return _placeholder(theme, '加载中...');
                  },
                )
              else
                _placeholder(theme, '未连接'),
              Positioned(
                top: 8,
                left: 8,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: Colors.black54,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.videocam, size: 14, color: Colors.white70),
                      const SizedBox(width: 4),
                      Text('LIVE',
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.bold,
                            color: connected ? Colors.greenAccent : Colors.redAccent,
                          )),
                    ],
                  ),
                ),
              ),
              Positioned(
                top: 8,
                right: 8,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                  decoration: BoxDecoration(
                    color: Colors.black54,
                    borderRadius: BorderRadius.circular(4),
                  ),
                  child: Text(
                    p.status.state,
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.bold,
                      color: _stateColor(p.status.state),
                    ),
                  ),
                ),
              ),
              // Manual refresh button — forces a cache-bust
              Positioned(
                bottom: 8,
                right: 8,
                child: GestureDetector(
                  onTap: () => setState(() => _refreshKey += 1000),
                  child: Container(
                    padding: const EdgeInsets.all(6),
                    decoration: BoxDecoration(
                      color: Colors.black54,
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: const Icon(Icons.refresh, size: 16, color: Colors.white70),
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _placeholder(ThemeData theme, String message) {
    return Container(
      color: Colors.black87,
      child: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.videocam_off, size: 48, color: theme.hintColor),
            const SizedBox(height: 8),
            Text(message, style: TextStyle(color: theme.hintColor)),
          ],
        ),
      ),
    );
  }

  Color _stateColor(String state) {
    return switch (state) {
      'TRACK' => Colors.greenAccent,
      'LOCK' => Colors.cyanAccent,
      'ENGAGE' => Colors.orangeAccent,
      'SEARCH' => Colors.amberAccent,
      _ => Colors.grey,
    };
  }
}
