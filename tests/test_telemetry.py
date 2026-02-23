"""遥测 logger 单元测试。"""

from __future__ import annotations

from src.rws_tracking.telemetry.logger import InMemoryTelemetryLogger


class TestInMemoryTelemetryLogger:
    def test_log_and_retrieve(self):
        logger = InMemoryTelemetryLogger()
        logger.log("control", 1.0, {"state": 1.0, "yaw_error_deg": 2.5, "pitch_error_deg": 1.0})
        assert len(logger.events) == 1
        assert logger.events[0].event_type == "control"

    def test_snapshot_metrics_empty(self):
        logger = InMemoryTelemetryLogger()
        m = logger.snapshot_metrics()
        assert m["lock_rate"] == 0.0
        assert m["avg_abs_error_deg"] == 0.0

    def test_snapshot_metrics_with_data(self):
        logger = InMemoryTelemetryLogger()
        for i in range(10):
            state = 2.0 if i >= 5 else 1.0
            logger.log("control", float(i), {
                "state": state,
                "yaw_error_deg": 1.0,
                "pitch_error_deg": 0.5,
            })
        m = logger.snapshot_metrics()
        assert m["lock_rate"] == 0.5
        assert m["avg_abs_error_deg"] == 1.0

    def test_ring_buffer(self):
        logger = InMemoryTelemetryLogger(max_events=5)
        for i in range(10):
            logger.log("control", float(i), {"state": 0.0, "yaw_error_deg": 0.0, "pitch_error_deg": 0.0})
        assert len(logger.events) == 5
        assert logger.events[0].timestamp == 5.0

    def test_switch_count(self):
        logger = InMemoryTelemetryLogger()
        logger.log("control", 0.0, {"state": 1.0, "yaw_error_deg": 0.0, "pitch_error_deg": 0.0})
        logger.log("switch", 1.0, {"track_id": 1.0})
        logger.log("switch", 2.0, {"track_id": 2.0})
        logger.log("control", 3.0, {"state": 1.0, "yaw_error_deg": 0.0, "pitch_error_deg": 0.0})
        m = logger.snapshot_metrics()
        assert m["switches_per_min"] > 0

    def test_lock_count_tracking(self):
        logger = InMemoryTelemetryLogger()
        logger.log("control", 0.0, {"state": 1.0, "yaw_error_deg": 0.0, "pitch_error_deg": 0.0})
        logger.log("control", 1.0, {"state": 2.0, "yaw_error_deg": 0.0, "pitch_error_deg": 0.0})
        logger.log("control", 2.0, {"state": 2.0, "yaw_error_deg": 0.0, "pitch_error_deg": 0.0})
        m = logger.snapshot_metrics()
        assert m["lock_rate"] == pytest.approx(2.0 / 3.0, abs=0.01)


import pytest  # noqa: E402 (for approx)
