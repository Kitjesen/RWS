"""硬件层数据类型：载体姿态、测距读数。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BodyState:
    """6-DOF body (base platform) state，来源可为 IMU 或编码器解算或二者融合。

    Note
    ----
    数据可由 IMU 解算、关节编码器+运动学解算、或 IMU+编码器融合得到；
    BodyMotionProvider 接口不限定具体传感器。
    """

    timestamp: float
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0
    roll_rate_dps: float = 0.0
    pitch_rate_dps: float = 0.0
    yaw_rate_dps: float = 0.0


@dataclass(frozen=True)
class RangefinderReading:
    """激光测距仪读数。"""

    timestamp: float = 0.0
    distance_m: float = 0.0
    signal_strength: float = 0.0
    valid: bool = False
