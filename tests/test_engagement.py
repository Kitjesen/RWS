"""威胁评估与交战排序模块单元测试。"""

import pytest

from src.rws_tracking.decision.engagement import (
    EngagementConfig,
    EngagementQueue,
    ThreatAssessor,
    ThreatWeights,
)
from src.rws_tracking.types import BoundingBox, Track, ThreatAssessment


def _track(tid=1, x=600, y=340, w=80, h=150, cls="person", vx=5.0, vy=2.0):
    return Track(
        track_id=tid, bbox=BoundingBox(x=x, y=y, w=w, h=h),
        confidence=0.9, class_id=cls, first_seen_ts=0.0, last_seen_ts=0.0,
        age_frames=10, velocity_px_per_s=(vx, vy),
    )


class TestThreatAssessor:
    @pytest.fixture
    def assessor(self):
        return ThreatAssessor(1280, 720, 970.0)

    def test_single_target(self, assessor):
        r = assessor.assess([_track()])
        assert len(r) == 1
        assert r[0].threat_score > 0.0
        assert r[0].priority_rank == 1

    def test_empty_tracks(self, assessor):
        assert assessor.assess([]) == []

    def test_near_beats_far(self, assessor):
        near = _track(tid=1, h=200)  # close
        far = _track(tid=2, h=50)    # far
        r = assessor.assess([near, far])
        assert r[0].threat_score >= r[1].threat_score

    def test_ranking_assigned(self, assessor):
        r = assessor.assess([_track(tid=1), _track(tid=2, x=100)])
        assert r[0].priority_rank == 1
        assert r[1].priority_rank == 2

    def test_out_of_range_filtered(self):
        cfg = EngagementConfig(max_engagement_range_m=1.0)
        a = ThreatAssessor(1280, 720, 970.0, config=cfg)
        r = a.assess([_track(h=10)])  # very far
        assert len(r) == 0

    def test_below_threshold_filtered(self):
        cfg = EngagementConfig(min_threat_threshold=0.99)
        a = ThreatAssessor(1280, 720, 970.0, config=cfg)
        r = a.assess([_track()])
        assert len(r) == 0

    def test_nearest_first_strategy(self):
        cfg = EngagementConfig(strategy="nearest_first")
        a = ThreatAssessor(1280, 720, 970.0, config=cfg)
        near = _track(tid=1, h=200)
        far = _track(tid=2, h=50)
        r = a.assess([far, near])
        assert r[0].track_id == 1  # near first

    def test_sector_sweep_strategy(self):
        cfg = EngagementConfig(strategy="sector_sweep", sector_size_deg=30.0)
        a = ThreatAssessor(1280, 720, 970.0, config=cfg)
        left = _track(tid=1, x=100)
        right = _track(tid=2, x=1100)
        r = a.assess([right, left])
        assert len(r) == 2

    def test_class_score(self):
        cfg = EngagementConfig()
        cfg.class_threat_levels["person"] = 1.0
        cfg.class_threat_levels["car"] = 0.1
        a = ThreatAssessor(1280, 720, 970.0, config=cfg)
        person = _track(tid=1, cls="person", h=100)
        car = _track(tid=2, cls="car", h=100)
        r = a.assess([person, car])
        scores = {x.track_id: x.threat_score for x in r}
        assert scores[1] > scores[2]

    def test_approaching_target_higher_velocity_score(self, assessor):
        approaching = _track(tid=1, x=200, vx=100.0, vy=0.0)  # moving toward center
        retreating = _track(tid=2, x=200, vx=-100.0, vy=0.0)  # moving away
        r = assessor.assess([approaching, retreating])
        scores = {x.track_id: x.velocity_score for x in r}
        assert scores[1] > scores[2]


class TestEngagementQueue:
    @pytest.fixture
    def queue(self):
        return EngagementQueue()

    def _assessments(self, n=3):
        return [
            ThreatAssessment(track_id=i, threat_score=1.0 - i * 0.1,
                             distance_score=0.5, velocity_score=0.5,
                             class_score=0.5, heading_score=0.5, priority_rank=i + 1)
            for i in range(n)
        ]

    def test_empty_queue(self, queue):
        assert queue.current_target_id is None
        assert queue.remaining == 0

    def test_update_sets_queue(self, queue):
        queue.update(self._assessments())
        assert queue.current_target_id == 0
        assert queue.remaining == 3

    def test_advance(self, queue):
        queue.update(self._assessments())
        next_id = queue.advance()
        assert next_id == 1
        assert queue.remaining == 2

    def test_advance_exhausts_queue(self, queue):
        queue.update(self._assessments(2))
        queue.advance()
        next_id = queue.advance()
        assert next_id is None
        assert queue.remaining == 0

    def test_skip(self, queue):
        queue.update(self._assessments())
        next_id = queue.skip()
        assert next_id == 1

    def test_update_preserves_current(self, queue):
        queue.update(self._assessments())
        queue.advance()  # now at track_id=1
        new_assessments = self._assessments()
        queue.update(new_assessments)
        assert queue.current_target_id == 1

    def test_update_resets_if_current_gone(self, queue):
        queue.update(self._assessments())
        queue.advance()  # now at track_id=1
        # New list without track_id=1
        new = [ThreatAssessment(track_id=99, threat_score=0.9,
                                distance_score=0.5, velocity_score=0.5,
                                class_score=0.5, heading_score=0.5, priority_rank=1)]
        queue.update(new)
        assert queue.current_target_id == 99

    def test_reset(self, queue):
        queue.update(self._assessments())
        queue.reset()
        assert queue.current_target_id is None
        assert queue.remaining == 0
