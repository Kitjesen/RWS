"""Session replay API — browse and query historical telemetry sessions.

The RWS backend writes one ``logs/telemetry.jsonl`` file per server
invocation (see ``FileTelemetryLogger``).  Each line is a JSON object:

    {"event_type": "fired", "timestamp": 1234.5, "data": {...}}

This blueprint exposes the saved sessions so the Flutter dashboard (or any
HTTP client) can render an after-action timeline without writing a separate
database.

Routes
------
GET  /api/replay/sessions
    List all ``*.jsonl`` files in the log directory with summary stats.

GET  /api/replay/sessions/<filename>
    Return all events from the given session file.
    Optional query params:
      ``event_type`` (repeatable) — filter to these types
      ``from_ts``                 — skip events before this timestamp
      ``to_ts``                   — skip events after this timestamp
      ``limit``                   — max events to return (default 5000)

GET  /api/replay/sessions/<filename>/summary
    Return event-count-by-type and duration without all the raw data.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

replay_bp = Blueprint("replay", __name__, url_prefix="/api/replay")

# Default directory where telemetry JSONL files are stored.
_DEFAULT_LOG_DIR = "logs"


def _log_dir() -> Path:
    """Return the telemetry log directory path."""
    custom = current_app.config.get("TELEMETRY_LOG_DIR")
    return Path(custom or _DEFAULT_LOG_DIR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_session_file(path: Path) -> list[dict]:
    """Parse a JSONL telemetry file; silently skip malformed lines."""
    events: list[dict] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    events.append(obj)
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return events


def _session_summary(events: list[dict]) -> dict:
    """Compute stats for a session without returning full event data."""
    if not events:
        return {
            "event_count": 0,
            "duration_s": 0.0,
            "start_ts": None,
            "end_ts": None,
            "counts_by_type": {},
        }

    timestamps = [e.get("timestamp", 0.0) for e in events if "timestamp" in e]
    start = min(timestamps) if timestamps else 0.0
    end = max(timestamps) if timestamps else 0.0

    counts: dict[str, int] = {}
    for e in events:
        t = e.get("event_type", "unknown")
        counts[t] = counts.get(t, 0) + 1

    return {
        "event_count": len(events),
        "duration_s": round(end - start, 3),
        "start_ts": round(start, 3),
        "end_ts": round(end, 3),
        "counts_by_type": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
    }


def _guard_filename(filename: str) -> bool:
    """Return True if filename is safe (no path traversal)."""
    return (
        ".." not in filename
        and "/" not in filename
        and "\\" not in filename
        and filename.endswith(".jsonl")
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@replay_bp.route("/sessions", methods=["GET"])
def list_sessions():
    """Return a list of available telemetry session files.

    Response shape (array of session descriptors)::

        [
          {
            "filename": "telemetry.jsonl",
            "size_bytes": 102400,
            "modified_at": 1700000000.0,
            "event_count": 3421,
            "duration_s": 120.5,
            "start_ts": 1700000000.0,
            "end_ts": 1700000120.5,
            "counts_by_type": {"track": 3200, "fired": 3, ...}
          },
          ...
        ]
    """
    log_dir = _log_dir()
    if not log_dir.exists():
        return jsonify([])

    sessions = []
    for entry in sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            stat = entry.stat()
            events = _parse_session_file(entry)
            summary = _session_summary(events)
            sessions.append(
                {
                    "filename": entry.name,
                    "size_bytes": stat.st_size,
                    "modified_at": round(stat.st_mtime, 3),
                    **summary,
                }
            )
        except OSError:
            continue

    return jsonify(sessions)


@replay_bp.route("/sessions/<path:filename>", methods=["GET"])
def get_session_events(filename: str):
    """Return events from a session file with optional filtering.

    Query parameters
    ----------------
    event_type : str (repeatable)
        Only return events of these types (e.g. ``?event_type=fired&event_type=track``).
    from_ts : float
        Skip events with ``timestamp < from_ts``.
    to_ts : float
        Skip events with ``timestamp > to_ts``.
    limit : int
        Maximum number of events to return (default 5000, max 50000).

    Response shape::

        {
          "filename": "telemetry.jsonl",
          "total_events": 3421,
          "returned_events": 1200,
          "events": [
            {"event_type": "fired", "timestamp": 123.4, "data": {...}},
            ...
          ]
        }
    """
    if not _guard_filename(filename):
        return jsonify({"error": "invalid filename"}), 400

    log_dir = _log_dir()
    path = log_dir / filename
    if not path.exists() or not path.is_file():
        return jsonify({"error": "session not found"}), 404

    events = _parse_session_file(path)
    total = len(events)

    # --- Filters ---
    type_filter: set[str] = set(request.args.getlist("event_type"))
    try:
        from_ts = float(request.args.get("from_ts", 0.0))
    except ValueError:
        from_ts = 0.0
    try:
        to_ts = float(request.args.get("to_ts", float("inf")))
    except ValueError:
        to_ts = float("inf")
    try:
        limit = min(int(request.args.get("limit", 5000)), 50_000)
    except ValueError:
        limit = 5000

    filtered = [
        e
        for e in events
        if (not type_filter or e.get("event_type") in type_filter)
        and from_ts <= e.get("timestamp", 0.0) <= to_ts
    ]

    # Chronological order and hard limit.
    filtered.sort(key=lambda e: e.get("timestamp", 0.0))
    filtered = filtered[:limit]

    return jsonify(
        {
            "filename": filename,
            "total_events": total,
            "returned_events": len(filtered),
            "events": filtered,
        }
    )


@replay_bp.route("/sessions/<path:filename>/summary", methods=["GET"])
def get_session_summary(filename: str):
    """Return summary statistics for a session without returning all events.

    Useful for displaying session cards in the UI before the user drills in.
    """
    if not _guard_filename(filename):
        return jsonify({"error": "invalid filename"}), 400

    log_dir = _log_dir()
    path = log_dir / filename
    if not path.exists() or not path.is_file():
        return jsonify({"error": "session not found"}), 404

    events = _parse_session_file(path)
    return jsonify({"filename": filename, **_session_summary(events)})
