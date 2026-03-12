"""弹道补偿模块 — 根据目标距离计算下坠补偿角与弹丸飞行时间。

提供三层弹道模型：
1. SimpleBallisticModel  — 经验二次函数（快速，需标定）
2. TableBallisticModel   — 实测查表插值（高精度，需射表）
3. PhysicsBallisticModel — 物理积分求解（含阻力/重力/风偏/科氏力）

所有模型均实现 BallisticModel 协议；PhysicsBallisticModel 额外实现
FullBallisticSolver 协议以返回完整 BallisticSolution。
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from ..types import (
    BallisticSolution,
    BoundingBox,
    EnvironmentParams,
    ProjectileParams,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 协议
# ---------------------------------------------------------------------------


class BallisticModel(Protocol):
    """弹道模型协议（基础）"""

    def compute(self, bbox: BoundingBox, camera_fy: float) -> float:
        """计算弹道补偿角（度），正值表示向上倾斜"""
        ...


class FullBallisticSolver(Protocol):
    """完整弹道解算协议（含飞行时间、风偏等）"""

    def solve(
        self,
        distance_m: float,
        elevation_deg: float = 0.0,
        environment: EnvironmentParams | None = None,
    ) -> BallisticSolution:
        """完整弹道解算。

        Parameters
        ----------
        distance_m : float
            目标斜距 (m)。
        elevation_deg : float
            射击仰角 (°)。
        environment : EnvironmentParams, optional
            环境参数，None 时使用标准大气。
        """
        ...


# ---------------------------------------------------------------------------
# 距离估算工具
# ---------------------------------------------------------------------------


def estimate_distance_from_bbox(
    bbox: BoundingBox,
    camera_fy: float,
    target_height_m: float = 1.8,
) -> float:
    """从 bbox 高度估算目标距离。

    公式: distance = (target_height_m * fy) / bbox_h
    """
    if bbox.h <= 1.0:
        return 0.0
    return (target_height_m * camera_fy) / bbox.h


# ---------------------------------------------------------------------------
# 1. SimpleBallisticModel — 经验二次函数
# ---------------------------------------------------------------------------


@dataclass
class SimpleBallisticConfig:
    """简单弹道模型配置"""

    target_height_m: float = 1.8
    quadratic_a: float = 0.001
    quadratic_b: float = 0.01
    quadratic_c: float = 0.0


class SimpleBallisticModel:
    """基于 bbox 高度估距的简单弹道模型

    距离估计: distance = (target_height * fy) / bbox.h
    补偿角:   compensation = a * distance² + b * distance + c
    """

    def __init__(self, config: SimpleBallisticConfig) -> None:
        self._cfg = config

    def compute(self, bbox: BoundingBox, camera_fy: float) -> float:
        distance_m = estimate_distance_from_bbox(bbox, camera_fy, self._cfg.target_height_m)
        if distance_m <= 0.0:
            return 0.0
        return (
            self._cfg.quadratic_a * distance_m**2
            + self._cfg.quadratic_b * distance_m
            + self._cfg.quadratic_c
        )


# ---------------------------------------------------------------------------
# 2. TableBallisticModel — 实测查表插值
# ---------------------------------------------------------------------------


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
        distance_m = estimate_distance_from_bbox(bbox, camera_fy, self._cfg.target_height_m)
        if distance_m <= 0.0:
            return 0.0
        return float(
            np.interp(
                distance_m,
                self._cfg.distance_table,
                self._cfg.compensation_table,
            )
        )


# ---------------------------------------------------------------------------
# 3. PhysicsBallisticModel — 物理弹道积分求解
# ---------------------------------------------------------------------------


# 标准 G1 阻力曲线 (马赫数 → 阻力系数), 简化近似
_G1_MACH_CD: list[tuple[float, float]] = [
    (0.0, 0.230),
    (0.5, 0.230),
    (0.7, 0.250),
    (0.8, 0.280),
    (0.9, 0.350),
    (0.95, 0.450),
    (1.0, 0.520),
    (1.05, 0.490),
    (1.1, 0.460),
    (1.2, 0.420),
    (1.5, 0.380),
    (2.0, 0.340),
    (2.5, 0.320),
    (3.0, 0.310),
]

_G7_MACH_CD: list[tuple[float, float]] = [
    (0.0, 0.120),
    (0.5, 0.120),
    (0.7, 0.125),
    (0.8, 0.135),
    (0.9, 0.165),
    (0.95, 0.230),
    (1.0, 0.285),
    (1.05, 0.265),
    (1.1, 0.250),
    (1.2, 0.230),
    (1.5, 0.200),
    (2.0, 0.180),
    (2.5, 0.170),
    (3.0, 0.165),
]


def _air_density(env: EnvironmentParams) -> float:
    """根据环境参数计算空气密度 (kg/m³)。

    使用理想气体近似：ρ = P / (R_specific * T)
    """
    t_kelvin = env.temperature_c + 273.15
    p_pa = env.pressure_hpa * 100.0
    # 干空气气体常数 R = 287.05 J/(kg·K)
    r_air = 287.05
    # 湿度修正（简化）: 水蒸气密度更低
    humidity_factor = 1.0 - 0.003 * (env.humidity_pct / 100.0)
    # 海拔气压修正（气压已含海拔效果时可跳过）
    return (p_pa / (r_air * t_kelvin)) * humidity_factor


def _speed_of_sound(env: EnvironmentParams) -> float:
    """音速 (m/s), 近似公式: c = 331.3 + 0.606 * T(°C)"""
    return 331.3 + 0.606 * env.temperature_c


def _lookup_cd(mach: float, drag_model: str) -> float:
    """查表获取给定马赫数的阻力系数。"""
    table = _G1_MACH_CD if drag_model == "g1" else _G7_MACH_CD
    machs = [m for m, _ in table]
    cds = [c for _, c in table]
    return float(np.interp(mach, machs, cds))


class PhysicsBallisticModel:
    """基于物理积分的弹道模型。

    采用四阶 Runge-Kutta 数值积分求解弹丸运动方程：

        ma = F_gravity + F_drag + F_wind

    其中:
        F_drag = -0.5 * ρ * Cd * A * |v_rel|² * v̂_rel
        v_rel  = v_projectile - v_wind

    功能:
        - 重力下坠补偿
        - 空气阻力 (G1/G7 阻力曲线)
        - 风偏补偿 (横风/纵风)
        - 温度/气压/湿度对空气密度的影响
        - 弹丸飞行时间精确计算

    同时实现 BallisticModel 和 FullBallisticSolver 协议。
    """

    def __init__(
        self,
        projectile: ProjectileParams = ProjectileParams(),
        target_height_m: float = 1.8,
        dt: float = 0.0005,
        max_range_m: float = 2000.0,
    ) -> None:
        self._proj = projectile
        self._target_height_m = target_height_m
        self._dt = dt
        self._max_range_m = max_range_m

        # 弹丸截面积 (m²)
        self._cross_section = math.pi * (projectile.projectile_diameter_m / 2.0) ** 2

    # --- BallisticModel 协议 ---

    def compute(self, bbox: BoundingBox, camera_fy: float) -> float:
        """兼容旧接口: 仅返回俯仰补偿角。"""
        distance_m = estimate_distance_from_bbox(bbox, camera_fy, self._target_height_m)
        if distance_m <= 0.0:
            return 0.0
        sol = self.solve(distance_m)
        return sol.drop_deg

    # --- FullBallisticSolver 协议 ---

    def solve(
        self,
        distance_m: float,
        elevation_deg: float = 0.0,
        environment: EnvironmentParams | None = None,
    ) -> BallisticSolution:
        """完整弹道解算。

        使用 RK4 积分弹丸三维运动方程, 计算到达指定斜距
        所需的飞行时间、下坠角、风偏角和着靶速度。
        """
        if distance_m <= 0.0:
            return BallisticSolution(distance_m=distance_m)

        env = environment or EnvironmentParams()
        rho = _air_density(env)
        c_sound = _speed_of_sound(env)

        v0 = self._proj.muzzle_velocity_mps
        mass = self._proj.projectile_mass_kg
        bc = max(self._proj.ballistic_coefficient, 0.01)
        drag_model = self._proj.drag_model

        elev_rad = math.radians(elevation_deg)

        # 风分量 (射击坐标系: X=前方, Y=右方, Z=上方)
        wind_rad = math.radians(env.wind_direction_deg)
        wind_x = -env.wind_speed_mps * math.cos(wind_rad)  # 纵风 (逆风为负)
        wind_y = env.wind_speed_mps * math.sin(wind_rad)  # 横风

        # 初始状态: [x, y, z, vx, vy, vz]
        # x = 前方, y = 右方, z = 上方
        vx0 = v0 * math.cos(elev_rad)
        vz0 = v0 * math.sin(elev_rad)
        state = np.array([0.0, 0.0, 0.0, vx0, 0.0, vz0], dtype=np.float64)

        g = 9.80665  # 标准重力加速度

        def derivatives(s: np.ndarray) -> np.ndarray:
            """计算状态导数 [dx,dy,dz,dvx,dvy,dvz]"""
            _, _, _, svx, svy, svz = s

            # 相对风速
            vrx = svx - wind_x
            vry = svy - wind_y
            vrz = svz

            v_rel = math.sqrt(vrx**2 + vry**2 + vrz**2)
            if v_rel < 0.01:
                return np.array([svx, svy, svz, 0.0, 0.0, -g])

            mach = v_rel / c_sound
            cd = _lookup_cd(mach, drag_model)

            # 形状因子: Cd_effective = Cd_ref / BC
            # BC 定义: BC = m / (Cd_ref * A), 所以 Cd_ref * A / m = 1/BC
            # F_drag = -0.5 * rho * v² * (Cd/BC_norm) * A_ref
            # 标准化: 阻力加速度 = 0.5 * rho * v² * cd * cross_section / mass / bc_factor
            # 简化: 使用 BC 归一化
            sectional_density = mass / self._cross_section  # kg/m²
            # BC = SD / Cd_form, Cd_form = SD / BC
            i_form = sectional_density / (bc * 703.07)  # 703.07 = lb/in² → kg/m² 换算

            drag_coeff = 0.5 * rho * cd * i_form * self._cross_section / mass
            a_drag = drag_coeff * v_rel

            dvx = -a_drag * vrx
            dvy = -a_drag * vry
            dvz = -a_drag * vrz - g

            return np.array([svx, svy, svz, dvx, dvy, dvz])

        # RK4 积分直到 x >= distance_m
        dt = self._dt
        t = 0.0
        max_steps = int(self._max_range_m / (v0 * dt)) + 10000

        for _ in range(max_steps):
            k1 = derivatives(state)
            k2 = derivatives(state + 0.5 * dt * k1)
            k3 = derivatives(state + 0.5 * dt * k2)
            k4 = derivatives(state + dt * k3)
            state = state + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
            t += dt

            if state[0] >= distance_m:
                break

        x_final, y_final, z_final = state[0], state[1], state[2]
        vx_f, vy_f, vz_f = state[3], state[4], state[5]
        v_impact = math.sqrt(vx_f**2 + vy_f**2 + vz_f**2)

        # 下坠补偿角: 弹丸在 distance_m 处的 z 偏移 → 需抬高多少度
        # drop_angle = atan2(-z_final, x_final)
        drop_deg = math.degrees(math.atan2(-z_final, max(x_final, 0.01)))

        # 风偏补偿角: y 偏移 → 需修正多少度
        windage_deg = math.degrees(math.atan2(-y_final, max(x_final, 0.01)))

        solution = BallisticSolution(
            flight_time_s=t,
            drop_deg=drop_deg,
            windage_deg=windage_deg,
            impact_velocity_mps=v_impact,
            distance_m=distance_m,
        )

        logger.debug(
            "ballistic solve: d=%.1fm, t=%.4fs, drop=%.3f°, windage=%.3f°, v_imp=%.1fm/s",
            distance_m,
            t,
            drop_deg,
            windage_deg,
            v_impact,
        )
        return solution

    def compute_flight_time(
        self,
        distance_m: float,
        environment: EnvironmentParams | None = None,
    ) -> float:
        """快速计算弹丸飞行时间 (s)。"""
        if distance_m <= 0.0:
            return 0.0
        return self.solve(distance_m, environment=environment).flight_time_s
