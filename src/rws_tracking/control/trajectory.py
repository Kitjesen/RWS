"""云台轨迹规划器 — 多目标切换时的平滑运动规划。

职责（单一）：
    为云台从当前指向切换到新目标位置生成平滑的时间-角度轨迹，
    避免 PID 直接跳变导致的冲击和超调。

核心算法：
    梯形速度曲线 (Trapezoidal Velocity Profile)：
    1. 加速段: 角速度从 0 线性增加到 max_rate
    2. 匀速段: 以 max_rate 运行
    3. 减速段: 角速度从 max_rate 线性减至 0

    对于短距离切换，退化为三角速度曲线（无匀速段）。

    S-曲线 (S-Curve, Jerk-limited) 可选，减少加速度突变。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class TrajectoryPhase(str, Enum):
    """轨迹执行阶段。"""

    IDLE = "idle"
    ACCELERATING = "accelerating"
    CRUISE = "cruise"
    DECELERATING = "decelerating"
    COMPLETE = "complete"


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrajectoryConfig:
    """轨迹规划器配置。

    Attributes
    ----------
    max_rate_dps : float
        最大角速度 (°/s)。
    max_acceleration_dps2 : float
        最大角加速度 (°/s²)。
    settling_threshold_deg : float
        到达判定阈值 (°)，误差小于此值视为到达。
    use_s_curve : bool
        是否使用 S-曲线（减少 jerk）。
    max_jerk_dps3 : float
        S-曲线最大 jerk (°/s³)，仅 use_s_curve=True 时有效。
    min_switch_interval_s : float
        最小目标切换间隔 (s)，防止频繁切换抖动。
    """

    max_rate_dps: float = 180.0
    max_acceleration_dps2: float = 720.0
    settling_threshold_deg: float = 0.5
    use_s_curve: bool = False
    max_jerk_dps3: float = 3600.0
    min_switch_interval_s: float = 0.3


# ---------------------------------------------------------------------------
# 单轴梯形轨迹段
# ---------------------------------------------------------------------------


@dataclass
class TrapezoidSegment:
    """单轴梯形速度规划结果。

    时间分段:
        [0, t_accel]              → 加速
        [t_accel, t_accel+t_cruise] → 匀速
        [..., t_total]            → 减速

    Attributes
    ----------
    distance_deg : float
        总角位移 (°)，带符号。
    t_accel : float
        加速段时长 (s)。
    t_cruise : float
        匀速段时长 (s)。
    t_decel : float
        减速段时长 (s)。
    peak_rate_dps : float
        峰值角速度 (°/s)，带符号。
    """

    distance_deg: float = 0.0
    t_accel: float = 0.0
    t_cruise: float = 0.0
    t_decel: float = 0.0
    peak_rate_dps: float = 0.0

    @property
    def t_total(self) -> float:
        return self.t_accel + self.t_cruise + self.t_decel


def plan_trapezoid(
    distance_deg: float,
    max_rate_dps: float,
    max_accel_dps2: float,
) -> TrapezoidSegment:
    """为单轴计算梯形速度曲线。

    Parameters
    ----------
    distance_deg : float
        期望角位移 (°), 带符号。
    max_rate_dps : float
        最大角速度 (°/s)。
    max_accel_dps2 : float
        最大角加速度 (°/s²)。

    Returns
    -------
    TrapezoidSegment
        轨迹参数。
    """
    if abs(distance_deg) < 1e-4:
        return TrapezoidSegment()

    sign = 1.0 if distance_deg > 0 else -1.0
    dist = abs(distance_deg)
    vmax = max_rate_dps
    amax = max_accel_dps2

    # 加速到 vmax 所需距离
    d_accel = vmax**2 / (2.0 * amax)

    if 2.0 * d_accel <= dist:
        # 梯形曲线: 有匀速段
        t_accel = vmax / amax
        t_decel = t_accel
        d_cruise = dist - 2.0 * d_accel
        t_cruise = d_cruise / vmax
        peak = vmax
    else:
        # 三角曲线: 无匀速段，峰值速度受限
        peak = math.sqrt(dist * amax)
        t_accel = peak / amax
        t_decel = t_accel
        t_cruise = 0.0

    return TrapezoidSegment(
        distance_deg=distance_deg,
        t_accel=t_accel,
        t_cruise=t_cruise,
        t_decel=t_decel,
        peak_rate_dps=sign * peak,
    )


def sample_trapezoid(seg: TrapezoidSegment, t: float) -> tuple[float, float]:
    """在轨迹上采样位置和速度。

    Parameters
    ----------
    seg : TrapezoidSegment
        轨迹段。
    t : float
        时间 (s), 从轨迹起始算起。

    Returns
    -------
    (position_deg, velocity_dps)
    """
    if seg.t_total <= 0.0 or t <= 0.0:
        return 0.0, 0.0

    sign = 1.0 if seg.peak_rate_dps >= 0 else -1.0
    vmax = abs(seg.peak_rate_dps)
    amax = vmax / seg.t_accel if seg.t_accel > 0 else 0.0

    t = min(t, seg.t_total)
    ta, tc, td = seg.t_accel, seg.t_cruise, seg.t_decel

    if t <= ta:
        # 加速段
        v = amax * t
        p = 0.5 * amax * t**2
    elif t <= ta + tc:
        # 匀速段
        dt = t - ta
        p_accel = 0.5 * amax * ta**2
        v = vmax
        p = p_accel + vmax * dt
    else:
        # 减速段
        dt = t - ta - tc
        p_accel = 0.5 * amax * ta**2
        p_cruise = vmax * tc
        v = vmax - amax * dt
        v = max(v, 0.0)
        p = p_accel + p_cruise + vmax * dt - 0.5 * amax * dt**2

    return sign * p, sign * v


# ---------------------------------------------------------------------------
# 双轴轨迹规划器
# ---------------------------------------------------------------------------


class GimbalTrajectoryPlanner:
    """双轴云台轨迹规划器。

    支持：
    - 梯形速度曲线（平滑加减速）
    - 多目标切换时自动重新规划
    - 最小切换间隔防抖
    - 双轴同步（较长轴决定总时间）

    用法:
        planner = GimbalTrajectoryPlanner(config)
        planner.set_target(yaw_target_deg, pitch_target_deg, current_yaw, current_pitch, timestamp)
        yaw_rate, pitch_rate = planner.get_rate_command(timestamp)
    """

    def __init__(self, config: TrajectoryConfig = TrajectoryConfig()) -> None:
        self._cfg = config
        self._yaw_seg: TrapezoidSegment = TrapezoidSegment()
        self._pitch_seg: TrapezoidSegment = TrapezoidSegment()
        self._start_ts: float = 0.0
        self._start_yaw: float = 0.0
        self._start_pitch: float = 0.0
        self._target_yaw: float = 0.0
        self._target_pitch: float = 0.0
        self._phase = TrajectoryPhase.IDLE
        self._last_switch_ts: float = 0.0
        self._active = False

    @property
    def phase(self) -> TrajectoryPhase:
        return self._phase

    @property
    def is_active(self) -> bool:
        return self._active

    def set_target(
        self,
        yaw_target_deg: float,
        pitch_target_deg: float,
        current_yaw_deg: float,
        current_pitch_deg: float,
        timestamp: float,
    ) -> bool:
        """设定新目标位置并规划轨迹。

        Parameters
        ----------
        yaw_target_deg, pitch_target_deg : float
            目标云台绝对角度 (°)。
        current_yaw_deg, current_pitch_deg : float
            当前云台角度 (°)。
        timestamp : float
            当前时间戳。

        Returns
        -------
        bool
            是否成功规划（可能因最小间隔被拒绝）。
        """
        # 最小切换间隔检查
        if timestamp - self._last_switch_ts < self._cfg.min_switch_interval_s:
            return False

        dy = yaw_target_deg - current_yaw_deg
        dp = pitch_target_deg - current_pitch_deg

        # 已在阈值内，不需要轨迹规划
        if (
            abs(dy) < self._cfg.settling_threshold_deg
            and abs(dp) < self._cfg.settling_threshold_deg
        ):
            self._active = False
            self._phase = TrajectoryPhase.IDLE
            return True

        self._yaw_seg = plan_trapezoid(
            dy, self._cfg.max_rate_dps, self._cfg.max_acceleration_dps2
        )
        self._pitch_seg = plan_trapezoid(
            dp, self._cfg.max_rate_dps, self._cfg.max_acceleration_dps2
        )

        # 双轴同步: 较短轴拉伸到较长轴的时间
        t_max = max(self._yaw_seg.t_total, self._pitch_seg.t_total)
        if t_max > 0:
            if self._yaw_seg.t_total < t_max and abs(dy) > 1e-4:
                # 降低 yaw 轴速度以匹配时间
                scaled_rate = abs(dy) / (t_max * 0.5)  # 近似
                self._yaw_seg = plan_trapezoid(
                    dy, min(scaled_rate, self._cfg.max_rate_dps),
                    self._cfg.max_acceleration_dps2,
                )
            if self._pitch_seg.t_total < t_max and abs(dp) > 1e-4:
                scaled_rate = abs(dp) / (t_max * 0.5)
                self._pitch_seg = plan_trapezoid(
                    dp, min(scaled_rate, self._cfg.max_rate_dps),
                    self._cfg.max_acceleration_dps2,
                )

        self._start_ts = timestamp
        self._start_yaw = current_yaw_deg
        self._start_pitch = current_pitch_deg
        self._target_yaw = yaw_target_deg
        self._target_pitch = pitch_target_deg
        self._active = True
        self._phase = TrajectoryPhase.ACCELERATING
        self._last_switch_ts = timestamp

        logger.info(
            "trajectory planned: Δyaw=%.1f° Δpitch=%.1f° t=%.3fs",
            dy, dp, t_max,
        )
        return True

    def get_rate_command(self, timestamp: float) -> tuple[float, float]:
        """获取当前时刻的轨迹速率指令。

        Parameters
        ----------
        timestamp : float
            当前时间戳。

        Returns
        -------
        (yaw_rate_dps, pitch_rate_dps)
        """
        if not self._active:
            return 0.0, 0.0

        t = timestamp - self._start_ts
        t_total = max(self._yaw_seg.t_total, self._pitch_seg.t_total)

        if t >= t_total:
            self._active = False
            self._phase = TrajectoryPhase.COMPLETE
            return 0.0, 0.0

        _, yaw_rate = sample_trapezoid(self._yaw_seg, t)
        _, pitch_rate = sample_trapezoid(self._pitch_seg, t)

        # 更新阶段
        ta = max(self._yaw_seg.t_accel, self._pitch_seg.t_accel)
        tc = max(self._yaw_seg.t_cruise, self._pitch_seg.t_cruise)
        if t <= ta:
            self._phase = TrajectoryPhase.ACCELERATING
        elif t <= ta + tc:
            self._phase = TrajectoryPhase.CRUISE
        else:
            self._phase = TrajectoryPhase.DECELERATING

        return yaw_rate, pitch_rate

    def cancel(self) -> None:
        """取消当前轨迹。"""
        self._active = False
        self._phase = TrajectoryPhase.IDLE
