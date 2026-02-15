"""
Ground Truth Detector for MuJoCo SIL
=====================================

Projects the known 3D target position into the camera image plane,
producing a synthetic Detection with perfect accuracy.

This separates control-loop testing from YOLO detection testing:
  - SIL + GroundTruthDetector  → tests PID, state machine, feedforward.
  - Real camera + YoloDetector → tests detection in real scenes.

Optionally adds configurable noise to simulate detection imperfections.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import mujoco

from ...types import BoundingBox, Detection


@dataclass
class DetectionNoise:
    """Configurable noise to make ground truth less perfect."""

    bbox_jitter_px: float = 0.0  # random offset on bbox center (pixels)
    size_jitter_frac: float = 0.0  # random scale on bbox size (fraction, e.g. 0.05 = ±5%)
    miss_rate: float = 0.0  # probability of returning no detection (0~1)
    confidence_mean: float = 0.92  # simulated confidence
    confidence_std: float = 0.03  # confidence noise


class GroundTruthDetector:
    """
    Produces detections by projecting the MuJoCo target body into the camera.

    Parameters
    ----------
    model, data : MuJoCo model and data handles.
    target_body : name of the target body in MJCF.
    camera_name : name of the camera in MJCF.
    target_half_size : approximate half-size of the target in meters (for bbox).
    class_id : class label to assign to detections.
    noise : optional detection noise config.
    """

    def __init__(
        self,
        model: mujoco.MjModel,
        data: mujoco.MjData,
        target_body: str = "target",
        camera_name: str = "gimbal_cam",
        target_half_height: float = 0.85,
        target_half_width: float = 0.25,
        class_id: str = "person",
        noise: DetectionNoise | None = None,
        image_width: int = 1280,
        image_height: int = 720,
    ) -> None:
        import mujoco as mj

        self._m = model
        self._d = data
        self._target_id = mj.mj_name2id(model, mj.mjtObj.mjOBJ_BODY, target_body)
        self._cam_id = mj.mj_name2id(model, mj.mjtObj.mjOBJ_CAMERA, camera_name)
        self._half_h = target_half_height
        self._half_w = target_half_width
        self._class_id = class_id
        self._noise = noise or DetectionNoise()
        self._img_w = image_width
        self._img_h = image_height

    def detect(self, frame: object, timestamp: float) -> list[Detection]:
        """
        Project target to image and return a Detection.

        ``frame`` is ignored — we read position directly from MuJoCo state.
        This matches the ``Detector`` protocol signature.
        """
        # Random miss
        if random.random() < self._noise.miss_rate:
            return []

        # Get target center in world frame
        target_center = self._d.body(self._target_id).xpos.copy()

        # Get camera position and orientation from MuJoCo
        cam_pos = self._d.cam_xpos[self._cam_id].copy()
        cam_mat = self._d.cam_xmat[self._cam_id].reshape(3, 3).copy()

        # Transform target to camera frame
        # MuJoCo camera: x=right, y=up, z=backward (looks along -z)
        delta = target_center - cam_pos
        cam_coords = cam_mat.T @ delta  # world to camera frame

        # Check if target is in front of camera (positive depth = -z in MuJoCo cam)
        depth = -cam_coords[2]
        if depth < 0.5:
            return []  # behind camera or too close

        # Project to normalized image coordinates
        # MuJoCo camera: u = -x/z (because z points backward), v = -y/z
        nx = cam_coords[0] / depth
        ny = cam_coords[1] / depth

        # Convert to pixel coordinates using MuJoCo camera model
        # fovy is the vertical field of view
        fovy_rad = self._m.cam_fovy[self._cam_id] * math.pi / 180.0
        fy = (self._img_h / 2.0) / math.tan(fovy_rad / 2.0)
        fx = fy  # square pixels

        cx = self._img_w / 2.0
        cy = self._img_h / 2.0

        u = cx + fx * nx
        v = cy - fy * ny  # y-up to y-down

        # Project target extents to get bbox
        bbox_half_w_px = fx * self._half_w / depth
        bbox_half_h_px = fy * self._half_h / depth

        # Apply noise
        n = self._noise
        if n.bbox_jitter_px > 0:
            u += random.gauss(0, n.bbox_jitter_px)
            v += random.gauss(0, n.bbox_jitter_px)
        if n.size_jitter_frac > 0:
            scale = 1.0 + random.gauss(0, n.size_jitter_frac)
            bbox_half_w_px *= scale
            bbox_half_h_px *= scale

        # Build bbox (x, y, w, h) — top-left origin
        bw = bbox_half_w_px * 2
        bh = bbox_half_h_px * 2
        bx = u - bbox_half_w_px
        by = v - bbox_half_h_px

        # Clip to image bounds
        bx = max(0, min(bx, self._img_w - bw))
        by = max(0, min(by, self._img_h - bh))
        bw = min(bw, self._img_w - bx)
        bh = min(bh, self._img_h - by)

        if bw < 2 or bh < 2:
            return []  # too small

        # Check if mostly inside image
        if bx + bw / 2 < 0 or bx + bw / 2 > self._img_w:
            return []
        if by + bh / 2 < 0 or by + bh / 2 > self._img_h:
            return []

        conf = max(0.1, min(1.0, random.gauss(n.confidence_mean, n.confidence_std)))

        return [
            Detection(
                bbox=BoundingBox(x=float(bx), y=float(by), w=float(bw), h=float(bh)),
                confidence=float(conf),
                class_id=self._class_id,
                timestamp=timestamp,
            )
        ]
