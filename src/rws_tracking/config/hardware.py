"""硬件层配置：驱动限位、测距仪。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DriverLimitsConfig:
    yaw_min_deg: float = -160.0
    yaw_max_deg: float = 160.0
    pitch_min_deg: float = -45.0
    pitch_max_deg: float = 75.0
    max_rate_dps: float = 240.0
    deadband_dps: float = 0.2
    inertia_time_constant_s: float = 0.05
    static_friction_dps: float = 0.5
    coulomb_friction_dps: float = 2.0


@dataclass(frozen=True)
class RangefinderConfig:
    enabled: bool = False
    type: str = "simulated"
    max_range_m: float = 1500.0
    min_range_m: float = 1.0
    noise_std_m: float = 0.5
    failure_rate: float = 0.05
    max_laser_age_s: float = 0.5
    target_height_m: float = 1.8
    serial_port: str = ""
    serial_baud: int = 9600
