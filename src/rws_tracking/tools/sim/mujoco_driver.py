"""
MuJoCo Gimbal Driver
=====================

Implements the ``GimbalDriver`` protocol by writing velocity commands
to MuJoCo actuators and reading joint sensors.

This module does NOT own the MuJoCo ``mj.MjModel`` or ``mj.MjData``
-- it receives them from ``MujocoEnv`` to avoid double ownership.

Units
-----
- Pipeline sends degrees/s.
- MuJoCo velocity actuator expects rad/s (with kv scaling).
- Sensors return rad and rad/s.
- All conversions happen here, so the rest of the pipeline stays in degrees.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import mujoco

from ...types import GimbalFeedback


class MujocoGimbalDriver:
    """
    Bridges ``GimbalDriver`` protocol ↔ MuJoCo actuators/sensors.

    Parameters
    ----------
    model : mujoco.MjModel
    data  : mujoco.MjData
    yaw_actuator   : name of the yaw velocity actuator in MJCF.
    pitch_actuator : name of the pitch velocity actuator in MJCF.
    yaw_sign : +1 or -1, corrects sign mismatch between pipeline and MJCF axis.
    pitch_sign : +1 or -1, corrects sign mismatch between pipeline and MJCF axis.
    """

    def __init__(
        self,
        model: "mujoco.MjModel",
        data: "mujoco.MjData",
        yaw_actuator: str = "yaw_motor",
        pitch_actuator: str = "pitch_motor",
        yaw_sign: float = -1.0,
        pitch_sign: float = -1.0,
    ) -> None:
        import mujoco as mj

        self._m = model
        self._d = data

        # Actuator indices
        self._yaw_act_id = mj.mj_name2id(model, mj.mjtObj.mjOBJ_ACTUATOR, yaw_actuator)
        self._pitch_act_id = mj.mj_name2id(model, mj.mjtObj.mjOBJ_ACTUATOR, pitch_actuator)

        self._yaw_sign = yaw_sign
        self._pitch_sign = pitch_sign

        # Sensor indices
        self._yaw_pos_adr = model.sensor_adr[mj.mj_name2id(model, mj.mjtObj.mjOBJ_SENSOR, "yaw_pos")]
        self._pitch_pos_adr = model.sensor_adr[mj.mj_name2id(model, mj.mjtObj.mjOBJ_SENSOR, "pitch_pos")]
        self._yaw_vel_adr = model.sensor_adr[mj.mj_name2id(model, mj.mjtObj.mjOBJ_SENSOR, "yaw_vel")]
        self._pitch_vel_adr = model.sensor_adr[mj.mj_name2id(model, mj.mjtObj.mjOBJ_SENSOR, "pitch_vel")]

    # ------------------------------------------------------------------
    # GimbalDriver protocol
    # ------------------------------------------------------------------

    def set_yaw_pitch_rate(
        self, yaw_rate_dps: float, pitch_rate_dps: float, timestamp: float
    ) -> None:
        """Write velocity command. MuJoCo velocity actuator ctrl is in rad/s.
        Sign correction maps pipeline convention to MJCF joint axis convention."""
        self._d.ctrl[self._yaw_act_id] = self._yaw_sign * math.radians(yaw_rate_dps)
        self._d.ctrl[self._pitch_act_id] = self._pitch_sign * math.radians(pitch_rate_dps)

    def get_feedback(self, timestamp: float) -> GimbalFeedback:
        """Read joint sensors, convert rad → deg with sign correction."""
        return GimbalFeedback(
            timestamp=timestamp,
            yaw_deg=self._yaw_sign * math.degrees(self._d.sensordata[self._yaw_pos_adr]),
            pitch_deg=self._pitch_sign * math.degrees(self._d.sensordata[self._pitch_pos_adr]),
            yaw_rate_dps=self._yaw_sign * math.degrees(self._d.sensordata[self._yaw_vel_adr]),
            pitch_rate_dps=self._pitch_sign * math.degrees(self._d.sensordata[self._pitch_vel_adr]),
        )
