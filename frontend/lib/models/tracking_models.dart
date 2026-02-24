/// RWS 数据模型
library;

class TrackingStatus {
  final bool running;
  final int frameCount;
  final int errorCount;
  final String state;
  final double yawDeg;
  final double pitchDeg;
  final double yawErrorDeg;
  final double pitchErrorDeg;
  final double yawRateDps;   // gimbal angular velocity yaw axis (°/s)
  final double pitchRateDps; // gimbal angular velocity pitch axis (°/s)
  final double fps;          // pipeline processing rate
  final double lockRate;
  final double avgError;
  final double switchesPerMin;

  TrackingStatus({
    this.running = false,
    this.frameCount = 0,
    this.errorCount = 0,
    this.state = 'SEARCH',
    this.yawDeg = 0.0,
    this.pitchDeg = 0.0,
    this.yawErrorDeg = 0.0,
    this.pitchErrorDeg = 0.0,
    this.yawRateDps = 0.0,
    this.pitchRateDps = 0.0,
    this.fps = 0.0,
    this.lockRate = 0.0,
    this.avgError = 0.0,
    this.switchesPerMin = 0.0,
  });

  factory TrackingStatus.fromJson(Map<String, dynamic> json) {
    // Gimbal rates may be nested under 'gimbal' or at top level
    final gimbal = json['gimbal'] as Map<String, dynamic>? ?? {};
    return TrackingStatus(
      running: json['running'] ?? false,
      frameCount: json['frame_count'] ?? 0,
      errorCount: json['error_count'] ?? 0,
      state: json['state'] ?? 'SEARCH',
      yawDeg: (json['yaw_deg'] ?? gimbal['yaw_deg'] ?? 0.0).toDouble(),
      pitchDeg: (json['pitch_deg'] ?? gimbal['pitch_deg'] ?? 0.0).toDouble(),
      yawErrorDeg: (json['yaw_error_deg'] ?? 0.0).toDouble(),
      pitchErrorDeg: (json['pitch_error_deg'] ?? 0.0).toDouble(),
      yawRateDps: (gimbal['yaw_rate_dps'] ?? json['yaw_rate_dps'] ?? 0.0).toDouble(),
      pitchRateDps: (gimbal['pitch_rate_dps'] ?? json['pitch_rate_dps'] ?? 0.0).toDouble(),
      fps: (json['fps'] ?? json['pipeline_fps'] ?? 0.0).toDouble(),
      lockRate: (json['lock_rate'] ?? 0.0).toDouble(),
      avgError: (json['avg_abs_error_deg'] ?? 0.0).toDouble(),
      switchesPerMin: (json['switches_per_min'] ?? 0.0).toDouble(),
    );
  }
}

class PidParams {
  double kp;
  double ki;
  double kd;

  PidParams({this.kp = 5.0, this.ki = 0.4, this.kd = 0.35});

  Map<String, dynamic> toJson() => {'kp': kp, 'ki': ki, 'kd': kd};

  factory PidParams.fromJson(Map<String, dynamic> json) {
    return PidParams(
      kp: (json['kp'] ?? 5.0).toDouble(),
      ki: (json['ki'] ?? 0.4).toDouble(),
      kd: (json['kd'] ?? 0.35).toDouble(),
    );
  }
}

class SafetyZoneModel {
  final String zoneId;
  final double centerYawDeg;
  final double centerPitchDeg;
  final double radiusDeg;
  final String zoneType;

  SafetyZoneModel({
    required this.zoneId,
    required this.centerYawDeg,
    required this.centerPitchDeg,
    required this.radiusDeg,
    this.zoneType = 'no_fire',
  });

  factory SafetyZoneModel.fromJson(Map<String, dynamic> j) => SafetyZoneModel(
    zoneId: j['zone_id'] as String? ?? '',
    centerYawDeg: (j['center_yaw_deg'] as num?)?.toDouble() ?? 0.0,
    centerPitchDeg: (j['center_pitch_deg'] as num?)?.toDouble() ?? 0.0,
    radiusDeg: (j['radius_deg'] as num?)?.toDouble() ?? 0.0,
    zoneType: j['zone_type'] as String? ?? 'no_fire',
  );

  Map<String, dynamic> toJson() => {
    'zone_id': zoneId,
    'center_yaw_deg': centerYawDeg,
    'center_pitch_deg': centerPitchDeg,
    'radius_deg': radiusDeg,
    'zone_type': zoneType,
  };
}

// --- 威胁队列 ---

class ThreatEntry {
  final int trackId;
  final double threatScore;
  final int priorityRank;
  final double distanceScore;
  final double velocityScore;
  final String classId;
  final double distanceM;

  ThreatEntry({
    required this.trackId,
    required this.threatScore,
    required this.priorityRank,
    required this.distanceScore,
    required this.velocityScore,
    required this.classId,
    required this.distanceM,
  });

  factory ThreatEntry.fromJson(Map<String, dynamic> j) => ThreatEntry(
    trackId: j['track_id'] ?? 0,
    threatScore: (j['threat_score'] ?? 0.0).toDouble(),
    priorityRank: j['priority_rank'] ?? 0,
    distanceScore: (j['distance_score'] ?? 0.0).toDouble(),
    velocityScore: (j['velocity_score'] ?? 0.0).toDouble(),
    classId: j['class_id'] ?? 'unknown',
    distanceM: (j['distance_m'] ?? 0.0).toDouble(),
  );
}

// --- 子系统健康 ---

class SubsystemHealth {
  final String name;
  final String status; // ok | degraded | failed | unknown
  final double? lastHeartbeatAgeS;
  final String? error;

  SubsystemHealth({
    required this.name,
    required this.status,
    this.lastHeartbeatAgeS,
    this.error,
  });

  factory SubsystemHealth.fromJson(String name, Map<String, dynamic> j) =>
      SubsystemHealth(
        name: name,
        status: j['status'] ?? 'unknown',
        lastHeartbeatAgeS: j['last_heartbeat_age_s']?.toDouble(),
        error: j['error'],
      );
}

// --- 任务状态 ---

class MissionStatus {
  final bool active;
  final String? profile;
  /// ROE profile name — may differ from the mission profile when a named ROE
  /// preset (training/exercise/live) is loaded separately.
  final String? roeProfile;
  final String? sessionId;
  /// ISO-8601 start timestamp, e.g. "2026-02-24T10:00:00+00:00"
  final String? startedAt;
  /// Elapsed seconds reported by the server (used for initial sync).
  final double elapsedS;
  /// Alias kept for backward compat — same as [elapsedS].
  double get durationS => elapsedS;
  final String? fireChainState;
  final int? targetsEngaged;
  final int? targetsDetected;
  final int? shotsFired;
  // Lifecycle breakdown: DETECTED / TRACKED / ARCHIVED / NEUTRALIZED counts
  final Map<String, int> lifecycleByState;

  MissionStatus({
    this.active = false,
    this.profile,
    this.roeProfile,
    this.sessionId,
    this.startedAt,
    this.elapsedS = 0.0,
    this.fireChainState,
    this.targetsEngaged,
    this.targetsDetected,
    this.shotsFired,
    this.lifecycleByState = const {},
  });

  factory MissionStatus.fromJson(Map<String, dynamic> j) {
    final lifecycle = j['lifecycle'] as Map<String, dynamic>? ?? {};
    final byState = lifecycle['by_state'] as Map<String, dynamic>? ?? {};
    return MissionStatus(
      active: j['active'] ?? false,
      profile: j['profile'],
      roeProfile: j['roe_profile'] as String?,
      sessionId: j['session_id'],
      startedAt: j['started_at'] as String?,
      // Prefer duration_s (new field), fall back to elapsed_s for compat.
      elapsedS: ((j['duration_s'] ?? j['elapsed_s']) ?? 0.0).toDouble(),
      fireChainState: j['fire_chain_state'],
      targetsEngaged: j['targets_engaged'] as int?,
      targetsDetected: j['targets_detected'] as int?,
      shotsFired: j['shots_fired'] as int?,
      lifecycleByState: byState.map((k, v) => MapEntry(k, (v as num).toInt())),
    );
  }

  /// Convenience: format elapsed seconds as mm:ss string.
  String get elapsedFormatted {
    final total = elapsedS.toInt();
    final mm = (total ~/ 60).toString().padLeft(2, '0');
    final ss = (total % 60).toString().padLeft(2, '0');
    return '$mm:$ss';
  }
}

// --- 交战驻留计时器状态 ---

class EngagementDwellStatus {
  final bool active;
  final int? trackId;
  final double elapsedS;
  final double totalS;
  final double fraction; // [0.0, 1.0]

  const EngagementDwellStatus({
    this.active = false,
    this.trackId,
    this.elapsedS = 0.0,
    this.totalS = 0.0,
    this.fraction = 0.0,
  });

  factory EngagementDwellStatus.fromJson(Map<String, dynamic> j) =>
      EngagementDwellStatus(
        active: j['active'] ?? false,
        trackId: j['track_id'] as int?,
        elapsedS: (j['elapsed_s'] ?? 0.0).toDouble(),
        totalS: (j['total_s'] ?? 0.0).toDouble(),
        fraction: (j['fraction'] ?? 0.0).toDouble(),
      );
}

// --- 任务前自检 ---

class SelfTestCheck {
  final String name;
  final bool passed;
  final String message;

  const SelfTestCheck({
    required this.name,
    required this.passed,
    required this.message,
  });

  factory SelfTestCheck.fromJson(Map<String, dynamic> j) => SelfTestCheck(
        name: j['name'] as String? ?? '',
        passed: j['passed'] as bool? ?? false,
        message: j['message'] as String? ?? '',
      );
}

// --- 火控链状态 ---

class FireChainStatus {
  final String state; // safe | armed | fire_authorized | fire_requested | fired | cooldown | not_configured
  final bool canFire;
  final String? operatorId;

  FireChainStatus({
    required this.state,
    required this.canFire,
    this.operatorId,
  });

  factory FireChainStatus.fromJson(Map<String, dynamic> j) => FireChainStatus(
    state: j['state'] ?? 'not_configured',
    canFire: j['can_fire'] ?? false,
    operatorId: j['operator_id'],
  );

  bool get isConfigured => state != 'not_configured';
  bool get isArmed =>
      ['armed', 'fire_authorized', 'fire_requested', 'fired', 'cooldown']
          .contains(state);
}
