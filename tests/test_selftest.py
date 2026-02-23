"""Tests for the /api/selftest and /api/fire/heartbeat endpoints.

Actual selftest response structure:
    {
        "go": bool,
        "passed": int,
        "failed": int,
        "timestamp": float,
        "checks": [
            {"name": str, "status": "pass"|"fail", "message": str, "elapsed_ms": float},
            ...
        ]
    }
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_selftest_app():
    from src.rws_tracking.api.selftest_routes import selftest_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(selftest_bp)
    return app


def _make_heartbeat_app(watchdog=None):
    from src.rws_tracking.api.fire_routes import fire_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    if watchdog is not None:
        app.extensions["operator_watchdog"] = watchdog
    app.register_blueprint(fire_bp)
    return app


def _make_health_app():
    from src.rws_tracking.api.health_routes import health_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(health_bp)
    return app


def _run_selftest(client):
    resp = client.get("/api/selftest")
    return resp, resp.get_json()


# ---------------------------------------------------------------------------
# GET /api/selftest
# ---------------------------------------------------------------------------


class TestSelftestEndpoint:
    def test_selftest_responds(self):
        """Selftest returns 200 (all pass) or 424 (some fail) — never 5xx."""
        app = _make_selftest_app()
        with app.test_client() as c:
            resp, _ = _run_selftest(c)
            assert resp.status_code in (200, 424)

    def test_selftest_response_has_go_field(self):
        app = _make_selftest_app()
        with app.test_client() as c:
            _, data = _run_selftest(c)
            assert "go" in data
            assert isinstance(data["go"], bool)

    def test_selftest_response_has_checks_list(self):
        app = _make_selftest_app()
        with app.test_client() as c:
            _, data = _run_selftest(c)
            assert "checks" in data
            assert isinstance(data["checks"], list)
            assert len(data["checks"]) > 0

    def test_selftest_checks_have_name_status_message(self):
        app = _make_selftest_app()
        with app.test_client() as c:
            _, data = _run_selftest(c)
            for check in data["checks"]:
                assert "name" in check, f"Check missing 'name': {check}"
                assert "status" in check, f"Check missing 'status': {check}"
                assert "message" in check, f"Check missing 'message': {check}"

    def test_selftest_check_status_values(self):
        app = _make_selftest_app()
        with app.test_client() as c:
            _, data = _run_selftest(c)
            for check in data["checks"]:
                assert check["status"] in ("pass", "fail"), (
                    f"Unexpected status {check['status']!r} in {check['name']!r}"
                )

    def test_selftest_covers_pipeline_imports(self):
        app = _make_selftest_app()
        with app.test_client() as c:
            _, data = _run_selftest(c)
            names = {c["name"] for c in data["checks"]}
            assert "pipeline_imports" in names

    def test_selftest_covers_config_valid(self):
        app = _make_selftest_app()
        with app.test_client() as c:
            _, data = _run_selftest(c)
            names = {c["name"] for c in data["checks"]}
            assert "config_valid" in names

    def test_selftest_covers_logs_dir(self):
        app = _make_selftest_app()
        with app.test_client() as c:
            _, data = _run_selftest(c)
            names = {c["name"] for c in data["checks"]}
            assert "logs_dir_writable" in names

    def test_selftest_go_matches_status_counts(self):
        """go == True iff all checks pass."""
        app = _make_selftest_app()
        with app.test_client() as c:
            _, data = _run_selftest(c)
            all_pass = all(ch["status"] == "pass" for ch in data["checks"])
            assert data["go"] == all_pass

    def test_selftest_has_passed_and_failed_counts(self):
        app = _make_selftest_app()
        with app.test_client() as c:
            _, data = _run_selftest(c)
            assert "passed" in data
            assert "failed" in data
            assert data["passed"] + data["failed"] == len(data["checks"])

    def test_selftest_pipeline_imports_passes(self):
        """pipeline_imports check should always pass in a correct install."""
        app = _make_selftest_app()
        with app.test_client() as c:
            _, data = _run_selftest(c)
            imports_check = next(
                (ch for ch in data["checks"] if ch["name"] == "pipeline_imports"),
                None,
            )
            assert imports_check is not None
            assert imports_check["status"] == "pass"

    def test_selftest_summary_returns_200_or_424(self):
        app = _make_selftest_app()
        with app.test_client() as c:
            resp = c.get("/api/selftest/summary")
            assert resp.status_code in (200, 424)

    def test_selftest_summary_has_go_field(self):
        app = _make_selftest_app()
        with app.test_client() as c:
            resp = c.get("/api/selftest/summary")
            data = resp.get_json()
            assert "go" in data
            assert isinstance(data["go"], bool)


# ---------------------------------------------------------------------------
# POST /api/fire/heartbeat
# ---------------------------------------------------------------------------


class TestOperatorHeartbeat:
    def test_heartbeat_no_watchdog_does_not_crash(self):
        """Without a watchdog, heartbeat returns 200 or 503 (not 5xx crash)."""
        app = _make_heartbeat_app()
        with app.test_client() as c:
            resp = c.post(
                "/api/fire/heartbeat",
                json={"operator_id": "op_test"},
            )
            assert resp.status_code in (200, 503)

    def test_heartbeat_with_watchdog_returns_200(self):
        watchdog = MagicMock()
        app = _make_heartbeat_app(watchdog=watchdog)
        with app.test_client() as c:
            resp = c.post(
                "/api/fire/heartbeat",
                json={"operator_id": "op_test"},
            )
            assert resp.status_code == 200

    def test_heartbeat_calls_watchdog_heartbeat(self):
        watchdog = MagicMock()
        app = _make_heartbeat_app(watchdog=watchdog)
        with app.test_client() as c:
            c.post(
                "/api/fire/heartbeat",
                json={"operator_id": "op_test"},
            )
        watchdog.heartbeat.assert_called_once()

    def test_heartbeat_response_is_json(self):
        watchdog = MagicMock()
        app = _make_heartbeat_app(watchdog=watchdog)
        with app.test_client() as c:
            resp = c.post(
                "/api/fire/heartbeat",
                json={"operator_id": "op_test"},
            )
            data = resp.get_json()
            assert data is not None

    def test_multiple_heartbeats_all_succeed(self):
        watchdog = MagicMock()
        app = _make_heartbeat_app(watchdog=watchdog)
        with app.test_client() as c:
            for _ in range(3):
                resp = c.post(
                    "/api/fire/heartbeat",
                    json={"operator_id": "op_test"},
                )
                assert resp.status_code == 200
        assert watchdog.heartbeat.call_count == 3

    def test_heartbeat_without_body_does_not_crash(self):
        watchdog = MagicMock()
        app = _make_heartbeat_app(watchdog=watchdog)
        with app.test_client() as c:
            resp = c.post("/api/fire/heartbeat")
            # Should not 500
            assert resp.status_code < 500


# ---------------------------------------------------------------------------
# GET /api/config/profiles
# ---------------------------------------------------------------------------


class TestConfigProfiles:
    def test_list_profiles_returns_200(self):
        app = _make_health_app()
        with app.test_client() as c:
            resp = c.get("/api/config/profiles")
            assert resp.status_code == 200

    def test_list_profiles_returns_list_or_dict(self):
        app = _make_health_app()
        with app.test_client() as c:
            resp = c.get("/api/config/profiles")
            data = resp.get_json()
            assert isinstance(data, (list, dict))

    def test_load_nonexistent_profile_returns_error(self):
        app = _make_health_app()
        with app.test_client() as c:
            resp = c.post("/api/config/profile/does_not_exist_xyz_abc")
            assert resp.status_code in (400, 404, 422, 503)
