"""Synthetic scene and target motion simulation for offline testing."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class SimTarget:
    """Legacy pixel-based target (deprecated - use WorldSimTarget instead)."""
    x: float
    y: float
    w: float
    h: float
    vx: float
    vy: float
    confidence: float
    class_id: str


@dataclass
class WorldSimTarget:
    """Target in world coordinates (angular position).

    This is the recommended way to simulate targets, as it correctly
    models how targets appear in the camera frame when the gimbal rotates.
    """
    world_yaw_deg: float  # Target position in world frame (degrees)
    world_pitch_deg: float
    vel_yaw_dps: float  # Target velocity (degrees per second)
    vel_pitch_dps: float
    bbox_width: float  # Bbox size in pixels
    bbox_height: float
    confidence: float
    class_id: str


class SyntheticScene:
    """Legacy pixel-based scene simulation.

    WARNING: This simulation is unrealistic because it moves targets in
    pixel coordinates without considering gimbal rotation. When the gimbal
    rotates, targets should move in the frame, but this simulation doesn't
    model that effect.

    For realistic simulation, use WorldCoordinateScene instead.
    """
    def __init__(self, width: int, height: int, seed: int = 42) -> None:
        self.width = width
        self.height = height
        self.rng = random.Random(seed)
        self.targets: List[SimTarget] = []

    def add_target(self, target: SimTarget) -> None:
        self.targets.append(target)

    def step(self, dt: float) -> List[dict]:
        out = []
        for t in self.targets:
            t.x += t.vx * dt
            t.y += t.vy * dt
            if t.x < 0 or t.x + t.w > self.width:
                t.vx *= -1.0
                t.x = min(max(t.x, 0.0), self.width - t.w)
            if t.y < 0 or t.y + t.h > self.height:
                t.vy *= -1.0
                t.y = min(max(t.y, 0.0), self.height - t.h)
            noisy_x = t.x + self.rng.uniform(-1.5, 1.5)
            noisy_y = t.y + self.rng.uniform(-1.5, 1.5)
            out.append({
                "bbox": (noisy_x, noisy_y, t.w, t.h),
                "confidence": max(0.05, min(0.99, t.confidence + self.rng.uniform(-0.02, 0.02))),
                "class_id": t.class_id,
            })
        return out


class WorldCoordinateScene:
    """Realistic scene simulation using world coordinates.

    Targets are positioned in world angular coordinates (yaw/pitch degrees).
    Each frame, targets are projected into the camera frame based on the
    current gimbal position. This correctly models how targets move in the
    image when the gimbal rotates.

    Example:
        scene = WorldCoordinateScene(cam_width=1280, cam_height=720,
                                      fx=970.0, fy=965.0, cx=640.0, cy=360.0)
        scene.add_target(WorldSimTarget(
            world_yaw_deg=5.0, world_pitch_deg=2.0,
            vel_yaw_dps=1.0, vel_pitch_dps=0.5,
            bbox_width=80, bbox_height=120,
            confidence=0.95, class_id="person"
        ))

        # Each frame:
        detections = scene.step(dt=0.033, gimbal_yaw_deg=0.0, gimbal_pitch_deg=0.0)
    """

    def __init__(
        self,
        cam_width: int,
        cam_height: int,
        fx: float,
        fy: float,
        cx: float,
        cy: float,
        seed: int = 42
    ):
        """Initialize world coordinate scene.

        Parameters
        ----------
        cam_width, cam_height : int
            Camera resolution
        fx, fy : float
            Camera focal lengths (pixels)
        cx, cy : float
            Camera principal point (pixels)
        seed : int
            Random seed for noise
        """
        self.cam_width = cam_width
        self.cam_height = cam_height
        self.fx = fx
        self.fy = fy
        self.cx = cx
        self.cy = cy
        self.rng = random.Random(seed)
        self.targets: List[WorldSimTarget] = []

    def add_target(self, target: WorldSimTarget) -> None:
        """Add a target to the scene."""
        self.targets.append(target)

    def step(
        self,
        dt: float,
        gimbal_yaw_deg: float = 0.0,
        gimbal_pitch_deg: float = 0.0
    ) -> List[dict]:
        """Update scene and return detections visible in current gimbal frame.

        Parameters
        ----------
        dt : float
            Time step (seconds)
        gimbal_yaw_deg : float
            Current gimbal yaw angle (degrees)
        gimbal_pitch_deg : float
            Current gimbal pitch angle (degrees)

        Returns
        -------
        List[dict]
            List of detection dicts with keys: bbox, confidence, class_id
        """
        detections = []

        for target in self.targets:
            # Update target world position
            target.world_yaw_deg += target.vel_yaw_dps * dt
            target.world_pitch_deg += target.vel_pitch_dps * dt

            # Limit target range (bounce at boundaries)
            if abs(target.world_yaw_deg) > 30.0:
                target.vel_yaw_dps *= -1.0
                target.world_yaw_deg = max(-30.0, min(30.0, target.world_yaw_deg))
            if abs(target.world_pitch_deg) > 20.0:
                target.vel_pitch_dps *= -1.0
                target.world_pitch_deg = max(-20.0, min(20.0, target.world_pitch_deg))

            # Compute target position relative to gimbal
            relative_yaw = target.world_yaw_deg - gimbal_yaw_deg
            relative_pitch = target.world_pitch_deg - gimbal_pitch_deg

            # Project to pixel coordinates using pinhole camera model
            # pixel_x = cx + fx * tan(yaw)
            # pixel_y = cy - fy * tan(pitch)  (negative because image Y is down)
            pixel_x = self.cx + self.fx * math.tan(math.radians(relative_yaw))
            pixel_y = self.cy - self.fy * math.tan(math.radians(relative_pitch))

            # Check if target is in frame
            if (0 <= pixel_x < self.cam_width and
                0 <= pixel_y < self.cam_height):

                # Add detection noise
                noisy_x = pixel_x + self.rng.uniform(-1.5, 1.5)
                noisy_y = pixel_y + self.rng.uniform(-1.5, 1.5)
                noisy_conf = target.confidence + self.rng.uniform(-0.02, 0.02)
                noisy_conf = max(0.05, min(0.99, noisy_conf))

                # Bbox in (x, y, w, h) format (top-left corner)
                bbox_x = noisy_x - target.bbox_width / 2
                bbox_y = noisy_y - target.bbox_height / 2

                detections.append({
                    "bbox": (bbox_x, bbox_y, target.bbox_width, target.bbox_height),
                    "confidence": noisy_conf,
                    "class_id": target.class_id,
                })

        return detections

