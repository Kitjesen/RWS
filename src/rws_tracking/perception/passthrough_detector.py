"""Lightweight detector adapter for simulation / testing."""

from __future__ import annotations

from collections.abc import Iterable

from ..types import BoundingBox, Detection


class PassthroughDetector:
    """
    Accepts an iterable of detection-like dicts and normalizes output.
    Used for synthetic scenes and CI tests where YOLO is not needed.
    """

    def detect(self, frame: object, timestamp: float) -> list[Detection]:
        if not isinstance(frame, Iterable):
            return []

        detections: list[Detection] = []
        for item in frame:
            if not isinstance(item, dict):
                continue
            bbox = item.get("bbox", (0.0, 0.0, 0.0, 0.0))
            if len(bbox) != 4:
                continue
            detections.append(
                Detection(
                    bbox=BoundingBox(
                        float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                    ),
                    confidence=float(item.get("confidence", 0.0)),
                    class_id=str(item.get("class_id", "unknown")),
                    timestamp=timestamp,
                )
            )
        return detections
