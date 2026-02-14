"""Perception layer interfaces -- implement these to swap detection/tracking/selection."""
from __future__ import annotations

from typing import List, Optional, Protocol

from ..types import Detection, TargetObservation, Track


class Detector(Protocol):
    """Takes a frame, returns a list of detections."""
    def detect(self, frame: object, timestamp: float) -> List[Detection]:
        ...


class Tracker(Protocol):
    """Takes detections, returns tracked objects with stable IDs."""
    def update(self, detections: List[Detection], timestamp: float) -> List[Track]:
        ...


class TargetSelector(Protocol):
    """Picks the best target from tracked objects."""
    def select(self, tracks: List[Track], timestamp: float) -> Optional[TargetObservation]:
        ...
