"""射击提前量计算器 — 融合目标运动预测与弹丸飞行时间。

职责（单一）：
    根据目标的像素速度/加速度和弹丸飞行时间，计算射击提前量
    （yaw/pitch 偏移角），使弹丸在飞行结束时命中目标预测位置。

核心公式：
    predicted_pos = current_pos + v * t_flight + 0.5 * a * t_flight²
    lead_angle    = pixel_to_angle(predicted_pos) - pixel_to_angle(current_pos)

依赖：
    - PhysicsBallisticModel / BallisticModel: 提供飞行时间
    - PixelToGimbalTransform: 像素 → 角度转换
    - TargetObservation: 目标状态（位置/速度/加速度）
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Protocol

from ..algebra import PixelToGimbalTransform
from ..types import (
    BoundingBox,
    EnvironmentParams,
    LeadAngle,
    TargetObservation,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 飞行时间提供者协议
# ---------------------------------------------------------------------------


class FlightTimeProvider(Protocol):
    """提供弹丸飞行时间的协议。"""

    def compute_flight_time(
        self,
        distance_m: float,
        environment: EnvironmentParams | None = None,
    ) -> float:
        """返回弹丸飞至 distance_m 所需时间 (s)。"""
        ...


class SimpleFlightTimeProvider:
    """简单飞行时间估算: t = d / v (忽略空气阻力)。"""

    def __init__(self, muzzle_velocity_mps: float = 900.0) -> None:
        self._v = max(muzzle_velocity_mps, 1.0)

    def compute_flight_time(
        self,
        distance_m: float,
        environment: EnvironmentParams | None = None,
    ) -> float:
        return max(distance_m, 0.0) / self._v


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LeadAngleConfig:
    """射击提前量计算配置。

    Attributes
    ----------
    enabled : bool
        是否启用提前量计算。
    use_acceleration : bool
        是否使用加速度项（二阶预测）。
    max_lead_deg : float
        提前量角度上限 (°), 防止异常值。
    min_confidence : float
        最低置信度阈值，低于此值不输出提前量。
    velocity_smoothing_alpha : float
        速度平滑系数 (0–1), 1 = 无平滑。
    target_height_m : float
        假设目标高度 (m), 用于 bbox 测距。
    convergence_iterations : int
        飞行时间迭代收敛次数（飞行时间与提前量互相依赖）。
    """

    enabled: bool = False
    use_acceleration: bool = True
    max_lead_deg: float = 5.0
    min_confidence: float = 0.3
    velocity_smoothing_alpha: float = 0.7
    target_height_m: float = 1.8
    convergence_iterations: int = 3


# ---------------------------------------------------------------------------
# 提前量计算器
# ---------------------------------------------------------------------------


class LeadAngleCalculator:
    """射击提前量计算器。

    工作流程:
    1. 从目标 bbox 估算距离
    2. 查询弹道模型获取飞行时间
    3. 用目标速度 + 加速度预测飞行时间后的目标位置
    4. 将预测位置转为角度偏移
    5. 迭代收敛（飞行时间依赖距离，距离依赖预测位置）

    置信度评估:
    - 目标跟踪帧数越长，速度估计越可靠
    - 加速度变化剧烈时降低置信度
    - 目标过小（远距离）时降低置信度
    """

    def __init__(
        self,
        transform: PixelToGimbalTransform,
        flight_time_provider: FlightTimeProvider,
        config: LeadAngleConfig = LeadAngleConfig(),
    ) -> None:
        self._transform = transform
        self._ftp = flight_time_provider
        self._cfg = config
        self._smoothed_vx: float = 0.0
        self._smoothed_vy: float = 0.0
        self._last_track_id: int | None = None
        # Jerk estimation: track previous acceleration for maneuver detection.
        # High jerk (da/dt) indicates an erratic maneuver, reducing prediction confidence.
        self._prev_ax: float = 0.0
        self._prev_ay: float = 0.0
        self._prev_obs_ts: float = 0.0

    def compute(
        self,
        target: TargetObservation,
        environment: EnvironmentParams | None = None,
    ) -> LeadAngle:
        """计算射击提前量。

        Parameters
        ----------
        target : TargetObservation
            当前目标观测。
        environment : EnvironmentParams, optional
            环境参数。

        Returns
        -------
        LeadAngle
            包含 yaw/pitch 提前角和预测命中点。
        """
        if not self._cfg.enabled:
            return LeadAngle()

        # 目标切换时重置速度平滑
        if target.track_id != self._last_track_id:
            self._smoothed_vx = target.velocity_px_per_s[0]
            self._smoothed_vy = target.velocity_px_per_s[1]
            self._last_track_id = target.track_id

        # 速度平滑
        alpha = self._cfg.velocity_smoothing_alpha
        raw_vx, raw_vy = target.velocity_px_per_s
        self._smoothed_vx = alpha * raw_vx + (1.0 - alpha) * self._smoothed_vx
        self._smoothed_vy = alpha * raw_vy + (1.0 - alpha) * self._smoothed_vy
        vx, vy = self._smoothed_vx, self._smoothed_vy

        ax, ay = (0.0, 0.0)
        if self._cfg.use_acceleration:
            ax, ay = target.acceleration_px_per_s2

        # Jerk estimation: rate of change of acceleration (px/s³).
        # Tracks how quickly the target is changing its acceleration pattern.
        # Used in _assess_confidence() to penalise erratic manoeuvres.
        now = time.monotonic()
        jerk_x, jerk_y = 0.0, 0.0
        if self._prev_obs_ts > 0.0 and target.track_id == self._last_track_id:
            dt_obs = max(now - self._prev_obs_ts, 0.01)
            jerk_x = (ax - self._prev_ax) / dt_obs
            jerk_y = (ay - self._prev_ay) / dt_obs
        self._prev_ax = ax
        self._prev_ay = ay
        self._prev_obs_ts = now

        # 目标当前中心
        cx, cy = target.mask_center if target.mask_center is not None else target.bbox.center

        # 估算距离
        cam_fy = self._transform.camera.fy
        distance_m = self._estimate_distance(target.bbox, cam_fy)
        if distance_m <= 0.0:
            return LeadAngle()

        # 迭代求解（飞行时间 ↔ 预测位置 ↔ 距离互相依赖）
        t_flight = 0.0
        pred_cx, pred_cy = cx, cy

        for _ in range(self._cfg.convergence_iterations):
            t_flight = self._ftp.compute_flight_time(distance_m, environment)
            if t_flight <= 0.0:
                return LeadAngle()

            # 预测目标位置（匀加速模型）
            pred_cx = cx + vx * t_flight + 0.5 * ax * t_flight**2
            pred_cy = cy + vy * t_flight + 0.5 * ay * t_flight**2

            # 更新距离估计（可选：如果有更好的距离模型）
            # 简化处理：保持初始距离估计不变

        # 当前角度
        yaw_current, pitch_current = self._transform.pixel_to_angle_error(cx, cy)
        # 预测角度
        yaw_pred, pitch_pred = self._transform.pixel_to_angle_error(pred_cx, pred_cy)

        lead_yaw = yaw_pred - yaw_current
        lead_pitch = pitch_pred - pitch_current

        # 限幅
        max_lead = self._cfg.max_lead_deg
        lead_yaw = max(-max_lead, min(max_lead, lead_yaw))
        lead_pitch = max(-max_lead, min(max_lead, lead_pitch))

        # 置信度评估
        confidence = self._assess_confidence(target, vx, vy, ax, ay, t_flight, jerk_x, jerk_y)

        if confidence < self._cfg.min_confidence:
            lead_yaw *= confidence / self._cfg.min_confidence
            lead_pitch *= confidence / self._cfg.min_confidence

        logger.debug(
            "lead angle: yaw=%.3f° pitch=%.3f° t_flight=%.4fs conf=%.2f d=%.1fm",
            lead_yaw,
            lead_pitch,
            t_flight,
            confidence,
            distance_m,
        )

        return LeadAngle(
            yaw_lead_deg=lead_yaw,
            pitch_lead_deg=lead_pitch,
            predicted_target_x=pred_cx,
            predicted_target_y=pred_cy,
            confidence=confidence,
        )

    def _estimate_distance(self, bbox: BoundingBox, camera_fy: float) -> float:
        """从 bbox 估距。"""
        if bbox.h <= 1.0:
            return 0.0
        return (self._cfg.target_height_m * camera_fy) / bbox.h

    def _assess_confidence(
        self,
        target: TargetObservation,
        vx: float,
        vy: float,
        ax: float,
        ay: float,
        t_flight: float,
        jerk_x: float = 0.0,
        jerk_y: float = 0.0,
    ) -> float:
        """评估提前量预测的置信度。

        考量因素:
        1. 速度大小: 静止目标无需提前量 → 低置信度
        2. 加速度稳定性: 高加速度 → 运动不稳定 → 降低置信度
        3. 飞行时间: 越长预测越不可靠
        4. 目标置信度: 检测器置信度
        5. 机动抖动 (jerk): 加速度变化率高 → 机动预测不可靠 → 降低置信度
        """
        speed = math.sqrt(vx**2 + vy**2)
        accel = math.sqrt(ax**2 + ay**2)

        # 速度得分: 速度太低时无意义
        speed_score = min(speed / 50.0, 1.0)

        # 加速度惩罚: 高加速度降低可靠性
        accel_penalty = max(1.0 - accel / 500.0, 0.2)

        # 飞行时间惩罚: 长飞行时间降低预测可靠性
        time_penalty = max(1.0 - t_flight / 2.0, 0.3)

        # 检测器置信度
        det_score = target.confidence

        # 机动检测: 抖动 (jerk = da/dt) 越大，加速度预测越不可靠
        # 参考值 2000 px/s³；超过此值时置信度降至 0.2
        jerk_mag = math.sqrt(jerk_x**2 + jerk_y**2)
        jerk_penalty = max(1.0 - jerk_mag / 2000.0, 0.2)

        confidence = speed_score * accel_penalty * time_penalty * det_score * jerk_penalty
        return max(min(confidence, 1.0), 0.0)
