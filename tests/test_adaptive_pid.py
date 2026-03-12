"""自适应PID增益调度模块单元测试。"""

import pytest

from src.rws_tracking.control.adaptive import (
    DistanceBasedScheduler,
    DistanceBasedSchedulerConfig,
    ErrorBasedScheduler,
    ErrorBasedSchedulerConfig,
)


class TestErrorBasedScheduler:
    @pytest.fixture
    def scheduler(self):
        return ErrorBasedScheduler(
            ErrorBasedSchedulerConfig(
                low_error_threshold_deg=2.0,
                high_error_threshold_deg=10.0,
                low_error_multiplier=0.8,
                high_error_multiplier=1.5,
            )
        )

    def test_low_error_reduces_gain(self, scheduler):
        kp, ki, kd = scheduler.compute_multipliers(1.0, 0.0)
        assert kp == pytest.approx(0.8)
        assert ki == pytest.approx(0.8)
        assert kd == pytest.approx(0.8)

    def test_high_error_increases_gain(self, scheduler):
        kp, ki, kd = scheduler.compute_multipliers(15.0, 0.0)
        assert kp == pytest.approx(1.5)

    def test_mid_error_interpolates(self, scheduler):
        kp, _, _ = scheduler.compute_multipliers(6.0, 0.0)
        assert 0.8 < kp < 1.5

    def test_exact_low_threshold(self, scheduler):
        kp, _, _ = scheduler.compute_multipliers(2.0, 0.0)
        assert kp == pytest.approx(0.8)

    def test_exact_high_threshold(self, scheduler):
        kp, _, _ = scheduler.compute_multipliers(10.0, 0.0)
        assert kp == pytest.approx(1.5)

    def test_zero_error(self, scheduler):
        kp, _, _ = scheduler.compute_multipliers(0.0, 0.0)
        assert kp == pytest.approx(0.8)

    def test_bbox_area_ignored(self, scheduler):
        kp1, _, _ = scheduler.compute_multipliers(5.0, 0.0)
        kp2, _, _ = scheduler.compute_multipliers(5.0, 99999.0)
        assert kp1 == kp2


class TestDistanceBasedScheduler:
    @pytest.fixture
    def scheduler(self):
        return DistanceBasedScheduler(
            DistanceBasedSchedulerConfig(
                near_distance_m=5.0,
                far_distance_m=30.0,
                near_multiplier=1.0,
                far_multiplier=1.3,
                bbox_area_max=50000.0,
                ki_distance_scale=0.8,
            )
        )

    def test_large_bbox_near_target(self, scheduler):
        kp, ki, kd = scheduler.compute_multipliers(5.0, 50000.0)
        assert kp == pytest.approx(1.0)
        assert ki == pytest.approx(0.8)

    def test_small_bbox_far_target(self, scheduler):
        kp, ki, kd = scheduler.compute_multipliers(5.0, 0.0)
        assert kp == pytest.approx(1.3)
        assert ki == pytest.approx(1.3 * 0.8)

    def test_mid_area(self, scheduler):
        kp, _, _ = scheduler.compute_multipliers(5.0, 25000.0)
        assert 1.0 < kp < 1.3

    def test_area_exceeds_max(self, scheduler):
        kp, _, _ = scheduler.compute_multipliers(5.0, 100000.0)
        assert kp == pytest.approx(1.0)

    def test_ki_scaled_differently(self, scheduler):
        kp, ki, kd = scheduler.compute_multipliers(5.0, 10000.0)
        assert ki < kp  # ki is scaled down
        assert kd == kp  # kd same as kp
