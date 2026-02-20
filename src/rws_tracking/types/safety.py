"""安全层数据类型：禁射区、安全状态。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyZone:
    """禁射区定义 (圆形区域, 云台坐标系)。"""

    zone_id: str = ""
    center_yaw_deg: float = 0.0
    center_pitch_deg: float = 0.0
    radius_deg: float = 10.0
    zone_type: str = "no_fire"


@dataclass(frozen=True)
class SafetyStatus:
    """安全系统状态。"""

    fire_authorized: bool = False
    blocked_reason: str = ""
    active_zone: str = ""
    operator_override: bool = False
    emergency_stop: bool = False
