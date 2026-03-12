"""Tests for the session replay API (src/rws_tracking/api/replay_routes.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask import Flask

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_app(log_dir: str) -> Flask:
    """Create a minimal Flask app with the replay blueprint wired."""
    from src.rws_tracking.api.replay_routes import replay_bp

    app = Flask(__name__)
    app.config["TELEMETRY_LOG_DIR"] = log_dir
    app.config["TESTING"] = True
    app.register_blueprint(replay_bp)
    return app


def _write_jsonl(path: Path, events: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")


SAMPLE_EVENTS = [
    {"event_type": "track", "timestamp": 1.0, "data": {"id": 1}},
    {"event_type": "track", "timestamp": 2.0, "data": {"id": 1}},
    {"event_type": "fired", "timestamp": 3.0, "data": {"target_id": 1}},
    {"event_type": "track", "timestamp": 4.0, "data": {"id": 2}},
    {"event_type": "mission_end", "timestamp": 5.0, "data": {}},
]


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------


class TestListSessions:
    def test_empty_log_dir(self, tmp_path):
        app = _make_app(str(tmp_path))
        with app.test_client() as client:
            resp = client.get("/api/replay/sessions")
            assert resp.status_code == 200
            assert resp.get_json() == []

    def test_nonexistent_log_dir(self, tmp_path):
        app = _make_app(str(tmp_path / "nonexistent"))
        with app.test_client() as client:
            resp = client.get("/api/replay/sessions")
            assert resp.status_code == 200
            assert resp.get_json() == []

    def test_lists_jsonl_files(self, tmp_path):
        _write_jsonl(tmp_path / "telemetry.jsonl", SAMPLE_EVENTS)
        (tmp_path / "notes.txt").write_text("ignored")

        app = _make_app(str(tmp_path))
        with app.test_client() as client:
            resp = client.get("/api/replay/sessions")
            assert resp.status_code == 200
            data = resp.get_json()
            assert len(data) == 1
            assert data[0]["filename"] == "telemetry.jsonl"
            assert data[0]["event_count"] == 5

    def test_summary_stats_in_listing(self, tmp_path):
        _write_jsonl(tmp_path / "session.jsonl", SAMPLE_EVENTS)
        app = _make_app(str(tmp_path))
        with app.test_client() as client:
            resp = client.get("/api/replay/sessions")
            sess = resp.get_json()[0]
            assert sess["duration_s"] == pytest.approx(4.0)
            assert sess["start_ts"] == pytest.approx(1.0)
            assert sess["end_ts"] == pytest.approx(5.0)
            assert sess["counts_by_type"]["track"] == 3
            assert sess["counts_by_type"]["fired"] == 1


# ---------------------------------------------------------------------------
# get_session_events
# ---------------------------------------------------------------------------


class TestGetSessionEvents:
    def test_returns_all_events(self, tmp_path):
        _write_jsonl(tmp_path / "session.jsonl", SAMPLE_EVENTS)
        app = _make_app(str(tmp_path))
        with app.test_client() as client:
            resp = client.get("/api/replay/sessions/session.jsonl")
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["total_events"] == 5
            assert body["returned_events"] == 5
            assert len(body["events"]) == 5

    def test_filter_by_event_type(self, tmp_path):
        _write_jsonl(tmp_path / "session.jsonl", SAMPLE_EVENTS)
        app = _make_app(str(tmp_path))
        with app.test_client() as client:
            resp = client.get("/api/replay/sessions/session.jsonl?event_type=fired")
            body = resp.get_json()
            assert body["returned_events"] == 1
            assert body["events"][0]["event_type"] == "fired"

    def test_filter_multiple_event_types(self, tmp_path):
        _write_jsonl(tmp_path / "session.jsonl", SAMPLE_EVENTS)
        app = _make_app(str(tmp_path))
        with app.test_client() as client:
            resp = client.get(
                "/api/replay/sessions/session.jsonl?event_type=fired&event_type=mission_end"
            )
            body = resp.get_json()
            assert body["returned_events"] == 2
            types = {e["event_type"] for e in body["events"]}
            assert types == {"fired", "mission_end"}

    def test_from_ts_filter(self, tmp_path):
        _write_jsonl(tmp_path / "session.jsonl", SAMPLE_EVENTS)
        app = _make_app(str(tmp_path))
        with app.test_client() as client:
            resp = client.get("/api/replay/sessions/session.jsonl?from_ts=3.0")
            body = resp.get_json()
            assert all(e["timestamp"] >= 3.0 for e in body["events"])

    def test_to_ts_filter(self, tmp_path):
        _write_jsonl(tmp_path / "session.jsonl", SAMPLE_EVENTS)
        app = _make_app(str(tmp_path))
        with app.test_client() as client:
            resp = client.get("/api/replay/sessions/session.jsonl?to_ts=2.0")
            body = resp.get_json()
            assert all(e["timestamp"] <= 2.0 for e in body["events"])

    def test_limit_parameter(self, tmp_path):
        _write_jsonl(tmp_path / "session.jsonl", SAMPLE_EVENTS)
        app = _make_app(str(tmp_path))
        with app.test_client() as client:
            resp = client.get("/api/replay/sessions/session.jsonl?limit=2")
            body = resp.get_json()
            assert body["returned_events"] == 2
            assert body["total_events"] == 5

    def test_events_sorted_chronologically(self, tmp_path):
        events = list(reversed(SAMPLE_EVENTS))
        _write_jsonl(tmp_path / "session.jsonl", events)
        app = _make_app(str(tmp_path))
        with app.test_client() as client:
            resp = client.get("/api/replay/sessions/session.jsonl")
            body = resp.get_json()
            tss = [e["timestamp"] for e in body["events"]]
            assert tss == sorted(tss)

    def test_404_for_missing_file(self, tmp_path):
        app = _make_app(str(tmp_path))
        with app.test_client() as client:
            resp = client.get("/api/replay/sessions/nonexistent.jsonl")
            assert resp.status_code == 404

    def test_malformed_lines_skipped(self, tmp_path):
        with (tmp_path / "session.jsonl").open("w") as f:
            f.write('{"event_type": "track", "timestamp": 1.0}\n')
            f.write("NOT VALID JSON\n")
            f.write('{"event_type": "fired", "timestamp": 2.0}\n')
        app = _make_app(str(tmp_path))
        with app.test_client() as client:
            resp = client.get("/api/replay/sessions/session.jsonl")
            body = resp.get_json()
            assert body["total_events"] == 2


# ---------------------------------------------------------------------------
# get_session_summary
# ---------------------------------------------------------------------------


class TestGetSessionSummary:
    def test_returns_summary_without_events(self, tmp_path):
        _write_jsonl(tmp_path / "session.jsonl", SAMPLE_EVENTS)
        app = _make_app(str(tmp_path))
        with app.test_client() as client:
            resp = client.get("/api/replay/sessions/session.jsonl/summary")
            assert resp.status_code == 200
            body = resp.get_json()
            assert body["event_count"] == 5
            assert "events" not in body

    def test_empty_file_summary(self, tmp_path):
        (tmp_path / "empty.jsonl").write_text("")
        app = _make_app(str(tmp_path))
        with app.test_client() as client:
            resp = client.get("/api/replay/sessions/empty.jsonl/summary")
            body = resp.get_json()
            assert body["event_count"] == 0
            assert body["duration_s"] == 0.0
