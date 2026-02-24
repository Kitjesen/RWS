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
class SafetyInterlockConfig:
    require_operator_auth: bool = True
    min_lock_time_s: float = 1.0
    min_engagement_range_m: float = 5.0
    max_engagement_range_m: float = 500.0
    system_check_interval_s: float = 1.0
    heartbeat_timeout_s: float = 5.0


# Backward-compat alias — remove after next major version
SafetyInterlockCfg = SafetyInterlockConfig


@dataclass(frozen=True)
class SafetyConfig:
    enabled: bool = False
    interlock: SafetyInterlockConfig = SafetyInterlockConfig()
    nfz_slow_down_margin_deg: float = 5.0
    zones: tuple[SafetyZoneConfig, ...] = ()
    # --- Two-man arming rule ---
    # When True, POST /api/fire/arm requires confirmation from two different
    # operators within arm_confirmation_timeout_s seconds.
    two_man_rule: bool = False
    arm_confirmation_timeout_s: float = 30.0
    # --- Rules of Engagement profile ---
    # "training" (default) | "exercise" | "live"
    roe_profile: str = "training"
