"""SimulatedGimbalDriver 单元测试 — 动力学模型验证。"""

import pytest

from src.rws_tracking.hardware.driver import DriverLimits, SimulatedGimbalDriver


@pytest.fixture
def driver():
    return SimulatedGimbalDriver(DriverLimits(
        yaw_min_deg=-160, yaw_max_deg=160,
        pitch_min_deg=-45, pitch_max_deg=75,
        max_rate_dps=240, deadband_dps=0.2,
        inertia_time_constant_s=0.05,
        static_friction_dps=0.5,
        coulomb_friction_dps=2.0,
    ))


@pytest.fixture
def ideal_driver():
    """No friction, no inertia."""
    return SimulatedGimbalDriver(DriverLimits(
        inertia_time_constant_s=0.0,
        static_friction_dps=0.0,
        coulomb_friction_dps=0.0,
        deadband_dps=0.0,
    ))


class TestBasicOperation:
    def test_initial_position_zero(self, driver):
        fb = driver.get_feedback(0.0)
        assert fb.yaw_deg == 0.0
        assert fb.pitch_deg == 0.0

    def test_set_rate_and_integrate(self, ideal_driver):
        ideal_driver.set_yaw_pitch_rate(100.0, 50.0, 0.0)
        fb = ideal_driver.get_feedback(1.0)
        assert abs(fb.yaw_deg - 100.0) < 1.0
        assert abs(fb.pitch_deg - 50.0) < 1.0

    def test_deadband(self, driver):
        driver.set_yaw_pitch_rate(0.1, 0.1, 0.0)
        fb = driver.get_feedback(1.0)
        assert fb.yaw_deg == 0.0
        assert fb.pitch_deg == 0.0

    def test_rate_clipping(self, driver):
        driver.set_yaw_pitch_rate(500.0, -500.0, 0.0)
        fb = driver.get_feedback(0.001)
        # Rate should be clipped to max_rate_dps
        assert abs(driver._yaw_cmd) <= 240.0
        assert abs(driver._pitch_cmd) <= 240.0


class TestPositionLimits:
    def test_yaw_clamped(self, ideal_driver):
        ideal_driver.set_yaw_pitch_rate(200.0, 0.0, 0.0)
        fb = ideal_driver.get_feedback(2.0)
        assert fb.yaw_deg <= 160.0

    def test_pitch_clamped(self, ideal_driver):
        ideal_driver.set_yaw_pitch_rate(0.0, 200.0, 0.0)
        fb = ideal_driver.get_feedback(2.0)
        assert fb.pitch_deg <= 75.0

    def test_negative_pitch_clamped(self, ideal_driver):
        ideal_driver.set_yaw_pitch_rate(0.0, -200.0, 0.0)
        fb = ideal_driver.get_feedback(2.0)
        assert fb.pitch_deg >= -45.0


class TestDynamics:
    def test_inertia_delays_response(self, driver):
        driver.set_yaw_pitch_rate(100.0, 0.0, 0.0)
        fb = driver.get_feedback(0.001)
        # With inertia, actual rate should be less than commanded
        assert abs(fb.yaw_rate_dps) < 100.0

    def test_static_friction_stops_low_speed(self, driver):
        driver.set_yaw_pitch_rate(0.3, 0.3, 0.0)
        # After some time, static friction should stop motion
        for i in range(100):
            driver.get_feedback(0.001 * (i + 1))
        fb = driver.get_feedback(0.101)
        # Rate should be zero due to static friction
        assert abs(fb.yaw_rate_dps) < 1.0

    def test_coulomb_friction_reduces_rate(self):
        d = SimulatedGimbalDriver(DriverLimits(
            inertia_time_constant_s=0.0,
            static_friction_dps=0.0,
            coulomb_friction_dps=5.0,
            deadband_dps=0.0,
        ))
        d.set_yaw_pitch_rate(50.0, 0.0, 0.0)
        fb = d.get_feedback(0.1)
        # Coulomb friction should reduce the actual rate
        assert fb.yaw_rate_dps < 50.0


class TestFromConfig:
    def test_from_config(self):
        from src.rws_tracking.config import DriverLimitsConfig
        cfg = DriverLimitsConfig()
        limits = DriverLimits.from_config(cfg)
        assert limits.yaw_min_deg == cfg.yaw_min_deg
        assert limits.max_rate_dps == cfg.max_rate_dps


class TestFeedbackTimestamp:
    def test_feedback_timestamp(self, driver):
        fb = driver.get_feedback(42.0)
        assert fb.timestamp == 42.0

    def test_zero_dt_no_crash(self, driver):
        driver.set_yaw_pitch_rate(10.0, 10.0, 1.0)
        fb = driver.get_feedback(1.0)
        assert fb is not None
