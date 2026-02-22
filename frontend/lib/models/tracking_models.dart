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
    this.lockRate = 0.0,
    this.avgError = 0.0,
    this.switchesPerMin = 0.0,
  });

  factory TrackingStatus.fromJson(Map<String, dynamic> json) {
    return TrackingStatus(
      running: json['running'] ?? false,
      frameCount: json['frame_count'] ?? 0,
      errorCount: json['error_count'] ?? 0,
      state: json['state'] ?? 'SEARCH',
      yawDeg: (json['yaw_deg'] ?? 0.0).toDouble(),
      pitchDeg: (json['pitch_deg'] ?? 0.0).toDouble(),
      yawErrorDeg: (json['yaw_error_deg'] ?? 0.0).toDouble(),
      pitchErrorDeg: (json['pitch_error_deg'] ?? 0.0).toDouble(),
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
  final String? sessionId;
  final double elapsedS;
  final String? fireChainState;
  final int? targetsEngaged;

  MissionStatus({
    this.active = false,
    this.profile,
    this.sessionId,
    this.elapsedS = 0.0,
    this.fireChainState,
    this.targetsEngaged,
  });

  factory MissionStatus.fromJson(Map<String, dynamic> j) => MissionStatus(
    active: j['active'] ?? false,
    profile: j['profile'],
    sessionId: j['session_id'],
    elapsedS: (j['elapsed_s'] ?? 0.0).toDouble(),
    fireChainState: j['fire_chain_state'],
    targetsEngaged: j['targets_engaged'],
  );

  /// Convenience: format elapsed seconds as mm:ss string
  String get elapsedFormatted {
    final total = elapsedS.toInt();
    final mm = (total ~/ 60).toString().padLeft(2, '0');
    final ss = (total % 60).toString().padLeft(2, '0');
    return '$mm:$ss';
  }
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
