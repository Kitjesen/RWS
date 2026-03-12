"""Tests for no-fire zone CRUD API (src/rws_tracking/api/safety_routes.py)."""

from __future__ import annotations

import pytest
from flask import Flask

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_safety_manager():
    """Build a real SafetyManager (no camera/YOLO needed)."""
    from src.rws_tracking.safety.manager import SafetyManager

    return SafetyManager()


def _make_app(safety_manager=None):
    from src.rws_tracking.api.safety_routes import safety_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    if safety_manager is not None:
        app.extensions["safety_manager"] = safety_manager
    app.register_blueprint(safety_bp)
    return app


# ---------------------------------------------------------------------------
# GET /api/safety/zones (list)
# ---------------------------------------------------------------------------


class TestListZones:
    def test_no_safety_manager_returns_empty_list(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.get("/api/safety/zones")
            assert resp.status_code == 200
            assert resp.get_json() == []

    def test_lists_existing_zones(self):
        from src.rws_tracking.types import SafetyZone

        sm = _make_safety_manager()
        sm.add_no_fire_zone(
            SafetyZone(
                zone_id="z1",
                center_yaw_deg=10.0,
                center_pitch_deg=5.0,
                radius_deg=8.0,
            )
        )
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.get("/api/safety/zones")
            zones = resp.get_json()
            assert len(zones) == 1
            assert zones[0]["zone_id"] == "z1"
            assert zones[0]["center_yaw_deg"] == pytest.approx(10.0)

    def test_empty_safety_manager_returns_empty(self):
        sm = _make_safety_manager()
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.get("/api/safety/zones")
            assert resp.get_json() == []


# ---------------------------------------------------------------------------
# GET /api/safety/zones/<id>
# ---------------------------------------------------------------------------


class TestGetZone:
    def test_returns_zone_by_id(self):
        from src.rws_tracking.types import SafetyZone

        sm = _make_safety_manager()
        sm.add_no_fire_zone(
            SafetyZone(
                zone_id="hospital",
                center_yaw_deg=30.0,
                center_pitch_deg=-2.0,
                radius_deg=12.0,
            )
        )
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.get("/api/safety/zones/hospital")
            assert resp.status_code == 200
            z = resp.get_json()
            assert z["zone_id"] == "hospital"
            assert z["radius_deg"] == pytest.approx(12.0)

    def test_returns_404_for_missing_zone(self):
        sm = _make_safety_manager()
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.get("/api/safety/zones/nonexistent")
            assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/safety/zones (add)
# ---------------------------------------------------------------------------


class TestAddZone:
    def test_add_zone_success(self):
        sm = _make_safety_manager()
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.post(
                "/api/safety/zones",
                json={
                    "zone_id": "nfz_east",
                    "center_yaw_deg": 90.0,
                    "center_pitch_deg": 0.0,
                    "radius_deg": 15.0,
                },
            )
            assert resp.status_code == 201
            data = resp.get_json()
            assert data["ok"] is True
            assert data["zone_id"] == "nfz_east"

        # Verify it's actually in the manager.
        zones = sm._nfz.zones
        assert any(z.zone_id == "nfz_east" for z in zones)

    def test_auto_generates_zone_id(self):
        sm = _make_safety_manager()
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.post(
                "/api/safety/zones",
                json={
                    "center_yaw_deg": 45.0,
                    "center_pitch_deg": 0.0,
                    "radius_deg": 10.0,
                },
            )
            assert resp.status_code == 201
            zone_id = resp.get_json()["zone_id"]
            assert zone_id.startswith("nfz_")

    def test_missing_required_fields_returns_400(self):
        sm = _make_safety_manager()
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.post("/api/safety/zones", json={"center_yaw_deg": 10.0})
            assert resp.status_code == 400

    def test_negative_radius_returns_400(self):
        sm = _make_safety_manager()
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.post(
                "/api/safety/zones",
                json={
                    "center_yaw_deg": 0.0,
                    "center_pitch_deg": 0.0,
                    "radius_deg": -5.0,
                },
            )
            assert resp.status_code == 400

    def test_no_safety_manager_returns_503(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.post(
                "/api/safety/zones",
                json={
                    "center_yaw_deg": 0.0,
                    "center_pitch_deg": 0.0,
                    "radius_deg": 5.0,
                },
            )
            assert resp.status_code == 503

    def test_zero_radius_returns_400(self):
        sm = _make_safety_manager()
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.post(
                "/api/safety/zones",
                json={
                    "center_yaw_deg": 0.0,
                    "center_pitch_deg": 0.0,
                    "radius_deg": 0.0,
                },
            )
            assert resp.status_code == 400

    def test_radius_too_large_returns_400(self):
        sm = _make_safety_manager()
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.post(
                "/api/safety/zones",
                json={
                    "center_yaw_deg": 0.0,
                    "center_pitch_deg": 0.0,
                    "radius_deg": 181.0,
                },
            )
            assert resp.status_code == 400

    def test_yaw_out_of_range_returns_400(self):
        sm = _make_safety_manager()
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.post(
                "/api/safety/zones",
                json={
                    "center_yaw_deg": 270.0,
                    "center_pitch_deg": 0.0,
                    "radius_deg": 10.0,
                },
            )
            assert resp.status_code == 400

    def test_pitch_out_of_range_returns_400(self):
        sm = _make_safety_manager()
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.post(
                "/api/safety/zones",
                json={
                    "center_yaw_deg": 0.0,
                    "center_pitch_deg": -95.0,
                    "radius_deg": 10.0,
                },
            )
            assert resp.status_code == 400

    def test_boundary_yaw_180_accepted(self):
        sm = _make_safety_manager()
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.post(
                "/api/safety/zones",
                json={
                    "center_yaw_deg": 180.0,
                    "center_pitch_deg": 0.0,
                    "radius_deg": 5.0,
                },
            )
            assert resp.status_code == 201

    def test_boundary_pitch_90_accepted(self):
        sm = _make_safety_manager()
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.post(
                "/api/safety/zones",
                json={
                    "center_yaw_deg": 0.0,
                    "center_pitch_deg": -90.0,
                    "radius_deg": 5.0,
                },
            )
            assert resp.status_code == 201

    def test_radius_exactly_180_accepted(self):
        sm = _make_safety_manager()
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.post(
                "/api/safety/zones",
                json={
                    "center_yaw_deg": 0.0,
                    "center_pitch_deg": 0.0,
                    "radius_deg": 180.0,
                },
            )
            assert resp.status_code == 201


# ---------------------------------------------------------------------------
# DELETE /api/safety/zones/<id>
# ---------------------------------------------------------------------------


class TestRemoveZone:
    def test_remove_existing_zone(self):
        from src.rws_tracking.types import SafetyZone

        sm = _make_safety_manager()
        sm.add_no_fire_zone(SafetyZone(zone_id="target", radius_deg=5.0))
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.delete("/api/safety/zones/target")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["ok"] is True
            assert data["zone_id"] == "target"

        # Verify it's gone.
        assert sm._nfz._zones.get("target") is None

    def test_remove_nonexistent_zone_returns_404(self):
        sm = _make_safety_manager()
        app = _make_app(sm)
        with app.test_client() as c:
            resp = c.delete("/api/safety/zones/ghost")
            assert resp.status_code == 404

    def test_no_safety_manager_returns_503(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.delete("/api/safety/zones/any")
            assert resp.status_code == 503
