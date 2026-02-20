"""安全联锁系统 — 软件/硬件安全检查。

职责（单一）：
    汇集所有安全条件（软件联锁 + 硬件联锁），
    只有全部条件满足时才授权射击。

联锁条件：
    1. 操作员授权    — 操作员主动确认
    2. 系统自检通过  — 通信正常、传感器就绪
    3. 目标确认      — 目标已锁定足够时间
    4. 安全距离      — 目标距离在最小/最大射程内
    5. 非紧急停止    — 未触发紧急停止
    6. 禁射区检查    — 由 NoFireZoneManager 提供
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SafetyInterlockConfig:
    """安全联锁配置。

    Attributes
    ----------
    require_operator_auth : bool
        是否需要操作员手动授权。
    min_lock_time_s : float
        目标锁定最短时间 (s), 低于此时间不允许射击。
    min_engagement_range_m : float
        最小射程 (m), 过近不安全。
    max_engagement_range_m : float
        最大射程 (m), 过远无效。
    system_check_interval_s : float
        系统自检间隔 (s)。
    heartbeat_timeout_s : float
        操作员心跳超时 (s), 超时自动锁定。
    """

    require_operator_auth: bool = True
    min_lock_time_s: float = 1.0
    min_engagement_range_m: float = 5.0
    max_engagement_range_m: float = 500.0
    system_check_interval_s: float = 1.0
    heartbeat_timeout_s: float = 5.0


class SafetyInterlock:
    """安全联锁系统。

    所有条件以 AND 逻辑组合: 任一条件不满足即阻止射击。
    每个条件独立跟踪状态, 方便诊断。

    用法:
        interlock = SafetyInterlock(config)
        interlock.set_operator_auth(True)
        interlock.update_system_status(comms_ok=True, sensors_ok=True)
        interlock.update_target_status(locked=True, lock_duration_s=2.0, distance_m=50)
        result = interlock.check()
        if result.authorized:
            # 允许射击
    """

    def __init__(self, config: SafetyInterlockConfig = SafetyInterlockConfig()) -> None:
        self._cfg = config

        # 状态
        self._operator_auth: bool = False
        self._emergency_stop: bool = False
        self._comms_ok: bool = False
        self._sensors_ok: bool = False
        self._target_locked: bool = False
        self._lock_duration_s: float = 0.0
        self._target_distance_m: float = 0.0
        self._nfz_clear: bool = True
        self._last_heartbeat: float = time.monotonic()

    # --- 状态更新接口 ---

    def set_operator_auth(self, authorized: bool) -> None:
        """设置操作员授权状态。"""
        if authorized != self._operator_auth:
            logger.info("interlock: operator auth = %s", authorized)
        self._operator_auth = authorized
        if authorized:
            self._last_heartbeat = time.monotonic()

    def operator_heartbeat(self) -> None:
        """操作员心跳, 刷新超时计时器。"""
        self._last_heartbeat = time.monotonic()

    def set_emergency_stop(self, active: bool) -> None:
        """触发/解除紧急停止。"""
        if active != self._emergency_stop:
            logger.warning("interlock: EMERGENCY STOP = %s", active)
        self._emergency_stop = active

    def update_system_status(
        self,
        comms_ok: bool = True,
        sensors_ok: bool = True,
    ) -> None:
        """更新系统自检状态。"""
        self._comms_ok = comms_ok
        self._sensors_ok = sensors_ok

    def update_target_status(
        self,
        locked: bool = False,
        lock_duration_s: float = 0.0,
        distance_m: float = 0.0,
    ) -> None:
        """更新目标锁定状态。"""
        self._target_locked = locked
        self._lock_duration_s = lock_duration_s
        self._target_distance_m = distance_m

    def update_nfz_status(self, clear: bool) -> None:
        """更新禁射区检查结果。"""
        self._nfz_clear = clear

    # --- 综合检查 ---

    def check(self) -> InterlockResult:
        """执行全部联锁检查, 返回综合结果。"""
        reasons: list[str] = []

        # 1. 紧急停止
        if self._emergency_stop:
            reasons.append("EMERGENCY_STOP")

        # 2. 操作员授权
        if self._cfg.require_operator_auth and not self._operator_auth:
            reasons.append("NO_OPERATOR_AUTH")

        # 3. 操作员心跳
        if self._cfg.require_operator_auth:
            elapsed = time.monotonic() - self._last_heartbeat
            if elapsed > self._cfg.heartbeat_timeout_s:
                reasons.append(f"HEARTBEAT_TIMEOUT ({elapsed:.1f}s)")

        # 4. 系统自检
        if not self._comms_ok:
            reasons.append("COMMS_FAILURE")
        if not self._sensors_ok:
            reasons.append("SENSOR_FAILURE")

        # 5. 目标锁定
        if not self._target_locked:
            reasons.append("TARGET_NOT_LOCKED")
        elif self._lock_duration_s < self._cfg.min_lock_time_s:
            reasons.append(
                f"LOCK_TOO_SHORT ({self._lock_duration_s:.2f}s < {self._cfg.min_lock_time_s}s)"
            )

        # 6. 射程检查
        if self._target_distance_m > 0:
            if self._target_distance_m < self._cfg.min_engagement_range_m:
                reasons.append(
                    f"TOO_CLOSE ({self._target_distance_m:.1f}m < {self._cfg.min_engagement_range_m}m)"
                )
            if self._target_distance_m > self._cfg.max_engagement_range_m:
                reasons.append(
                    f"TOO_FAR ({self._target_distance_m:.1f}m > {self._cfg.max_engagement_range_m}m)"
                )

        # 7. 禁射区
        if not self._nfz_clear:
            reasons.append("IN_NO_FIRE_ZONE")

        authorized = len(reasons) == 0

        if not authorized:
            logger.debug("interlock BLOCKED: %s", ", ".join(reasons))

        return InterlockResult(
            authorized=authorized,
            blocked_reasons=reasons,
            emergency_stop=self._emergency_stop,
            operator_auth=self._operator_auth,
        )


class InterlockResult:
    """联锁检查结果。"""

    __slots__ = ("authorized", "blocked_reasons", "emergency_stop", "operator_auth")

    def __init__(
        self,
        authorized: bool = False,
        blocked_reasons: list[str] | None = None,
        emergency_stop: bool = False,
        operator_auth: bool = False,
    ) -> None:
        self.authorized = authorized
        self.blocked_reasons = blocked_reasons or []
        self.emergency_stop = emergency_stop
        self.operator_auth = operator_auth

    @property
    def reason_string(self) -> str:
        """所有阻止原因的拼接字符串。"""
        return "; ".join(self.blocked_reasons) if self.blocked_reasons else "CLEAR"
