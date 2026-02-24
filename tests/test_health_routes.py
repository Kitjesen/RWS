"""Tests for health subsystem and profile management routes."""

from __future__ import annotations

from unittest.mock import MagicMock

from flask import Flask

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(extensions: dict | None = None):
    from src.rws_tracking.api.health_routes import health_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    if extensions:
        app.extensions.update(extensions)
    app.register_blueprint(health_bp)
    return app


# ---------------------------------------------------------------------------
# GET /api/health/subsystems
# ---------------------------------------------------------------------------


class TestSubsystemHealth:
    def test_no_monitor_returns_unknown(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.get("/api/health/subsystems")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["overall"] == "unknown"
            assert data["subsystems"] == {}

    def test_monitor_returns_status(self):
        mock_hm = MagicMock()
        mock_hm.overall_status.return_value = "ok"
        mock_hm.get_status.return_value = {
            "pipeline": "ok",
            "imu": "degraded",
        }
        app = _make_app({"health_monitor": mock_hm})
        with app.test_client() as c:
            resp = c.get("/api/health/subsystems")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["overall"] == "ok"
            assert "pipeline" in data["subsystems"]
            assert "imu" in data["subsystems"]

    def test_response_is_json(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.get("/api/health/subsystems")
            assert resp.content_type.startswith("application/json")


# ---------------------------------------------------------------------------
# GET /api/config/profiles
# ---------------------------------------------------------------------------


class TestListProfiles:
    def test_no_profile_manager_uses_fallback_dir(self):
        """When no profile_manager extension, falls back to 'profiles/' dir.
        Since the dir likely doesn't exist, returns empty list."""
        app = _make_app()
        with app.test_client() as c:
            resp = c.get("/api/config/profiles")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "profiles" in data
            assert isinstance(data["profiles"], list)

    def test_with_mock_profile_manager(self):
        mock_pm = MagicMock()
        mock_pm.list_profiles.return_value = ["urban_cqb", "open_field", "surveillance"]
        mock_pm.current_profile = "urban_cqb"
        app = _make_app({"profile_manager": mock_pm})
        with app.test_client() as c:
            resp = c.get("/api/config/profiles")
            assert resp.status_code == 200
            data = resp.get_json()
            assert "urban_cqb" in data["profiles"]
            assert "open_field" in data["profiles"]
            assert data["current"] == "urban_cqb"

    def test_empty_profile_directory(self, tmp_path):
        """A real ProfileManager with an empty dir returns empty list."""
        from src.rws_tracking.config.profiles import ProfileManager
        pm = ProfileManager(tmp_path)
        app = _make_app({"profile_manager": pm})
        with app.test_client() as c:
            resp = c.get("/api/config/profiles")
            data = resp.get_json()
            assert data["profiles"] == []
            assert data["current"] is None

    def test_profile_directory_with_yaml_files(self, tmp_path):
        """ProfileManager lists *.yaml stems from the directory."""
        (tmp_path / "alpha.yaml").write_text("dummy: true")
        (tmp_path / "bravo.yaml").write_text("dummy: true")

        from src.rws_tracking.config.profiles import ProfileManager
        pm = ProfileManager(tmp_path)
        app = _make_app({"profile_manager": pm})
        with app.test_client() as c:
            resp = c.get("/api/config/profiles")
            data = resp.get_json()
            assert "alpha" in data["profiles"]
            assert "bravo" in data["profiles"]
            assert len(data["profiles"]) == 2


# ---------------------------------------------------------------------------
# POST /api/config/profile/<name>
# ---------------------------------------------------------------------------


class TestSwitchProfile:
    def test_switch_to_existing_profile(self, tmp_path):
        """Switching to a profile that exists returns 200."""
        from src.rws_tracking.config.profiles import ProfileManager

        profile_file = tmp_path / "drill.yaml"
        # Write a minimal valid config
        profile_file.write_text("version: 1\n")

        pm = ProfileManager(tmp_path)
        app = _make_app({"profile_manager": pm})

        with app.test_client() as c:
            # Mock load_profile so we don't need a fully valid YAML config
            import unittest.mock as mock
            with mock.patch.object(pm, "load_profile", return_value=None) as m:
                resp = c.post("/api/config/profile/drill")
                assert resp.status_code == 200
                data = resp.get_json()
                assert data["status"] == "ok"
                assert data["profile"] == "drill"
                m.assert_called_once_with("drill")

    def test_switch_to_missing_profile_returns_404(self, tmp_path):
        """Switching to a non-existent profile returns 404."""
        from src.rws_tracking.config.profiles import ProfileManager
        pm = ProfileManager(tmp_path)
        app = _make_app({"profile_manager": pm})
        with app.test_client() as c:
            resp = c.post("/api/config/profile/nonexistent")
            assert resp.status_code == 404
            data = resp.get_json()
            assert "error" in data

    def test_switch_no_profile_manager_creates_one(self):
        """When no profile_manager extension, the route creates a fallback PM."""
        app = _make_app()
        with app.test_client() as c:
            resp = c.post("/api/config/profile/ghost")
            # No profiles dir, so FileNotFoundError → 404
            assert resp.status_code == 404
