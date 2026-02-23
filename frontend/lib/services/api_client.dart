/// RWS REST API 客户端
library;

import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/tracking_models.dart';

class RwsApiClient {
  final String baseUrl;
  final http.Client _client;

  RwsApiClient({required this.baseUrl}) : _client = http.Client();

  void dispose() => _client.close();

  // --- 状态 ---

  Future<TrackingStatus> getStatus() async {
    final resp = await _client.get(Uri.parse('$baseUrl/api/status'));
    if (resp.statusCode == 200) {
      return TrackingStatus.fromJson(jsonDecode(resp.body));
    }
    throw Exception('Failed to get status: ${resp.statusCode}');
  }

  Future<Map<String, dynamic>> getMetrics() async {
    final resp = await _client.get(Uri.parse('$baseUrl/api/metrics'));
    if (resp.statusCode == 200) {
      return jsonDecode(resp.body);
    }
    throw Exception('Failed to get metrics: ${resp.statusCode}');
  }

  // --- 控制 ---

  Future<bool> startTracking({int? cameraSource}) async {
    final body = cameraSource != null ? {'source': cameraSource} : {};
    final resp = await _client.post(
      Uri.parse('$baseUrl/api/tracking/start'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode(body),
    );
    if (resp.statusCode == 200) {
      final data = jsonDecode(resp.body);
      return data['success'] ?? false;
    }
    return false;
  }

  Future<bool> stopTracking() async {
    final resp = await _client.post(Uri.parse('$baseUrl/api/tracking/stop'));
    if (resp.statusCode == 200) {
      final data = jsonDecode(resp.body);
      return data['success'] ?? false;
    }
    return false;
  }

  // --- PID 调参 ---

  Future<bool> updatePid(String axis, PidParams params) async {
    final resp = await _client.post(
      Uri.parse('$baseUrl/api/config'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'pid': {axis: params.toJson()},
      }),
    );
    if (resp.statusCode == 200) {
      final data = jsonDecode(resp.body);
      return data['success'] ?? false;
    }
    return false;
  }

  // --- 安全区域 ---

  Future<bool> addSafetyZone(SafetyZoneModel zone) async {
    final resp = await _client.post(
      Uri.parse('$baseUrl/api/config'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'safety_zones': {'action': 'add', 'zone': zone.toJson()},
      }),
    );
    if (resp.statusCode == 200) {
      final data = jsonDecode(resp.body);
      return data['success'] ?? false;
    }
    return false;
  }

  Future<bool> removeSafetyZone(String zoneId) async {
    final resp = await _client.post(
      Uri.parse('$baseUrl/api/config'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({
        'safety_zones': {'action': 'remove', 'zone_id': zoneId},
      }),
    );
    if (resp.statusCode == 200) {
      final data = jsonDecode(resp.body);
      return data['success'] ?? false;
    }
    return false;
  }

  // --- 威胁队列 ---

  Future<List<ThreatEntry>> getThreats() async {
    try {
      final resp = await _client.get(Uri.parse('$baseUrl/api/threats'));
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        final list = data['threats'] as List<dynamic>? ?? [];
        return list
            .map((j) => ThreatEntry.fromJson(j as Map<String, dynamic>))
            .toList();
      }
    } catch (_) {}
    return [];
  }

  // --- 子系统健康 ---

  Future<Map<String, SubsystemHealth>> getSubsystemHealth() async {
    try {
      final resp =
          await _client.get(Uri.parse('$baseUrl/api/health/subsystems'));
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        final subs = data['subsystems'] as Map<String, dynamic>? ?? {};
        return subs.map((name, val) => MapEntry(
            name,
            SubsystemHealth.fromJson(name, val as Map<String, dynamic>)));
      }
    } catch (_) {}
    return {};
  }

  // --- 火控状态 ---

  Future<FireChainStatus> getFireStatus() async {
    try {
      final resp = await _client.get(Uri.parse('$baseUrl/api/fire/status'));
      if (resp.statusCode == 200) {
        return FireChainStatus.fromJson(jsonDecode(resp.body));
      }
    } catch (_) {}
    return FireChainStatus(state: 'not_configured', canFire: false);
  }

  Future<bool> armSystem(String operatorId) async {
    try {
      final resp = await _client.post(
        Uri.parse('$baseUrl/api/fire/arm'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'operator_id': operatorId}),
      );
      return resp.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<bool> safeSystem(String reason) async {
    try {
      final resp = await _client.post(
        Uri.parse('$baseUrl/api/fire/safe'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'reason': reason}),
      );
      return resp.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<bool> requestFire(String operatorId) async {
    try {
      final resp = await _client.post(
        Uri.parse('$baseUrl/api/fire/request'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'operator_id': operatorId}),
      );
      return resp.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// Send operator liveness heartbeat to prevent auto-safe on timeout.
  /// Call every ≤5 s while armed.
  Future<bool> sendHeartbeat({String operatorId = 'operator_1'}) async {
    try {
      final resp = await _client.post(
        Uri.parse('$baseUrl/api/fire/heartbeat'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'operator_id': operatorId}),
      );
      return resp.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// GET /api/selftest — run pre-mission go/no-go checks (7 subsystems).
  Future<Map<String, dynamic>> runSelfTest() async {
    try {
      final resp = await _client.get(Uri.parse('$baseUrl/api/selftest'));
      if (resp.statusCode == 200) {
        return jsonDecode(resp.body) as Map<String, dynamic>;
      }
      return {'go': false, 'error': 'HTTP ${resp.statusCode}'};
    } catch (e) {
      return {'go': false, 'error': e.toString()};
    }
  }

  // --- 任务控制 ---

  Future<MissionStatus> getMissionStatus() async {
    try {
      final resp = await _client.get(Uri.parse('$baseUrl/api/mission/status'));
      if (resp.statusCode == 200) {
        return MissionStatus.fromJson(jsonDecode(resp.body));
      }
    } catch (_) {}
    return MissionStatus();
  }

  Future<Map<String, dynamic>> startMission({
    String? profile,
    int cameraSource = 0,
    String? missionName,
  }) async {
    final body = <String, dynamic>{
      'camera_source': cameraSource,
    };
    if (profile != null) body['profile'] = profile;
    if (missionName != null) body['mission_name'] = missionName;

    try {
      final resp = await _client.post(
        Uri.parse('$baseUrl/api/mission/start'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(body),
      );
      if (resp.statusCode == 200) {
        return jsonDecode(resp.body);
      }
      return {'success': false, 'error': 'HTTP ${resp.statusCode}'};
    } catch (e) {
      return {'success': false, 'error': e.toString()};
    }
  }

  Future<Map<String, dynamic>> endMission() async {
    try {
      final resp = await _client.post(
        Uri.parse('$baseUrl/api/mission/end'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({}),
      );
      if (resp.statusCode == 200) {
        return jsonDecode(resp.body);
      }
      return {'success': false, 'error': 'HTTP ${resp.statusCode}'};
    } catch (e) {
      return {'success': false, 'error': e.toString()};
    }
  }

  // --- 禁射区管理 (NFZ CRUD) ---

  Future<List<SafetyZoneModel>> listNfzZones() async {
    try {
      final resp = await _client.get(Uri.parse('$baseUrl/api/safety/zones'));
      if (resp.statusCode == 200) {
        final list = jsonDecode(resp.body) as List<dynamic>;
        return list
            .map((j) => SafetyZoneModel.fromJson(j as Map<String, dynamic>))
            .toList();
      }
    } catch (_) {}
    return [];
  }

  Future<Map<String, dynamic>> addNfzZone(SafetyZoneModel zone) async {
    try {
      final body = <String, dynamic>{
        'center_yaw_deg': zone.centerYawDeg,
        'center_pitch_deg': zone.centerPitchDeg,
        'radius_deg': zone.radiusDeg,
      };
      if (zone.zoneId.isNotEmpty) body['zone_id'] = zone.zoneId;
      final resp = await _client.post(
        Uri.parse('$baseUrl/api/safety/zones'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(body),
      );
      if (resp.statusCode == 201) {
        return jsonDecode(resp.body) as Map<String, dynamic>;
      }
      return {'ok': false, 'error': 'HTTP ${resp.statusCode}'};
    } catch (e) {
      return {'ok': false, 'error': e.toString()};
    }
  }

  Future<bool> deleteNfzZone(String zoneId) async {
    try {
      final resp = await _client.delete(
        Uri.parse('$baseUrl/api/safety/zones/$zoneId'),
      );
      return resp.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  // --- IFF (识别敌我) 友军白名单 ---

  Future<List<int>> getIffFriendlyIds() async {
    try {
      final resp =
          await _client.get(Uri.parse('$baseUrl/api/fire/iff/status'));
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        final list =
            data['friendly_track_ids'] as List<dynamic>? ?? [];
        return list.map((e) => e as int).toList();
      }
    } catch (_) {}
    return [];
  }

  Future<bool> markFriendly(int trackId) async {
    try {
      final resp = await _client.post(
        Uri.parse('$baseUrl/api/fire/iff/mark_friendly'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'track_id': trackId}),
      );
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        return data['ok'] == true;
      }
    } catch (_) {}
    return false;
  }

  Future<bool> unmarkFriendly(int trackId) async {
    try {
      final resp = await _client.post(
        Uri.parse('$baseUrl/api/fire/iff/unmark_friendly'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'track_id': trackId}),
      );
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        return data['ok'] == true;
      }
    } catch (_) {}
    return false;
  }

  // --- 目标指定 (C2 designation) ---

  Future<bool> designateTarget(int trackId, {String operatorId = 'operator_1'}) async {
    try {
      final resp = await _client.post(
        Uri.parse('$baseUrl/api/fire/designate'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'track_id': trackId, 'operator_id': operatorId}),
      );
      return resp.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<bool> clearDesignation() async {
    try {
      final resp = await _client.delete(Uri.parse('$baseUrl/api/fire/designate'));
      return resp.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  Future<int?> getDesignatedTrackId() async {
    try {
      final resp = await _client.get(Uri.parse('$baseUrl/api/fire/designate'));
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        return data['designated'] == true ? data['track_id'] as int? : null;
      }
    } catch (_) {}
    return null;
  }

  // --- 视频流 URL ---

  String get videoFeedUrl => '$baseUrl/api/video/feed';
  String get snapshotUrl => '$baseUrl/api/video/snapshot';

  // --- Replay API ---

  Future<List<Map<String, dynamic>>> getReplaySessions() async {
    try {
      final resp = await _client.get(Uri.parse('$baseUrl/api/replay/sessions'));
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        final list = data is List ? data : (data['sessions'] as List<dynamic>? ?? []);
        return list.cast<Map<String, dynamic>>();
      }
    } catch (_) {}
    return [];
  }

  Future<Map<String, dynamic>?> getReplaySession(
    String filename, {
    List<String> eventTypes = const [],
    int limit = 5000,
  }) async {
    try {
      final queryParams = <String, String>{'limit': limit.toString()};
      for (final t in eventTypes) {
        queryParams['event_type'] = t;
      }
      final uri = Uri.parse('$baseUrl/api/replay/sessions/$filename')
          .replace(queryParameters: queryParams);
      final resp = await _client.get(uri);
      if (resp.statusCode == 200) {
        return jsonDecode(resp.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    return null;
  }

  Future<Map<String, dynamic>?> getReplaySessionSummary(String filename) async {
    try {
      final resp = await _client.get(
        Uri.parse('$baseUrl/api/replay/sessions/$filename/summary'),
      );
      if (resp.statusCode == 200) {
        return jsonDecode(resp.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    return null;
  }

  /// Fetches the current effective configuration from GET /api/config.
  /// Returns null on any error.
  Future<Map<String, dynamic>?> getConfig() async {
    try {
      final resp = await _client.get(Uri.parse('$baseUrl/api/config'));
      if (resp.statusCode == 200) {
        return jsonDecode(resp.body) as Map<String, dynamic>;
      }
    } catch (_) {}
    return null;
  }

  /// Returns the list of available mission profile names from the server.
  /// Falls back to an empty list on any error.
  Future<List<String>> fetchProfiles() async {
    try {
      final resp = await _client.get(Uri.parse('$baseUrl/api/config/profiles'));
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        // Response may be {"profiles": [...]} or a bare list.
        final List<dynamic> raw = data is Map ? (data['profiles'] ?? []) : data;
        return raw.map((e) => e.toString()).toList();
      }
    } catch (_) {}
    return [];
  }
}
