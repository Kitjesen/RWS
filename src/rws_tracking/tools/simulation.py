"""Synthetic scene and target motion simulation for offline testing."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass
class SimTarget:
    """Legacy pixel-based target (deprecated - use WorldSimTarget instead)."""

    cx: float  # centre-x in pixels (was 'x' in older API)
    cy: float  # centre-y in pixels (was 'y' in older API)
    w: float
    h: float
    vx: float = 0.0
    vy: float = 0.0
    confidence: float = 0.85
    class_id: str = "unknown"

    def step(self, dt: float) -> None:
        """Advance the target by *dt* seconds."""
        self.cx += self.vx * dt
        self.cy += self.vy * dt


@dataclass
class WorldSimTarget:
    """Target in world coordinates (angular position).

    This is the recommended way to simulate targets, as it correctly
    models how targets appear in the camera frame when the gimbal rotates.
    """

    world_yaw_deg: float  # Target position in world frame (degrees)
    world_pitch_deg: float
    bbox_width: float  # Bbox size in pixels
    bbox_height: float
    vel_yaw_dps: float = 0.0  # Target velocity (degrees per second)
    vel_pitch_dps: float = 0.0
    confidence: float = 0.85
    class_id: str = "unknown"


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
        self.targets: list[SimTarget] = []

    def add_target(self, target: SimTarget) -> None:
        self.targets.append(target)

    def step(self, dt: float) -> list:
        from ..types import BoundingBox, Detection

        out = []
        surviving = []
        for t in self.targets:
            t.cx += t.vx * dt
            t.cy += t.vy * dt
            # Bounce at scene boundaries (top-left of bbox)
            left = t.cx - t.w / 2
            right = t.cx + t.w / 2
            top = t.cy - t.h / 2
            bottom = t.cy + t.h / 2
            if left < 0 or right > self.width:
                t.vx *= -1.0
                t.cx = max(t.w / 2, min(self.width - t.w / 2, t.cx))
            if top < 0 or bottom > self.height:
                t.vy *= -1.0
                t.cy = max(t.h / 2, min(self.height - t.h / 2, t.cy))
            # Remove targets fully outside the frame
            if right < 0 or left > self.width or bottom < 0 or top > self.height:
                continue
            surviving.append(t)
            noisy_cx = t.cx + self.rng.uniform(-1.5, 1.5)
            noisy_cy = t.cy + self.rng.uniform(-1.5, 1.5)
            conf = max(0.05, min(0.99, t.confidence + self.rng.uniform(-0.02, 0.02)))
            out.append(Detection(
                bbox=BoundingBox(x=noisy_cx - t.w / 2, y=noisy_cy - t.h / 2, w=t.w, h=t.h),
                confidence=conf,
                class_id=t.class_id,
            ))
        self.targets = surviving
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
        seed: int = 42,
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
        self.targets: list[WorldSimTarget] = []

    def add_target(self, target: WorldSimTarget) -> None:
        """Add a target to the scene."""
        self.targets.append(target)

    def step(
        self, dt: float, gimbal_yaw_deg: float = 0.0, gimbal_pitch_deg: float = 0.0
    ) -> list[dict]:
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
        from ..types import BoundingBox, Detection

        detections = []

        for target in self.targets:
            # Update target world position
            target.world_yaw_deg += target.vel_yaw_dps * dt
            target.world_pitch_deg += target.vel_pitch_dps * dt

            # Compute target position relative to gimbal
            relative_yaw = target.world_yaw_deg - gimbal_yaw_deg
            relative_pitch = target.world_pitch_deg - gimbal_pitch_deg

            # Clamp relative angle to avoid tan(90°) overflow; targets beyond
            # ±89° are definitely outside any realistic FOV.
            if abs(relative_yaw) >= 89.0 or abs(relative_pitch) >= 89.0:
                # Apply velocity reversal to keep simulation target in arena
                if abs(target.world_yaw_deg) > 30.0:
                    target.vel_yaw_dps *= -1.0
                    target.world_yaw_deg = max(-30.0, min(30.0, target.world_yaw_deg))
                if abs(target.world_pitch_deg) > 20.0:
                    target.vel_pitch_dps *= -1.0
                    target.world_pitch_deg = max(-20.0, min(20.0, target.world_pitch_deg))
                continue  # not visible in frame

            # Project to pixel coordinates using pinhole camera model
            # pixel_x = cx + fx * tan(yaw)
            # pixel_y = cy - fy * tan(pitch)  (negative because image Y is down)
            pixel_x = self.cx + self.fx * math.tan(math.radians(relative_yaw))
            pixel_y = self.cy - self.fy * math.tan(math.radians(relative_pitch))

            # Bounce targets that drift out of the simulation arena (±30°/±20°)
            if abs(target.world_yaw_deg) > 30.0:
                target.vel_yaw_dps *= -1.0
                target.world_yaw_deg = max(-30.0, min(30.0, target.world_yaw_deg))
            if abs(target.world_pitch_deg) > 20.0:
                target.vel_pitch_dps *= -1.0
                target.world_pitch_deg = max(-20.0, min(20.0, target.world_pitch_deg))

            # Check if target is in frame
            if 0 <= pixel_x < self.cam_width and 0 <= pixel_y < self.cam_height:
                # Add detection noise
                noisy_x = pixel_x + self.rng.uniform(-1.5, 1.5)
                noisy_y = pixel_y + self.rng.uniform(-1.5, 1.5)
                noisy_conf = target.confidence + self.rng.uniform(-0.02, 0.02)
                noisy_conf = max(0.05, min(0.99, noisy_conf))

                # Bbox in (x, y, w, h) format (top-left corner)
                bbox_x = noisy_x - target.bbox_width / 2
                bbox_y = noisy_y - target.bbox_height / 2

                detections.append(Detection(
                    bbox=BoundingBox(x=bbox_x, y=bbox_y, w=target.bbox_width, h=target.bbox_height),
                    confidence=noisy_conf,
                    class_id=target.class_id,
                ))

        return detections
