"""感知层数据类型：检测、跟踪、目标观测。"""

from __future__ import annotations

from dataclasses import dataclass

from .common import BoundingBox


@dataclass(frozen=True)
class Detection:
    bbox: BoundingBox
    confidence: float
    class_id: str
    timestamp: float = 0.0


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
    mask_center: tuple[float, float] | None = None


@dataclass(frozen=True)
class TargetObservation:
    timestamp: float
    track_id: int
    bbox: BoundingBox
    confidence: float
    class_id: str
    velocity_px_per_s: tuple[float, float] = (0.0, 0.0)
    acceleration_px_per_s2: tuple[float, float] = (0.0, 0.0)
    mask_center: tuple[float, float] | None = None
