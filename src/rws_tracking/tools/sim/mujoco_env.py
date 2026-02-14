"""
MuJoCo Simulation Environment
===============================

Owns the MuJoCo model/data lifecycle.  Provides:
  - Physics stepping
  - Target motion control (programmatic waypoints or patterns)
  - Composition of MujocoGimbalDriver + MujocoCameraRenderer
  - Optional base (robot dog body) sinusoidal disturbance

This is the single entry point for creating a MuJoCo SIL session.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from .mujoco_camera import MujocoCameraRenderer
from .mujoco_driver import MujocoGimbalDriver

# Default MJCF paths (relative to this file)
_DEFAULT_XML = Path(__file__).parent / "assets" / "gimbal_2dof.xml"
_MOVING_BASE_XML = Path(__file__).parent / "assets" / "gimbal_2dof_moving_base.xml"


@dataclass
class BaseDisturbance:
    """
    Sinusoidal base (robot dog body) oscillation parameters.

    When provided to :class:`MujocoEnv`, the base joints are driven with
    sinusoidal position commands that simulate walking gait oscillation.

    Attributes
    ----------
    roll_amplitude_deg, pitch_amplitude_deg, yaw_amplitude_deg : float
        Oscillation amplitude for each axis (degrees).
    roll_freq_hz, pitch_freq_hz, yaw_freq_hz : float
        Oscillation frequency for each axis (Hz).
    """
    roll_amplitude_deg: float = 3.0
    roll_freq_hz: float = 2.0
    pitch_amplitude_deg: float = 5.0
    pitch_freq_hz: float = 2.0
    yaw_amplitude_deg: float = 2.0
    yaw_freq_hz: float = 1.0


@dataclass
class TargetMotion:
    """
    Describes how the target moves during simulation.

    Patterns
    --------
    - ``"static"``     : stays at ``start_pos``.
    - ``"linear"``     : moves from ``start_pos`` at constant ``velocity_mps``.
    - ``"circle"``     : orbits around ``center`` at ``radius_m`` with ``omega_dps``.
    - ``"waypoints"``  : moves through ``waypoints`` list sequentially.
    """
    pattern: str = "static"
    start_pos: Tuple[float, float, float] = (5.0, 0.0, 1.5)
    velocity_mps: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    # circle params
    center: Tuple[float, float, float] = (5.0, 0.0, 1.5)
    radius_m: float = 2.0
    omega_dps: float = 30.0
    # waypoint params
    waypoints: List[Tuple[float, float, float]] = field(default_factory=list)
    waypoint_speed_mps: float = 1.0


class MujocoEnv:
    """
    Full MuJoCo simulation environment for RWS SIL testing.

    Usage::

        env = MujocoEnv()
        driver = env.driver       # → plug into VisionGimbalPipeline
        camera = env.camera       # → render frames for YOLO

        for _ in range(1000):
            env.step()                       # advance physics
            frame = camera.render()          # get camera image
            pipeline.step(frame, env.time)   # run tracking pipeline
    """

    def __init__(
        self,
        xml_path: Optional[str] = None,
        target_motion: Optional[TargetMotion] = None,
        render_width: int = 1280,
        render_height: int = 720,
        base_disturbance: Optional[BaseDisturbance] = None,
    ) -> None:
        import mujoco as mj

        # Select XML: use moving-base variant when disturbance is requested
        if xml_path is not None:
            xml = xml_path
        elif base_disturbance is not None:
            xml = str(_MOVING_BASE_XML)
        else:
            xml = str(_DEFAULT_XML)

        self._m = mj.MjModel.from_xml_path(xml)
        self._d = mj.MjData(self._m)

        self._driver = MujocoGimbalDriver(self._m, self._d)
        self._camera = MujocoCameraRenderer(
            self._m, self._d,
            width=render_width, height=render_height,
        )

        self._target_motion = target_motion or TargetMotion()
        self._target_body_id = mj.mj_name2id(self._m, mj.mjtObj.mjOBJ_BODY, "target")

        # Target joint indices (slide joints for x, y, z)
        self._target_jnt_ids = [
            mj.mj_name2id(self._m, mj.mjtObj.mjOBJ_JOINT, f"target_{ax}")
            for ax in ("x", "y", "z")
        ]
        self._waypoint_idx = 0

        # Base disturbance (moving platform simulation)
        self._base_dist = base_disturbance
        if self._base_dist is not None:
            self._base_roll_act = mj.mj_name2id(
                self._m, mj.mjtObj.mjOBJ_ACTUATOR, "base_roll_motor"
            )
            self._base_pitch_act = mj.mj_name2id(
                self._m, mj.mjtObj.mjOBJ_ACTUATOR, "base_pitch_motor"
            )
            self._base_yaw_act = mj.mj_name2id(
                self._m, mj.mjtObj.mjOBJ_ACTUATOR, "base_yaw_motor"
            )
            # Base sensors for reading actual state
            self._base_roll_pos_adr = self._m.sensor_adr[
                mj.mj_name2id(self._m, mj.mjtObj.mjOBJ_SENSOR, "base_roll_pos")
            ]
            self._base_pitch_pos_adr = self._m.sensor_adr[
                mj.mj_name2id(self._m, mj.mjtObj.mjOBJ_SENSOR, "base_pitch_pos")
            ]
            self._base_yaw_pos_adr = self._m.sensor_adr[
                mj.mj_name2id(self._m, mj.mjtObj.mjOBJ_SENSOR, "base_yaw_pos")
            ]
            self._base_roll_vel_adr = self._m.sensor_adr[
                mj.mj_name2id(self._m, mj.mjtObj.mjOBJ_SENSOR, "base_roll_vel")
            ]
            self._base_pitch_vel_adr = self._m.sensor_adr[
                mj.mj_name2id(self._m, mj.mjtObj.mjOBJ_SENSOR, "base_pitch_vel")
            ]
            self._base_yaw_vel_adr = self._m.sensor_adr[
                mj.mj_name2id(self._m, mj.mjtObj.mjOBJ_SENSOR, "base_yaw_vel")
            ]

        # Set initial target position
        self._set_target_position(*self._target_motion.start_pos)

        # Step once to initialize
        mj.mj_forward(self._m, self._d)

    @property
    def driver(self) -> MujocoGimbalDriver:
        """GimbalDriver interface for the pipeline."""
        return self._driver

    @property
    def camera(self) -> MujocoCameraRenderer:
        """Camera renderer for getting frames."""
        return self._camera

    @property
    def time(self) -> float:
        """Current simulation time in seconds."""
        return self._d.time

    @property
    def timestep(self) -> float:
        """Physics timestep in seconds."""
        return self._m.opt.timestep

    @property
    def model(self):
        return self._m

    @property
    def data(self):
        return self._d

    @property
    def has_base_disturbance(self) -> bool:
        """True when the environment is configured with a moving base."""
        return self._base_dist is not None

    def get_body_state(self):
        """Read the actual body (base platform) state from MuJoCo sensors.

        Returns
        -------
        BodyState
            Current base orientation and angular velocity, or a zero state
            if no base disturbance is configured.
        """
        from ...types import BodyState

        if self._base_dist is None:
            return BodyState(timestamp=self.time)

        return BodyState(
            timestamp=self.time,
            roll_deg=math.degrees(self._d.sensordata[self._base_roll_pos_adr]),
            pitch_deg=math.degrees(self._d.sensordata[self._base_pitch_pos_adr]),
            yaw_deg=math.degrees(self._d.sensordata[self._base_yaw_pos_adr]),
            roll_rate_dps=math.degrees(self._d.sensordata[self._base_roll_vel_adr]),
            pitch_rate_dps=math.degrees(self._d.sensordata[self._base_pitch_vel_adr]),
            yaw_rate_dps=math.degrees(self._d.sensordata[self._base_yaw_vel_adr]),
        )

    def step(self, n_steps: int = 1) -> None:
        """Advance physics by n_steps and update target position."""
        import mujoco as mj

        for _ in range(n_steps):
            self._update_target_motion()
            self._apply_base_disturbance()
            mj.mj_step(self._m, self._d)

    def step_seconds(self, dt: float) -> None:
        """Advance physics by approximately ``dt`` seconds."""
        n = max(1, int(round(dt / self.timestep)))
        self.step(n)

    def get_target_position(self) -> Tuple[float, float, float]:
        """Get current target position in world frame."""
        pos = self._d.body(self._target_body_id).xpos
        return float(pos[0]), float(pos[1]), float(pos[2])

    def reset(self) -> None:
        """Reset simulation to initial state."""
        import mujoco as mj

        mj.mj_resetData(self._m, self._d)
        self._set_target_position(*self._target_motion.start_pos)
        self._waypoint_idx = 0
        mj.mj_forward(self._m, self._d)

    def close(self) -> None:
        """Release resources."""
        self._camera.close()

    # ------------------------------------------------------------------
    # Target motion
    # ------------------------------------------------------------------

    def _set_target_position(self, x: float, y: float, z: float) -> None:
        """Directly set target position via joint qpos."""
        for i, val in enumerate((x, y, z)):
            jnt_id = self._target_jnt_ids[i]
            qpos_adr = self._m.jnt_qposadr[jnt_id]
            self._d.qpos[qpos_adr] = val

    def _update_target_motion(self) -> None:
        """Update target position based on motion pattern."""
        m = self._target_motion
        t = self.time

        if m.pattern == "static":
            # Re-apply position every step to counteract gravity
            self._set_target_position(*m.start_pos)
            return

        elif m.pattern == "linear":
            x = m.start_pos[0] + m.velocity_mps[0] * t
            y = m.start_pos[1] + m.velocity_mps[1] * t
            z = m.start_pos[2] + m.velocity_mps[2] * t
            self._set_target_position(x, y, z)

        elif m.pattern == "circle":
            angle = math.radians(m.omega_dps * t)
            x = m.center[0] + m.radius_m * math.cos(angle)
            y = m.center[1] + m.radius_m * math.sin(angle)
            z = m.center[2]
            self._set_target_position(x, y, z)

        elif m.pattern == "waypoints" and len(m.waypoints) > 0:
            self._move_toward_waypoint(m)

    def _move_toward_waypoint(self, m: TargetMotion) -> None:
        """Move target toward current waypoint at fixed speed."""
        if self._waypoint_idx >= len(m.waypoints):
            self._waypoint_idx = 0  # loop

        target_wp = np.array(m.waypoints[self._waypoint_idx])
        cur_pos = np.array(self.get_target_position())
        diff = target_wp - cur_pos
        dist = np.linalg.norm(diff)

        if dist < 0.1:
            self._waypoint_idx = (self._waypoint_idx + 1) % len(m.waypoints)
            return

        direction = diff / dist
        step_dist = m.waypoint_speed_mps * self.timestep
        new_pos = cur_pos + direction * min(step_dist, dist)
        self._set_target_position(float(new_pos[0]), float(new_pos[1]), float(new_pos[2]))

    # ------------------------------------------------------------------
    # Base (robot dog body) disturbance
    # ------------------------------------------------------------------

    def _apply_base_disturbance(self) -> None:
        """Apply sinusoidal position commands to the base joints.

        The position actuators drive the base to follow a gait-like
        oscillation, which in turn physically moves the gimbal+camera,
        causing the tracking error that the feedforward should compensate.
        """
        if self._base_dist is None:
            return

        t = self.time
        bd = self._base_dist
        TWO_PI = 2.0 * math.pi

        # Compute desired angles in degrees
        roll_deg = bd.roll_amplitude_deg * math.sin(TWO_PI * bd.roll_freq_hz * t)
        pitch_deg = bd.pitch_amplitude_deg * math.sin(TWO_PI * bd.pitch_freq_hz * t)
        yaw_deg = bd.yaw_amplitude_deg * math.sin(TWO_PI * bd.yaw_freq_hz * t)

        # MuJoCo position actuator ctrl expects radians (hinge joints are
        # always in radians at runtime, regardless of <compiler angle="degree"/>)
        self._d.ctrl[self._base_roll_act] = math.radians(roll_deg)
        self._d.ctrl[self._base_pitch_act] = math.radians(pitch_deg)
        self._d.ctrl[self._base_yaw_act] = math.radians(yaw_deg)
