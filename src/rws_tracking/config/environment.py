"""环境与弹丸配置；相机内参配置。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectileConfig:
    enabled: bool = False
    muzzle_velocity_mps: float = 850.0
    ballistic_coefficient: float = 0.4
    projectile_mass_kg: float = 0.0098
    projectile_diameter_m: float = 0.00762
    drag_model: str = "g1"


@dataclass(frozen=True)
class EnvironmentConfig:
    temperature_c: float = 15.0
    pressure_hpa: float = 1013.25
    humidity_pct: float = 50.0
    wind_speed_mps: float = 0.0
    wind_direction_deg: float = 0.0
    altitude_m: float = 0.0


@dataclass(frozen=True)
class CameraConfig:
    width: int = 1280
    height: int = 720
    fx: float = 970.0
    fy: float = 965.0
    cx: float = 640.0
    cy: float = 360.0
    distortion_k1: float = 0.0
    distortion_k2: float = 0.0
    distortion_p1: float = 0.0
    distortion_p2: float = 0.0
    distortion_k3: float = 0.0
    mount_roll_deg: float = 0.0
    mount_pitch_deg: float = 0.0
    mount_yaw_deg: float = 0.0
