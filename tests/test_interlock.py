"""安全联锁系统独立完整测试。"""

import time

import pytest

from src.rws_tracking.safety.interlock import (
    InterlockResult,
    SafetyInterlock,
    SafetyInterlockConfig,
)


@pytest.fixture
def interlock():
    return SafetyInterlock(
        SafetyInterlockConfig(
            require_operator_auth=True,
            min_lock_time_s=1.0,
            min_engagement_range_m=5.0,
            max_engagement_range_m=500.0,
            heartbeat_timeout_s=100.0,
        )
    )


def _authorize_all(il):
    il.set_operator_auth(True)
    il.update_system_status(comms_ok=True, sensors_ok=True)
    il.update_target_status(locked=True, lock_duration_s=2.0, distance_m=50.0)


class TestAllConditionsMet:
    def test_authorized(self, interlock):
        _authorize_all(interlock)
        r = interlock.check()
        assert r.authorized
        assert len(r.blocked_reasons) == 0


class TestEmergencyStop:
    def test_blocks(self, interlock):
        _authorize_all(interlock)
        interlock.set_emergency_stop(True)
        r = interlock.check()
        assert not r.authorized
        assert r.emergency_stop

    def test_release(self, interlock):
        _authorize_all(interlock)
        interlock.set_emergency_stop(True)
        interlock.set_emergency_stop(False)
        r = interlock.check()
        assert r.authorized


class TestOperatorAuth:
    def test_no_auth_blocks(self, interlock):
        interlock.update_system_status(True, True)
        interlock.update_target_status(True, 2.0, 50.0)
        r = interlock.check()
        assert not r.authorized
        assert any("OPERATOR" in x for x in r.blocked_reasons)

    def test_auth_not_required(self):
        il = SafetyInterlock(SafetyInterlockConfig(require_operator_auth=False))
        il.update_system_status(True, True)
        il.update_target_status(True, 2.0, 50.0)
        r = il.check()
        assert r.authorized


class TestHeartbeat:
    def test_timeout_blocks(self):
        il = SafetyInterlock(
            SafetyInterlockConfig(
                require_operator_auth=True,
                heartbeat_timeout_s=0.001,
            )
        )
        il.set_operator_auth(True)
        il.update_system_status(True, True)
        il.update_target_status(True, 2.0, 50.0)
        time.sleep(0.01)
        r = il.check()
        assert not r.authorized
        assert any("HEARTBEAT" in x for x in r.blocked_reasons)

    def test_heartbeat_refreshes(self, interlock):
        _authorize_all(interlock)
        interlock.operator_heartbeat()
        r = interlock.check()
        assert r.authorized


class TestSystemStatus:
    def test_comms_failure(self, interlock):
        _authorize_all(interlock)
        interlock.update_system_status(comms_ok=False, sensors_ok=True)
        r = interlock.check()
        assert not r.authorized
        assert any("COMMS" in x for x in r.blocked_reasons)

    def test_sensor_failure(self, interlock):
        _authorize_all(interlock)
        interlock.update_system_status(comms_ok=True, sensors_ok=False)
        r = interlock.check()
        assert not r.authorized
        assert any("SENSOR" in x for x in r.blocked_reasons)


class TestTargetStatus:
    def test_not_locked(self, interlock):
        interlock.set_operator_auth(True)
        interlock.update_system_status(True, True)
        interlock.update_target_status(locked=False, distance_m=50.0)
        r = interlock.check()
        assert not r.authorized

    def test_lock_too_short(self, interlock):
        interlock.set_operator_auth(True)
        interlock.update_system_status(True, True)
        interlock.update_target_status(locked=True, lock_duration_s=0.3, distance_m=50.0)
        r = interlock.check()
        assert not r.authorized
        assert any("LOCK_TOO_SHORT" in x for x in r.blocked_reasons)

    def test_too_close(self, interlock):
        interlock.set_operator_auth(True)
        interlock.update_system_status(True, True)
        interlock.update_target_status(locked=True, lock_duration_s=2.0, distance_m=2.0)
        r = interlock.check()
        assert not r.authorized
        assert any("TOO_CLOSE" in x for x in r.blocked_reasons)

    def test_too_far(self, interlock):
        interlock.set_operator_auth(True)
        interlock.update_system_status(True, True)
        interlock.update_target_status(locked=True, lock_duration_s=2.0, distance_m=600.0)
        r = interlock.check()
        assert not r.authorized
        assert any("TOO_FAR" in x for x in r.blocked_reasons)

    def test_zero_distance_no_range_check(self, interlock):
        interlock.set_operator_auth(True)
        interlock.update_system_status(True, True)
        interlock.update_target_status(locked=True, lock_duration_s=2.0, distance_m=0.0)
        r = interlock.check()
        assert r.authorized  # distance=0 skips range check


class TestNFZStatus:
    def test_in_nfz_blocks(self, interlock):
        _authorize_all(interlock)
        interlock.update_nfz_status(clear=False)
        r = interlock.check()
        assert not r.authorized
        assert any("NO_FIRE_ZONE" in x for x in r.blocked_reasons)


class TestInterlockResult:
    def test_reason_string_clear(self):
        r = InterlockResult(authorized=True)
        assert r.reason_string == "CLEAR"

    def test_reason_string_blocked(self):
        r = InterlockResult(authorized=False, blocked_reasons=["A", "B"])
        assert r.reason_string == "A; B"

    def test_defaults(self):
        r = InterlockResult()
        assert not r.authorized
        assert not r.emergency_stop
        assert not r.operator_auth
