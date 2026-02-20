"""弹道层数据类型：弹丸参数、环境参数、弹道解、提前量。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectileParams:
    """弹丸物理参数。"""

    muzzle_velocity_mps: float = 850.0
    ballistic_coefficient: float = 0.4
    projectile_mass_kg: float = 0.0098
    projectile_diameter_m: float = 0.00762
    drag_model: str = "g1"


@dataclass(frozen=True)
class EnvironmentParams:
    """射击环境参数。"""

    temperature_c: float = 15.0
    pressure_hpa: float = 1013.25
    humidity_pct: float = 50.0
    wind_speed_mps: float = 0.0
    wind_direction_deg: float = 0.0
    altitude_m: float = 0.0


@dataclass(frozen=True)
class BallisticSolution:
    """弹道解算结果。"""

    flight_time_s: float = 0.0
    drop_deg: float = 0.0
    windage_deg: float = 0.0
    impact_velocity_mps: float = 0.0
    distance_m: float = 0.0


@dataclass(frozen=True)
class LeadAngle:
    """射击提前量结果。"""

    yaw_lead_deg: float = 0.0
    pitch_lead_deg: float = 0.0
    predicted_target_x: float = 0.0
    predicted_target_y: float = 0.0
    confidence: float = 0.0
