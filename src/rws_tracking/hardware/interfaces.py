"""
Hardware layer interfaces -- implement these to connect your gimbal hardware.
=============================================================================

To connect your own gimbal (CAN, PWM, direct motor driver, etc.):

    1. Create a class that implements ``GimbalDriver``.
    2. Implement ``set_yaw_pitch_rate`` to send rate commands to your hardware.
    3. Implement ``get_feedback`` to read current yaw/pitch angles and rates.
    4. Inject your driver into ``VisionGimbalPipeline`` via the ``driver`` parameter.

Example::

    class MyCanGimbalDriver:
        def set_yaw_pitch_rate(self, yaw_rate_dps, pitch_rate_dps, timestamp):
            # Send CAN frame to motor controller
            ...

        def get_feedback(self, timestamp):
            # Read encoder / IMU feedback
            return GimbalFeedback(...)

    pipeline = VisionGimbalPipeline(
        ...,
        driver=MyCanGimbalDriver(),
        ...,
    )
"""
from __future__ import annotations

from typing import Protocol

from ..types import GimbalFeedback


class GimbalDriver(Protocol):
    """
    Abstract interface for gimbal hardware.

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

    def set_yaw_pitch_rate(self, yaw_rate_dps: float, pitch_rate_dps: float, timestamp: float) -> None:
        ...

    def get_feedback(self, timestamp: float) -> GimbalFeedback:
        ...
