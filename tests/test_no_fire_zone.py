"""禁射区管理器单元测试。"""


import pytest

from src.rws_tracking.safety.no_fire_zone import NFZCheckResult, NoFireZoneManager
from src.rws_tracking.types import SafetyZone


@pytest.fixture
def nfz():
    mgr = NoFireZoneManager(slow_down_margin_deg=5.0)
    mgr.add_zone(SafetyZone(
        zone_id="nfz1", center_yaw_deg=90.0, center_pitch_deg=0.0,
        radius_deg=10.0, zone_type="no_fire",
    ))
    return mgr


class TestZoneManagement:
    def test_add_zone(self):
        mgr = NoFireZoneManager()
        mgr.add_zone(SafetyZone(zone_id="z1", center_yaw_deg=0.0,
                                center_pitch_deg=0.0, radius_deg=5.0))
        assert len(mgr.zones) == 1

    def test_remove_zone(self):
        mgr = NoFireZoneManager()
        mgr.add_zone(SafetyZone(zone_id="z1", center_yaw_deg=0.0,
                                center_pitch_deg=0.0, radius_deg=5.0))
        assert mgr.remove_zone("z1")
        assert len(mgr.zones) == 0

    def test_remove_nonexistent(self):
        mgr = NoFireZoneManager()
        assert not mgr.remove_zone("nope")

    def test_clear(self):
        mgr = NoFireZoneManager()
        mgr.add_zone(SafetyZone(zone_id="z1", center_yaw_deg=0.0,
                                center_pitch_deg=0.0, radius_deg=5.0))
        mgr.add_zone(SafetyZone(zone_id="z2", center_yaw_deg=10.0,
                                center_pitch_deg=0.0, radius_deg=5.0))
        mgr.clear()
        assert len(mgr.zones) == 0

    def test_update_zone(self):
        mgr = NoFireZoneManager()
        mgr.add_zone(SafetyZone(zone_id="z1", center_yaw_deg=0.0,
                                center_pitch_deg=0.0, radius_deg=5.0))
        mgr.add_zone(SafetyZone(zone_id="z1", center_yaw_deg=10.0,
                                center_pitch_deg=0.0, radius_deg=5.0))
        assert len(mgr.zones) == 1
        assert mgr.zones[0].center_yaw_deg == 10.0


class TestNoFireCheck:
    def test_inside_nfz_blocks(self, nfz):
        result = nfz.check(90.0, 0.0)
        assert result.fire_blocked
        assert result.active_zone_id == "nfz1"

    def test_outside_nfz_clear(self, nfz):
        result = nfz.check(0.0, 0.0)
        assert not result.fire_blocked

    def test_on_boundary(self, nfz):
        result = nfz.check(80.0, 0.0)  # exactly on boundary
        assert not result.fire_blocked

    def test_just_inside(self, nfz):
        result = nfz.check(81.0, 0.0)  # just inside
        assert result.fire_blocked


class TestCautionZone:
    def test_caution_zone_no_block(self):
        mgr = NoFireZoneManager()
        mgr.add_zone(SafetyZone(zone_id="caution1", center_yaw_deg=0.0,
                                center_pitch_deg=0.0, radius_deg=10.0,
                                zone_type="caution"))
        result = mgr.check(0.0, 0.0)
        assert not result.fire_blocked
        assert result.in_caution_zone

    def test_caution_speed_factor(self):
        mgr = NoFireZoneManager()
        mgr.add_zone(SafetyZone(zone_id="caution1", center_yaw_deg=0.0,
                                center_pitch_deg=0.0, radius_deg=10.0,
                                zone_type="caution"))
        result = mgr.check(0.0, 0.0)
        assert result.speed_factor == pytest.approx(0.3)


class TestSpeedFactor:
    def test_far_from_nfz_full_speed(self, nfz):
        result = nfz.check(0.0, 0.0)
        assert result.speed_factor == 1.0

    def test_inside_nfz_zero_speed(self, nfz):
        result = nfz.check(90.0, 0.0)
        assert result.speed_factor == 0.0

    def test_in_margin_reduced_speed(self, nfz):
        # margin is 5 deg, boundary at 80 deg
        result = nfz.check(77.0, 0.0)  # 3 deg from boundary
        assert 0.0 < result.speed_factor < 1.0

    def test_no_zones_full_speed(self):
        mgr = NoFireZoneManager()
        result = mgr.check(0.0, 0.0)
        assert result.speed_factor == 1.0


class TestMultipleZones:
    def test_multiple_nfz(self):
        mgr = NoFireZoneManager()
        mgr.add_zone(SafetyZone(zone_id="z1", center_yaw_deg=0.0,
                                center_pitch_deg=0.0, radius_deg=5.0,
                                zone_type="no_fire"))
        mgr.add_zone(SafetyZone(zone_id="z2", center_yaw_deg=90.0,
                                center_pitch_deg=0.0, radius_deg=5.0,
                                zone_type="no_fire"))
        assert nfz_check(mgr, 0.0, 0.0).fire_blocked
        assert nfz_check(mgr, 90.0, 0.0).fire_blocked
        assert not nfz_check(mgr, 45.0, 0.0).fire_blocked


def nfz_check(mgr, yaw, pitch):
    return mgr.check(yaw, pitch)


class TestNFZCheckResult:
    def test_defaults(self):
        r = NFZCheckResult()
        assert not r.fire_blocked
        assert not r.in_caution_zone
        assert r.speed_factor == 1.0
        assert r.closest_zone is None
