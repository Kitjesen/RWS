"""Gimbal hardware driver abstraction (simulated implementation)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..config import DriverLimitsConfig
from ..types import GimbalFeedback

logger = logging.getLogger(__name__)


@dataclass
class DriverLimits:
    yaw_min_deg: float = -160.0
    yaw_max_deg: float = 160.0
    pitch_min_deg: float = -45.0
    pitch_max_deg: float = 75.0
    max_rate_dps: float = 240.0
    deadband_dps: float = 0.2
    # 动力学参数
    inertia_time_constant_s: float = 0.05  # 一阶惯性时间常数（越大越慢）
    static_friction_dps: float = 0.5  # 静摩擦阈值
    coulomb_friction_dps: float = 2.0  # 库仑摩擦（恒定阻力）

    @classmethod
    def from_config(cls, cfg: DriverLimitsConfig) -> DriverLimits:
        """Create DriverLimits from a DriverLimitsConfig."""
        return cls(
            yaw_min_deg=cfg.yaw_min_deg,
            yaw_max_deg=cfg.yaw_max_deg,
            pitch_min_deg=cfg.pitch_min_deg,
            pitch_max_deg=cfg.pitch_max_deg,
            max_rate_dps=cfg.max_rate_dps,
            deadband_dps=cfg.deadband_dps,
            inertia_time_constant_s=cfg.inertia_time_constant_s,
            static_friction_dps=cfg.static_friction_dps,
            coulomb_friction_dps=cfg.coulomb_friction_dps,
        )


class SimulatedGimbalDriver:
    """仿真云台驱动，包含动力学模型

    动力学特性：
    - 一阶惯性：实际速率以时间常数 τ 跟随命令速率
    - 静摩擦：速率低于阈值时停止运动
    - 库仑摩擦：恒定阻力，与速率方向相反
    """

    def __init__(self, limits: DriverLimits = DriverLimits()) -> None:
        self._limits = limits
        self._yaw = 0.0
        self._pitch = 0.0
        self._yaw_rate = 0.0  # 实际速率（受动力学影响）
        self._pitch_rate = 0.0
        self._yaw_cmd = 0.0  # 命令速率
        self._pitch_cmd = 0.0
        self._last_ts = 0.0

    def set_yaw_pitch_rate(
        self, yaw_rate_dps: float, pitch_rate_dps: float, timestamp: float
    ) -> None:
        self._integrate_to(timestamp)
        self._yaw_cmd = self._clip_rate(yaw_rate_dps)
        self._pitch_cmd = self._clip_rate(pitch_rate_dps)
        logger.debug(
            "cmd  yaw=%.2f dps  pitch=%.2f dps  t=%.3f",
            self._yaw_cmd,
            self._pitch_cmd,
            timestamp,
        )

    def get_feedback(self, timestamp: float) -> GimbalFeedback:
        self._integrate_to(timestamp)
        logger.debug(
            "fb   yaw=%.2f°  pitch=%.2f°  rate=(%.2f, %.2f) dps  t=%.3f",
            self._yaw,
            self._pitch,
            self._yaw_rate,
            self._pitch_rate,
            timestamp,
        )
        return GimbalFeedback(
            timestamp=timestamp,
            yaw_deg=self._yaw,
            pitch_deg=self._pitch,
            yaw_rate_dps=self._yaw_rate,
            pitch_rate_dps=self._pitch_rate,
        )

    def _clip_rate(self, value: float) -> float:
        clipped = max(-self._limits.max_rate_dps, min(self._limits.max_rate_dps, value))
        if abs(clipped) < self._limits.deadband_dps:
            return 0.0
        return clipped

    def _integrate_to(self, timestamp: float) -> None:
        if self._last_ts == 0.0:
            self._last_ts = timestamp
            return
        dt = max(timestamp - self._last_ts, 0.0)
        self._last_ts = timestamp

        # 一阶惯性：实际速率跟随命令速率
        tau = self._limits.inertia_time_constant_s
        if tau > 1e-6:
            alpha = dt / (tau + dt)  # 离散化一阶惯性
            self._yaw_rate += alpha * (self._yaw_cmd - self._yaw_rate)
            self._pitch_rate += alpha * (self._pitch_cmd - self._pitch_rate)
        else:
            # tau=0 时退化为理想响应
            self._yaw_rate = self._yaw_cmd
            self._pitch_rate = self._pitch_cmd

        # 库仑摩擦：恒定阻力
        friction = self._limits.coulomb_friction_dps
        if abs(self._yaw_rate) > 1e-3:
            sign = 1.0 if self._yaw_rate > 0 else -1.0
            self._yaw_rate -= sign * friction * dt
            # 防止摩擦导致反向
            if (self._yaw_rate > 0) != (sign > 0):
                self._yaw_rate = 0.0

        if abs(self._pitch_rate) > 1e-3:
            sign = 1.0 if self._pitch_rate > 0 else -1.0
            self._pitch_rate -= sign * friction * dt
            if (self._pitch_rate > 0) != (sign > 0):
                self._pitch_rate = 0.0

        # 静摩擦：低速时停止（仅当阈值 > 0 时应用）
        static_thresh = self._limits.static_friction_dps
        if static_thresh > 0.0:
            if abs(self._yaw_rate) < static_thresh:
                self._yaw_rate = 0.0
            if abs(self._pitch_rate) < static_thresh:
                self._pitch_rate = 0.0

        # 积分位置
        self._yaw += self._yaw_rate * dt
        self._pitch += self._pitch_rate * dt

        # 限位
        self._yaw = max(self._limits.yaw_min_deg, min(self._limits.yaw_max_deg, self._yaw))
        self._pitch = max(self._limits.pitch_min_deg, min(self._limits.pitch_max_deg, self._pitch))
