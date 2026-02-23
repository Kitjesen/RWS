"""Mission lifecycle REST API.

Provides one-click mission start / end with automatic profile loading,
session recording, and report generation.

State machine:
    IDLE -> ACTIVE (POST /api/mission/start)
    ACTIVE -> IDLE  (POST /api/mission/end  → generates HTML report)

Blueprint is registered by create_flask_app() in server.py.
It accesses the TrackingAPI instance via current_app.extensions['tracking_api'].
"""

from __future__ import annotations

import datetime
import logging
import time
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request, send_file

logger = logging.getLogger(__name__)

mission_bp = Blueprint("mission", __name__, url_prefix="/api/mission")


def _api():
    return current_app.extensions.get("tracking_api")


# ---------------------------------------------------------------------------
# Mission state (server-side singleton, owned by the Blueprint)
# ---------------------------------------------------------------------------

_mission_state: dict = {
    "active": False,
    "profile": None,
    "started_at": None,       # epoch float
    "started_at_str": None,   # human-readable
    "camera_source": 0,
    "session_id": None,
    "targets_engaged": 0,
    "last_report_path": None,
}


def _reset_state() -> None:
    _mission_state.update(
        active=False,
        profile=None,
        started_at=None,
        started_at_str=None,
        camera_source=0,
        session_id=None,
        targets_engaged=0,
        last_report_path=None,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@mission_bp.route("/status", methods=["GET"])
def mission_status():
    """Return current mission state."""
    s = _mission_state.copy()
    if s["started_at"] is not None:
        s["elapsed_s"] = round(time.time() - s["started_at"], 1)
    else:
        s["elapsed_s"] = 0.0

    # Augment with lifecycle summary if available
    api = _api()
    if api is not None and api.pipeline is not None:
        lm = getattr(api.pipeline, "_lifecycle_manager", None)
        if lm is not None:
            s["lifecycle"] = lm.summary()

        chain = getattr(api.pipeline, "_shooting_chain", None)
        if chain is not None:
            s["fire_chain_state"] = chain.state.value

    return jsonify(s)


@mission_bp.route("/start", methods=["POST"])
def mission_start():
    """Start a new mission.

    Body (JSON, all optional):
    {
        "profile": "urban_cqb",      // mission profile name
        "camera_source": 0,          // camera index or path
        "mission_name": "Alpha-1"    // display name
    }
    """
    if _mission_state["active"]:
        return jsonify({"error": "Mission already active. Call /api/mission/end first."}), 409

    api = _api()
    if api is None:
        return jsonify({"error": "tracking_api not configured"}), 503

    data = request.get_json(silent=True) or {}
    profile_name = data.get("profile")
    camera_source = data.get("camera_source", 0)
    mission_name = data.get("mission_name", f"Mission-{datetime.datetime.now():%Y%m%d-%H%M%S}")

    # Load profile if specified
    if profile_name:
        from ..config.profiles import ProfileManager
        try:
            pm = ProfileManager()
            profile_cfg = pm.load_profile(profile_name)
            logger.info("mission: loaded profile '%s'", profile_name)
        except (FileNotFoundError, ValueError) as exc:
            return jsonify({"error": f"Profile '{profile_name}' not found: {exc}"}), 404

    # Reset lifecycle + audit logger for fresh session
    if api.pipeline is not None:
        lm = getattr(api.pipeline, "_lifecycle_manager", None)
        if lm is not None:
            lm.reset()
            logger.info("mission: lifecycle manager reset")

        chain = getattr(api.pipeline, "_shooting_chain", None)
        if chain is not None:
            chain.safe("mission_start")

    # Start tracking
    result = api.start_tracking(camera_source)
    if not result.get("success"):
        return jsonify({"error": result.get("error", "Failed to start tracking")}), 500

    session_id = f"{mission_name.replace(' ', '_')}_{datetime.datetime.now():%Y%m%d_%H%M%S}"
    _mission_state.update(
        active=True,
        profile=profile_name,
        started_at=time.time(),
        started_at_str=datetime.datetime.now().isoformat(),
        camera_source=camera_source,
        session_id=session_id,
        targets_engaged=0,
        last_report_path=None,
    )

    logger.info("mission START: session=%s profile=%s", session_id, profile_name)

    try:
        from .events import event_bus
        event_bus.emit("mission_started", {
            "session_id": session_id,
            "profile": profile_name,
            "ts": round(time.time(), 3),
        })
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "session_id": session_id,
        "profile": profile_name,
        "camera_source": camera_source,
        "started_at": _mission_state["started_at_str"],
    })


@mission_bp.route("/end", methods=["POST"])
def mission_end():
    """End the active mission and generate a debrief report.

    Body (JSON, optional):
    { "reason": "mission complete" }

    Returns the path to the generated HTML report.
    """
    if not _mission_state["active"]:
        return jsonify({"error": "No active mission"}), 409

    api = _api()

    # Auto-safe the fire chain before stopping
    if api is not None and api.pipeline is not None:
        chain = getattr(api.pipeline, "_shooting_chain", None)
        if chain is not None:
            chain.safe("mission_end")

    # Stop tracking
    if api is not None:
        api.stop_tracking()

    # Generate audit report
    report_path = None
    if api is not None and api.pipeline is not None:
        audit = getattr(api.pipeline, "_audit_logger", None)
        if audit is not None and audit._records:  # noqa: SLF001
            from ..telemetry.report import generate_report
            mission_label = _mission_state.get("session_id") or "mission"
            report_dir = Path("logs/reports")
            report_dir.mkdir(parents=True, exist_ok=True)
            report_file = report_dir / f"{mission_label}_report.html"
            generate_report(audit, mission_name=mission_label, output_path=str(report_file))
            report_path = str(report_file)
            logger.info("mission: report written to %s", report_path)

    # Gather final stats
    elapsed = round(time.time() - _mission_state["started_at"], 1) if _mission_state["started_at"] else 0
    session_id = _mission_state.get("session_id")

    _reset_state()

    try:
        from .events import event_bus
        event_bus.emit("mission_ended", {
            "session_id": session_id,
            "elapsed_s": elapsed,
            "report_path": report_path,
            "ts": round(time.time(), 3),
        })
    except Exception:
        pass

    # Build a URL the frontend can open directly.
    report_url = (
        f"/api/mission/report/{Path(report_path).name}"
        if report_path
        else None
    )

    return jsonify({
        "ok": True,
        "session_id": session_id,
        "elapsed_s": elapsed,
        "report_path": report_path,
        "report_url": report_url,
    })


# ---------------------------------------------------------------------------
# Report file download
# ---------------------------------------------------------------------------

@mission_bp.route("/report/<path:filename>", methods=["GET"])
def download_report(filename: str):
    """Serve a mission HTML report from logs/reports/.

    Example: GET /api/mission/report/my_session_report.html
    """
    report_dir = Path("logs/reports")
    report_file = report_dir / filename
    if not report_file.exists() or not report_file.is_file():
        return jsonify({"error": "report not found"}), 404
    # Prevent path traversal
    try:
        report_file.resolve().relative_to(report_dir.resolve())
    except ValueError:
        return jsonify({"error": "invalid path"}), 400
    return send_file(str(report_file), mimetype="text/html")
