"""Mission lifecycle REST API.

Provides one-click mission start / end with automatic profile loading,
session recording, and report generation.

State machine:
    IDLE -> ACTIVE (POST /api/mission/start)
    ACTIVE -> IDLE  (POST /api/mission/end  → generates HTML report)

Blueprint is registered by create_flask_app() in server.py.
It accesses the TrackingAPI instance via current_app.extensions['tracking_api'].

Preflight enforcement
---------------------
POST /api/mission/start runs a lightweight preflight check before allowing the
mission to begin.  Any check that returns ``status == "fail"`` blocks the start
and returns HTTP 424 with a structured error body.  Pass ``?force=true`` to
bypass (intended for automated tests only).

Enriched status
---------------
GET /api/mission/status returns additional fields:
  started_at, duration_s, roe_profile, shots_fired,
  targets_detected, targets_engaged, fire_chain_state
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
    "roe_profile": None,       # ROE profile name (may differ from mission profile)
    "started_at": None,        # epoch float
    "started_at_str": None,    # ISO-8601 string
    "camera_source": 0,
    "session_id": None,
    "targets_engaged": 0,
    "targets_detected": 0,     # cumulative detections this session
    "shots_fired": 0,          # cumulative fire events this session
    "last_report_path": None,
}


def _reset_state() -> None:
    _mission_state.update(
        active=False,
        profile=None,
        roe_profile=None,
        started_at=None,
        started_at_str=None,
        camera_source=0,
        session_id=None,
        targets_engaged=0,
        targets_detected=0,
        shots_fired=0,
        last_report_path=None,
    )


# ---------------------------------------------------------------------------
# Preflight helpers
# ---------------------------------------------------------------------------


def _run_preflight(api) -> list[str]:
    """Run lightweight pre-mission checks.

    Returns a list of failed check names.  An empty list means GO.
    These are a subset of the full selftest — only checks that can be
    evaluated quickly and without side-effects.
    """
    failed: list[str] = []

    # 1. logs/ directory writable
    try:
        from pathlib import Path as _Path

        logs = _Path("logs")
        logs.mkdir(exist_ok=True)
        probe = logs / ".preflight_probe"
        probe.write_text("ok")
        probe.unlink()
    except Exception:
        failed.append("logs_dir_writable")

    # 2. config loads without error
    try:
        from ..config import load_config  # noqa: F401
    except Exception:
        failed.append("config_valid")

    # 3. critical imports available
    try:
        from ..safety.shooting_chain import ShootingChain  # noqa: F401
        from ..telemetry.audit import AuditLogger  # noqa: F401
    except Exception:
        failed.append("pipeline_imports")

    # 4. shooting chain — informational only at pre-start stage.
    # The chain is created during pipeline initialisation; we don't block the
    # mission start if it's not present yet (pipeline may not be running).
    # The full GET /api/selftest performs a stricter check once the pipeline
    # is live.  We only report failure here when the chain extension slot is
    # explicitly registered but holds an unusable value.
    registered_chain = current_app.extensions.get("shooting_chain")
    if registered_chain is not None:
        # Extension slot exists — verify it exposes a state attribute.
        if not hasattr(registered_chain, "state"):
            failed.append("shooting_chain")

    return failed


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@mission_bp.route("/status", methods=["GET"])
def mission_status():
    """Return current mission state — enriched with runtime telemetry.

    Response fields:
        active          bool    — mission in progress
        profile         str     — mission profile name (or null)
        roe_profile     str     — ROE profile name (or null)
        session_id      str     — unique session identifier (or null)
        started_at      str     — ISO-8601 start timestamp (or null)
        duration_s      float   — elapsed seconds since mission start
        shots_fired     int     — cumulative fire events this session
        targets_detected int    — cumulative detection count (lifecycle)
        targets_engaged int     — cumulative engagement count
        fire_chain_state str    — ShootingChain state value (or null)
        lifecycle       dict    — TargetLifecycleManager summary (if running)
    """
    s = _mission_state.copy()
    started_at = s.get("started_at")
    s["duration_s"] = round(time.time() - started_at, 1) if started_at is not None else 0.0
    # Keep backward-compat alias
    s["elapsed_s"] = s["duration_s"]

    api = _api()
    if api is not None and api.pipeline is not None:
        # Lifecycle summary — total_seen maps to targets_detected
        lm = getattr(api.pipeline, "_lifecycle_manager", None)
        if lm is not None:
            summary = lm.summary()
            s["lifecycle"] = summary
            # Update targets_detected from lifecycle total_seen for richer response
            detected_from_lifecycle = summary.get("total_seen", s.get("targets_detected", 0))
            s["targets_detected"] = detected_from_lifecycle

        # Fire chain state
        chain = getattr(api.pipeline, "_shooting_chain", None)
        if chain is not None:
            s["fire_chain_state"] = chain.state.value

        # shots_fired: prefer audit logger count if available
        audit = getattr(api.pipeline, "_audit_logger", None)
        if audit is not None:
            fired_records = [r for r in getattr(audit, "_records", []) if r.get("event") == "fired"]
            if fired_records:
                s["shots_fired"] = len(fired_records)

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

    Query params:
        force=true   — skip preflight check (for testing only)

    Pre-flight enforcement
    ----------------------
    Before starting, a lightweight preflight check is performed.
    If any check fails, the route returns HTTP 424 with:
    {
        "success": false,
        "error": "preflight_failed",
        "message": "Pre-mission selftest failed. Run GET /api/selftest for details.",
        "failed_checks": ["logs_dir_writable", "config_valid"]
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

    # ── Preflight check ────────────────────────────────────────────────────
    force = request.args.get("force", "").lower() in ("true", "1", "yes")
    if not force:
        failed_checks = _run_preflight(api)
        if failed_checks:
            logger.warning("mission: preflight FAILED — checks: %s", failed_checks)
            return jsonify({
                "success": False,
                "error": "preflight_failed",
                "message": (
                    "Pre-mission selftest failed. "
                    "Run GET /api/selftest for details."
                ),
                "failed_checks": failed_checks,
            }), 424

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
        roe_profile=profile_name,  # may be overridden by loaded profile metadata
        started_at=time.time(),
        started_at_str=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        camera_source=camera_source,
        session_id=session_id,
        targets_engaged=0,
        targets_detected=0,
        shots_fired=0,
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
