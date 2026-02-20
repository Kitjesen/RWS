"""
Hardware layer interfaces -- implement these to connect your gimbal hardware.
=============================================================================

双轴云台 = 两个电机，控制与通信建议分开：
    - 实现单轴协议 ``GimbalAxisDriver``（每个轴独立串口/CAN/总线），再使用
      ``CompositeGimbalDriver(yaw_axis, pitch_axis)`` 组合成 ``GimbalDriver`` 注入 pipeline。
    - 或直接实现 ``GimbalDriver``，在内部对 yaw/pitch 两路分别发指令、分别读反馈。

To connect your own gimbal (CAN, PWM, direct motor driver, etc.):

    1. Option A — 两轴通信分开：实现两个 ``GimbalAxisDriver``（yaw 轴、pitch 轴各一个），
       用 ``CompositeGimbalDriver(yaw_axis, pitch_axis)`` 组合后注入 pipeline。
    2. Option B：直接实现 ``GimbalDriver``（set_yaw_pitch_rate + get_feedback）。
    3. 将 driver 注入 ``VisionGimbalPipeline`` 的 ``driver`` 参数。

Example (两轴分开)::

    yaw_axis = SerialAxisDriver(port="COM1", ...)   # 方位轴单独通信
    pitch_axis = SerialAxisDriver(port="COM2", ...) # 俯仰轴单独通信
    driver = CompositeGimbalDriver(yaw_axis=yaw_axis, pitch_axis=pitch_axis)
    pipeline = VisionGimbalPipeline(..., driver=driver, ...)
"""

from __future__ import annotations

from typing import Protocol

from ..types import AxisFeedback, GimbalFeedback


class GimbalAxisDriver(Protocol):
    """
    单轴云台电机抽象（方位轴或俯仰轴二选一）。

    双轴云台可拆成两个 GimbalAxisDriver，各自独立通信（如两条串口、两路 CAN），
    再通过 CompositeGimbalDriver 组合成 GimbalDriver。

    Methods
    -------
    set_rate_dps(rate_dps, timestamp)
        下发该轴角速度指令（度/秒）。
    get_feedback(timestamp)
        读该轴当前角度与角速度。
    """

    def set_rate_dps(self, rate_dps: float, timestamp: float) -> None: ...

    def get_feedback(self, timestamp: float) -> AxisFeedback: ...


class GimbalDriver(Protocol):
    """
    云台硬件抽象（双轴一起的接口，供 pipeline 使用）。

    Methods
    -------
    set_yaw_pitch_rate(yaw_rate_dps, pitch_rate_dps, timestamp)
        Send angular rate command to the gimbal.
        Units: degrees per second.
        Positive yaw = rotate right.  Positive pitch = tilt up.

    get_feedback(timestamp)
        Read current gimbal state.
        Returns GimbalFeedback with current angles and angular rates.
    """

    def set_yaw_pitch_rate(
        self, yaw_rate_dps: float, pitch_rate_dps: float, timestamp: float
    ) -> None: ...

    def get_feedback(self, timestamp: float) -> GimbalFeedback: ...


class CompositeGimbalDriver:
    """
    由两个单轴驱动组合成的双轴 GimbalDriver，两轴控制与通信完全分开。

    yaw_axis / pitch_axis 各自独立（例如两条串口、两路 CAN），
    set_yaw_pitch_rate 内部分别下发两轴，get_feedback 分别读取再合并为 GimbalFeedback。
    """

    def __init__(
        self,
        yaw_axis: GimbalAxisDriver,
        pitch_axis: GimbalAxisDriver,
    ) -> None:
        self._yaw_axis = yaw_axis
        self._pitch_axis = pitch_axis

    def set_yaw_pitch_rate(
        self, yaw_rate_dps: float, pitch_rate_dps: float, timestamp: float
    ) -> None:
        self._yaw_axis.set_rate_dps(yaw_rate_dps, timestamp)
        self._pitch_axis.set_rate_dps(pitch_rate_dps, timestamp)

    def get_feedback(self, timestamp: float) -> GimbalFeedback:
        yaw_fb = self._yaw_axis.get_feedback(timestamp)
        pitch_fb = self._pitch_axis.get_feedback(timestamp)
        return GimbalFeedback(
            timestamp=timestamp,
            yaw_deg=yaw_fb.angle_deg,
            pitch_deg=pitch_fb.angle_deg,
            yaw_rate_dps=yaw_fb.rate_dps,
            pitch_rate_dps=pitch_fb.rate_dps,
        )
