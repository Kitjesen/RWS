"""激光测距仪接口 — 提供精确目标距离测量。

职责（单一）：
    抽象激光测距仪硬件，提供距离读数。
    实现端可对接不同硬件协议（串口、CAN、网络等）。

提供：
    - RangefinderProvider (Protocol): 测距仪抽象接口
    - SimulatedRangefinder: 仿真实现（基于 bbox 估距 + 噪声）
    - SerialRangefinder: 串口协议实现模板

距离融合策略（由上层决定）：
    当同时有 bbox 估距和激光测距时，应优先使用激光测距。
    仅在激光无效时回退到 bbox 估距。
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Protocol

from ..types import BoundingBox, RangefinderReading

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 协议
# ---------------------------------------------------------------------------


class RangefinderProvider(Protocol):
    """激光测距仪抽象接口。

    Methods
    -------
    set_target_bbox(bbox)
        设置当前跟踪目标（用于距离估计或瞄准）。
    measure(timestamp)
        触发一次测量并返回读数。
    get_last_reading()
        获取最近一次有效读数（不触发新测量）。
    """

    def set_target_bbox(self, bbox: BoundingBox | None) -> None:
        """设置当前目标 bbox。"""
        ...

    def measure(self, timestamp: float) -> RangefinderReading:
        """触发测量, 返回最新读数。"""
        ...

    def get_last_reading(self) -> RangefinderReading:
        """获取缓存的最近有效读数。"""
        ...


# ---------------------------------------------------------------------------
# 仿真实现
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimulatedRangefinderConfig:
    """仿真测距仪配置。

    Attributes
    ----------
    noise_std_m : float
        测量噪声标准差 (m)。
    max_range_m : float
        最大测量距离 (m)。
    min_range_m : float
        最小测量距离 (m)。
    failure_rate : float
        测量失败概率 (0–1)。
    latency_s : float
        模拟测量延迟 (s), 仅影响时间戳。
    """

    noise_std_m: float = 0.5
    max_range_m: float = 1500.0
    min_range_m: float = 1.0
    failure_rate: float = 0.05
    latency_s: float = 0.01


class SimulatedRangefinder:
    """仿真激光测距仪。

    基于 bbox 高度估距，叠加高斯噪声和随机失败，
    模拟真实激光测距仪行为。

    用法:
        rf = SimulatedRangefinder(config, camera_fy=970.0)
        rf.set_target_bbox(bbox)
        reading = rf.measure(timestamp)
    """

    def __init__(
        self,
        config: SimulatedRangefinderConfig = SimulatedRangefinderConfig(),
        camera_fy: float = 970.0,
        target_height_m: float = 1.8,
    ) -> None:
        self._cfg = config
        self._fy = camera_fy
        self._target_h = target_height_m
        self._last_reading = RangefinderReading()
        self._current_bbox: BoundingBox | None = None

    def set_target_bbox(self, bbox: BoundingBox | None) -> None:
        """设置当前目标 bbox（用于估距生成真值）。"""
        self._current_bbox = bbox

    def measure(self, timestamp: float) -> RangefinderReading:
        """模拟测距。"""
        # 随机失败
        if random.random() < self._cfg.failure_rate:
            reading = RangefinderReading(
                timestamp=timestamp,
                distance_m=0.0,
                signal_strength=0.0,
                valid=False,
            )
            self._last_reading = reading
            return reading

        if self._current_bbox is None or self._current_bbox.h <= 1.0:
            reading = RangefinderReading(
                timestamp=timestamp,
                distance_m=0.0,
                signal_strength=0.0,
                valid=False,
            )
            self._last_reading = reading
            return reading

        # 真值距离
        true_dist = (self._target_h * self._fy) / self._current_bbox.h

        # 加噪声
        measured = true_dist + random.gauss(0, self._cfg.noise_std_m)
        measured = max(measured, 0.0)

        # 范围检查
        valid = self._cfg.min_range_m <= measured <= self._cfg.max_range_m

        # 信号强度模拟（距离越远信号越弱）
        signal = max(1.0 - measured / self._cfg.max_range_m, 0.05) if valid else 0.0

        reading = RangefinderReading(
            timestamp=timestamp + self._cfg.latency_s,
            distance_m=measured if valid else 0.0,
            signal_strength=signal,
            valid=valid,
        )
        if valid:
            self._last_reading = reading
        return reading

    def get_last_reading(self) -> RangefinderReading:
        return self._last_reading


# ---------------------------------------------------------------------------
# 距离融合器
# ---------------------------------------------------------------------------


class DistanceFusion:
    """距离信息融合 — 激光测距优先, bbox 估距兜底。

    策略:
    1. 激光有效且新鲜 → 直接使用
    2. 激光过期但 bbox 可用 → 使用 bbox 估距
    3. 都无效 → 返回 0

    用法:
        fuser = DistanceFusion(max_laser_age_s=0.5, camera_fy=970.0)
        dist = fuser.fuse(laser_reading, bbox, timestamp)
    """

    def __init__(
        self,
        max_laser_age_s: float = 0.5,
        camera_fy: float = 970.0,
        target_height_m: float = 1.8,
    ) -> None:
        self._max_age = max_laser_age_s
        self._fy = camera_fy
        self._target_h = target_height_m

    def fuse(
        self,
        laser: RangefinderReading | None,
        bbox: BoundingBox | None,
        timestamp: float,
    ) -> float:
        """融合距离信息, 返回最佳距离估计 (m)。

        Parameters
        ----------
        laser : RangefinderReading | None
            激光测距读数。
        bbox : BoundingBox | None
            目标 bbox。
        timestamp : float
            当前时间戳。

        Returns
        -------
        float
            估计距离 (m), 0.0 表示无有效数据。
        """
        # 优先激光
        if laser is not None and laser.valid:
            age = timestamp - laser.timestamp
            if age <= self._max_age:
                return laser.distance_m

        # 回退 bbox
        if bbox is not None and bbox.h > 1.0:
            return (self._target_h * self._fy) / bbox.h

        return 0.0
