/// SSE (Server-Sent Events) client for real-time RWS operator alerts.
///
/// Connects to GET /api/events and emits [RwsEvent] objects to a broadcast
/// [Stream].  Automatically reconnects on connection loss with exponential
/// back-off (cap 30 s).
///
/// Usage:
/// ```dart
/// final es = EventStreamService(baseUrl: 'http://localhost:5000');
/// es.events.listen((event) => print('${event.type}: ${event.data}'));
/// es.connect();
/// // ...
/// es.dispose();
/// ```
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

// ---------------------------------------------------------------------------
// Data model
// ---------------------------------------------------------------------------

/// One parsed SSE event frame.
@immutable
class RwsEvent {
  final String type;
  final Map<String, dynamic> data;
  final DateTime receivedAt;

  const RwsEvent({
    required this.type,
    required this.data,
    required this.receivedAt,
  });

  @override
  String toString() => 'RwsEvent($type @ $receivedAt)';
}

// ---------------------------------------------------------------------------
// Service
// ---------------------------------------------------------------------------

class EventStreamService extends ChangeNotifier {
  final String baseUrl;

  EventStreamService({required this.baseUrl});

  // Public event stream (broadcast so multiple widgets can listen).
  final StreamController<RwsEvent> _controller =
      StreamController<RwsEvent>.broadcast();

  Stream<RwsEvent> get events => _controller.stream;

  // Last received event of each type, keyed by event type string.
  final Map<String, RwsEvent> _lastByType = {};
  RwsEvent? lastOf(String type) => _lastByType[type];

  // Connection state
  bool _connected = false;
  bool get connected => _connected;

  bool _disposed = false;
  http.Client? _httpClient;
  Timer? _reconnectTimer;
  int _backoffMs = 1000;

  // ---------------------------------------------------------------------------
  // Lifecycle
  // ---------------------------------------------------------------------------

  /// Start the SSE connection.  Reconnects automatically on failure.
  void connect() {
    if (_disposed) return;
    _doConnect();
  }

  /// Permanently close the stream.  Call in [State.dispose].
  @override
  void dispose() {
    _disposed = true;
    _reconnectTimer?.cancel();
    _httpClient?.close();
    _controller.close();
    super.dispose();
  }

  // ---------------------------------------------------------------------------
  // Internal
  // ---------------------------------------------------------------------------

  Future<void> _doConnect() async {
    _httpClient?.close();
    _httpClient = http.Client();

    final uri = Uri.parse('$baseUrl/api/events');

    try {
      final request = http.Request('GET', uri);
      request.headers['Accept'] = 'text/event-stream';
      request.headers['Cache-Control'] = 'no-cache';

      final response =
          await _httpClient!.send(request).timeout(const Duration(seconds: 10));

      if (response.statusCode != 200) {
        _scheduleReconnect();
        return;
      }

      _connected = true;
      _backoffMs = 1000; // reset back-off on successful connect
      notifyListeners();

      // Parse the SSE stream line-by-line.
      final lineStream = response.stream
          .transform(utf8.decoder)
          .transform(const LineSplitter());

      String currentEvent = '';
      String currentData = '';

      await for (final line in lineStream) {
        if (_disposed) break;

        if (line.startsWith('event:')) {
          currentEvent = line.substring(6).trim();
        } else if (line.startsWith('data:')) {
          currentData = line.substring(5).trim();
        } else if (line.isEmpty) {
          // Empty line = end of event frame.
          if (currentEvent.isNotEmpty) {
            _dispatchEvent(currentEvent, currentData);
          }
          currentEvent = '';
          currentData = '';
        }
        // Ignore 'id:' and comment lines (':').
      }
    } catch (_) {
      // connection lost / parse error — fall through to reconnect
    }

    if (!_disposed) {
      _connected = false;
      notifyListeners();
      _scheduleReconnect();
    }
  }

  void _dispatchEvent(String eventType, String rawData) {
    Map<String, dynamic> data = {};
    try {
      data = json.decode(rawData) as Map<String, dynamic>;
    } catch (_) {
      data = {'raw': rawData};
    }

    final event = RwsEvent(
      type: eventType,
      data: data,
      receivedAt: DateTime.now(),
    );

    _lastByType[eventType] = event;

    if (!_controller.isClosed) {
      _controller.add(event);
    }
    notifyListeners();
  }

  void _scheduleReconnect() {
    if (_disposed) return;
    _reconnectTimer?.cancel();
    final delay = Duration(milliseconds: _backoffMs);
    _backoffMs = (_backoffMs * 2).clamp(1000, 30000);
    _reconnectTimer = Timer(delay, _doConnect);
  }
}
