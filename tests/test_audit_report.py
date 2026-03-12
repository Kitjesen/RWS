"""Tests for AuditLogger + report generator (Task F)."""

from __future__ import annotations

import pytest

from src.rws_tracking.telemetry.audit import AuditLogger
from src.rws_tracking.telemetry.report import generate_report


@pytest.fixture()
def logger_with_events(tmp_path):
    """AuditLogger pre-populated with a typical fire sequence."""
    al = AuditLogger(tmp_path / "mission.jsonl")
    al.log("arm", "op1", "armed")
    al.log(
        "fire_authorized",
        "op1",
        "fire_authorized",
        target_id=3,
        threat_score=0.82,
        distance_m=45.0,
        fire_authorized=True,
    )
    al.log("fire_requested", "op1", "fire_requested", target_id=3)
    al.log("fired", "op1", "fired", target_id=3, threat_score=0.82, distance_m=45.0)
    al.log("cooldown_expired", "op1", "armed")
    al.log("safe", "op1", "safe")
    return al


# ---------------------------------------------------------------------------
# AuditLogger
# ---------------------------------------------------------------------------


class TestAuditLogger:
    def test_records_appended(self, logger_with_events):
        assert len(logger_with_events._records) == 6

    def test_chain_valid(self, logger_with_events):
        ok, err = logger_with_events.verify_chain()
        assert ok, err

    def test_seq_monotone(self, logger_with_events):
        seqs = [r.seq for r in logger_with_events._records]
        assert seqs == list(range(len(seqs)))

    def test_prev_hash_chained(self, logger_with_events):
        recs = logger_with_events._records
        for i in range(1, len(recs)):
            assert recs[i].prev_hash == recs[i - 1].record_hash

    def test_tampered_chain_detected(self, logger_with_events):
        recs = logger_with_events._records
        # Tamper a record in-place (break the chain)
        original = recs[2]
        from dataclasses import replace

        recs[2] = replace(original, threat_score=99.0)
        ok, err = logger_with_events.verify_chain()
        assert not ok

    def test_persist_and_reload(self, tmp_path):
        path = tmp_path / "log.jsonl"
        al1 = AuditLogger(path)
        al1.log("arm", "op1", "armed")
        al1.log("fired", "op1", "fired", target_id=1, threat_score=0.9, distance_m=30.0)

        # Reload from disk
        al2 = AuditLogger(path)
        assert len(al2._records) == 2
        ok, err = al2.verify_chain()
        assert ok, err

    def test_get_recent_limit(self, logger_with_events):
        recent = logger_with_events.get_recent(2)
        assert len(recent) == 2
        assert recent[-1].seq == 5  # last record


# ---------------------------------------------------------------------------
# Report generator
# ---------------------------------------------------------------------------


class TestReportGenerator:
    def test_html_structure(self, logger_with_events):
        html = generate_report(logger_with_events, "Test Mission")
        assert "<!DOCTYPE html>" in html
        assert "<title>Test Mission</title>" in html
        assert "Chain valid" in html

    def test_counts_shots(self, logger_with_events):
        html = generate_report(logger_with_events, "M")
        # 1 fired event
        assert "Shots fired" in html

    def test_empty_logger(self, tmp_path):
        al = AuditLogger(tmp_path / "empty.jsonl")
        html = generate_report(al, "Empty")
        assert "<!DOCTYPE html>" in html
        assert "No events recorded" in html

    def test_chain_broken_flag_in_report(self, logger_with_events):
        from dataclasses import replace

        recs = logger_with_events._records
        recs[1] = replace(recs[1], threat_score=99.0)
        html = generate_report(logger_with_events, "Tampered")
        assert "Chain broken" in html

    def test_output_path(self, logger_with_events, tmp_path):
        out = tmp_path / "report.html"
        generate_report(logger_with_events, "M", output_path=str(out))
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
