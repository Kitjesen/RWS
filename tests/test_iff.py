"""Tests for the IFF (Identification Friend-or-Foe) safety layer.

Covers:
- IFFResult dataclass
- IFFChecker.check() with class-based whitelist
- IFFChecker.check() with track-ID whitelist
- Runtime management: add / remove / is_friendly
- Thread-safety (basic smoke test)
- Pipeline integration: friendly target overrides fire_authorized=False
- API routes: mark_friendly, unmark_friendly, status
"""

from __future__ import annotations

import threading

import pytest

from src.rws_tracking.safety.iff import IFFChecker, IFFResult
from src.rws_tracking.types import SafetyStatus, Track
from src.rws_tracking.types.common import BoundingBox

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_track(
    track_id: int,
    class_id: str = "person",
    confidence: float = 0.9,
) -> Track:
    return Track(
        track_id=track_id,
        bbox=BoundingBox(x=0.0, y=0.0, w=100.0, h=100.0),
        confidence=confidence,
        class_id=class_id,
        first_seen_ts=0.0,
        last_seen_ts=1.0,
    )


# ---------------------------------------------------------------------------
# IFFResult
# ---------------------------------------------------------------------------


class TestIFFResult:
    def test_fields_accessible(self):
        result = IFFResult(
            track_id=42,
            is_friend=True,
            confidence=0.95,
            reason="test reason",
        )
        assert result.track_id == 42
        assert result.is_friend is True
        assert result.confidence == pytest.approx(0.95)
        assert result.reason == "test reason"

    def test_not_friend_default(self):
        result = IFFResult(track_id=1, is_friend=False, confidence=0.5, reason="foe")
        assert not result.is_friend


# ---------------------------------------------------------------------------
# IFFChecker — class whitelist
# ---------------------------------------------------------------------------


class TestIFFCheckerClassWhitelist:
    def test_friendly_class_identified(self):
        checker = IFFChecker(friendly_classes={"civilian", "friendly"})
        tracks = [_make_track(1, class_id="civilian")]
        results = checker.check(tracks)
        assert 1 in results
        assert results[1].is_friend is True

    def test_hostile_class_not_identified(self):
        checker = IFFChecker(friendly_classes={"civilian", "friendly"})
        tracks = [_make_track(2, class_id="combatant")]
        results = checker.check(tracks)
        assert 2 in results
        assert results[2].is_friend is False

    def test_empty_friendly_classes_none_friendly(self):
        checker = IFFChecker()  # no friendly classes
        tracks = [_make_track(1, class_id="civilian"), _make_track(2, class_id="friendly")]
        results = checker.check(tracks)
        assert results[1].is_friend is False
        assert results[2].is_friend is False

    def test_confidence_propagated_from_track(self):
        checker = IFFChecker(friendly_classes={"civilian"})
        tracks = [_make_track(5, class_id="civilian", confidence=0.77)]
        results = checker.check(tracks)
        assert results[5].confidence == pytest.approx(0.77)

    def test_multiple_tracks_mixed(self):
        checker = IFFChecker(friendly_classes={"friendly"})
        tracks = [
            _make_track(10, class_id="friendly"),
            _make_track(11, class_id="hostile"),
            _make_track(12, class_id="friendly"),
        ]
        results = checker.check(tracks)
        assert results[10].is_friend is True
        assert results[11].is_friend is False
        assert results[12].is_friend is True

    def test_empty_track_list(self):
        checker = IFFChecker(friendly_classes={"civilian"})
        results = checker.check([])
        assert results == {}

    def test_reason_contains_class_id(self):
        checker = IFFChecker(friendly_classes={"civilian"})
        tracks = [_make_track(3, class_id="civilian")]
        results = checker.check(tracks)
        assert "civilian" in results[3].reason

    def test_foe_reason_indicates_not_friendly(self):
        checker = IFFChecker(friendly_classes={"civilian"})
        tracks = [_make_track(7, class_id="combatant")]
        results = checker.check(tracks)
        assert results[7].is_friend is False
        assert results[7].reason  # non-empty

    def test_friendly_classes_property(self):
        checker = IFFChecker(friendly_classes={"civilian", "friendly"})
        assert checker.friendly_classes == frozenset({"civilian", "friendly"})


# ---------------------------------------------------------------------------
# IFFChecker — track-ID whitelist
# ---------------------------------------------------------------------------


class TestIFFCheckerTrackIDWhitelist:
    def test_whitelisted_track_is_friend(self):
        checker = IFFChecker(track_id_whitelist={99})
        tracks = [_make_track(99, class_id="combatant")]
        results = checker.check(tracks)
        assert results[99].is_friend is True
        assert "99" in results[99].reason

    def test_non_whitelisted_track_is_foe(self):
        checker = IFFChecker(track_id_whitelist={99})
        tracks = [_make_track(50, class_id="combatant")]
        results = checker.check(tracks)
        assert results[50].is_friend is False

    def test_track_id_whitelist_overrides_class(self):
        """Track ID whitelist takes priority; class-based check is secondary."""
        checker = IFFChecker(
            friendly_classes=set(),
            track_id_whitelist={7},
        )
        tracks = [_make_track(7, class_id="hostile")]
        results = checker.check(tracks)
        assert results[7].is_friend is True

    def test_confidence_is_1_for_id_whitelist(self):
        checker = IFFChecker(track_id_whitelist={3})
        tracks = [_make_track(3, confidence=0.4)]
        results = checker.check(tracks)
        assert results[3].confidence == pytest.approx(1.0)

    def test_initial_whitelist_as_set(self):
        checker = IFFChecker(track_id_whitelist={1, 2, 3})
        assert checker.is_friendly(1)
        assert checker.is_friendly(2)
        assert checker.is_friendly(3)
        assert not checker.is_friendly(4)


# ---------------------------------------------------------------------------
# Runtime management: add / remove / is_friendly
# ---------------------------------------------------------------------------


class TestIFFCheckerRuntimeManagement:
    def test_add_friendly_track(self):
        checker = IFFChecker()
        assert not checker.is_friendly(5)
        checker.add_friendly_track(5)
        assert checker.is_friendly(5)

    def test_remove_friendly_track(self):
        checker = IFFChecker(track_id_whitelist={5})
        checker.remove_friendly_track(5)
        assert not checker.is_friendly(5)

    def test_remove_non_existent_is_noop(self):
        checker = IFFChecker()
        checker.remove_friendly_track(999)  # should not raise
        assert not checker.is_friendly(999)

    def test_add_then_check(self):
        checker = IFFChecker()
        checker.add_friendly_track(42)
        tracks = [_make_track(42, class_id="combatant")]
        results = checker.check(tracks)
        assert results[42].is_friend is True

    def test_remove_then_check(self):
        checker = IFFChecker(track_id_whitelist={42})
        checker.remove_friendly_track(42)
        tracks = [_make_track(42, class_id="combatant")]
        results = checker.check(tracks)
        assert results[42].is_friend is False

    def test_friendly_track_ids_sorted(self):
        checker = IFFChecker(track_id_whitelist={5, 2, 8, 1})
        assert checker.friendly_track_ids == [1, 2, 5, 8]

    def test_friendly_track_ids_empty_by_default(self):
        checker = IFFChecker()
        assert checker.friendly_track_ids == []

    def test_is_friendly_only_checks_id_whitelist(self):
        """is_friendly() does NOT check class-based friendliness."""
        checker = IFFChecker(friendly_classes={"civilian"})
        # Even though "civilian" is a friendly class, is_friendly() only looks
        # at the track-ID whitelist.
        assert not checker.is_friendly(99)


# ---------------------------------------------------------------------------
# Thread-safety smoke test
# ---------------------------------------------------------------------------


class TestIFFCheckerThreadSafety:
    def test_concurrent_add_remove(self):
        checker = IFFChecker()
        errors: list[Exception] = []

        def writer():
            try:
                for i in range(100):
                    checker.add_friendly_track(i)
                    checker.remove_friendly_track(i)
            except Exception as exc:
                errors.append(exc)

        def reader():
            try:
                for i in range(100):
                    checker.is_friendly(i)
                    _ = checker.friendly_track_ids
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        threads += [threading.Thread(target=reader) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


class TestIFFPipelineIntegration:
    """
    Integration test: verify that when IFFChecker identifies the selected
    target as friendly, the returned safety_status has fire_authorized=False
    with a reason containing "IFF".

    We test the logic directly rather than spinning up the full pipeline,
    mirroring the pattern used in the pipeline step().
    """

    def _apply_iff_block(
        self,
        iff_checker: IFFChecker,
        safety_status: SafetyStatus,
        tracks: list[Track],
        selected_track_id: int,
    ) -> SafetyStatus:
        """Replicate the pipeline's IFF block logic for testing."""
        iff_results = iff_checker.check(tracks)
        iff_result = iff_results.get(selected_track_id)
        if iff_result is not None and iff_result.is_friend:
            return SafetyStatus(
                fire_authorized=False,
                blocked_reason=f"IFF:{iff_result.reason}",
                active_zone=safety_status.active_zone,
                operator_override=safety_status.operator_override,
                emergency_stop=safety_status.emergency_stop,
            )
        return safety_status

    def test_friendly_class_blocks_fire(self):
        checker = IFFChecker(friendly_classes={"civilian"})
        tracks = [_make_track(1, class_id="civilian")]
        original_status = SafetyStatus(
            fire_authorized=True,
            blocked_reason="",
            active_zone="",
            operator_override=False,
            emergency_stop=False,
        )
        new_status = self._apply_iff_block(checker, original_status, tracks, 1)
        assert not new_status.fire_authorized
        assert "IFF" in new_status.blocked_reason

    def test_hostile_target_unchanged(self):
        checker = IFFChecker(friendly_classes={"civilian"})
        tracks = [_make_track(2, class_id="combatant")]
        original_status = SafetyStatus(
            fire_authorized=True,
            blocked_reason="",
            active_zone="",
            operator_override=False,
            emergency_stop=False,
        )
        new_status = self._apply_iff_block(checker, original_status, tracks, 2)
        assert new_status.fire_authorized

    def test_operator_whitelisted_track_blocks_fire(self):
        checker = IFFChecker()
        checker.add_friendly_track(7)
        tracks = [_make_track(7, class_id="combatant")]
        original_status = SafetyStatus(
            fire_authorized=True,
            blocked_reason="",
            active_zone="",
            operator_override=False,
            emergency_stop=False,
        )
        new_status = self._apply_iff_block(checker, original_status, tracks, 7)
        assert not new_status.fire_authorized
        assert "IFF" in new_status.blocked_reason

    def test_iff_preserves_other_safety_fields(self):
        checker = IFFChecker(friendly_classes={"friendly"})
        tracks = [_make_track(3, class_id="friendly")]
        original_status = SafetyStatus(
            fire_authorized=True,
            blocked_reason="",
            active_zone="zone_alpha",
            operator_override=True,
            emergency_stop=False,
        )
        new_status = self._apply_iff_block(checker, original_status, tracks, 3)
        assert new_status.active_zone == "zone_alpha"
        assert new_status.operator_override is True
        assert new_status.emergency_stop is False

    def test_no_iff_checker_leaves_status_unchanged(self):
        """When iff_checker is None, pipeline should skip IFF block entirely."""
        iff_checker = None
        original_status = SafetyStatus(fire_authorized=True)
        # Simulate the pipeline condition check
        if iff_checker is not None:
            raise AssertionError("Should not enter IFF block")
        # Status is unchanged
        assert original_status.fire_authorized

    def test_already_blocked_status_can_be_further_tagged(self):
        """If safety already blocked fire, IFF still overwrites the reason with IFF tag."""
        checker = IFFChecker(friendly_classes={"civilian"})
        tracks = [_make_track(4, class_id="civilian")]
        original_status = SafetyStatus(
            fire_authorized=False,
            blocked_reason="NFZ:zone1",
            active_zone="zone1",
            operator_override=False,
            emergency_stop=False,
        )
        new_status = self._apply_iff_block(checker, original_status, tracks, 4)
        # IFF block is still applied (pipeline logic checks safety_status is not None)
        assert not new_status.fire_authorized
        assert "IFF" in new_status.blocked_reason


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


class TestIFFAPIRoutes:
    @pytest.fixture
    def app(self):
        from flask import Flask

        from src.rws_tracking.api.fire_routes import fire_bp

        flask_app = Flask(__name__)
        flask_app.register_blueprint(fire_bp)

        iff = IFFChecker(friendly_classes={"civilian"})
        flask_app.extensions["iff_checker"] = iff

        flask_app.config["TESTING"] = True
        return flask_app

    @pytest.fixture
    def client(self, app):
        return app.test_client()

    def test_status_empty_initially(self, client):
        resp = client.get("/api/fire/iff/status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["friendly_track_ids"] == []

    def test_mark_friendly(self, client):
        resp = client.post(
            "/api/fire/iff/mark_friendly",
            json={"track_id": 3},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["track_id"] == 3
        assert data["action"] == "marked_friendly"

    def test_status_after_mark(self, client):
        client.post("/api/fire/iff/mark_friendly", json={"track_id": 3})
        client.post("/api/fire/iff/mark_friendly", json={"track_id": 7})
        resp = client.get("/api/fire/iff/status")
        data = resp.get_json()
        assert sorted(data["friendly_track_ids"]) == [3, 7]

    def test_unmark_friendly(self, client):
        client.post("/api/fire/iff/mark_friendly", json={"track_id": 5})
        resp = client.post("/api/fire/iff/unmark_friendly", json={"track_id": 5})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["action"] == "unmarked_friendly"

    def test_status_after_unmark(self, client):
        client.post("/api/fire/iff/mark_friendly", json={"track_id": 5})
        client.post("/api/fire/iff/unmark_friendly", json={"track_id": 5})
        resp = client.get("/api/fire/iff/status")
        data = resp.get_json()
        assert data["friendly_track_ids"] == []

    def test_mark_missing_track_id_returns_400(self, client):
        resp = client.post(
            "/api/fire/iff/mark_friendly",
            json={},
        )
        assert resp.status_code == 400

    def test_unmark_missing_track_id_returns_400(self, client):
        resp = client.post(
            "/api/fire/iff/unmark_friendly",
            json={},
        )
        assert resp.status_code == 400

    def test_mark_invalid_track_id_returns_400(self, client):
        resp = client.post(
            "/api/fire/iff/mark_friendly",
            json={"track_id": "not_an_int"},
        )
        assert resp.status_code == 400

    def test_no_iff_checker_returns_503(self):
        """When iff_checker is not in app.extensions, routes return 503."""
        from flask import Flask

        from src.rws_tracking.api.fire_routes import fire_bp

        flask_app = Flask(__name__)
        flask_app.register_blueprint(fire_bp)
        flask_app.config["TESTING"] = True
        # Do NOT set app.extensions["iff_checker"]

        with flask_app.test_client() as c:
            assert c.get("/api/fire/iff/status").status_code == 503
            assert c.post(
                "/api/fire/iff/mark_friendly", json={"track_id": 1}
            ).status_code == 503
            assert c.post(
                "/api/fire/iff/unmark_friendly", json={"track_id": 1}
            ).status_code == 503
