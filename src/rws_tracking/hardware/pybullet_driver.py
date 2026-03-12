"""
PyBullet physics simulation driver for the RWS 2-DOF gimbal.
=============================================================

Implements GimbalDriver protocol using PyBullet joint velocity control.
The gimbal URDF is loaded, joints are driven by PD controllers that
mimic the real motor response (inertia, friction, limits).

Requires::

    pip install pybullet pybullet_data

Usage::

    from rws_tracking.hardware.pybullet_driver import PyBulletGimbalDriver

    driver = PyBulletGimbalDriver(gui=True)        # opens 3D viewer
    driver = PyBulletGimbalDriver(gui=False)       # headless physics

    # Then pass to pipeline as a normal GimbalDriver:
    pipeline = VisionGimbalPipeline(..., driver=driver)
    driver.close()

Joint mapping
-------------
yaw_joint  (index 0)  — revolute, Z-axis, ±160 deg
pitch_joint (index 1) — revolute, Y-axis, −45…+75 deg
"""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path

from ..types import GimbalFeedback
from .driver import DriverLimits

logger = logging.getLogger(__name__)

# Path to the URDF, relative to this file
# __file__ = src/rws_tracking/hardware/pybullet_driver.py
# 4× parent  → project root (RWS/)
_URDF_PATH = (
    Path(__file__).parent.parent.parent.parent / "hardware" / "gimbal_model" / "rws_gimbal.urdf"
)

# Joint names in the URDF
_YAW_JOINT_NAME = "yaw_joint"
_PITCH_JOINT_NAME = "pitch_joint"


class PyBulletGimbalDriver:
    """
    PyBullet-based 2-DOF gimbal simulation.

    The gimbal URDF is loaded into a PyBullet world.  Each joint is
    controlled via VELOCITY_CONTROL so it faithfully reproduces the
    rate-command interface expected by the RWS PID controller.

    Parameters
    ----------
    gui : bool
        Open a GUI window (``pybullet.GUI``).  Set False for headless CI/SIL.
    urdf_path : str or None
        Override default URDF path.
    limits : DriverLimits or None
        Physical limits for rate clipping.
    gravity : bool
        Enable gravity (no effect on gimbal but useful for ground plane).
    """

    def __init__(
        self,
        gui: bool = True,
        urdf_path: str | None = None,
        limits: DriverLimits | None = None,
        gravity: bool = True,
    ) -> None:
        try:
            import pybullet as p
            import pybullet_data
        except ImportError as exc:
            raise ImportError(
                "PyBullet not installed.  Run: pip install pybullet pybullet_data"
            ) from exc

        self._p = p
        self._limits = limits or DriverLimits()

        # Connect
        connection = p.GUI if gui else p.DIRECT
        self._client = p.connect(connection)
        p.setAdditionalSearchPath(pybullet_data.getDataPath())

        if gravity:
            p.setGravity(0, 0, -9.81)
            p.loadURDF("plane.urdf")

        # Load gimbal
        urdf = urdf_path or str(_URDF_PATH)
        if not os.path.exists(urdf):
            raise FileNotFoundError(f"URDF not found: {urdf}")

        self._robot = p.loadURDF(
            urdf,
            basePosition=[0, 0, 0.05],
            useFixedBase=True,
        )
        logger.info("Loaded gimbal URDF: %s  body_id=%d", urdf, self._robot)

        # Discover joint indices
        self._yaw_idx = -1
        self._pitch_idx = -1
        self._joint_names: dict[int, str] = {}
        n = p.getNumJoints(self._robot)
        for i in range(n):
            info = p.getJointInfo(self._robot, i)
            name = info[1].decode()
            self._joint_names[i] = name
            if name == _YAW_JOINT_NAME:
                self._yaw_idx = i
            elif name == _PITCH_JOINT_NAME:
                self._pitch_idx = i

        if self._yaw_idx < 0 or self._pitch_idx < 0:
            raise RuntimeError(
                f"URDF joint names not found: yaw={self._yaw_idx} "
                f"pitch={self._pitch_idx}.  Expected '{_YAW_JOINT_NAME}' "
                f"and '{_PITCH_JOINT_NAME}' in URDF."
            )
        logger.info(
            "Joints  yaw_idx=%d  pitch_idx=%d",
            self._yaw_idx,
            self._pitch_idx,
        )

        # Enable joint velocity control (disable default position control)
        p.setJointMotorControl2(
            self._robot,
            self._yaw_idx,
            p.VELOCITY_CONTROL,
            force=0,
        )
        p.setJointMotorControl2(
            self._robot,
            self._pitch_idx,
            p.VELOCITY_CONTROL,
            force=0,
        )

        # Physics timestep
        self._dt = 1.0 / 240.0  # PyBullet default
        p.setTimeStep(self._dt)

        self._last_ts: float | None = None
        self._yaw_cmd_rps = 0.0
        self._pitch_cmd_rps = 0.0

        # GUI camera preset
        if gui:
            p.resetDebugVisualizerCamera(
                cameraDistance=0.45,
                cameraYaw=45,
                cameraPitch=-25,
                cameraTargetPosition=[0, 0, 0.08],
            )

    # ------------------------------------------------------------------
    # GimbalDriver Protocol
    # ------------------------------------------------------------------

    def set_yaw_pitch_rate(
        self,
        yaw_rate_dps: float,
        pitch_rate_dps: float,
        timestamp: float,
    ) -> None:
        """Send angular rate commands to both joints (deg/s → rad/s)."""
        p = self._p

        # Clip to physical limits
        max_rps = math.radians(self._limits.max_rate_dps)
        yaw_rps = max(-max_rps, min(max_rps, math.radians(yaw_rate_dps)))
        pitch_rps = max(-max_rps, min(max_rps, math.radians(pitch_rate_dps)))

        # Deadband
        db_rps = math.radians(self._limits.deadband_dps)
        if abs(yaw_rps) < db_rps:
            yaw_rps = 0.0
        if abs(pitch_rps) < db_rps:
            pitch_rps = 0.0

        self._yaw_cmd_rps = yaw_rps
        self._pitch_cmd_rps = pitch_rps

        # Velocity control with torque limit
        max_torque = 5.0
        p.setJointMotorControl2(
            self._robot,
            self._yaw_idx,
            p.VELOCITY_CONTROL,
            targetVelocity=yaw_rps,
            force=max_torque,
        )
        p.setJointMotorControl2(
            self._robot,
            self._pitch_idx,
            p.VELOCITY_CONTROL,
            targetVelocity=pitch_rps,
            force=max_torque,
        )

        # Step simulation to advance time
        if self._last_ts is not None:
            dt = timestamp - self._last_ts
            steps = max(1, int(round(dt / self._dt)))
            for _ in range(min(steps, 10)):  # cap at 10 substeps
                p.stepSimulation()
        self._last_ts = timestamp

    def get_feedback(self, timestamp: float) -> GimbalFeedback:
        """Read current joint state from PyBullet."""
        p = self._p

        yaw_pos, yaw_vel, *_ = p.getJointState(self._robot, self._yaw_idx)
        pitch_pos, pitch_vel, *_ = p.getJointState(self._robot, self._pitch_idx)

        return GimbalFeedback(
            timestamp=timestamp,
            yaw_deg=math.degrees(yaw_pos),
            pitch_deg=math.degrees(pitch_pos),
            yaw_rate_dps=math.degrees(yaw_vel),
            pitch_rate_dps=math.degrees(pitch_vel),
        )

    # ------------------------------------------------------------------
    # Extras
    # ------------------------------------------------------------------

    def reset(self, yaw_deg: float = 0.0, pitch_deg: float = 0.0) -> None:
        """Reset gimbal to a known position (useful between test runs)."""
        p = self._p
        p.resetJointState(self._robot, self._yaw_idx, math.radians(yaw_deg))
        p.resetJointState(self._robot, self._pitch_idx, math.radians(pitch_deg))
        self._last_ts = None

    def close(self) -> None:
        """Disconnect PyBullet."""
        try:
            self._p.disconnect(self._client)
        except Exception:
            pass

    def __del__(self) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"PyBulletGimbalDriver(yaw_idx={self._yaw_idx}, pitch_idx={self._pitch_idx})"
