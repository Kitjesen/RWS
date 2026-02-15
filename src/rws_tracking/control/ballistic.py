"""弹道补偿模块 — 根据目标距离计算下坠补偿角"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from ..types import BoundingBox


class BallisticModel(Protocol):
    """弹道模型协议"""

    def compute(self, bbox: BoundingBox, camera_fy: float) -> float:
        """计算弹道补偿角（度），正值表示向上倾斜"""
        ...


@dataclass
class SimpleBallisticConfig:
    """简单弹道模型配置"""

    target_height_m: float = 1.8  # 假设目标高度（人体）
    quadratic_a: float = 0.001  # 二次项系数
    quadratic_b: float = 0.01  # 一次项系数
    quadratic_c: float = 0.0  # 常数项


class SimpleBallisticModel:
    """基于bbox高度估算距离的简单弹道模型

    距离估计：distance = (target_height * fy) / bbox.h
    补偿角：compensation = a * distance^2 + b * distance + c
    """

    def __init__(self, config: SimpleBallisticConfig) -> None:
        self._cfg = config

    def compute(self, bbox: BoundingBox, camera_fy: float) -> float:
        if bbox.h <= 1.0:
            return 0.0

        # 估算距离（米）
        distance_m = (self._cfg.target_height_m * camera_fy) / bbox.h

        # 二次函数补偿
        compensation_deg = (
            self._cfg.quadratic_a * distance_m**2
            + self._cfg.quadratic_b * distance_m
            + self._cfg.quadratic_c
        )
        return compensation_deg


@dataclass
class TableBallisticConfig:
    """查找表弹道模型配置"""

    target_height_m: float = 1.8
    distance_table: tuple[float, ...] = (5.0, 10.0, 15.0, 20.0, 25.0, 30.0)
    compensation_table: tuple[float, ...] = (0.1, 0.4, 0.9, 1.6, 2.5, 3.6)


class TableBallisticModel:
    """基于查找表的精确弹道模型（需实测标定）"""

    def __init__(self, config: TableBallisticConfig) -> None:
        self._cfg = config
        if len(config.distance_table) != len(config.compensation_table):
            raise ValueError("distance_table and compensation_table must have same length")

    def compute(self, bbox: BoundingBox, camera_fy: float) -> float:
        if bbox.h <= 1.0:
            return 0.0

        # 估算距离
        distance_m = (self._cfg.target_height_m * camera_fy) / bbox.h

        # 线性插值查表
        return float(
            np.interp(
                distance_m,
                self._cfg.distance_table,
                self._cfg.compensation_table,
            )
        )
