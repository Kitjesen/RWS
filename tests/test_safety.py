"""安全管理器、联锁系统、禁射区单元测试。"""

from __future__ import annotations

import pytest

from src.rws_tracking.safety.interlock import SafetyInterlock, SafetyInterlockConfig
from src.rws_tracking.safety.manager import SafetyManager, SafetyManagerConfig
from src.rws_tracking.types import SafetyZone


class TestSafetyInterlock:
    @pytest.fixture
    def interlock(self) -> SafetyInterlock:
        cfg = SafetyInterlockConfig(
            require_operator_auth=True,
            min_lock_time_s=1.0,
            min_engagement_range_m=5.0,
            max_engagement_range_m=500.0,
            heartbeat_timeout_s=100.0,
        )
        return SafetyInterlock(cfg)

    def test_all_conditions_met_allows_fire(self, interlock: SafetyInterlock):
        interlock.set_operator_auth(True)
        interlock.update_system_status(comms_ok=True, sensors_ok=True)
        interlock.update_target_status(locked=True, lock_duration_s=2.0, distance_m=50.0)
        result = interlock.check()
        assert result.authorized

    def test_no_operator_auth_blocks(self, interlock: SafetyInterlock):
        interlock.update_system_status(comms_ok=True, sensors_ok=True)
        interlock.update_target_status(locked=True, lock_duration_s=2.0, distance_m=50.0)
        result = interlock.check()
        assert not result.authorized
        assert any("OPERATOR" in r for r in result.blocked_reasons)

    def test_emergency_stop_blocks(self, interlock: SafetyInterlock):
        interlock.set_operator_auth(True)
        interlock.update_system_status(comms_ok=True, sensors_ok=True)
        interlock.update_target_status(locked=True, lock_duration_s=2.0, distance_m=50.0)
        interlock.set_emergency_stop(True)
        result = interlock.check()
        assert not result.authorized
        assert result.emergency_stop

    def test_lock_too_short_blocks(self, interlock: SafetyInterlock):
        interlock.set_operator_auth(True)
        interlock.update_system_status(comms_ok=True, sensors_ok=True)
        interlock.update_target_status(locked=True, lock_duration_s=0.3, distance_m=50.0)
        result = interlock.check()
        assert not result.authorized
        assert any("LOCK_TOO_SHORT" in r for r in result.blocked_reasons)

    def test_too_close_blocks(self, interlock: SafetyInterlock):
        interlock.set_operator_auth(True)
        interlock.update_system_status(comms_ok=True, sensors_ok=True)
        interlock.update_target_status(locked=True, lock_duration_s=2.0, distance_m=2.0)
        result = interlock.check()
        assert not result.authorized
        assert any("TOO_CLOSE" in r for r in result.blocked_reasons)

    def test_too_far_blocks(self, interlock: SafetyInterlock):
        interlock.set_operator_auth(True)
        interlock.update_system_status(comms_ok=True, sensors_ok=True)
        interlock.update_target_status(locked=True, lock_duration_s=2.0, distance_m=600.0)
        result = interlock.check()
        assert not result.authorized
        assert any("TOO_FAR" in r for r in result.blocked_reasons)

    def test_target_not_locked_blocks(self, interlock: SafetyInterlock):
        interlock.set_operator_auth(True)
        interlock.update_system_status(comms_ok=True, sensors_ok=True)
        interlock.update_target_status(locked=False, distance_m=50.0)
        result = interlock.check()
        assert not result.authorized

    def test_comms_failure_blocks(self, interlock: SafetyInterlock):
        interlock.set_operator_auth(True)
        interlock.update_system_status(comms_ok=False, sensors_ok=True)
        interlock.update_target_status(locked=True, lock_duration_s=2.0, distance_m=50.0)
        result = interlock.check()
        assert not result.authorized
        assert any("COMMS" in r for r in result.blocked_reasons)


class TestSafetyManager:
    @pytest.fixture
    def manager(self) -> SafetyManager:
        zone = SafetyZone(
            zone_id="test_nfz",
            center_yaw_deg=90.0,
            center_pitch_deg=0.0,
            radius_deg=10.0,
            zone_type="no_fire",
        )
        cfg = SafetyManagerConfig(
            interlock=SafetyInterlockConfig(
                require_operator_auth=False,
                heartbeat_timeout_s=100.0,
            ),
            nfz_slow_down_margin_deg=5.0,
            zones=(zone,),
        )
        mgr = SafetyManager(cfg)
        mgr.update_system_status(comms_ok=True, sensors_ok=True)
        return mgr

    def test_clear_position_allows_fire(self, manager: SafetyManager):
        status = manager.evaluate(
            yaw_deg=0.0, pitch_deg=0.0,
            target_locked=True, lock_duration_s=2.0, target_distance_m=50.0,
        )
        assert status.fire_authorized

    def test_nfz_blocks_fire(self, manager: SafetyManager):
        status = manager.evaluate(
            yaw_deg=90.0, pitch_deg=0.0,
            target_locked=True, lock_duration_s=2.0, target_distance_m=50.0,
        )
        assert not status.fire_authorized
        assert "NFZ" in status.blocked_reason

    def test_speed_factor_away_from_nfz(self, manager: SafetyManager):
        factor = manager.get_speed_factor(0.0, 0.0)
        assert factor == 1.0

    def test_speed_factor_inside_nfz(self, manager: SafetyManager):
        factor = manager.get_speed_factor(90.0, 0.0)
        assert factor < 1.0

    def test_add_and_remove_nfz(self, manager: SafetyManager):
        new_zone = SafetyZone(zone_id="tmp", center_yaw_deg=0.0, center_pitch_deg=0.0, radius_deg=5.0)
        manager.add_no_fire_zone(new_zone)
        status = manager.evaluate(
            yaw_deg=0.0, pitch_deg=0.0,
            target_locked=True, lock_duration_s=2.0, target_distance_m=50.0,
        )
        assert not status.fire_authorized

        removed = manager.remove_no_fire_zone("tmp")
        assert removed
        status = manager.evaluate(
            yaw_deg=0.0, pitch_deg=0.0,
            target_locked=True, lock_duration_s=2.0, target_distance_m=50.0,
        )
        assert status.fire_authorized
