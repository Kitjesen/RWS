"""自适应PID增益调度模块"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Tuple


class GainScheduler(Protocol):
    """增益调度器协议"""
    def compute_multipliers(self, error_mag: float, bbox_area: float) -> Tuple[float, float, float]:
        """返回 (kp_mult, ki_mult, kd_mult)"""
        ...


@dataclass
class ErrorBasedSchedulerConfig:
    """基于误差的增益调度配置"""
    low_error_threshold_deg: float = 2.0
    high_error_threshold_deg: float = 10.0
    low_error_multiplier: float = 0.8
    high_error_multiplier: float = 1.5


class ErrorBasedScheduler:
    """根据误差大小分段调整增益

    - 小误差（< low_threshold）：降低增益，精确锁定
    - 中等误差：标准增益
    - 大误差（> high_threshold）：提高增益，快速追赶
    """
    def __init__(self, config: ErrorBasedSchedulerConfig) -> None:
        self._cfg = config

    def compute_multipliers(self, error_mag: float, bbox_area: float) -> Tuple[float, float, float]:
        if error_mag < self._cfg.low_error_threshold_deg:
            mult = self._cfg.low_error_multiplier
        elif error_mag > self._cfg.high_error_threshold_deg:
            mult = self._cfg.high_error_multiplier
        else:
            # 线性插值
            ratio = (error_mag - self._cfg.low_error_threshold_deg) / (
                self._cfg.high_error_threshold_deg - self._cfg.low_error_threshold_deg
            )
            mult = self._cfg.low_error_multiplier + ratio * (
                self._cfg.high_error_multiplier - self._cfg.low_error_multiplier
            )

        return mult, mult, mult  # kp, ki, kd 同步调整


@dataclass
class DistanceBasedSchedulerConfig:
    """基于距离的增益调度配置"""
    near_distance_m: float = 5.0
    far_distance_m: float = 30.0
    near_multiplier: float = 1.0
    far_multiplier: float = 1.3
    target_height_m: float = 1.8
    bbox_area_max: float = 50000.0  # bbox 面积归一化上限 (px^2)
    ki_distance_scale: float = 0.8  # 远距离时 ki 缩放系数


class DistanceBasedScheduler:
    """根据目标距离调整增益

    - 近距离：标准增益
    - 远距离：提高增益（补偿角分辨率下降）
    """
    def __init__(self, config: DistanceBasedSchedulerConfig) -> None:
        self._cfg = config

    def compute_multipliers(self, error_mag: float, bbox_area: float) -> Tuple[float, float, float]:
        # 从 bbox 面积估算距离代理：area 小 = 距离远
        # 归一化距离：0 = 近，1 = 远
        area_max = max(self._cfg.bbox_area_max, 1.0)
        normalized_dist = 1.0 - min(max(bbox_area / area_max, 0.0), 1.0)

        mult = self._cfg.near_multiplier + normalized_dist * (
            self._cfg.far_multiplier - self._cfg.near_multiplier
        )

        # ki 稍微降低，避免远距离积分饱和
        return mult, mult * self._cfg.ki_distance_scale, mult
