"""禁射区 (No-Fire Zone) 管理。

职责（单一）：
    管理多个禁射区域定义，判断给定云台指向是否处于禁射区内，
    提供最近禁射区边界距离用于降速控制。

禁射区类型：
    - "no_fire"  : 绝对禁止射击, 云台可进入但不允许开火
    - "caution"  : 警戒区, 降低云台速率并发出警告

坐标系：
    所有角度以云台 yaw/pitch 坐标系表示 (°)。
"""

from __future__ import annotations

import logging
import math

from ..types import SafetyZone

logger = logging.getLogger(__name__)


class NoFireZoneManager:
    """禁射区管理器。

    支持：
    - 动态增删禁射区
    - 判断是否在禁射区内
    - 返回最近禁射区及到边界的角距
    - 降速因子计算（靠近禁射区时逐渐降速）

    用法:
        nfz = NoFireZoneManager()
        nfz.add_zone(SafetyZone(zone_id="friendly", center_yaw_deg=30, ...))
        status = nfz.check(current_yaw_deg=35, current_pitch_deg=0)
    """

    def __init__(self, slow_down_margin_deg: float = 5.0) -> None:
        """
        Parameters
        ----------
        slow_down_margin_deg : float
            禁射区外缘降速缓冲带宽度 (°)。
            进入缓冲带后线性降速至边界处为 0。
        """
        self._zones: dict[str, SafetyZone] = {}
        self._margin = slow_down_margin_deg

    # --- 区域管理 ---

    def add_zone(self, zone: SafetyZone) -> None:
        """添加或更新禁射区。"""
        self._zones[zone.zone_id] = zone
        logger.info(
            "NFZ added: id=%s type=%s center=(%.1f, %.1f) r=%.1f°",
            zone.zone_id, zone.zone_type,
            zone.center_yaw_deg, zone.center_pitch_deg, zone.radius_deg,
        )

    def remove_zone(self, zone_id: str) -> bool:
        """移除禁射区, 返回是否存在。"""
        if zone_id in self._zones:
            del self._zones[zone_id]
            logger.info("NFZ removed: id=%s", zone_id)
            return True
        return False

    def clear(self) -> None:
        """清除所有禁射区。"""
        self._zones.clear()

    @property
    def zones(self) -> list[SafetyZone]:
        """当前所有禁射区（只读）。"""
        return list(self._zones.values())

    # --- 检查 ---

    def check(
        self,
        yaw_deg: float,
        pitch_deg: float,
    ) -> NFZCheckResult:
        """检查给定指向是否在禁射区内。

        Parameters
        ----------
        yaw_deg, pitch_deg : float
            当前云台指向 (°)。

        Returns
        -------
        NFZCheckResult
            包含是否禁止射击、所在区域、到最近边界距离等信息。
        """
        closest_zone: SafetyZone | None = None
        closest_dist = float("inf")
        in_no_fire = False
        in_caution = False
        active_zone_id = ""

        for zone in self._zones.values():
            angular_dist = self._angular_distance(
                yaw_deg, pitch_deg,
                zone.center_yaw_deg, zone.center_pitch_deg,
            )
            dist_to_boundary = angular_dist - zone.radius_deg

            if dist_to_boundary < closest_dist:
                closest_dist = dist_to_boundary
                closest_zone = zone

            if angular_dist < zone.radius_deg:
                active_zone_id = zone.zone_id
                if zone.zone_type == "no_fire":
                    in_no_fire = True
                elif zone.zone_type == "caution":
                    in_caution = True

        # 计算降速因子
        speed_factor = 1.0
        if in_no_fire:
            speed_factor = 0.0  # 禁射区内可以移动但不能开火
        elif closest_dist < self._margin and closest_dist > 0:
            speed_factor = closest_dist / self._margin
        elif closest_dist <= 0:
            speed_factor = 0.3 if in_caution else 0.0

        return NFZCheckResult(
            fire_blocked=in_no_fire,
            in_caution_zone=in_caution,
            active_zone_id=active_zone_id,
            distance_to_boundary_deg=closest_dist,
            speed_factor=max(min(speed_factor, 1.0), 0.0),
            closest_zone=closest_zone,
        )

    @staticmethod
    def _angular_distance(
        yaw1: float, pitch1: float,
        yaw2: float, pitch2: float,
    ) -> float:
        """两个指向之间的角距 (°)。"""
        dy = yaw1 - yaw2
        dp = pitch1 - pitch2
        return math.sqrt(dy**2 + dp**2)


class NFZCheckResult:
    """禁射区检查结果。"""

    __slots__ = (
        "fire_blocked",
        "in_caution_zone",
        "active_zone_id",
        "distance_to_boundary_deg",
        "speed_factor",
        "closest_zone",
    )

    def __init__(
        self,
        fire_blocked: bool = False,
        in_caution_zone: bool = False,
        active_zone_id: str = "",
        distance_to_boundary_deg: float = float("inf"),
        speed_factor: float = 1.0,
        closest_zone: SafetyZone | None = None,
    ) -> None:
        self.fire_blocked = fire_blocked
        self.in_caution_zone = in_caution_zone
        self.active_zone_id = active_zone_id
        self.distance_to_boundary_deg = distance_to_boundary_deg
        self.speed_factor = speed_factor
        self.closest_zone = closest_zone
