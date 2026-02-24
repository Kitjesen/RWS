"""遥测日志器完整测试 — InMemory + File。"""

import json

import pytest

from src.rws_tracking.telemetry.logger import (
    EventRecord,
    FileTelemetryLogger,
    InMemoryTelemetryLogger,
)


class TestInMemoryTelemetryLogger:
    def test_log_event(self):
        logger = InMemoryTelemetryLogger()
        logger.log("control", 1.0, {"yaw_error_deg": 2.0, "pitch_error_deg": 1.0, "state": 1.0})
        assert len(logger.events) == 1

    def test_snapshot_empty(self):
        logger = InMemoryTelemetryLogger()
        m = logger.snapshot_metrics()
        assert m["lock_rate"] == 0.0

    def test_lock_rate(self):
        logger = InMemoryTelemetryLogger()
        for i in range(10):
            state = 2.0 if i < 7 else 1.0
            logger.log("control", float(i), {"state": state, "yaw_error_deg": 0.5, "pitch_error_deg": 0.3})
        m = logger.snapshot_metrics()
        assert m["lock_rate"] == pytest.approx(0.7)

    def test_avg_error(self):
        logger = InMemoryTelemetryLogger()
        logger.log("control", 0.0, {"yaw_error_deg": 3.0, "pitch_error_deg": 1.0, "state": 1.0})
        logger.log("control", 1.0, {"yaw_error_deg": 1.0, "pitch_error_deg": 5.0, "state": 1.0})
        m = logger.snapshot_metrics()
        assert m["avg_abs_error_deg"] == pytest.approx((3.0 + 5.0) / 2.0)

    def test_switches_per_min(self):
        logger = InMemoryTelemetryLogger()
        logger.log("control", 0.0, {"state": 1.0, "yaw_error_deg": 0.0, "pitch_error_deg": 0.0})
        logger.log("switch", 30.0, {"from_id": 1, "to_id": 2})
        logger.log("control", 60.0, {"state": 1.0, "yaw_error_deg": 0.0, "pitch_error_deg": 0.0})
        m = logger.snapshot_metrics()
        assert m["switches_per_min"] == pytest.approx(1.0)

    def test_ring_buffer(self):
        logger = InMemoryTelemetryLogger(max_events=5)
        for i in range(10):
            logger.log("control", float(i), {"state": 1.0, "yaw_error_deg": 0.0, "pitch_error_deg": 0.0})
        assert len(logger.events) == 5

    def test_export_jsonl(self):
        logger = InMemoryTelemetryLogger()
        logger.log("control", 1.0, {"state": 1.0, "yaw_error_deg": 0.0, "pitch_error_deg": 0.0})
        logger.log("switch", 2.0, {"from_id": 1, "to_id": 2})
        jsonl = logger.export_jsonl()
        lines = jsonl.strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["event_type"] == "control"

    def test_thread_safety(self):
        import threading
        logger = InMemoryTelemetryLogger()
        def writer():
            for i in range(100):
                logger.log("control", float(i), {"state": 1.0, "yaw_error_deg": 0.0, "pitch_error_deg": 0.0})
        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(logger.events) == 400


class TestFileTelemetryLogger:
    def test_write_and_read(self, tmp_path):
        p = tmp_path / "log.jsonl"
        with FileTelemetryLogger(p) as logger:
            logger.log("control", 1.0, {"state": 2.0, "yaw_error_deg": 0.5, "pitch_error_deg": 0.3})
            logger.log("switch", 2.0, {"from_id": 1, "to_id": 2})
        lines = p.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_metrics(self, tmp_path):
        p = tmp_path / "log.jsonl"
        with FileTelemetryLogger(p) as logger:
            logger.log("control", 0.0, {"state": 2.0, "yaw_error_deg": 1.0, "pitch_error_deg": 0.5})
            logger.log("control", 1.0, {"state": 2.0, "yaw_error_deg": 0.5, "pitch_error_deg": 0.3})
            m = logger.snapshot_metrics()
        assert m["lock_rate"] == 1.0

    def test_append_mode(self, tmp_path):
        p = tmp_path / "log.jsonl"
        with FileTelemetryLogger(p) as logger:
            logger.log("control", 0.0, {"state": 1.0, "yaw_error_deg": 0.0, "pitch_error_deg": 0.0})
        with FileTelemetryLogger(p, append=True) as logger:
            logger.log("control", 1.0, {"state": 1.0, "yaw_error_deg": 0.0, "pitch_error_deg": 0.0})
        lines = p.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_close_idempotent(self, tmp_path):
        p = tmp_path / "log.jsonl"
        logger = FileTelemetryLogger(p)
        logger.close()
        logger.close()  # should not crash

    def test_log_after_close(self, tmp_path):
        p = tmp_path / "log.jsonl"
        logger = FileTelemetryLogger(p)
        logger.close()
        logger.log("control", 0.0, {"state": 1.0})  # should not crash

    def test_context_manager(self, tmp_path):
        p = tmp_path / "log.jsonl"
        with FileTelemetryLogger(p) as logger:
            logger.log("control", 0.0, {"state": 1.0, "yaw_error_deg": 0.0, "pitch_error_deg": 0.0})
        assert p.exists()

    def test_empty_metrics(self, tmp_path):
        p = tmp_path / "log.jsonl"
        with FileTelemetryLogger(p) as logger:
            m = logger.snapshot_metrics()
        assert m["lock_rate"] == 0.0


class TestEventRecord:
    def test_fields(self):
        e = EventRecord(event_type="control", timestamp=1.0, payload={"a": 1.0})
        assert e.event_type == "control"
        assert e.timestamp == 1.0
        assert e.payload["a"] == 1.0
