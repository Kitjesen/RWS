"""轨迹规划器单元测试。"""

import pytest

from src.rws_tracking.control.trajectory import (
    GimbalTrajectoryPlanner,
    TrajectoryConfig,
    TrajectoryPhase,
    TrapezoidSegment,
    plan_trapezoid,
    sample_trapezoid,
)


class TestPlanTrapezoid:
    def test_zero_distance(self):
        seg = plan_trapezoid(0.0, 180.0, 720.0)
        assert seg.t_total == 0.0

    def test_positive_distance(self):
        seg = plan_trapezoid(90.0, 180.0, 720.0)
        assert seg.t_total > 0.0
        assert seg.peak_rate_dps > 0.0

    def test_negative_distance(self):
        seg = plan_trapezoid(-90.0, 180.0, 720.0)
        assert seg.peak_rate_dps < 0.0

    def test_short_distance_triangle(self):
        seg = plan_trapezoid(1.0, 180.0, 720.0)
        assert seg.t_cruise == 0.0  # Triangle profile

    def test_long_distance_trapezoid(self):
        seg = plan_trapezoid(180.0, 180.0, 720.0)
        assert seg.t_cruise > 0.0  # Has cruise phase


class TestSampleTrapezoid:
    def test_zero_segment(self):
        seg = TrapezoidSegment()
        pos, vel = sample_trapezoid(seg, 0.5)
        assert pos == 0.0
        assert vel == 0.0

    def test_at_start(self):
        seg = plan_trapezoid(90.0, 180.0, 720.0)
        pos, vel = sample_trapezoid(seg, 0.0)
        assert pos == 0.0
        assert vel == 0.0

    def test_at_end(self):
        seg = plan_trapezoid(90.0, 180.0, 720.0)
        pos, vel = sample_trapezoid(seg, seg.t_total)
        assert abs(pos - 90.0) < 1.0
        assert abs(vel) < 1.0

    def test_velocity_positive_during_accel(self):
        seg = plan_trapezoid(90.0, 180.0, 720.0)
        _, vel = sample_trapezoid(seg, seg.t_accel * 0.5)
        assert vel > 0.0

    def test_negative_time(self):
        seg = plan_trapezoid(90.0, 180.0, 720.0)
        pos, vel = sample_trapezoid(seg, -1.0)
        assert pos == 0.0


class TestGimbalTrajectoryPlanner:
    @pytest.fixture
    def planner(self):
        return GimbalTrajectoryPlanner(TrajectoryConfig(
            max_rate_dps=180.0,
            max_acceleration_dps2=720.0,
            settling_threshold_deg=0.5,
            min_switch_interval_s=0.0,
        ))

    def test_initial_idle(self, planner):
        assert planner.phase == TrajectoryPhase.IDLE
        assert not planner.is_active

    def test_set_target_activates(self, planner):
        ok = planner.set_target(30.0, 10.0, 0.0, 0.0, 0.0)
        assert ok
        assert planner.is_active

    def test_within_threshold_stays_idle(self, planner):
        ok = planner.set_target(0.1, 0.1, 0.0, 0.0, 0.0)
        assert ok
        assert not planner.is_active

    def test_rate_command_nonzero(self, planner):
        planner.set_target(30.0, 10.0, 0.0, 0.0, 0.0)
        yr, pr = planner.get_rate_command(0.05)
        assert abs(yr) + abs(pr) > 0.0

    def test_rate_command_zero_when_inactive(self, planner):
        yr, pr = planner.get_rate_command(0.0)
        assert yr == 0.0
        assert pr == 0.0

    def test_completes_trajectory(self, planner):
        planner.set_target(10.0, 5.0, 0.0, 0.0, 0.0)
        yr, pr = planner.get_rate_command(100.0)
        assert yr == 0.0
        assert pr == 0.0
        assert planner.phase == TrajectoryPhase.COMPLETE

    def test_cancel(self, planner):
        planner.set_target(30.0, 10.0, 0.0, 0.0, 0.0)
        planner.cancel()
        assert not planner.is_active
        assert planner.phase == TrajectoryPhase.IDLE

    def test_min_switch_interval(self):
        p = GimbalTrajectoryPlanner(TrajectoryConfig(min_switch_interval_s=1.0))
        p.set_target(30.0, 10.0, 0.0, 0.0, 0.0)
        ok = p.set_target(60.0, 20.0, 0.0, 0.0, 0.5)
        assert not ok  # Too soon

    def test_phase_transitions(self, planner):
        planner.set_target(90.0, 0.0, 0.0, 0.0, 0.0)
        phases_seen = set()
        for i in range(200):
            t = i * 0.01
            planner.get_rate_command(t)
            phases_seen.add(planner.phase)
        assert TrajectoryPhase.ACCELERATING in phases_seen
