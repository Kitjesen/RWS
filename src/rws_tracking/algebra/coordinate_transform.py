"""
Coordinate Transform Module
============================

Responsibility (single):
    pixel (u,v) -> camera ray -> gimbal-frame angular error (yaw_deg, pitch_deg)

Coordinate chain::

    pixel (u, v)
      |  undistort (optional, if distortion coefficients provided)
      v
    normalized camera coords (xn, yn)  = ((u - cx) / fx,  (v - cy) / fy)
      |  camera-to-gimbal rotation (mount extrinsics)
      v
    gimbal-frame direction vector (Xg, Yg, Zg)
      |  extract angular error
      v
    (yaw_error_deg, pitch_error_deg) relative to gimbal boresight

Convention
----------
- Camera frame: X-right, Y-down, Z-forward (OpenCV standard).
- Gimbal frame: X-right, Y-down, Z-forward after applying mount rotation.
- Yaw:  positive = target is to the RIGHT of boresight.
- Pitch: positive = target is ABOVE boresight (note sign flip from pixel Y-down).

Units
-----
- Pixel coordinates: float, origin top-left.
- Angles: degrees.
- Distortion coefficients: OpenCV 5-param model [k1, k2, p1, p2, k3].
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ..types import BodyState, GimbalFeedback


@dataclass(frozen=True)
class DistortionCoeffs:
    """OpenCV 5-parameter distortion model."""
    k1: float = 0.0
    k2: float = 0.0
    p1: float = 0.0
    p2: float = 0.0
    k3: float = 0.0

    def as_array(self) -> np.ndarray:
        return np.array([self.k1, self.k2, self.p1, self.p2, self.k3], dtype=np.float64)

    @property
    def is_zero(self) -> bool:
        return all(abs(v) < 1e-12 for v in (self.k1, self.k2, self.p1, self.p2, self.k3))


@dataclass(frozen=True)
class MountExtrinsics:
    """
    Rotation from camera frame to gimbal frame, expressed as small-angle
    roll/pitch/yaw offsets (degrees).
    """
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0

    def rotation_matrix(self) -> np.ndarray:
        """Camera-to-gimbal rotation matrix (3×3).

        Uses **camera-frame Euler convention** Ry(yaw) @ Rx(pitch) @ Rz(roll)
        because both camera and gimbal frames are Z-forward (OpenCV):

        * Yaw   = rotation around Y (down)    → turns boresight left / right
        * Pitch = rotation around X (right)   → tilts boresight up / down
        * Roll  = rotation around Z (forward) → rolls image plane
        """
        return _euler_camera_to_rotation(
            self.yaw_deg, self.pitch_deg, self.roll_deg,
        )


@dataclass
class CameraModel:
    """
    Pinhole camera model with optional distortion.

    Attributes
    ----------
    width, height : image resolution in pixels.
    fx, fy : focal lengths in pixels.
    cx, cy : principal point in pixels.
    distortion : 5-param distortion coefficients (None = no distortion).
    """
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    distortion: Optional[DistortionCoeffs] = None

    def camera_matrix(self) -> np.ndarray:
        return np.array([
            [self.fx, 0.0, self.cx],
            [0.0, self.fy, self.cy],
            [0.0, 0.0, 1.0],
        ], dtype=np.float64)


class PixelToGimbalTransform:
    """
    Stateless transform: pixel (u, v) -> gimbal angular error (yaw_deg, pitch_deg).

    This is the **single** place in the codebase that owns the coordinate
    conversion math.  Controller and pipeline only call this interface.
    """

    def __init__(
        self,
        camera: CameraModel,
        mount: MountExtrinsics = MountExtrinsics(),
    ) -> None:
        self._cam = camera
        self._K = camera.camera_matrix()
        self._K_inv = np.linalg.inv(self._K)
        self._dist = camera.distortion
        self._R_cam2gimbal = mount.rotation_matrix()
        self._use_undistort = self._dist is not None and not self._dist.is_zero
        if self._use_undistort:
            import cv2  # type: ignore[import-untyped]
            self._cv2 = cv2

    @property
    def camera(self) -> CameraModel:
        """Expose camera model for external use (e.g. velocity conversion)."""
        return self._cam

    def pixel_to_angle_error(self, u: float, v: float) -> Tuple[float, float]:
        """
        Convert pixel location to gimbal angular error.

        Returns (yaw_error_deg, pitch_error_deg).
        Positive yaw = target right of boresight.
        Positive pitch = target above boresight.
        """
        xn, yn = self._undistort_and_normalize(u, v)
        cam_dir = np.array([xn, yn, 1.0], dtype=np.float64)
        gimbal_dir = self._R_cam2gimbal @ cam_dir
        yaw_rad = math.atan2(gimbal_dir[0], gimbal_dir[2])
        pitch_rad = -math.atan2(gimbal_dir[1], gimbal_dir[2])
        return math.degrees(yaw_rad), math.degrees(pitch_rad)

    def bbox_center_to_angle_error(
        self, x: float, y: float, w: float, h: float
    ) -> Tuple[float, float]:
        """Convenience: convert bounding box (x, y, w, h) to angular error."""
        cu = x + w * 0.5
        cv = y + h * 0.5
        return self.pixel_to_angle_error(cu, cv)

    def _undistort_and_normalize(self, u: float, v: float) -> Tuple[float, float]:
        if not self._use_undistort:
            xn = (u - self._cam.cx) / self._cam.fx
            yn = (v - self._cam.cy) / self._cam.fy
            return xn, yn

        pts = np.array([[[u, v]]], dtype=np.float64)
        undistorted = self._cv2.undistortPoints(
            pts, self._K, self._dist.as_array(), P=None,  # type: ignore[union-attr]
        )
        return float(undistorted[0, 0, 0]), float(undistorted[0, 0, 1])


# ---------------------------------------------------------------------------
# Helper: Euler rotation matrices
# ---------------------------------------------------------------------------

def _euler_camera_to_rotation(
    yaw_deg: float, pitch_deg: float, roll_deg: float,
) -> np.ndarray:
    """Rotation matrix for Z-forward frames: Ry(yaw) @ Rx(pitch) @ Rz(roll).

    Applicable to **camera**, **gimbal**, and any other Z-forward frame
    (OpenCV convention: X-right, Y-down, Z-forward).

    Axis-to-motion mapping
    ----------------------
    * Yaw   → Ry — rotation around Y (down):    positive = boresight turns RIGHT
    * Pitch → Rx — rotation around X (right):   positive = boresight tilts UP
    * Roll  → Rz — rotation around Z (forward): positive = CW image rotation

    Parameters
    ----------
    yaw_deg, pitch_deg, roll_deg : float
        Angles in degrees.

    Returns
    -------
    np.ndarray
        3×3 rotation matrix.
    """
    y = math.radians(yaw_deg)
    p = math.radians(pitch_deg)
    r = math.radians(roll_deg)

    cy, sy = math.cos(y), math.sin(y)
    cp, sp = math.cos(p), math.sin(p)
    cr, sr = math.cos(r), math.sin(r)

    # Ry(y) @ Rx(p) @ Rz(r)
    return np.array([
        [cy * cr + sy * sp * sr, -cy * sr + sy * sp * cr, sy * cp],
        [cp * sr,                 cp * cr,                -sp    ],
        [-sy * cr + cy * sp * sr, sy * sr + cy * sp * cr, cy * cp],
    ], dtype=np.float64)


# ---------------------------------------------------------------------------
# Full-chain transform: pixel -> camera -> gimbal -> body -> world
# ---------------------------------------------------------------------------

class FullChainTransform:
    """
    Full coordinate chain from pixel to world direction.

    Coordinate chain::

        World (inertial)
          ↑ R_body2world — from dog IMU (roll, pitch, yaw)
        Body (dog frame)
          ↑ R_gimbal2body — from gimbal encoder feedback (yaw_deg, pitch_deg)
        Gimbal (weapon station frame)
          ↑ R_cam2gimbal — MountExtrinsics (static calibration)
        Camera (OpenCV convention)
          ↑ K^{-1} — camera intrinsics inverse
        Pixel (u, v)

    The class reuses :class:`PixelToGimbalTransform` for the lower part of
    the chain (pixel → gimbal) and adds the upper part (gimbal → body → world).

    When ``body_state`` is ``None`` the transform degrades to the static
    (base-fixed) case, producing results identical to :class:`PixelToGimbalTransform`.
    """

    def __init__(
        self,
        camera: CameraModel,
        mount: MountExtrinsics = MountExtrinsics(),
    ) -> None:
        self._pixel_to_gimbal = PixelToGimbalTransform(camera, mount)
        self._cam = camera

    # ---- public API --------------------------------------------------------

    def pixel_to_world_direction(
        self,
        u: float,
        v: float,
        gimbal_fb: "GimbalFeedback",
        body: "Optional[BodyState]" = None,
    ) -> Tuple[float, float]:
        """Pixel (u, v) → world-frame direction (yaw_deg, pitch_deg).

        If *body* is ``None`` the body-to-world rotation is identity
        (stationary base assumption).

        Returns
        -------
        (world_yaw_deg, world_pitch_deg) : Tuple[float, float]
            Direction of the pixel ray in the world/inertial frame.
        """
        # pixel → gimbal direction (unit-ish vector in gimbal frame)
        xn, yn = self._pixel_to_gimbal._undistort_and_normalize(u, v)
        cam_dir = np.array([xn, yn, 1.0], dtype=np.float64)
        gimbal_dir = self._pixel_to_gimbal._R_cam2gimbal @ cam_dir

        # gimbal → body  (gimbal frame is Z-forward → camera convention)
        R_gimbal2body = _euler_camera_to_rotation(
            gimbal_fb.yaw_deg, gimbal_fb.pitch_deg, 0.0,
        )
        body_dir = R_gimbal2body @ gimbal_dir

        # body → world  (body frame also treated as Z-forward — see module docstring)
        if body is not None:
            R_body2world = _euler_camera_to_rotation(
                body.yaw_deg, body.pitch_deg, body.roll_deg,
            )
            world_dir = R_body2world @ body_dir
        else:
            world_dir = body_dir

        # Extract yaw / pitch from world direction vector
        world_yaw = math.degrees(math.atan2(world_dir[0], world_dir[2]))
        world_pitch = math.degrees(-math.atan2(world_dir[1], world_dir[2]))
        return world_yaw, world_pitch

    def target_lock_error(
        self,
        u: float,
        v: float,
        gimbal_fb: "GimbalFeedback",
        body: "Optional[BodyState]" = None,
    ) -> Tuple[float, float]:
        """Compute gimbal correction needed to keep the weapon aimed at the target.

        This is the error signal fed to the PID controller when running on a
        moving base.

        When *body* is ``None``, falls back to the simple pixel-to-gimbal
        angular error (identical to :meth:`PixelToGimbalTransform.pixel_to_angle_error`).

        Parameters
        ----------
        u, v : float
            Target pixel coordinates.
        gimbal_fb : GimbalFeedback
            Current gimbal angles from encoder.
        body : BodyState, optional
            Current body orientation from IMU.

        Returns
        -------
        (yaw_error_deg, pitch_error_deg) : Tuple[float, float]
            Angular correction the gimbal should apply.
            Positive yaw = rotate right, positive pitch = tilt up.
        """
        if body is None:
            # No body info → simple pixel-to-gimbal error (legacy behaviour)
            return self._pixel_to_gimbal.pixel_to_angle_error(u, v)

        # Full chain: compute where the target is in body frame,
        # then derive desired gimbal angles directly (no redundant world transform).

        # Step 1: pixel → gimbal direction vector
        xn, yn = self._pixel_to_gimbal._undistort_and_normalize(u, v)
        cam_dir = np.array([xn, yn, 1.0], dtype=np.float64)
        gimbal_dir = self._pixel_to_gimbal._R_cam2gimbal @ cam_dir

        # Step 2: gimbal → body (using current gimbal angles, Z-forward convention)
        R_gimbal2body = _euler_camera_to_rotation(
            gimbal_fb.yaw_deg, gimbal_fb.pitch_deg, 0.0,
        )
        body_dir = R_gimbal2body @ gimbal_dir

        # Step 3: desired gimbal angles to aim at body_dir
        desired_yaw = math.degrees(math.atan2(body_dir[0], body_dir[2]))
        desired_pitch = math.degrees(-math.atan2(body_dir[1], body_dir[2]))

        # Error = desired - current
        yaw_error = desired_yaw - gimbal_fb.yaw_deg
        pitch_error = desired_pitch - gimbal_fb.pitch_deg

        return yaw_error, pitch_error
