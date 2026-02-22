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

  // --- 视频流 URL ---

  String get videoFeedUrl => '$baseUrl/api/video/feed';
  String get snapshotUrl => '$baseUrl/api/video/snapshot';
}
