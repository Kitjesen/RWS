from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BoundingBox:
    x: float
    y: float
    w: float
    h: float

    @property
    def area(self) -> float:
        return max(self.w, 0.0) * max(self.h, 0.0)

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.w * 0.5, self.y + self.h * 0.5


@dataclass(frozen=True)
class Detection:
    bbox: BoundingBox
    confidence: float
    class_id: str
    timestamp: float


@dataclass
class Track:
    track_id: int
    bbox: BoundingBox
    confidence: float
    class_id: str
    first_seen_ts: float
    last_seen_ts: float
    age_frames: int = 1
    misses: int = 0
    velocity_px_per_s: tuple[float, float] = (0.0, 0.0)
    acceleration_px_per_s2: tuple[float, float] = (0.0, 0.0)
    mask_center: tuple[float, float] | None = None  # segmentation mask centroid (px)


@dataclass(frozen=True)
class TargetObservation:
    timestamp: float
    track_id: int
    bbox: BoundingBox
    confidence: float
    class_id: str
    velocity_px_per_s: tuple[float, float] = (0.0, 0.0)
    acceleration_px_per_s2: tuple[float, float] = (0.0, 0.0)
    mask_center: tuple[float, float] | None = None  # segmentation mask centroid (px)


@dataclass
class GimbalFeedback:
    timestamp: float
    yaw_deg: float
    pitch_deg: float
    yaw_rate_dps: float
    pitch_rate_dps: float


@dataclass
class ControlCommand:
    timestamp: float
    yaw_rate_cmd_dps: float
    pitch_rate_cmd_dps: float
    metadata: dict[str, float] = field(default_factory=dict)


@dataclass
class BodyState:
    """6-DOF body (base platform) state from IMU / robot SDK.

    Attributes
    ----------
    timestamp : float
        Monotonic timestamp (seconds).
    roll_deg, pitch_deg, yaw_deg : float
        Body orientation in world frame (degrees).
    roll_rate_dps, pitch_rate_dps, yaw_rate_dps : float
        Body angular velocity (degrees per second).
    """

    timestamp: float
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0
    roll_rate_dps: float = 0.0
    pitch_rate_dps: float = 0.0
    yaw_rate_dps: float = 0.0


@dataclass(frozen=True)
class CameraIntrinsics:
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float


@dataclass(frozen=True)
class MountCalibration:
    yaw_bias_deg: float = 0.0
    pitch_bias_deg: float = 0.0


@dataclass(frozen=True)
class TargetError:
    timestamp: float
    yaw_error_deg: float
    pitch_error_deg: float
    target_id: int | None
