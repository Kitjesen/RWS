"""安全管理器 — 统一安全检查入口。

职责（单一）：
    组合禁射区管理器和安全联锁, 提供单一入口执行全部安全检查，
    输出统一的 SafetyStatus。

数据流：
    cloud台反馈 + 目标状态 + 操作员输入
        → SafetyManager.evaluate()
            → NoFireZoneManager.check()
            → SafetyInterlock.check()
        → SafetyStatus
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..types import SafetyStatus, SafetyZone
from .interlock import SafetyInterlock, SafetyInterlockConfig
from .no_fire_zone import NoFireZoneManager

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SafetyManagerConfig:
    """安全管理器配置。

    Attributes
    ----------
    interlock : SafetyInterlockConfig
        联锁配置。
    nfz_slow_down_margin_deg : float
        禁射区缓冲带宽度 (°)。
    zones : tuple[SafetyZone, ...]
        预定义禁射区列表。
    """

    interlock: SafetyInterlockConfig = SafetyInterlockConfig()
    nfz_slow_down_margin_deg: float = 5.0
    zones: tuple[SafetyZone, ...] = ()


class SafetyManager:
    """统一安全管理器。

    集成：
    - 禁射区检查 (NoFireZoneManager)
    - 安全联锁检查 (SafetyInterlock)

    用法:
        mgr = SafetyManager(config)
        mgr.set_operator_auth(True)
        mgr.update_system_status(comms_ok=True, sensors_ok=True)

        # 每帧调用
        status = mgr.evaluate(
            yaw_deg=current_yaw,
            pitch_deg=current_pitch,
            target_locked=True,
            lock_duration_s=2.0,
            target_distance_m=50.0,
        )
        if status.fire_authorized:
            # 允许射击
    """

    def __init__(self, config: SafetyManagerConfig = SafetyManagerConfig()) -> None:
        self._cfg = config
        self._nfz = NoFireZoneManager(
            slow_down_margin_deg=config.nfz_slow_down_margin_deg
        )
        self._interlock = SafetyInterlock(config.interlock)

        # 加载预定义禁射区
        for zone in config.zones:
            self._nfz.add_zone(zone)

    # --- 代理接口 ---

    @property
    def nfz_manager(self) -> NoFireZoneManager:
        """访问底层禁射区管理器。"""
        return self._nfz

    @property
    def interlock(self) -> SafetyInterlock:
        """访问底层联锁系统。"""
        return self._interlock

    def set_operator_auth(self, authorized: bool) -> None:
        self._interlock.set_operator_auth(authorized)

    def operator_heartbeat(self) -> None:
        self._interlock.operator_heartbeat()

    def set_emergency_stop(self, active: bool) -> None:
        self._interlock.set_emergency_stop(active)

    def update_system_status(
        self,
        comms_ok: bool = True,
        sensors_ok: bool = True,
    ) -> None:
        self._interlock.update_system_status(comms_ok, sensors_ok)

    def add_no_fire_zone(self, zone: SafetyZone) -> None:
        self._nfz.add_zone(zone)

    def remove_no_fire_zone(self, zone_id: str) -> bool:
        return self._nfz.remove_zone(zone_id)

    # --- 综合评估 ---

    def evaluate(
        self,
        yaw_deg: float,
        pitch_deg: float,
        target_locked: bool = False,
        lock_duration_s: float = 0.0,
        target_distance_m: float = 0.0,
    ) -> SafetyStatus:
        """执行全部安全检查。

        Parameters
        ----------
        yaw_deg, pitch_deg : float
            当前云台指向 (°)。
        target_locked : bool
            目标是否已锁定。
        lock_duration_s : float
            目标已锁定时长 (s)。
        target_distance_m : float
            目标估计距离 (m)。

        Returns
        -------
        SafetyStatus
            综合安全状态。
        """
        # 1. 禁射区检查
        nfz_result = self._nfz.check(yaw_deg, pitch_deg)
        self._interlock.update_nfz_status(not nfz_result.fire_blocked)

        # 2. 更新目标状态
        self._interlock.update_target_status(
            locked=target_locked,
            lock_duration_s=lock_duration_s,
            distance_m=target_distance_m,
        )

        # 3. 综合联锁检查
        interlock_result = self._interlock.check()

        fire_authorized = interlock_result.authorized and not nfz_result.fire_blocked
        blocked_reason = ""
        if not fire_authorized:
            reasons = []
            if nfz_result.fire_blocked:
                reasons.append(f"NFZ:{nfz_result.active_zone_id}")
            reasons.extend(interlock_result.blocked_reasons)
            blocked_reason = "; ".join(reasons)

        return SafetyStatus(
            fire_authorized=fire_authorized,
            blocked_reason=blocked_reason,
            active_zone=nfz_result.active_zone_id,
            operator_override=interlock_result.operator_auth,
            emergency_stop=interlock_result.emergency_stop,
        )

    def get_speed_factor(self, yaw_deg: float, pitch_deg: float) -> float:
        """获取当前指向的速度限制因子。

        用于在接近禁射区时逐渐降速。

        Returns
        -------
        float
            0.0 = 停止, 1.0 = 全速。
        """
        nfz_result = self._nfz.check(yaw_deg, pitch_deg)
        return nfz_result.speed_factor
