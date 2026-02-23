"""IMU接口与Mock IMU单元测试。"""

import math

import pytest

from src.rws_tracking.hardware.mock_imu import (
    ReplayBodyMotion,
    SinusoidalBodyMotion,
    SinusoidalConfig,
    StaticBodyMotion,
)
from src.rws_tracking.types import BodyState


class TestStaticBodyMotion:
    def test_zero_rates(self):
        imu = StaticBodyMotion()
        state = imu.get_body_state(0.0)
        assert state.yaw_rate_dps == 0.0
        assert state.pitch_rate_dps == 0.0
        assert state.roll_rate_dps == 0.0

    def test_custom_rates(self):
        imu = StaticBodyMotion(yaw_rate_dps=5.0, pitch_rate_dps=3.0, roll_rate_dps=1.0)
        state = imu.get_body_state(0.0)
        assert state.yaw_rate_dps == 5.0
        assert state.pitch_rate_dps == 3.0
        assert state.roll_rate_dps == 1.0

    def test_constant_over_time(self):
        imu = StaticBodyMotion(yaw_rate_dps=5.0)
        s1 = imu.get_body_state(0.0)
        s2 = imu.get_body_state(100.0)
        assert s1.yaw_rate_dps == s2.yaw_rate_dps


class TestSinusoidalBodyMotion:
    @pytest.fixture
    def cfg(self):
        return SinusoidalConfig(
            yaw_amplitude_deg=2.0,
            pitch_amplitude_deg=0.8,
            roll_amplitude_deg=0.3,
            yaw_freq_hz=1.0,
            pitch_freq_hz=2.0,
            roll_freq_hz=0.5,
        )

    @pytest.fixture
    def imu(self, cfg):
        return SinusoidalBodyMotion(cfg)

    def test_at_zero(self, imu, cfg):
        state = imu.get_body_state(0.0)
        # Cosine-derivative model: rate at t=0 equals amplitude * 2π * freq (max)
        expected = cfg.yaw_amplitude_deg * 2.0 * math.pi * cfg.yaw_freq_hz
        assert abs(state.yaw_rate_dps - expected) < 0.1

    def test_at_quarter_period(self, imu):
        # At quarter period (t=0.25s for 1Hz), cos(π/2) ≈ 0
        state = imu.get_body_state(0.25)
        assert abs(state.yaw_rate_dps) < 0.1

    def test_bounded(self, imu, cfg):
        max_yaw = cfg.yaw_amplitude_deg * 2.0 * math.pi * cfg.yaw_freq_hz + 0.1
        max_pitch = cfg.pitch_amplitude_deg * 2.0 * math.pi * cfg.pitch_freq_hz + 0.1
        max_roll = cfg.roll_amplitude_deg * 2.0 * math.pi * cfg.roll_freq_hz + 0.1
        for t in [0.0, 0.1, 0.25, 0.5, 0.75, 1.0]:
            state = imu.get_body_state(t)
            assert abs(state.yaw_rate_dps) <= max_yaw
            assert abs(state.pitch_rate_dps) <= max_pitch
            assert abs(state.roll_rate_dps) <= max_roll

    def test_periodic(self, imu):
        s1 = imu.get_body_state(0.0)
        s2 = imu.get_body_state(1.0)  # full period for 1Hz
        assert abs(s1.yaw_rate_dps - s2.yaw_rate_dps) < 0.01


class TestReplayBodyMotion:
    def test_basic_replay(self):
        timestamps = [0.0, 1.0, 2.0]
        yaw_rates = [0.0, 10.0, 0.0]
        pitch_rates = [0.0, 5.0, 0.0]
        roll_rates = [0.0, 2.0, 0.0]
        data = [
            BodyState(timestamp=t, yaw_rate_dps=y, pitch_rate_dps=p, roll_rate_dps=r)
            for t, y, p, r in zip(timestamps, yaw_rates, pitch_rates, roll_rates)
        ]
        imu = ReplayBodyMotion(data=data)
        state = imu.get_body_state(0.5)
        assert abs(state.yaw_rate_dps - 5.0) < 0.1  # interpolated

    def test_before_start(self):
        data = [
            BodyState(timestamp=1.0, yaw_rate_dps=10.0, pitch_rate_dps=5.0),
            BodyState(timestamp=2.0, yaw_rate_dps=20.0, pitch_rate_dps=10.0),
        ]
        imu = ReplayBodyMotion(data=data)
        state = imu.get_body_state(0.0)
        assert state.yaw_rate_dps == pytest.approx(10.0)

    def test_after_end(self):
        data = [
            BodyState(timestamp=0.0, yaw_rate_dps=10.0),
            BodyState(timestamp=1.0, yaw_rate_dps=20.0),
        ]
        imu = ReplayBodyMotion(data=data)
        state = imu.get_body_state(5.0)
        assert state.yaw_rate_dps == pytest.approx(20.0)

    def test_exact_timestamp(self):
        data = [
            BodyState(timestamp=0.0, yaw_rate_dps=0.0),
            BodyState(timestamp=1.0, yaw_rate_dps=10.0),
            BodyState(timestamp=2.0, yaw_rate_dps=0.0),
        ]
        imu = ReplayBodyMotion(data=data)
        state = imu.get_body_state(1.0)
        assert state.yaw_rate_dps == pytest.approx(10.0)
