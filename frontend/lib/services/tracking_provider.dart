/// RWS 状态管理 Provider
library;

import 'dart:async';
import 'package:flutter/foundation.dart';
import '../models/tracking_models.dart';
import 'api_client.dart';
import 'audio_service.dart';
import 'event_stream.dart';

class TrackingProvider extends ChangeNotifier {
  final RwsApiClient _api;
  Timer? _pollTimer;

  TrackingStatus _status = TrackingStatus();
  bool _connected = false;
  String _error = '';

  // 操作员身份 — 用于 arm/fire/heartbeat/designate
  String _operatorId = 'operator_1';

  // 新增: 威胁、健康、火控状态
  List<ThreatEntry> _threats = [];
  bool _pipelineActive = false;
  Map<String, SubsystemHealth> _health = {};
  FireChainStatus _fireStatus =
      FireChainStatus(state: 'not_configured', canFire: false);

  // 任务状态
  MissionStatus _missionStatus = MissionStatus();
  String? _lastReportPath;

  // 目标指定状态 (C2)
  int? _designatedTrackId;

  // 开火统计 — 每次 fire_executed SSE 事件自增
  int _shotsFiredCount = 0;

  // 上次配置热重载时间戳
  DateTime? _lastConfigReload;

  // 禁射区列表
  List<SafetyZoneModel> _nfzZones = [];

  // 交战驻留计时器状态
  EngagementDwellStatus _dwellStatus = const EngagementDwellStatus();

  // 双人规则武装挂起状态
  ArmPendingStatus _armPendingStatus = ArmPendingStatus.none;

  // 最近一次安全触发原因 (safety_triggered SSE)
  String? _lastSafetyTriggerReason;

  // 操作员心跳定时器 (armed 时每 5s 发送一次, 防止 watchdog 自动安全)
  Timer? _heartbeatTimer;

  // 连续轮询失败计数器 — 超过阈值才标记离线，避免单次网络抖动导致状态闪烁
  int _consecutiveFailures = 0;
  static const int _maxFailuresBeforeOffline = 3;

  // 指数退避: 连续失败时加倍轮询间隔，最长 10s，恢复后立即重置到基础间隔
  static const Duration _pollIntervalBase = Duration(milliseconds: 200);
  static const Duration _pollIntervalMax = Duration(seconds: 10);
  Duration _currentPollInterval = _pollIntervalBase;

  // 误差历史 (用于图表)
  final List<double> yawErrorHistory = [];
  final List<double> pitchErrorHistory = [];
  final List<double> timestampHistory = [];
  final List<String> _stateHistory = [];
  static const int maxHistory = 300; // 10s @ 30Hz

  TrackingProvider({required RwsApiClient api}) : _api = api;

  TrackingStatus get status => _status;
  bool get connected => _connected;
  String get error => _error;
  String get snapshotUrl => _api.snapshotUrl;
  RwsApiClient get api => _api;
  String get operatorId => _operatorId;
  List<ThreatEntry> get threats => _threats;
  bool get pipelineActive => _pipelineActive;
  Map<String, SubsystemHealth> get health => _health;
  FireChainStatus get fireStatus => _fireStatus;
  MissionStatus get missionStatus => _missionStatus;
  String? get lastReportPath => _lastReportPath;
  int? get designatedTrackId => _designatedTrackId;
  int get shotsFiredCount => _shotsFiredCount;
  DateTime? get lastConfigReload => _lastConfigReload;
  List<SafetyZoneModel> get nfzZones => _nfzZones;
  EngagementDwellStatus get dwellStatus => _dwellStatus;
  ArmPendingStatus get armPendingStatus => _armPendingStatus;
  String? get lastSafetyTriggerReason => _lastSafetyTriggerReason;
  List<String> get stateHistory => _stateHistory;

  void startPolling({Duration interval = const Duration(milliseconds: 200)}) {
    _pollTimer?.cancel();
    _currentPollInterval = interval;
    _schedulePoll();
  }

  /// Schedule the next poll as a single-shot timer so the interval can vary.
  void _schedulePoll() {
    _pollTimer = Timer(_currentPollInterval, () async {
      await _poll();
      // Re-schedule only if polling is still active (stopPolling sets timer=null).
      if (_pollTimer != null) _schedulePoll();
    });
  }

  void stopPolling() {
    _pollTimer?.cancel();
    _pollTimer = null;
    _currentPollInterval = _pollIntervalBase;
    _stopHeartbeat();
  }

  // --- 操作员心跳管理 ---

  /// 设置操作员 ID（武装前调用）.
  void setOperatorId(String id) {
    final trimmed = id.trim();
    if (trimmed.isNotEmpty && trimmed != _operatorId) {
      _operatorId = trimmed;
      notifyListeners();
    }
  }

  /// 当系统处于 armed 状态时, 每 5s 自动发送心跳, 防止 OperatorWatchdog 超时.
  void _updateHeartbeatTimer() {
    if (_fireStatus.isArmed) {
      _heartbeatTimer ??= Timer.periodic(
        const Duration(seconds: 5),
        (_) => _api.sendHeartbeat(operatorId: _operatorId),
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
      _consecutiveFailures = 0;
      _currentPollInterval = _pollIntervalBase; // recover to full speed on success
      _connected = true;
      _error = '';

      // 记录历史
      final now = DateTime.now().millisecondsSinceEpoch / 1000.0;
      yawErrorHistory.add(_status.yawErrorDeg);
      pitchErrorHistory.add(_status.pitchErrorDeg);
      timestampHistory.add(now);
      _stateHistory.add(_status.state);
      if (yawErrorHistory.length > maxHistory) {
        yawErrorHistory.removeAt(0);
        pitchErrorHistory.removeAt(0);
        timestampHistory.removeAt(0);
        _stateHistory.removeAt(0);
      }

      notifyListeners();

      // 并行拉取威胁、健康、火控 (不阻塞主状态)
      _pollExtended();
    } catch (e) {
      _consecutiveFailures++;
      if (_consecutiveFailures >= _maxFailuresBeforeOffline) {
        _connected = false;
        _error = e.toString();
        // Exponential backoff: double interval on each failure, cap at max.
        final nextMs = (_currentPollInterval.inMilliseconds * 2)
            .clamp(0, _pollIntervalMax.inMilliseconds);
        _currentPollInterval = Duration(milliseconds: nextMs);
        notifyListeners();
      }
    }
  }

  Future<void> _pollExtended() async {
    try {
      final results = await Future.wait([
        _api.getThreats(),
        _api.getSubsystemHealth(),
        _api.getFireStatus(),
        _api.getDesignatedTrackId(),
        _api.getDwellStatus(),
        _api.getArmPendingStatus(),
      ]);
      final threatResult = results[0] as ({List<ThreatEntry> threats, bool pipelineActive});
      _threats = threatResult.threats;
      _pipelineActive = threatResult.pipelineActive;
      _health = results[1] as Map<String, SubsystemHealth>;
      final newFireStatus = results[2] as FireChainStatus;
      _fireStatus = newFireStatus;
      _designatedTrackId = results[3] as int?;
      _dwellStatus = results[4] as EngagementDwellStatus;
      _armPendingStatus = results[5] as ArmPendingStatus;
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

  /// Returns true if armed immediately, false if a two-man pending request was started.
  Future<bool> armSystem() async {
    try {
      final result = await _api.armSystem(_operatorId);
      if (result.pending) {
        // Two-man rule: first operator initiated; fetch updated pending status
        _armPendingStatus = await _api.getArmPendingStatus();
        notifyListeners();
        return false;
      }
      return result.success;
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      return false;
    }
  }

  /// Second-operator confirmation for the two-man arming rule.
  Future<bool> armConfirm(String secondOperatorId) async {
    try {
      final ok = await _api.confirmArm(secondOperatorId);
      if (ok) {
        _armPendingStatus = ArmPendingStatus.none;
        notifyListeners();
      }
      return ok;
    } catch (e) {
      _error = e.toString();
      notifyListeners();
      return false;
    }
  }

  Future<void> safeSystem() async {
    try {
      await _api.safeSystem(_operatorId);
    } catch (e) {
      _error = e.toString();
      notifyListeners();
    }
  }

  Future<void> requestFire() async {
    try {
      await _api.requestFire(_operatorId);
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

  Future<bool> setGimbalPosition(double yawDeg, double pitchDeg) async {
    try {
      return await _api.setGimbalPosition(yawDeg, pitchDeg);
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
      final ok = await _api.designateTarget(trackId, operatorId: _operatorId);
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

  final _audio = AudioService();

  // --- SSE 事件即时响应 ---
  // Called from main.dart when the EventStreamService emits an event.
  // This provides sub-200ms updates on critical state changes without
  // waiting for the next polling cycle.
  void onSseEvent(RwsEvent event) {
    switch (event.type) {
      case 'fire_chain_state':
        // Update fire status directly from event data — fastest possible update
        final stateStr = event.data['state'] as String?;
        if (stateStr != null) {
          _fireStatus = FireChainStatus(
            state: stateStr,
            canFire: event.data['can_fire'] as bool? ?? false,
            operatorId: event.data['operator_id'] as String?,
          );
          if (stateStr == 'armed') _audio.playArmed();
          _updateHeartbeatTimer();
          notifyListeners();
        }
      case 'operator_timeout':
        // Watchdog fired — force to safe state immediately in UI
        _audio.playOperatorTimeout();
        _fireStatus = FireChainStatus(state: 'safe', canFire: false);
        _stopHeartbeat();
        notifyListeners();
      case 'health_degraded':
        // Re-fetch health subsystems immediately
        _audio.playHealthDegraded();
        _api.getSubsystemHealth().then((h) {
          _health = h;
          notifyListeners();
        }).catchError((_) {});
      case 'threat_detected':
        // New high-threat target — re-fetch threat queue immediately
        _api.getThreats().then((result) {
          _threats = result.threats;
          _pipelineActive = result.pipelineActive;
          notifyListeners();
        }).catchError((_) {});
      case 'target_neutralized':
        // Target lifecycle changed — refresh threats + mission status
        _pollExtended();
      case 'mission_started':
      case 'mission_ended':
        // Mission lifecycle changed — refresh mission status
        _api.getMissionStatus().then((ms) {
          _missionStatus = ms;
          notifyListeners();
        }).catchError((_) {});
      case 'nfz_added':
      case 'nfz_removed':
        // Safety zone changed — refresh NFZ list
        loadNfzZones();
      case 'fire_executed':
        // 射击已执行 — 累计开火次数，同步刷新任务状态（更新 targets_engaged 等统计）
        _audio.playFireExecuted();
        _shotsFiredCount++;
        _api.getMissionStatus().then((ms) {
          _missionStatus = ms;
          notifyListeners();
        }).catchError((_) {});
        notifyListeners();
      case 'target_designated':
        // 操作员指定目标 — 直接从事件数据同步，避免等待下次轮询
        final trackId = event.data['track_id'];
        if (trackId != null) {
          _designatedTrackId = trackId is int ? trackId : int.tryParse(trackId.toString());
        } else {
          _designatedTrackId = null; // 清除指定
        }
        notifyListeners();
      case 'config_reloaded':
        // 配置热重载已应用 — 记录时间戳，UI 可据此展示"配置已更新"提示
        _lastConfigReload = DateTime.now();
        notifyListeners();
      case 'safety_triggered':
        // 安全系统介入（NFZ、IFF、联锁等）— 强制刷新火控状态，展示原因
        final reason = event.data['reason'] as String?;
        _lastSafetyTriggerReason = reason;
        _audio.playHealthDegraded(); // reuse degraded audio cue for safety alert
        _api.getFireStatus().then((fs) {
          _fireStatus = fs;
          notifyListeners();
        }).catchError((_) {});
        notifyListeners();
    }
  }

  @override
  void dispose() {
    stopPolling();
    _stopHeartbeat();
    super.dispose();
  }
}
