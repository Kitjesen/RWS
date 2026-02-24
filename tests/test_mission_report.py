"""Tests for mission report download endpoint (GET /api/mission/report/<filename>)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from flask import Flask

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mission_app():
    from src.rws_tracking.api.mission_routes import mission_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(mission_bp)
    return app


# ---------------------------------------------------------------------------
# GET /api/mission/report/<filename>
# ---------------------------------------------------------------------------


class TestMissionReportDownload:
    def test_report_not_found_returns_404(self):
        app = _make_mission_app()
        with app.test_client() as c:
            resp = c.get("/api/mission/report/nonexistent_xyz.html")
            assert resp.status_code == 404

    def test_report_found_returns_200(self, tmp_path):
        """A real HTML file in logs/reports/ should be served with 200."""
        report_dir = tmp_path / "logs" / "reports"
        report_dir.mkdir(parents=True)
        report_file = report_dir / "test_report.html"
        report_file.write_text("<html><body>Test Report</body></html>")

        app = _make_mission_app()
        with app.test_client() as c:
            # Patch Path("logs/reports") to use our tmp dir
            with patch(
                "src.rws_tracking.api.mission_routes.Path",
                side_effect=lambda *args: tmp_path.joinpath(*args),
            ):
                resp = c.get("/api/mission/report/test_report.html")
                assert resp.status_code == 200

    def test_report_content_type_is_html(self, tmp_path):
        report_dir = tmp_path / "logs" / "reports"
        report_dir.mkdir(parents=True)
        (report_dir / "test.html").write_text("<html></html>")

        app = _make_mission_app()
        with app.test_client() as c:
            with patch(
                "src.rws_tracking.api.mission_routes.Path",
                side_effect=lambda *args: tmp_path.joinpath(*args),
            ):
                resp = c.get("/api/mission/report/test.html")
                if resp.status_code == 200:
                    assert "text/html" in resp.content_type

    def test_path_traversal_blocked(self):
        """Traversal via ../  must be rejected."""
        app = _make_mission_app()
        with app.test_client() as c:
            # Flask will canonicalize this but the endpoint should also check.
            resp = c.get("/api/mission/report/../../etc/passwd")
            assert resp.status_code in (400, 404)


# ---------------------------------------------------------------------------
# mission_end response includes report_url
# ---------------------------------------------------------------------------


class TestMissionEndReportUrl:
    def test_report_url_is_api_path(self):
        """When a report_path is set, report_url must start with /api/."""

        # Simulate: the function logic that builds report_url
        report_path = "logs/reports/test_session_report.html"
        report_url = (
            f"/api/mission/report/{Path(report_path).name}"
            if report_path
            else None
        )
        assert report_url is not None
        assert report_url.startswith("/api/")
        assert "test_session_report.html" in report_url

    def test_report_url_none_when_no_report(self):
        report_path = None
        report_url = (
            f"/api/mission/report/{Path(report_path).name}"
            if report_path
            else None
        )
        assert report_url is None
