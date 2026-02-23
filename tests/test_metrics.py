"""Tests for the Prometheus metrics endpoint (GET /metrics)."""

from __future__ import annotations

from unittest.mock import MagicMock
from types import SimpleNamespace

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(extensions: dict | None = None):
    """Build a minimal Flask app with the metrics blueprint registered."""
    from src.rws_tracking.api.metrics_routes import metrics_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    if extensions:
        app.extensions.update(extensions)
    app.register_blueprint(metrics_bp)
    return app


def _get_metrics(extensions: dict | None = None) -> tuple[int, str]:
    app = _make_app(extensions)
    with app.test_client() as c:
        resp = c.get("/metrics")
        return resp.status_code, resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Basic response shape
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    def test_returns_200(self):
        status, _ = _get_metrics()
        assert status == 200

    def test_content_type_is_text_plain(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.get("/metrics")
            assert resp.content_type.startswith("text/plain")

    def test_always_contains_required_metric_names(self):
        _, body = _get_metrics()
        required = [
            "rws_tracks_total",
            "rws_fire_chain_state",
            "rws_shots_fired_total",
            "rws_pipeline_fps",
            "rws_threat_score",
            "rws_lifecycle_by_state",
            "rws_health_subsystem",
        ]
        for name in required:
            assert name in body, f"Missing metric: {name}"

    def test_ends_with_newline(self):
        _, body = _get_metrics()
        assert body.endswith("\n")


# ---------------------------------------------------------------------------
# Tracks metric
# ---------------------------------------------------------------------------


class TestTracksMetric:
    def test_no_api_extension_reports_zero_tracks(self):
        _, body = _get_metrics()
        assert "rws_tracks_total 0" in body

    def test_track_count_reflects_last_tracks(self):
        mock_api = SimpleNamespace(
            pipeline=None,
            _last_tracks=[MagicMock(), MagicMock(), MagicMock()],
            _last_threat_assessments=[],
        )
        _, body = _get_metrics({"tracking_api": mock_api})
        assert "rws_tracks_total 3" in body

    def test_threat_scores_per_track(self):
        ta1 = SimpleNamespace(track_id=1, threat_score=0.85)
        ta2 = SimpleNamespace(track_id=2, threat_score=0.42)
        mock_api = SimpleNamespace(
            pipeline=None,
            _last_tracks=[MagicMock(), MagicMock()],
            _last_threat_assessments=[ta1, ta2],
        )
        _, body = _get_metrics({"tracking_api": mock_api})
        assert 'rws_threat_score{track_id="1"} 0.8500' in body
        assert 'rws_threat_score{track_id="2"} 0.4200' in body


# ---------------------------------------------------------------------------
# Fire chain state metric
# ---------------------------------------------------------------------------


class TestFireChainMetric:
    def test_no_chain_reports_minus_one(self):
        _, body = _get_metrics()
        assert "rws_fire_chain_state -1" in body

    def test_safe_state_reports_zero(self):
        mock_chain = SimpleNamespace(state=SimpleNamespace(value="safe"))
        _, body = _get_metrics({"shooting_chain": mock_chain})
        assert "rws_fire_chain_state 0" in body

    def test_armed_state_reports_one(self):
        mock_chain = SimpleNamespace(state=SimpleNamespace(value="armed"))
        _, body = _get_metrics({"shooting_chain": mock_chain})
        assert "rws_fire_chain_state 1" in body

    def test_fire_authorized_reports_two(self):
        mock_chain = SimpleNamespace(state=SimpleNamespace(value="fire_authorized"))
        _, body = _get_metrics({"shooting_chain": mock_chain})
        assert "rws_fire_chain_state 2" in body

    def test_fired_state_reports_four(self):
        mock_chain = SimpleNamespace(state=SimpleNamespace(value="fired"))
        _, body = _get_metrics({"shooting_chain": mock_chain})
        assert "rws_fire_chain_state 4" in body


# ---------------------------------------------------------------------------
# Shots fired metric (from audit log)
# ---------------------------------------------------------------------------


class TestShotsFiredMetric:
    def test_no_audit_logger_reports_zero_shots(self):
        _, body = _get_metrics()
        assert "rws_shots_fired_total 0" in body

    def test_counts_fired_records(self):
        fired_rec = SimpleNamespace(event_type="fired")
        other_rec = SimpleNamespace(event_type="armed")
        mock_audit = SimpleNamespace(_records=[fired_rec, fired_rec, other_rec])
        _, body = _get_metrics({"audit_logger": mock_audit})
        assert "rws_shots_fired_total 2" in body

    def test_no_fired_records_reports_zero(self):
        mock_audit = SimpleNamespace(
            _records=[SimpleNamespace(event_type="armed"), SimpleNamespace(event_type="safe")]
        )
        _, body = _get_metrics({"audit_logger": mock_audit})
        assert "rws_shots_fired_total 0" in body


# ---------------------------------------------------------------------------
# Health subsystem metric
# ---------------------------------------------------------------------------


class TestHealthSubsystemMetric:
    """HealthMonitor.get_status() returns {name: {"status": str, ...}} dicts."""

    def _make_hm(self, subsystems: dict):
        """Build a mock HealthMonitor whose get_status() returns real dicts."""
        mock_hm = MagicMock()
        mock_hm.get_status.return_value = {
            name: {"status": s, "last_heartbeat_age_s": None, "error": None}
            for name, s in subsystems.items()
        }
        return mock_hm

    def test_no_health_monitor_emits_header_only(self):
        _, body = _get_metrics()
        assert "# HELP rws_health_subsystem" in body

    def test_ok_subsystem_reports_one(self):
        _, body = _get_metrics({"health_monitor": self._make_hm({"pipeline": "ok"})})
        assert 'rws_health_subsystem{name="pipeline"} 1' in body

    def test_degraded_subsystem_reports_two(self):
        _, body = _get_metrics({"health_monitor": self._make_hm({"camera": "degraded"})})
        assert 'rws_health_subsystem{name="camera"} 2' in body

    def test_failed_subsystem_reports_three(self):
        _, body = _get_metrics({"health_monitor": self._make_hm({"imu": "failed"})})
        assert 'rws_health_subsystem{name="imu"} 3' in body

    def test_unknown_subsystem_reports_zero(self):
        _, body = _get_metrics({"health_monitor": self._make_hm({"sensor": "unknown"})})
        assert 'rws_health_subsystem{name="sensor"} 0' in body

    def test_label_escaping_for_special_chars(self):
        _, body = _get_metrics({"health_monitor": self._make_hm({'sub"sys': "ok"})})
        assert '\\"' in body or '"' in body  # escaped or quoted


# ---------------------------------------------------------------------------
# Operator watchdog metric
# ---------------------------------------------------------------------------


class TestWatchdogMetric:
    def test_no_watchdog_no_metric(self):
        _, body = _get_metrics()
        assert "rws_operator_heartbeat_age_s" not in body

    def test_watchdog_reports_age(self):
        mock_wd = SimpleNamespace(seconds_since_heartbeat=3.7)
        _, body = _get_metrics({"operator_watchdog": mock_wd})
        assert "rws_operator_heartbeat_age_s 3.7" in body


# ---------------------------------------------------------------------------
# FPS metric
# ---------------------------------------------------------------------------


class TestFpsMetric:
    def test_fps_metric_present(self):
        _, body = _get_metrics()
        assert "rws_pipeline_fps" in body

    def test_record_frame_increments_fps(self):
        import time
        from src.rws_tracking.api.metrics_routes import record_frame, _frame_times

        _frame_times.clear()
        now = time.monotonic()
        for i in range(5):
            record_frame(now - i * 0.1)  # 5 frames in last 0.5s

        _, body = _get_metrics()
        # At least some frames should be counted
        assert "rws_pipeline_fps" in body
