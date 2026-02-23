/// RWS 状态管理 Provider
library;

import 'dart:async';
import 'package:flutter/foundation.dart';
import '../models/tracking_models.dart';
import 'api_client.dart';

class TrackingProvider extends ChangeNotifier {
  final RwsApiClient _api;
  Timer? _pollTimer;

  TrackingStatus _status = TrackingStatus();
  bool _connected = false;
  String _error = '';

  // 新增: 威胁、健康、火控状态
  List<ThreatEntry> _threats = [];
  Map<String, SubsystemHealth> _health = {};
  FireChainStatus _fireStatus =
      FireChainStatus(state: 'not_configured', canFire: false);

  // 任务状态
  MissionStatus _missionStatus = MissionStatus();
  String? _lastReportPath;

  // 目标指定状态 (C2)
  int? _designatedTrackId;

  // 禁射区列表
  List<SafetyZoneModel> _nfzZones = [];

  // 操作员心跳定时器 (armed 时每 5s 发送一次, 防止 watchdog 自动安全)
  Timer? _heartbeatTimer;

  // 误差历史 (用于图表)
  final List<double> yawErrorHistory = [];
  final List<double> pitchErrorHistory = [];
  final List<double> timestampHistory = [];
  static const int maxHistory = 300; // 10s @ 30Hz

  TrackingProvider({required RwsApiClient api}) : _api = api;

  TrackingStatus get status => _status;
  bool get connected => _connected;
  String get error => _error;
  String get snapshotUrl => _api.snapshotUrl;
  RwsApiClient get api => _api;
  List<ThreatEntry> get threats => _threats;
  Map<String, SubsystemHealth> get health => _health;
  FireChainStatus get fireStatus => _fireStatus;
  MissionStatus get missionStatus => _missionStatus;
  String? get lastReportPath => _lastReportPath;
  int? get designatedTrackId => _designatedTrackId;
  List<SafetyZoneModel> get nfzZones => _nfzZones;

  void startPolling({Duration interval = const Duration(milliseconds: 200)}) {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(interval, (_) => _poll());
  }

  void stopPolling() {
    _pollTimer?.cancel();
    _pollTimer = null;
    _stopHeartbeat();
  }

  // --- 操作员心跳管理 ---

  /// 当系统处于 armed 状态时, 每 5s 自动发送心跳, 防止 OperatorWatchdog 超时.
  void _updateHeartbeatTimer() {
    if (_fireStatus.isArmed) {
      _heartbeatTimer ??= Timer.periodic(
        const Duration(seconds: 5),
        (_) => _api.sendHeartbeat(),
      );
    } else {
      _stopHeartbeat();
    }
  }

  void _stopHeartbeat() {
    _heartbeatTimer?.cancel();
    _heartbeatTimer = null;
  }

  Future<void> _poll() async {
    try {
      _status = await _api.getStatus();
      _connected = true;
      _error = '';

      // 记录历史
      final now = DateTime.now().millisecondsSinceEpoch / 1000.0;
      yawErrorHistory.add(_status.yawErrorDeg);
      pitchErrorHistory.add(_status.pitchErrorDeg);
      timestampHistory.add(now);
      if (yawErrorHistory.length > maxHistory) {
        yawErrorHistory.removeAt(0);
        pitchErrorHistory.removeAt(0);
        timestampHistory.removeAt(0);
      }

      notifyListeners();

      // 并行拉取威胁、健康、火控 (不阻塞主状态)
      _pollExtended();
    } catch (e) {
      _connected = false;
      _error = e.toString();
      notifyListeners();
    }
  }

  Future<void> _pollExtended() async {
    try {
      final results = await Future.wait([
        _api.getThreats(),
        _api.getSubsystemHealth(),
        _api.getFireStatus(),
      ]);
      _threats = results[0] as List<ThreatEntry>;
      _health = results[1] as Map<String, SubsystemHealth>;
      final newFireStatus = results[2] as FireChainStatus;
      _fireStatus = newFireStatus;
      _updateHeartbeatTimer();
      notifyListeners();
    } catch (_) {
      // 扩展轮询失败不影响主连接状态
    }

    // 任务状态: 每次扩展轮询时同步拉取 (约每 200ms 一次, 满足 <=2s 要求)
    try {
      final ms = await _api.getMissionStatus();
      _missionStatus = ms;
      notifyListeners();
    } catch (_) {
      // 任务状态拉取失败不影响其他状态
    }
  }

  // --- 火控操作 ---

  Future<void> armSystem() async {
    try {
      await _api.armSystem('operator_1');
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  Future<void> safeSystem() async {
    try {
      await _api.safeSystem('operator request');
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  Future<void> requestFire() async {
    try {
      await _api.requestFire('operator_1');
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  Future<bool> startTracking() async {
    try {
      return await _api.startTracking();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      return false;
    }
  }

  Future<bool> stopTracking() async {
    try {
      return await _api.stopTracking();
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      return false;
    }
  }

  Future<bool> updatePid(String axis, PidParams params) async {
    try {
      return await _api.updatePid(axis, params);
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      return false;
    }
  }

  // --- 任务操作 ---

  Future<bool> startMission(String profile, {int cameraSource = 0}) async {
    try {
      final result = await _api.startMission(
        profile: profile,
        cameraSource: cameraSource,
      );
      final ok = result['success'] == true;
      if (ok) {
        // 立即拉取最新任务状态
        _missionStatus = await _api.getMissionStatus();
        notifyListeners();
      }
      return ok;
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      return false;
    }
  }

  Future<String?> endMission() async {
    try {
      final result = await _api.endMission();
      // 服务端可能返回 report_path 或 report_url 字段
      final reportPath =
          result['report_path'] as String? ?? result['report_url'] as String?;
      _lastReportPath = reportPath;
      // 刷新任务状态 (应已变为非活跃)
      _missionStatus = await _api.getMissionStatus();
      notifyListeners();
      return reportPath;
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      return null;
    }
  }

  // --- 禁射区管理 ---

  Future<void> loadNfzZones() async {
    try {
      _nfzZones = await _api.listNfzZones();
      notifyListeners();
    } catch (_) {}
  }

  Future<bool> addNfzZone(SafetyZoneModel zone) async {
    try {
      final result = await _api.addNfzZone(zone);
      if (result['ok'] == true) {
        await loadNfzZones();
        return true;
      }
      return false;
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      return false;
    }
  }

  Future<bool> deleteNfzZone(String zoneId) async {
    try {
      final ok = await _api.deleteNfzZone(zoneId);
      if (ok) {
        _nfzZones = _nfzZones.where((z) => z.zoneId != zoneId).toList();
        notifyListeners();
      }
      return ok;
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      return false;
    }
  }

  // --- 目标指定 ---

  Future<bool> designateTarget(int trackId) async {
    try {
      final ok = await _api.designateTarget(trackId);
      if (ok) {
        _designatedTrackId = trackId;
        notifyListeners();
      }
      return ok;
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      return false;
    }
  }

  Future<bool> clearDesignation() async {
    try {
      final ok = await _api.clearDesignation();
      if (ok) {
        _designatedTrackId = null;
        notifyListeners();
      }
      return ok;
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      return false;
    }
  }

  @override
  void dispose() {
    stopPolling();
    _stopHeartbeat();
    super.dispose();
  }
}
