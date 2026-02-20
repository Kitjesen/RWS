"""
Body motion provider interface.
================================

Abstracts the source of base-platform (robot dog) orientation and angular
velocity data.  **数据来源不限定**：可以是 IMU、编码器解算、或二者融合。

- **IMU**：陀螺 + 加速度计解算姿态与角速度（如 BNO055、ICM-42688、Unitree/Spot 机身 IMU）。
- **编码器**：关节编码器 → 运动学解算机身姿态，角速度可由姿态差分或滤波得到。
- **融合**：IMU + 编码器/里程计融合（如 Spot 的 kinematic_state 已含融合结果）。
- 其他：ROS topic、上位机 SDK、录播回放、Mock 等。

实现方只需在 get_body_state(timestamp) 中返回当前 BodyState（姿态 + 角速度），
接口不关心数据来自 IMU 还是编码器。

Example::

    class MyDogSDKMotion:
        def get_body_state(self, timestamp: float) -> BodyState:
            pose = dog_sdk.get_imu()  # 或 get_pose_from_encoders()
            return BodyState(
                timestamp=timestamp,
                roll_deg=pose.roll, pitch_deg=pose.pitch, yaw_deg=pose.yaw,
                roll_rate_dps=pose.gyro_x, pitch_rate_dps=pose.gyro_y,
                yaw_rate_dps=pose.gyro_z,
            )

    pipeline = VisionGimbalPipeline(..., body_provider=MyDogSDKMotion())
"""

from __future__ import annotations

from typing import Protocol

from ..types import BodyState


class BodyMotionProvider(Protocol):
    """
    Abstract interface for body (base platform) motion sensing.

    Methods
    -------
    get_body_state(timestamp)
        Return the current body orientation and angular velocity.
        All angles in degrees, angular rates in degrees per second.
    """

    def get_body_state(self, timestamp: float) -> BodyState: ...
