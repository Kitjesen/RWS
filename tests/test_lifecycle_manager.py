"""Tests for TargetLifecycleManager (Task E)."""

from __future__ import annotations

import pytest

from src.rws_tracking.decision.lifecycle import (
    TargetLifecycleManager,
    TargetState,
)
from src.rws_tracking.types import BoundingBox, ThreatAssessment, Track


def _make_track(track_id: int, age: int = 1, class_id: str = "person") -> Track:
    return Track(
        track_id=track_id,
        bbox=BoundingBox(x=100.0, y=100.0, w=50.0, h=100.0),
        confidence=0.9,
        class_id=class_id,
        first_seen_ts=0.0,
        last_seen_ts=0.0,
        age_frames=age,
    )


def _make_assessment(track_id: int, score: float = 0.5) -> ThreatAssessment:
    return ThreatAssessment(
        track_id=track_id,
        threat_score=score,
        distance_score=0.5,
        velocity_score=0.5,
        class_score=0.5,
        heading_score=0.5,
        priority_rank=1,
    )


# ---------------------------------------------------------------------------


class TestDetectedToTracked:
    def test_new_target_starts_detected(self):
        mgr = TargetLifecycleManager(confirm_age_frames=3)
        mgr.update([_make_track(1, age=1)], [], timestamp=0.0)
        assert mgr.get_record(1).state == TargetState.DETECTED

    def test_promoted_to_tracked_at_confirm_age(self):
        mgr = TargetLifecycleManager(confirm_age_frames=3)
        mgr.update([_make_track(1, age=3)], [], timestamp=1.0)
        assert mgr.get_record(1).state == TargetState.TRACKED

    def test_not_promoted_before_confirm_age(self):
        mgr = TargetLifecycleManager(confirm_age_frames=3)
        mgr.update([_make_track(1, age=2)], [], timestamp=1.0)
        assert mgr.get_record(1).state == TargetState.DETECTED


class TestTrackedToAssessed:
    def test_assessed_after_threat_score(self):
        mgr = TargetLifecycleManager(confirm_age_frames=1)
        mgr.update(
            [_make_track(1, age=5)],
            [_make_assessment(1, 0.7)],
            timestamp=1.0,
        )
        rec = mgr.get_record(1)
        assert rec.state == TargetState.ASSESSED
        assert rec.threat_score == pytest.approx(0.7)

    def test_no_assessment_stays_tracked(self):
        mgr = TargetLifecycleManager(confirm_age_frames=1)
        mgr.update([_make_track(1, age=5)], [], timestamp=1.0)
        assert mgr.get_record(1).state == TargetState.TRACKED


class TestNeutralized:
    def test_mark_neutralized_prevents_reengagement(self):
        mgr = TargetLifecycleManager()
        mgr.update([_make_track(1, age=5)], [], timestamp=0.0)
        mgr.mark_neutralized(1, timestamp=1.0)

        rec = mgr.get_record(1)
        assert rec.state == TargetState.NEUTRALIZED
        assert rec.neutralized_at_ts == pytest.approx(1.0)

    def test_filter_active_excludes_neutralized(self):
        mgr = TargetLifecycleManager()
        tracks = [_make_track(1), _make_track(2)]
        mgr.update(tracks, [], timestamp=0.0)
        mgr.mark_neutralized(1, timestamp=1.0)

        active = mgr.filter_active(tracks)
        assert len(active) == 1
        assert active[0].track_id == 2


class TestArchived:
    def test_gone_target_archived_after_timeout(self):
        mgr = TargetLifecycleManager(archive_after_s=5.0)
        mgr.update([_make_track(1, age=3)], [], timestamp=0.0)
        # Target disappears; advance time past archive threshold
        mgr.update([], [], timestamp=10.0)
        assert mgr.get_record(1).state == TargetState.ARCHIVED

    def test_filter_active_excludes_archived(self):
        mgr = TargetLifecycleManager(archive_after_s=5.0)
        tracks = [_make_track(1)]
        mgr.update(tracks, [], timestamp=0.0)
        mgr.update([], [], timestamp=10.0)

        active = mgr.filter_active(tracks)
        assert len(active) == 0

    def test_gone_target_not_archived_before_timeout(self):
        mgr = TargetLifecycleManager(archive_after_s=10.0)
        mgr.update([_make_track(1, age=3)], [], timestamp=0.0)
        mgr.update([], [], timestamp=5.0)
        assert mgr.get_record(1).state != TargetState.ARCHIVED


class TestSummary:
    def test_summary_counts_states(self):
        mgr = TargetLifecycleManager(confirm_age_frames=1)
        mgr.update(
            [_make_track(1, age=5), _make_track(2, age=1)],
            [],
            timestamp=0.0,
        )
        mgr.mark_neutralized(1, timestamp=1.0)
        s = mgr.summary()
        assert s["total_seen"] == 2
        assert 1 in s["neutralized_ids"]

    def test_reset_clears_records(self):
        mgr = TargetLifecycleManager()
        mgr.update([_make_track(1)], [], timestamp=0.0)
        mgr.reset()
        assert mgr.summary()["total_seen"] == 0


class TestIsActive:
    def test_unknown_target_is_active(self):
        mgr = TargetLifecycleManager()
        assert mgr.is_active(999) is True

    def test_neutralized_is_not_active(self):
        mgr = TargetLifecycleManager()
        mgr.update([_make_track(1)], [], timestamp=0.0)
        mgr.mark_neutralized(1, timestamp=0.5)
        assert mgr.is_active(1) is False

    def test_tracked_is_active(self):
        mgr = TargetLifecycleManager(confirm_age_frames=1)
        mgr.update([_make_track(1, age=5)], [], timestamp=0.0)
        assert mgr.is_active(1) is True
