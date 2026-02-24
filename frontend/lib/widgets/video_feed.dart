// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;
import 'dart:ui_web' as ui_web;
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/tracking_provider.dart';

class VideoFeedWidget extends StatefulWidget {
  const VideoFeedWidget({super.key});

  @override
  State<VideoFeedWidget> createState() => _VideoFeedWidgetState();
}

class _VideoFeedWidgetState extends State<VideoFeedWidget> {
  late final String _viewId;
  html.ImageElement? _img;
  bool _registered = false;
  bool _wasConnected = false;
  String _lastUrl = '';

  @override
  void initState() {
    super.initState();
    _viewId = 'mjpeg_${identityHashCode(this)}';
  }

  /// Register the platform view factory on first call; update src on URL/reconnect.
  void _syncStream(String url, {bool forceReload = false}) {
    if (!_registered) {
      _registered = true;
      _lastUrl = url;
      ui_web.platformViewRegistry.registerViewFactory(_viewId, (int id) {
        final img = html.ImageElement()
          ..style.width = '100%'
          ..style.height = '100%'
          ..style.objectFit = 'contain'
          ..style.display = 'block'
          ..src = _lastUrl;
        _img = img;
        return img;
      });
    } else if (url != _lastUrl || forceReload) {
      _lastUrl = url;
      // Clear + reassign forces the browser to re-open the MJPEG connection.
      _img?.src = '';
      _img?.src = url;
    }
  }

  void _reloadStream() {
    if (_lastUrl.isNotEmpty) {
      _img?.src = '';
      _img?.src = _lastUrl;
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Consumer<TrackingProvider>(
      builder: (_, p, __) {
        final connected = p.connected;
        final videoUrl = p.api.videoFeedUrl;

        if (connected) {
          // forceReload=true on reconnect so the browser re-opens the stream.
          final reconnected = !_wasConnected;
          _wasConnected = true;
          _syncStream(videoUrl, forceReload: reconnected);
        } else {
          _wasConnected = false;
        }

        return Card(
          clipBehavior: Clip.antiAlias,
          child: Stack(
            fit: StackFit.expand,
            children: [
              if (connected && _registered)
                HtmlElementView(viewType: _viewId)
              else
                _placeholder(theme, connected ? '初始化中...' : '未连接'),
              // LIVE / offline badge
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
                      Text(
                        'LIVE',
                        style: TextStyle(
                          fontSize: 11,
                          fontWeight: FontWeight.bold,
                          color: connected ? Colors.greenAccent : Colors.redAccent,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              // Tracking state badge
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
              // Reconnect / reload button
              Positioned(
                bottom: 8,
                right: 8,
                child: GestureDetector(
                  onTap: _reloadStream,
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
