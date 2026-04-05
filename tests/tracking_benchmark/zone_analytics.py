"""Zone analytics: LineZone in/out counting + PolygonZone occupancy.

Usage::

    analytics = ZoneAnalytics.from_yaml(zones_yaml_path, video_stem)
    if analytics:
        # inside the per-frame loop:
        analytics.update(detections)
        frame = analytics.annotate(frame, detections)
    # after the loop:
    report = analytics.report  # ZoneReport dataclass
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import supervision as sv
import yaml


@dataclass
class ZoneReport:
    """Accumulated zone statistics for one benchmark run."""
    line_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    """Per-line {name: {in: N, out: N}} cumulative crossing counts."""

    polygon_occupancy: dict[str, int] = field(default_factory=dict)
    """Per-polygon current occupancy (last frame)."""

    polygon_dwell: dict[str, int] = field(default_factory=dict)
    """Per-polygon total frame-occupancy (sum over all frames)."""


class ZoneAnalytics:
    """Wraps sv.LineZone and sv.PolygonZone for a single benchmark scene."""

    def __init__(self, scene_config: dict) -> None:
        self._line_zones: list[tuple[str, sv.LineZone]] = []
        self._polygon_zones: list[tuple[str, sv.PolygonZone]] = []
        self._line_annotators: list[sv.LineZoneAnnotator] = []
        self._polygon_annotators: list[sv.PolygonZoneAnnotator] = []
        self.report = ZoneReport()

        for lz in scene_config.get("line_zones", []):
            zone = sv.LineZone(
                start=sv.Point(*lz["start"]),
                end=sv.Point(*lz["end"]),
            )
            annotator = sv.LineZoneAnnotator(
                custom_in_text=f"{lz['name']} IN",
                custom_out_text=f"{lz['name']} OUT",
            )
            self._line_zones.append((lz["name"], zone))
            self._line_annotators.append(annotator)
            self.report.line_counts[lz["name"]] = {"in": 0, "out": 0}

        for pz in scene_config.get("polygon_zones", []):
            polygon = np.array(pz["polygon"], dtype=np.int64)
            zone = sv.PolygonZone(polygon=polygon)
            annotator = sv.PolygonZoneAnnotator(zone=zone)
            self._polygon_zones.append((pz["name"], zone))
            self._polygon_annotators.append(annotator)
            self.report.polygon_occupancy[pz["name"]] = 0
            self.report.polygon_dwell[pz["name"]] = 0

    @classmethod
    def from_yaml(cls, yaml_path: Path, video_stem: str) -> ZoneAnalytics | None:
        """Load zone config for *video_stem* from *yaml_path*.

        Returns ``None`` if the yaml file is missing or the scene has no entry.
        """
        if not yaml_path.exists():
            return None
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        config = data.get("scenes", {}).get(video_stem)
        if not config:
            return None
        return cls(config)

    def update(self, detections: sv.Detections) -> None:
        """Trigger all zones with *detections* and accumulate statistics."""
        for name, zone in self._line_zones:
            crossed_in, crossed_out = zone.trigger(detections)
            self.report.line_counts[name]["in"] += int(crossed_in.sum())
            self.report.line_counts[name]["out"] += int(crossed_out.sum())

        for name, zone in self._polygon_zones:
            in_zone = zone.trigger(detections)
            count = int(in_zone.sum())
            self.report.polygon_occupancy[name] = count
            self.report.polygon_dwell[name] += count

    def annotate(self, frame: np.ndarray, detections: sv.Detections) -> np.ndarray:
        """Overlay all zone annotations onto *frame* and return it."""
        for (_, zone), annotator in zip(self._line_zones, self._line_annotators):
            frame = annotator.annotate(frame, line_counter=zone)
        for (_, zone), annotator in zip(self._polygon_zones, self._polygon_annotators):
            frame = annotator.annotate(frame, detections=detections)
        return frame
