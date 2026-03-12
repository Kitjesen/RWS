"""测距仪 + 距离融合 单元测试。"""

from __future__ import annotations

import pytest

from src.rws_tracking.hardware.rangefinder import (
    DistanceFusion,
    SimulatedRangefinder,
    SimulatedRangefinderConfig,
)
from src.rws_tracking.types import BoundingBox, RangefinderReading


class TestSimulatedRangefinder:
    @pytest.fixture
    def rangefinder(self) -> SimulatedRangefinder:
        cfg = SimulatedRangefinderConfig(
            noise_std_m=0.0,
            max_range_m=1000.0,
            min_range_m=1.0,
            failure_rate=0.0,
        )
        return SimulatedRangefinder(
            config=cfg,
            camera_fy=965.0,
            target_height_m=1.8,
        )

    def test_measure_without_target_returns_invalid(self, rangefinder: SimulatedRangefinder):
        reading = rangefinder.measure(1.0)
        assert not reading.valid

    def test_measure_with_target(self, rangefinder: SimulatedRangefinder):
        bbox = BoundingBox(x=500, y=300, w=100, h=50)
        rangefinder.set_target_bbox(bbox)
        reading = rangefinder.measure(1.0)
        assert reading.valid
        assert reading.distance_m > 0

    def test_get_last_reading(self, rangefinder: SimulatedRangefinder):
        last = rangefinder.get_last_reading()
        assert not last.valid

        bbox = BoundingBox(x=500, y=300, w=100, h=50)
        rangefinder.set_target_bbox(bbox)
        rangefinder.measure(1.0)
        last = rangefinder.get_last_reading()
        assert last.valid

    def test_max_range_clamp(self):
        cfg = SimulatedRangefinderConfig(
            max_range_m=50.0, min_range_m=1.0, failure_rate=0.0, noise_std_m=0.0
        )
        rf = SimulatedRangefinder(config=cfg, camera_fy=965.0, target_height_m=1.8)
        tiny_bbox = BoundingBox(x=500, y=300, w=10, h=2)
        rf.set_target_bbox(tiny_bbox)
        reading = rf.measure(1.0)
        if reading.valid:
            assert reading.distance_m <= 50.0


class TestDistanceFusion:
    @pytest.fixture
    def fusion(self) -> DistanceFusion:
        return DistanceFusion(
            max_laser_age_s=0.5,
            camera_fy=965.0,
            target_height_m=1.8,
        )

    def test_laser_preferred_over_bbox(self, fusion: DistanceFusion):
        laser = RangefinderReading(timestamp=1.0, distance_m=30.0, signal_strength=0.9, valid=True)
        bbox = BoundingBox(x=500, y=300, w=100, h=50)
        d = fusion.fuse(laser, bbox, 1.0)
        assert abs(d - 30.0) < 5.0

    def test_bbox_fallback_when_no_laser(self, fusion: DistanceFusion):
        bbox = BoundingBox(x=500, y=300, w=100, h=50)
        d = fusion.fuse(None, bbox, 1.0)
        assert d > 0

    def test_stale_laser_ignored(self, fusion: DistanceFusion):
        laser = RangefinderReading(timestamp=0.0, distance_m=30.0, signal_strength=0.9, valid=True)
        bbox = BoundingBox(x=500, y=300, w=100, h=50)
        d = fusion.fuse(laser, bbox, 10.0)
        assert d > 0
