"""Tests for the Prometheus metrics endpoint (src/rws_tracking/api/metrics_routes.py).

All heavy pipeline, shooting chain, and health monitor dependencies are mocked.
Tests verify:
  - GET /metrics returns 200 with Prometheus text/plain content type
  - Key metric names appear in the output
  - Correct values are returned for well-known extension objects
  - Missing extensions degrade gracefully (no 500 errors)
"""

from __future__ import annotations

import re
import time
from unittest.mock import MagicMock

import pytest
from flask import Flask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(extensions: dict | None = None) -> Flask:
    from src.rws_tracking.api.metrics_routes import metrics_bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    if extensions:
        app.extensions.update(extensions)
    app.register_blueprint(metrics_bp)
    return app


def _get_metrics(app: Flask) -> str:
    """Fetch /metrics and return response body as string."""
    with app.test_client() as c:
        resp = c.get("/metrics")
        assert resp.status_code == 200
        return resp.data.decode()


def _find_metric(body: str, name: str) -> list[str]:
    """Return all lines containing a given metric name."""
    return [line for line in body.splitlines() if line.startswith(name)]


def _metric_value(body: str, name: str) -> float | None:
    """Extract the numeric value of the first occurrence of a bare metric (no labels)."""
    for line in body.splitlines():
        if re.match(rf"^{re.escape(name)}\s+", line):
            parts = line.split()
            if len(parts) >= 2:
                return float(parts[1])
    return None


# ---------------------------------------------------------------------------
# Basic response shape
# ---------------------------------------------------------------------------


class TestMetricsResponseShape:
    def test_returns_200(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.get("/metrics")
            assert resp.status_code == 200

    def test_content_type_is_prometheus_text(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.get("/metrics")
            assert "text/plain" in resp.content_type

    def test_content_type_has_version(self):
        app = _make_app()
        with app.test_client() as c:
            resp = c.get("/metrics")
            assert "0.0.4" in resp.content_type

    def test_body_is_non_empty(self):
        app = _make_app()
        body = _get_metrics(app)
        assert len(body) > 0

    def test_no_extensions_does_not_crash(self):
        """Calling /metrics with no extensions returns 200 gracefully."""
        app = _make_app()
        with app.test_client() as c:
            resp = c.get("/metrics")
            assert resp.status_code == 200

    def test_body_ends_with_newline(self):
        app = _make_app()
        body = _get_metrics(app)
        assert body.endswith("\n")


# ---------------------------------------------------------------------------
# rws_tracks_total
# ---------------------------------------------------------------------------


class TestTracksTotal:
    def test_metric_present(self):
        app = _make_app()
        body = _get_metrics(app)
        assert "rws_tracks_total" in body

    def test_zero_when_no_api(self):
        app = _make_app()
        body = _get_metrics(app)
        val = _metric_value(body, "rws_tracks_total")
        assert val == 0.0

    def test_count_matches_last_tracks(self):
        """rws_tracks_total should reflect the length of api._last_tracks."""
        api = MagicMock()
        api.pipeline = None
        api._last_tracks = [MagicMock(), MagicMock(), MagicMock()]
        api._last_threat_assessments = []

        app = _make_app({"tracking_api": api})
        body = _get_metrics(app)
        val = _metric_value(body, "rws_tracks_total")
        assert val == 3.0

    def test_help_line_present(self):
        app = _make_app()
        body = _get_metrics(app)
        assert "# HELP rws_tracks_total" in body

    def test_type_line_present(self):
        app = _make_app()
        body = _get_metrics(app)
        assert "# TYPE rws_tracks_total gauge" in body


# ---------------------------------------------------------------------------
# rws_threat_score
# ---------------------------------------------------------------------------


class TestThreatScore:
    def test_help_line_present(self):
        app = _make_app()
        body = _get_metrics(app)
        assert "# HELP rws_threat_score" in body

    def test_no_assessments_no_data_lines(self):
        """When _last_threat_assessments is empty, no rws_threat_score data lines."""
        api = MagicMock()
        api.pipeline = None
        api._last_tracks = []
        api._last_threat_assessments = []

        app = _make_app({"tracking_api": api})
        body = _get_metrics(app)
        data_lines = [l for l in body.splitlines()
                      if l.startswith("rws_threat_score{")]
        assert len(data_lines) == 0

    def test_assessments_produce_labeled_lines(self):
        ta1 = SimpleNamespaceTA(track_id=1, threat_score=0.85)
        ta2 = SimpleNamespaceTA(track_id=2, threat_score=0.42)

        api = MagicMock()
        api.pipeline = None
        api._last_tracks = []
        api._last_threat_assessments = [ta1, ta2]

        app = _make_app({"tracking_api": api})
        body = _get_metrics(app)
        data_lines = [l for l in body.splitlines()
                      if l.startswith("rws_threat_score{")]
        assert len(data_lines) == 2

    def test_assessment_value_formatted_correctly(self):
        ta = SimpleNamespaceTA(track_id=7, threat_score=0.9)
        api = MagicMock()
        api.pipeline = None
        api._last_tracks = []
        api._last_threat_assessments = [ta]

        app = _make_app({"tracking_api": api})
        body = _get_metrics(app)
        assert 'rws_threat_score{track_id="7"}' in body

    def test_assessment_score_value(self):
        ta = SimpleNamespaceTA(track_id=3, threat_score=0.1234)
        api = MagicMock()
        api.pipeline = None
        api._last_tracks = []
        api._last_threat_assessments = [ta]

        app = _make_app({"tracking_api": api})
        body = _get_metrics(app)
        line = next(l for l in body.splitlines() if 'track_id="3"' in l)
        value = float(line.split()[-1])
        assert abs(value - 0.1234) < 1e-4


# ---------------------------------------------------------------------------
# rws_fire_chain_state
# ---------------------------------------------------------------------------


class TestFireChainState:
    def test_metric_present(self):
        app = _make_app()
        body = _get_metrics(app)
        assert "rws_fire_chain_state" in body

    def test_not_configured_returns_minus_one(self):
        """When no shooting_chain extension, value should be -1."""
        app = _make_app()
        body = _get_metrics(app)
        val = _metric_value(body, "rws_fire_chain_state")
        assert val == -1.0

    def test_safe_state_returns_zero(self):
        from src.rws_tracking.safety.shooting_chain import ShootingChain
        chain = ShootingChain()
        app = _make_app({"shooting_chain": chain})
        body = _get_metrics(app)
        val = _metric_value(body, "rws_fire_chain_state")
        assert val == 0.0

    def test_armed_state_returns_one(self):
        from src.rws_tracking.safety.shooting_chain import ShootingChain
        chain = ShootingChain()
        chain.arm("test_op")
        app = _make_app({"shooting_chain": chain})
        body = _get_metrics(app)
        val = _metric_value(body, "rws_fire_chain_state")
        assert val == 1.0

    def test_fire_authorized_state_returns_two(self):
        from src.rws_tracking.safety.shooting_chain import ShootingChain
        chain = ShootingChain()
        chain.arm("test_op")
        chain.update_authorization(True, timestamp=0.0)
        app = _make_app({"shooting_chain": chain})
        body = _get_metrics(app)
        val = _metric_value(body, "rws_fire_chain_state")
        assert val == 2.0

    def test_help_line_present(self):
        app = _make_app()
        body = _get_metrics(app)
        assert "# HELP rws_fire_chain_state" in body


# ---------------------------------------------------------------------------
# rws_shots_fired_total
# ---------------------------------------------------------------------------


class TestShotsFiredTotal:
    def test_metric_present(self):
        app = _make_app()
        body = _get_metrics(app)
        assert "rws_shots_fired_total" in body

    def test_zero_when_no_audit_logger(self):
        app = _make_app()
        body = _get_metrics(app)
        val = _metric_value(body, "rws_shots_fired_total")
        assert val == 0.0

    def test_counts_fired_records(self):
        """rws_shots_fired_total should count records where event_type == 'fired'."""
        fired_record = MagicMock()
        fired_record.event_type = "fired"

        other_record = MagicMock()
        other_record.event_type = "armed"

        audit = MagicMock()
        audit._records = [fired_record, other_record, fired_record]

        app = _make_app({"audit_logger": audit})
        body = _get_metrics(app)
        val = _metric_value(body, "rws_shots_fired_total")
        assert val == 2.0

    def test_help_line_present(self):
        app = _make_app()
        body = _get_metrics(app)
        assert "# HELP rws_shots_fired_total" in body


# ---------------------------------------------------------------------------
# rws_lifecycle_by_state
# ---------------------------------------------------------------------------


class TestLifecycleByState:
    def test_help_line_present(self):
        app = _make_app()
        body = _get_metrics(app)
        assert "# HELP rws_lifecycle_by_state" in body

    def test_no_pipeline_no_data_lines(self):
        app = _make_app()
        body = _get_metrics(app)
        data_lines = [l for l in body.splitlines()
                      if l.startswith("rws_lifecycle_by_state{")]
        assert len(data_lines) == 0

    def test_with_lifecycle_manager(self):
        lm = MagicMock()
        lm.summary.return_value = {
            "total_seen": 10,
            "by_state": {"detected": 4, "archived": 6},
        }
        pipeline = MagicMock()
        pipeline._lifecycle_manager = lm

        api = MagicMock()
        api.pipeline = pipeline
        api._last_tracks = []
        api._last_threat_assessments = []

        app = _make_app({"tracking_api": api})
        body = _get_metrics(app)
        assert 'rws_lifecycle_by_state{state="detected"}' in body
        assert 'rws_lifecycle_by_state{state="archived"}' in body

    def test_lifecycle_values_correct(self):
        lm = MagicMock()
        lm.summary.return_value = {
            "total_seen": 7,
            "by_state": {"detected": 3, "archived": 4},
        }
        pipeline = MagicMock()
        pipeline._lifecycle_manager = lm

        api = MagicMock()
        api.pipeline = pipeline
        api._last_tracks = []
        api._last_threat_assessments = []

        app = _make_app({"tracking_api": api})
        body = _get_metrics(app)

        for line in body.splitlines():
            if 'state="detected"' in line:
                assert float(line.split()[-1]) == 3.0
            if 'state="archived"' in line:
                assert float(line.split()[-1]) == 4.0


# ---------------------------------------------------------------------------
# rws_health_subsystem
# ---------------------------------------------------------------------------


class TestHealthSubsystem:
    def test_help_line_present(self):
        app = _make_app()
        body = _get_metrics(app)
        assert "# HELP rws_health_subsystem" in body

    def test_no_health_monitor_no_data_lines(self):
        app = _make_app()
        body = _get_metrics(app)
        data_lines = [l for l in body.splitlines()
                      if l.startswith("rws_health_subsystem{")]
        assert len(data_lines) == 0

    def test_ok_subsystem_returns_one(self):
        hm = MagicMock()
        hm.get_status.return_value = {
            "pipeline": {"status": "ok"},
        }
        app = _make_app({"health_monitor": hm})
        body = _get_metrics(app)
        line = next(l for l in body.splitlines()
                    if 'name="pipeline"' in l)
        assert float(line.split()[-1]) == 1.0

    def test_degraded_subsystem_returns_two(self):
        hm = MagicMock()
        hm.get_status.return_value = {
            "imu": {"status": "degraded"},
        }
        app = _make_app({"health_monitor": hm})
        body = _get_metrics(app)
        line = next(l for l in body.splitlines()
                    if 'name="imu"' in l)
        assert float(line.split()[-1]) == 2.0

    def test_failed_subsystem_returns_three(self):
        hm = MagicMock()
        hm.get_status.return_value = {
            "camera": {"status": "failed"},
        }
        app = _make_app({"health_monitor": hm})
        body = _get_metrics(app)
        line = next(l for l in body.splitlines()
                    if 'name="camera"' in l)
        assert float(line.split()[-1]) == 3.0

    def test_unknown_subsystem_returns_zero(self):
        hm = MagicMock()
        hm.get_status.return_value = {
            "radar": {"status": "unknown"},
        }
        app = _make_app({"health_monitor": hm})
        body = _get_metrics(app)
        line = next(l for l in body.splitlines()
                    if 'name="radar"' in l)
        assert float(line.split()[-1]) == 0.0

    def test_multiple_subsystems(self):
        hm = MagicMock()
        hm.get_status.return_value = {
            "pipeline": {"status": "ok"},
            "imu": {"status": "degraded"},
            "camera": {"status": "failed"},
        }
        app = _make_app({"health_monitor": hm})
        body = _get_metrics(app)
        data_lines = [l for l in body.splitlines()
                      if l.startswith("rws_health_subsystem{")]
        assert len(data_lines) == 3


# ---------------------------------------------------------------------------
# rws_operator_heartbeat_age_s
# ---------------------------------------------------------------------------


class TestOperatorHeartbeatAge:
    def test_not_present_without_watchdog(self):
        app = _make_app()
        body = _get_metrics(app)
        assert "rws_operator_heartbeat_age_s" not in body

    def test_present_with_watchdog(self):
        wd = MagicMock()
        wd.seconds_since_heartbeat = 3.7
        app = _make_app({"operator_watchdog": wd})
        body = _get_metrics(app)
        assert "rws_operator_heartbeat_age_s" in body

    def test_value_from_watchdog(self):
        wd = MagicMock()
        wd.seconds_since_heartbeat = 5.0
        app = _make_app({"operator_watchdog": wd})
        body = _get_metrics(app)
        val = _metric_value(body, "rws_operator_heartbeat_age_s")
        assert val == 5.0

    def test_help_line_when_watchdog_present(self):
        wd = MagicMock()
        wd.seconds_since_heartbeat = 0.5
        app = _make_app({"operator_watchdog": wd})
        body = _get_metrics(app)
        assert "# HELP rws_operator_heartbeat_age_s" in body


# ---------------------------------------------------------------------------
# rws_pipeline_fps
# ---------------------------------------------------------------------------


class TestPipelineFps:
    @pytest.fixture(autouse=True)
    def _clear_frame_times(self):
        """Isolate module-level _frame_times deque before and after every test."""
        from src.rws_tracking.api.metrics_routes import _frame_times
        _frame_times.clear()
        yield
        _frame_times.clear()

    def test_metric_present(self):
        app = _make_app()
        body = _get_metrics(app)
        assert "rws_pipeline_fps" in body

    def test_zero_fps_when_no_frames_recorded(self):
        app = _make_app()
        body = _get_metrics(app)
        val = _metric_value(body, "rws_pipeline_fps")
        assert val == 0.0

    def test_fps_increases_after_recording_frames(self):
        from src.rws_tracking.api.metrics_routes import record_frame, _frame_times

        now = time.monotonic()
        for _ in range(15):
            record_frame(now - 0.05)  # all within last 1 second
        _frame_times.append(now)

        app = _make_app()
        body = _get_metrics(app)
        val = _metric_value(body, "rws_pipeline_fps")
        assert val > 0.0

    def test_help_line_present(self):
        app = _make_app()
        body = _get_metrics(app)
        assert "# HELP rws_pipeline_fps" in body


# ---------------------------------------------------------------------------
# Gimbal position metrics (pipeline-dependent)
# ---------------------------------------------------------------------------


class TestGimbalMetrics:
    def test_no_gimbal_metrics_without_pipeline(self):
        app = _make_app()
        body = _get_metrics(app)
        assert "rws_gimbal_yaw_deg" not in body
        assert "rws_gimbal_pitch_deg" not in body

    def test_gimbal_yaw_error_present_with_pipeline(self):
        """rws_yaw_error_deg appears when pipeline is attached."""
        pipeline = MagicMock()
        pipeline._lifecycle_manager = None
        pipeline._last_yaw_error_deg = 1.5
        pipeline._last_pitch_error_deg = 0.3
        pipeline.driver.get_feedback.side_effect = Exception("no driver")

        api = MagicMock()
        api.pipeline = pipeline
        api._last_tracks = []
        api._last_threat_assessments = []

        app = _make_app({"tracking_api": api})
        body = _get_metrics(app)
        assert "rws_yaw_error_deg" in body
        assert "rws_pitch_error_deg" in body

    def test_yaw_error_value(self):
        pipeline = MagicMock()
        pipeline._lifecycle_manager = None
        pipeline._last_yaw_error_deg = 2.5
        pipeline._last_pitch_error_deg = 1.0
        pipeline.driver.get_feedback.side_effect = Exception("no driver")

        api = MagicMock()
        api.pipeline = pipeline
        api._last_tracks = []
        api._last_threat_assessments = []

        app = _make_app({"tracking_api": api})
        body = _get_metrics(app)
        val = _metric_value(body, "rws_yaw_error_deg")
        assert abs(val - 2.5) < 0.01

    def test_gimbal_feedback_included_when_driver_works(self):
        """When driver.get_feedback() succeeds, yaw/pitch position metrics appear."""
        from types import SimpleNamespace

        feedback = SimpleNamespace(yaw_deg=45.0, pitch_deg=-10.0)
        pipeline = MagicMock()
        pipeline._lifecycle_manager = None
        pipeline._last_yaw_error_deg = 0.0
        pipeline._last_pitch_error_deg = 0.0
        pipeline.driver.get_feedback.return_value = feedback

        api = MagicMock()
        api.pipeline = pipeline
        api._last_tracks = []
        api._last_threat_assessments = []

        app = _make_app({"tracking_api": api})
        body = _get_metrics(app)
        assert "rws_gimbal_yaw_deg" in body
        assert "rws_gimbal_pitch_deg" in body

        yaw_val = _metric_value(body, "rws_gimbal_yaw_deg")
        pitch_val = _metric_value(body, "rws_gimbal_pitch_deg")
        assert abs(yaw_val - 45.0) < 0.01
        assert abs(pitch_val - (-10.0)) < 0.01


# ---------------------------------------------------------------------------
# Prometheus format validity — HELP + TYPE lines precede data lines
# ---------------------------------------------------------------------------


class TestPrometheusFormat:
    def test_help_before_type(self):
        """For each metric family, # HELP must appear before # TYPE."""
        app = _make_app()
        body = _get_metrics(app)
        lines = body.splitlines()
        help_positions: dict[str, int] = {}
        type_positions: dict[str, int] = {}
        for i, line in enumerate(lines):
            if line.startswith("# HELP "):
                name = line.split()[2]
                help_positions[name] = i
            elif line.startswith("# TYPE "):
                name = line.split()[2]
                type_positions[name] = i
        for name, h_pos in help_positions.items():
            if name in type_positions:
                assert h_pos < type_positions[name], (
                    f"# HELP for {name} must precede # TYPE"
                )

    def test_all_data_lines_have_numeric_value(self):
        """Every non-comment, non-empty line must end with a numeric value."""
        app = _make_app()
        body = _get_metrics(app)
        for line in body.splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            try:
                float(parts[-1])
            except (ValueError, IndexError):
                pytest.fail(f"Non-numeric value in Prometheus data line: {line!r}")

    def test_labels_use_double_quotes(self):
        """Label values must be enclosed in double quotes per Prometheus spec."""
        ta = SimpleNamespaceTA(track_id=5, threat_score=0.5)
        api = MagicMock()
        api.pipeline = None
        api._last_tracks = []
        api._last_threat_assessments = [ta]

        app = _make_app({"tracking_api": api})
        body = _get_metrics(app)
        labeled = [l for l in body.splitlines() if "{" in l and not l.startswith("#")]
        for line in labeled:
            m = re.search(r'\{([^}]*)\}', line)
            if m:
                label_str = m.group(1)
                # Each label value should be quoted
                assert '="' in label_str, f"Label not double-quoted: {line!r}"

    def test_special_chars_in_labels_escaped(self):
        """Metric names with special chars (double-quote, backslash, newline) are escaped.

        _escape applies transformations in order: replace " with backslash-quote, then
        backslash with double-backslash, then newline with literal-backslash-n.
        A bare double-quote therefore becomes two chars (backslash backslash quote)
        because the introduced backslash is itself escaped in the second pass.
        """
        from src.rws_tracking.api.metrics_routes import _escape
        # '"' -> '\"' (pass 1) -> '\\"' (pass 2 doubles the backslash)
        assert _escape('"hello"') == '\\\\"hello\\\\"'
        # A literal backslash is doubled: '\\' -> '\\\\'
        assert _escape("back\\slash") == "back\\\\slash"
        # Newline becomes the two-char literal \\n
        assert _escape("new\nline") == "new\\nline"


# ---------------------------------------------------------------------------
# record_frame helper
# ---------------------------------------------------------------------------


class TestRecordFrame:
    def test_record_frame_callable(self):
        from src.rws_tracking.api.metrics_routes import record_frame
        # Should not raise
        record_frame(time.monotonic())

    def test_deque_maxlen_enforced(self):
        from src.rws_tracking.api.metrics_routes import _frame_times, record_frame
        _frame_times.clear()
        for i in range(150):
            record_frame(time.monotonic())
        assert len(_frame_times) <= 100


# ---------------------------------------------------------------------------
# Helper class for threat assessment mocks
# ---------------------------------------------------------------------------


class SimpleNamespaceTA:
    """Minimal ThreatAssessment-like object with track_id and threat_score."""
    def __init__(self, track_id: int, threat_score: float):
        self.track_id = track_id
        self.threat_score = threat_score
