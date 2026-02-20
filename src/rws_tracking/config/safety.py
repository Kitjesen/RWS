"""安全层配置：禁射区、联锁。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyZoneConfig:
    zone_id: str = ""
    center_yaw_deg: float = 0.0
    center_pitch_deg: float = 0.0
    radius_deg: float = 10.0
    zone_type: str = "no_fire"


@dataclass(frozen=True)
class SafetyInterlockCfg:
    require_operator_auth: bool = True
    min_lock_time_s: float = 1.0
    min_engagement_range_m: float = 5.0
    max_engagement_range_m: float = 500.0
    system_check_interval_s: float = 1.0
    heartbeat_timeout_s: float = 5.0


@dataclass(frozen=True)
class SafetyConfig:
    enabled: bool = False
    interlock: SafetyInterlockCfg = SafetyInterlockCfg()
    nfz_slow_down_margin_deg: float = 5.0
    zones: tuple[SafetyZoneConfig, ...] = ()
