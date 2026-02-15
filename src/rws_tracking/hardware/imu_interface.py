"""
Body motion provider interface.
================================

Abstracts the source of base-platform (robot dog) orientation and angular
velocity data.  Implementations can read from:

- Serial/CAN IMU chip (BNO055, ICM-42688, etc.)
- Robot dog SDK / API
- ROS topic bridge
- Recorded data replay
- Mock for testing

Example::

    class MyDogSDKMotion:
        def get_body_state(self, timestamp: float) -> BodyState:
            pose = dog_sdk.get_imu()
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
