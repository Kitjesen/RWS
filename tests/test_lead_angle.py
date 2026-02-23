"""射击提前量计算器单元测试。"""

import pytest

from src.rws_tracking.algebra import CameraModel, PixelToGimbalTransform
from src.rws_tracking.control.lead_angle import (
    LeadAngleCalculator,
    LeadAngleConfig,
    SimpleFlightTimeProvider,
)
from src.rws_tracking.types import BoundingBox, TargetObservation


CAM = CameraModel(width=1280, height=720, fx=970.0, fy=965.0, cx=640.0, cy=360.0)


def _obs(tid=1, x=600, y=340, w=80, h=150, vx=50.0, vy=10.0, ax=0.0, ay=0.0, conf=0.9):
    return TargetObservation(
        timestamp=0.0, track_id=tid,
        bbox=BoundingBox(x=x, y=y, w=w, h=h),
        confidence=conf, class_id="person",
        velocity_px_per_s=(vx, vy),
        acceleration_px_per_s2=(ax, ay),
    )


class TestSimpleFlightTimeProvider:
    def test_basic(self):
        ftp = SimpleFlightTimeProvider(1000.0)
        assert ftp.compute_flight_time(500.0) == pytest.approx(0.5)

    def test_zero_distance(self):
        ftp = SimpleFlightTimeProvider(1000.0)
        assert ftp.compute_flight_time(0.0) == 0.0

    def test_negative_distance(self):
        ftp = SimpleFlightTimeProvider(1000.0)
        assert ftp.compute_flight_time(-10.0) == 0.0

    def test_very_low_velocity_clamped(self):
        ftp = SimpleFlightTimeProvider(0.0)
        t = ftp.compute_flight_time(100.0)
        assert t == pytest.approx(100.0)


class TestLeadAngleCalculator:
    @pytest.fixture
    def calc(self):
        return LeadAngleCalculator(
            transform=PixelToGimbalTransform(CAM),
            flight_time_provider=SimpleFlightTimeProvider(900.0),
            config=LeadAngleConfig(enabled=True, max_lead_deg=5.0, min_confidence=0.3),
        )

    @pytest.fixture
    def disabled_calc(self):
        return LeadAngleCalculator(
            transform=PixelToGimbalTransform(CAM),
            flight_time_provider=SimpleFlightTimeProvider(900.0),
            config=LeadAngleConfig(enabled=False),
        )

    def test_disabled_returns_zero(self, disabled_calc):
        lead = disabled_calc.compute(_obs())
        assert lead.yaw_lead_deg == 0.0
        assert lead.pitch_lead_deg == 0.0

    def test_moving_target_nonzero_lead(self, calc):
        lead = calc.compute(_obs(vx=100.0, vy=0.0))
        assert lead.yaw_lead_deg != 0.0

    def test_stationary_target_near_zero_lead(self, calc):
        lead = calc.compute(_obs(vx=0.0, vy=0.0))
        assert abs(lead.yaw_lead_deg) < 0.01

    def test_lead_clamped_to_max(self, calc):
        lead = calc.compute(_obs(vx=5000.0, vy=5000.0))
        assert abs(lead.yaw_lead_deg) <= 5.0
        assert abs(lead.pitch_lead_deg) <= 5.0

    def test_acceleration_affects_lead(self, calc):
        lead_no_acc = calc.compute(_obs(vx=50.0, vy=0.0, ax=0.0, ay=0.0))
        calc2 = LeadAngleCalculator(
            transform=PixelToGimbalTransform(CAM),
            flight_time_provider=SimpleFlightTimeProvider(900.0),
            config=LeadAngleConfig(enabled=True, use_acceleration=True),
        )
        lead_with_acc = calc2.compute(_obs(vx=50.0, vy=0.0, ax=200.0, ay=0.0))
        # With acceleration, lead should be different
        assert lead_with_acc.yaw_lead_deg != lead_no_acc.yaw_lead_deg

    def test_confidence_output(self, calc):
        lead = calc.compute(_obs(vx=100.0))
        assert 0.0 <= lead.confidence <= 1.0

    def test_predicted_position_set(self, calc):
        lead = calc.compute(_obs(vx=100.0))
        assert lead.predicted_target_x != 0.0

    def test_target_switch_resets_smoothing(self, calc):
        calc.compute(_obs(tid=1, vx=100.0))
        lead2 = calc.compute(_obs(tid=2, vx=-100.0))
        # After switch, should use new target's velocity
        assert lead2.yaw_lead_deg < 0.0

    def test_zero_height_bbox(self, calc):
        lead = calc.compute(_obs(h=0, vx=100.0))
        assert lead.yaw_lead_deg == 0.0

    def test_low_confidence_target(self, calc):
        lead = calc.compute(_obs(vx=100.0, conf=0.1))
        # Low confidence should reduce lead
        assert abs(lead.yaw_lead_deg) < 1.0
