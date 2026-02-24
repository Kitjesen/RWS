"""类型定义单元测试。"""


from src.rws_tracking.types import (
    BallisticSolution,
    BodyState,
    BoundingBox,
    ControlCommand,
    Detection,
    EnvironmentParams,
    GimbalFeedback,
    LeadAngle,
    ProjectileParams,
    RangefinderReading,
    SafetyStatus,
    SafetyZone,
    TargetError,
    TargetObservation,
    ThreatAssessment,
    Track,
    TrackState,
)


class TestBoundingBox:
    def test_area(self):
        b = BoundingBox(x=0, y=0, w=100, h=50)
        assert b.area == 5000.0

    def test_center(self):
        b = BoundingBox(x=10, y=20, w=100, h=50)
        cx, cy = b.center
        assert cx == 60.0
        assert cy == 45.0

    def test_zero_area(self):
        b = BoundingBox(x=0, y=0, w=0, h=0)
        assert b.area == 0.0


class TestTrackState:
    def test_values(self):
        # TrackState uses string values for serialization/logging
        assert TrackState.SEARCH.value == "search"
        assert TrackState.TRACK.value == "track"
        assert TrackState.LOCK.value == "lock"
        assert TrackState.LOST.value == "lost"
        # All four states are distinct
        values = {s.value for s in TrackState}
        assert len(values) == 4


class TestDetection:
    def test_creation(self):
        d = Detection(
            bbox=BoundingBox(x=10, y=20, w=30, h=40),
            confidence=0.95,
            class_id="person",
        )
        assert d.confidence == 0.95
        assert d.class_id == "person"


class TestTrack:
    def test_creation(self):
        t = Track(
            track_id=1,
            bbox=BoundingBox(x=10, y=20, w=30, h=40),
            confidence=0.9,
            class_id="person",
            first_seen_ts=0.0,
            last_seen_ts=1.0,
            age_frames=30,
        )
        assert t.track_id == 1
        assert t.age_frames == 30

    def test_default_velocity(self):
        t = Track(
            track_id=1,
            bbox=BoundingBox(x=0, y=0, w=10, h=10),
            confidence=0.9,
            class_id="x",
            first_seen_ts=0.0,
            last_seen_ts=0.0,
        )
        assert t.velocity_px_per_s == (0.0, 0.0)


class TestTargetObservation:
    def test_creation(self):
        obs = TargetObservation(
            timestamp=1.0,
            track_id=5,
            bbox=BoundingBox(x=100, y=200, w=50, h=80),
            confidence=0.88,
            class_id="vehicle",
        )
        assert obs.track_id == 5


class TestControlCommand:
    def test_creation(self):
        cmd = ControlCommand(
            yaw_rate_cmd_dps=10.0,
            pitch_rate_cmd_dps=-5.0,
        )
        assert cmd.yaw_rate_cmd_dps == 10.0

    def test_metadata(self):
        cmd = ControlCommand(
            yaw_rate_cmd_dps=0.0,
            pitch_rate_cmd_dps=0.0,
            metadata={"state": 2.0},
        )
        assert cmd.metadata["state"] == 2.0


class TestGimbalFeedback:
    def test_creation(self):
        fb = GimbalFeedback(
            timestamp=1.0,
            yaw_deg=45.0,
            pitch_deg=-10.0,
            yaw_rate_dps=5.0,
            pitch_rate_dps=-2.0,
        )
        assert fb.yaw_deg == 45.0


class TestBallisticSolution:
    def test_defaults(self):
        sol = BallisticSolution(distance_m=100.0)
        assert sol.flight_time_s == 0.0
        assert sol.drop_deg == 0.0
        assert sol.windage_deg == 0.0


class TestEnvironmentParams:
    def test_defaults(self):
        env = EnvironmentParams()
        assert env.temperature_c == 15.0
        assert env.pressure_hpa == 1013.25


class TestProjectileParams:
    def test_defaults(self):
        p = ProjectileParams()
        assert p.muzzle_velocity_mps > 0


class TestSafetyZone:
    def test_creation(self):
        z = SafetyZone(
            zone_id="test",
            center_yaw_deg=90.0,
            center_pitch_deg=0.0,
            radius_deg=10.0,
            zone_type="no_fire",
        )
        assert z.zone_id == "test"
        assert z.zone_type == "no_fire"


class TestSafetyStatus:
    def test_creation(self):
        s = SafetyStatus(
            fire_authorized=True,
            blocked_reason="",
            active_zone="",
        )
        assert s.fire_authorized


class TestBodyState:
    def test_creation(self):
        bs = BodyState(
            timestamp=0.0,
            yaw_rate_dps=5.0,
            pitch_rate_dps=3.0,
            roll_rate_dps=1.0,
        )
        assert bs.yaw_rate_dps == 5.0


class TestLeadAngle:
    def test_defaults(self):
        la = LeadAngle()
        assert la.yaw_lead_deg == 0.0
        assert la.pitch_lead_deg == 0.0


class TestThreatAssessment:
    def test_creation(self):
        ta = ThreatAssessment(
            track_id=1,
            threat_score=0.85,
            distance_score=0.7,
            velocity_score=0.6,
            class_score=0.9,
            heading_score=0.5,
            priority_rank=1,
        )
        assert ta.threat_score == 0.85


class TestTargetError:
    def test_creation(self):
        te = TargetError(
            timestamp=1.0,
            yaw_error_deg=2.5,
            pitch_error_deg=-1.3,
            target_id=42,
        )
        assert te.target_id == 42


class TestRangefinderReading:
    def test_creation(self):
        r = RangefinderReading(distance_m=50.0, valid=True, timestamp=1.0)
        assert r.distance_m == 50.0
        assert r.valid
