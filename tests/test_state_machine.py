"""状态机单元测试。"""

import pytest

from src.rws_tracking.config import GimbalControllerConfig, PIDConfig
from src.rws_tracking.decision.state_machine import TrackStateMachine
from src.rws_tracking.types import TargetError, TrackState


@pytest.fixture
def cfg():
    pid = PIDConfig(kp=5.0, ki=0.3, kd=0.2)
    return GimbalControllerConfig(
        yaw_pid=pid, pitch_pid=pid,
        lock_error_threshold_deg=1.0,
        lock_hold_time_s=0.5,
        lost_timeout_s=1.0,
        max_track_error_timeout_s=3.0,
        high_error_multiplier=5.0,
    )


@pytest.fixture
def sm(cfg):
    return TrackStateMachine(cfg)


def _err(yaw=0.0, pitch=0.0, ts=0.0, tid=1):
    return TargetError(timestamp=ts, yaw_error_deg=yaw, pitch_error_deg=pitch, target_id=tid)


class TestInitialState:
    def test_starts_in_search(self, sm):
        assert sm.state == TrackState.SEARCH


class TestSearchToTrack:
    def test_target_detected(self, sm):
        state = sm.update(_err(yaw=5.0, ts=0.0), 0.0)
        assert state == TrackState.TRACK

    def test_small_error_starts_track(self, sm):
        state = sm.update(_err(yaw=0.5, ts=0.0), 0.0)
        assert state == TrackState.TRACK


class TestTrackToLock:
    def test_sustained_small_error_locks(self, sm):
        for i in range(20):
            t = i * 0.1
            state = sm.update(_err(yaw=0.3, pitch=0.2, ts=t), t)
        assert state == TrackState.LOCK

    def test_brief_small_error_stays_track(self, sm):
        state = sm.update(_err(yaw=0.3, ts=0.0), 0.0)
        assert state == TrackState.TRACK


class TestLockToTrack:
    def test_large_error_drops_to_track(self, sm):
        # Achieve lock
        for i in range(20):
            sm.update(_err(yaw=0.3, ts=i * 0.1), i * 0.1)
        # Sustained large error for > exit hysteresis (lock_hold_time_s * 0.5).
        # Fixture uses lock_hold_time_s=0.5 so exit_hold=0.25s; run 0.3s to clear it.
        state = None
        for i in range(7):
            state = sm.update(_err(yaw=3.0, ts=3.0 + i * 0.05), 3.0 + i * 0.05)
        assert state == TrackState.TRACK


class TestTrackToLost:
    def test_target_disappears(self, sm):
        sm.update(_err(yaw=2.0, ts=0.0), 0.0)
        state = sm.update(None, 0.5)
        assert state == TrackState.LOST


class TestLostToSearch:
    def test_timeout(self, sm):
        sm.update(_err(yaw=2.0, ts=0.0), 0.0)
        sm.update(None, 0.5)
        state = sm.update(None, 2.0)
        assert state == TrackState.SEARCH


class TestHighErrorTimeout:
    def test_sustained_high_error_returns_to_search(self, sm):
        # Error > lock_threshold * high_error_multiplier = 1.0 * 5.0 = 5.0
        for i in range(50):
            t = i * 0.1
            state = sm.update(_err(yaw=6.0, ts=t), t)
        assert state == TrackState.SEARCH

    def test_moderate_error_stays_track(self, sm):
        for i in range(50):
            t = i * 0.1
            state = sm.update(_err(yaw=3.0, ts=t), t)
        assert state == TrackState.TRACK


class TestLostRecovery:
    def test_target_reappears(self, sm):
        sm.update(_err(yaw=2.0, ts=0.0), 0.0)
        sm.update(None, 0.5)
        state = sm.update(_err(yaw=2.0, ts=0.8), 0.8)
        assert state == TrackState.TRACK
