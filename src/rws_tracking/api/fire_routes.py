"""Flask Blueprint for fire-control REST endpoints.

The :class:`~rws_tracking.safety.shooting_chain.ShootingChain` instance
must be stored as ``current_app.extensions['shooting_chain']`` by the
caller that creates the Flask app.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request, send_file

from ..telemetry.video_ring_buffer import _parse_timestamp_from_filename


def _check_fire_rate_limit():
    """Return a 429 response if the caller has exceeded the fire-endpoint rate limit.

    Uses the ``fire_rate_limiter`` stored in ``current_app.extensions`` (set by
    ``create_flask_app``).  Falls back gracefully if the limiter is absent so
    the Blueprint can be mounted on a bare Flask app in tests without issues.

    Returns None when the request is allowed, or a (Response, 429) tuple when
    the limit is exceeded.
    """
    limiter = current_app.extensions.get("fire_rate_limiter")
    if limiter is None:
        return None
    key = request.remote_addr or "unknown"
    if not limiter.is_allowed(key):
        return jsonify({"error": "Rate limit exceeded"}), 429
    return None

logger = logging.getLogger(__name__)

fire_bp = Blueprint("fire", __name__, url_prefix="/api/fire")


def _get_chain():
    """Get ShootingChain from app extensions, falling back to the live pipeline."""
    chain = current_app.extensions.get("shooting_chain")
    if chain is not None:
        return chain
    api = current_app.extensions.get("tracking_api")
    if api is not None:
        pipeline = getattr(api, "pipeline", None)
        if pipeline is not None:
            return getattr(pipeline, "_shooting_chain", None)
    return None


def _get_iff():
    """Get IFFChecker from app extensions, falling back to the live pipeline."""
    iff = current_app.extensions.get("iff_checker")
    if iff is not None:
        return iff
    api = current_app.extensions.get("tracking_api")
    if api is not None:
        pipeline = getattr(api, "pipeline", None)
        if pipeline is not None:
            return getattr(pipeline, "_iff_checker", None)
    return None


@fire_bp.route("/status", methods=["GET"])
def get_status():
    """Return current fire chain state."""
    chain = _get_chain()
    if chain is None:
        return jsonify({"state": "not_configured", "can_fire": False}), 200
    return jsonify({
        "state": chain.state.value,
        "can_fire": chain.can_fire,
        "operator_id": chain.operator_id,
    })


@fire_bp.route("/arm", methods=["POST"])
def arm():
    """ARM the system.  Body: {"operator_id": "op1"}

    When the two-man rule is enabled on the shooting chain this endpoint uses
    ``chain.initiate_arm()`` so that the first call returns a
    ``pending_confirmation`` status and the second (different) operator's call
    completes the arm.  Use ``GET /api/fire/arm/pending`` to poll the pending
    status and ``POST /api/fire/arm/confirm`` as a semantic alias for the
    second-operator confirmation.
    """
    rate_err = _check_fire_rate_limit()
    if rate_err is not None:
        return rate_err
    chain = _get_chain()
    if chain is None:
        return jsonify({"error": "shooting_chain not configured"}), 503
    data = request.get_json(silent=True) or {}
    operator_id = str(data.get("operator_id", ""))[:64]  # cap at 64 chars
    if not operator_id:
        return jsonify({"error": "operator_id required"}), 400

    # Two-man rule: delegate to initiate_arm() when enabled.
    if getattr(chain, "_two_man_rule_enabled", False):
        result = chain.initiate_arm(operator_id)
        status = result.get("status")
        if status == "error":
            return jsonify(result), 409
        if status == "expired":
            return jsonify(result), 410
        # pending_confirmation (202) or armed (200)
        http_code = 200 if status == "armed" else 202
        result["chain_state"] = chain.state.value
        try:
            from .events import event_bus
            event_bus.emit("fire_chain_state", {
                "state": chain.state.value,
                "two_man_status": status,
                "operator_id": operator_id,
            })
        except Exception:
            pass
        return jsonify(result), http_code

    # Normal single-operator arm.
    ok = chain.arm(operator_id)
    if not ok:
        return jsonify({
            "error": f"cannot arm from state {chain.state.value}",
        }), 409
    return jsonify({"state": chain.state.value, "operator_id": operator_id})


@fire_bp.route("/arm/pending", methods=["GET"])
def arm_pending():
    """Return the pending two-man arm request status (for the second operator).

    Response when a request is pending::

        {"pending": true, "initiated_by": "op1", "expires_in_s": 23.4}

    Response when no request is pending::

        {"pending": false}

    Returns 503 if the shooting chain is not configured.
    """
    chain = _get_chain()
    if chain is None:
        return jsonify({"error": "shooting_chain not configured"}), 503
    if not getattr(chain, "_two_man_rule_enabled", False):
        return jsonify({"pending": False, "two_man_rule_enabled": False})
    status = chain.get_arm_pending_status()
    if status is None:
        return jsonify({"pending": False, "two_man_rule_enabled": True})
    return jsonify({"pending": True, **status})


@fire_bp.route("/arm/confirm", methods=["POST"])
def arm_confirm():
    """Second-operator confirmation endpoint for the two-man arming rule.

    Semantically identical to ``POST /api/fire/arm`` but makes the operator's
    intent explicit.  Body: {"operator_id": "op2"}
    """
    rate_err = _check_fire_rate_limit()
    if rate_err is not None:
        return rate_err
    chain = _get_chain()
    if chain is None:
        return jsonify({"error": "shooting_chain not configured"}), 503
    data = request.get_json(silent=True) or {}
    operator_id = data.get("operator_id", "")
    if not operator_id:
        return jsonify({"error": "operator_id required"}), 400
    if not getattr(chain, "_two_man_rule_enabled", False):
        return jsonify({"error": "two_man_rule is not enabled"}), 409
    result = chain.initiate_arm(operator_id)
    status = result.get("status")
    if status == "error":
        return jsonify(result), 409
    if status == "expired":
        return jsonify(result), 410
    if status == "pending_confirmation":
        # Caller used /confirm but there was no pending request — treat as
        # a first-initiation.
        result["chain_state"] = chain.state.value
        return jsonify(result), 202
    result["chain_state"] = chain.state.value
    try:
        from .events import event_bus
        event_bus.emit("fire_chain_state", {
            "state": chain.state.value,
            "two_man_status": "armed",
            "operator_id": operator_id,
        })
    except Exception:
        pass
    return jsonify(result)


@fire_bp.route("/safe", methods=["POST"])
def make_safe():
    """Return to SAFE.  Body: {"reason": "optional"}"""
    rate_err = _check_fire_rate_limit()
    if rate_err is not None:
        return rate_err
    chain = _get_chain()
    if chain is None:
        return jsonify({"error": "shooting_chain not configured"}), 503
    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "")
    chain.safe(reason)
    return jsonify({"state": chain.state.value})


@fire_bp.route("/request", methods=["POST"])
def request_fire():
    """Human fire request.  Body: {"operator_id": "op1"}

    Returns 403 if not in FIRE_AUTHORIZED state.
    """
    rate_err = _check_fire_rate_limit()
    if rate_err is not None:
        return rate_err
    chain = _get_chain()
    if chain is None:
        return jsonify({"error": "shooting_chain not configured"}), 503
    data = request.get_json(silent=True) or {}
    operator_id = data.get("operator_id", "")
    if not operator_id:
        return jsonify({"error": "operator_id required"}), 400
    ok = chain.request_fire(operator_id)
    if not ok:
        return jsonify({
            "error": f"cannot request fire from state {chain.state.value}",
        }), 403
    return jsonify({
        "state": chain.state.value,
        "can_fire": chain.can_fire,
    })


@fire_bp.route("/report", methods=["GET"])
def get_report():
    """Download HTML mission debrief report from audit log.

    Query params:
      mission (str): mission name shown in report title (default "Mission Debrief")
    """
    audit = current_app.extensions.get("audit_logger")
    if audit is None:
        return jsonify({"error": "audit_logger not configured"}), 503

    mission_name = request.args.get("mission", "Mission Debrief")
    from ..telemetry.report import generate_report
    html_content = generate_report(audit, mission_name=mission_name)
    return Response(
        html_content,
        mimetype="text/html",
        headers={"Content-Disposition": "inline; filename=mission_report.html"},
    )


@fire_bp.route("/iff/mark_friendly", methods=["POST"])
def iff_mark_friendly():
    """Mark a track ID as friendly (operator-designated IFF whitelist).

    Body: {"track_id": 3}
    """
    iff = _get_iff()
    if iff is None:
        return jsonify({"error": "iff_checker not configured"}), 503
    data = request.get_json(silent=True) or {}
    track_id = data.get("track_id")
    if track_id is None:
        return jsonify({"error": "track_id required"}), 400
    try:
        track_id = int(track_id)
    except (TypeError, ValueError):
        return jsonify({"error": "track_id must be an integer"}), 400
    iff.add_friendly_track(track_id)
    logger.info("IFF: track %d marked friendly via API", track_id)
    return jsonify({"ok": True, "track_id": track_id, "action": "marked_friendly"})


@fire_bp.route("/iff/unmark_friendly", methods=["POST"])
def iff_unmark_friendly():
    """Remove a track ID from the friendly whitelist.

    Body: {"track_id": 3}
    """
    iff = _get_iff()
    if iff is None:
        return jsonify({"error": "iff_checker not configured"}), 503
    data = request.get_json(silent=True) or {}
    track_id = data.get("track_id")
    if track_id is None:
        return jsonify({"error": "track_id required"}), 400
    try:
        track_id = int(track_id)
    except (TypeError, ValueError):
        return jsonify({"error": "track_id must be an integer"}), 400
    iff.remove_friendly_track(track_id)
    logger.info("IFF: track %d unmarked friendly via API", track_id)
    return jsonify({"ok": True, "track_id": track_id, "action": "unmarked_friendly"})


@fire_bp.route("/iff/status", methods=["GET"])
def iff_status():
    """Return the list of operator-designated friendly track IDs."""
    iff = _get_iff()
    if iff is None:
        return jsonify({"error": "iff_checker not configured"}), 503
    return jsonify({"friendly_track_ids": iff.friendly_track_ids})


@fire_bp.route("/heartbeat", methods=["POST"])
def operator_heartbeat():
    """Refresh operator heartbeat.  Body: {"operator_id": "op1"}

    Calls safety_manager.interlock.operator_heartbeat() if available.
    """
    data = request.get_json(silent=True) or {}
    operator_id = str(data.get("operator_id", ""))[:64]  # cap at 64 chars
    if not operator_id:
        return jsonify({"error": "operator_id required"}), 400

    sm = current_app.extensions.get("safety_manager")
    if sm is None:
        api = current_app.extensions.get("tracking_api")
        if api is not None:
            pipeline = getattr(api, "pipeline", None)
            if pipeline is not None:
                sm = getattr(pipeline, "_safety_manager", None)
    if sm is not None and hasattr(sm, "interlock"):
        sm.interlock.operator_heartbeat()

    watchdog = current_app.extensions.get("operator_watchdog")
    if watchdog is not None:
        watchdog.heartbeat(operator_id)

    return jsonify({"ok": True, "operator_id": operator_id})


# ---------------------------------------------------------------------------
# Fire-event clip endpoints
# ---------------------------------------------------------------------------

def _clips_dir() -> Path | None:
    """Return the clips output directory from the video_ring_buffer extension."""
    vrb = current_app.extensions.get("video_ring_buffer")
    if vrb is not None:
        return Path(vrb.output_dir)
    # Fall back to a configurable app config key.
    clips_dir = current_app.config.get("CLIPS_DIR")
    if clips_dir:
        return Path(clips_dir)
    return None


@fire_bp.route("/clips", methods=["GET"])
def list_clips():
    """List all saved fire-event clip files.

    Returns a JSON array of objects with keys:
      - ``filename`` : bare filename (not a full path)
      - ``size_bytes`` : file size in bytes
      - ``timestamp`` : float seconds parsed from the filename, or 0.0
    """
    clips_dir = _clips_dir()
    if clips_dir is None or not clips_dir.exists():
        return jsonify([])

    entries = []
    for entry in sorted(clips_dir.iterdir()):
        if not entry.is_file():
            continue
        size = entry.stat().st_size
        ts = _parse_timestamp_from_filename(entry.name)
        entries.append({
            "filename": entry.name,
            "size_bytes": size,
            "timestamp": ts,
        })

    # Most-recent first.
    entries.sort(key=lambda e: e["timestamp"], reverse=True)
    return jsonify(entries)


@fire_bp.route("/clips/<path:filename>", methods=["GET"])
def download_clip(filename: str):
    """Serve a clip file for download.

    ``filename`` must be a bare filename (no directory traversal).
    Returns 404 if not found, 400 if the filename looks suspicious.
    """
    # Guard against path traversal.
    if os.sep in filename or "/" in filename or "\\" in filename or ".." in filename:
        return jsonify({"error": "invalid filename"}), 400

    clips_dir = _clips_dir()
    if clips_dir is None:
        return jsonify({"error": "clips directory not configured"}), 503

    clip_path = clips_dir / filename
    if not clip_path.exists() or not clip_path.is_file():
        return jsonify({"error": "clip not found"}), 404

    return send_file(
        str(clip_path),
        as_attachment=True,
        download_name=filename,
    )


# ---------------------------------------------------------------------------
# Target designation (operator C2 override)
# ---------------------------------------------------------------------------


def _get_pipeline():
    """Get the active pipeline from the tracking_api extension, or None."""
    api = current_app.extensions.get("tracking_api")
    if api is not None:
        return getattr(api, "pipeline", None)
    return None


@fire_bp.route("/dwell", methods=["GET"])
def get_dwell_status():
    """Return engagement dwell timer status.

    While the pipeline has a target in LOCK + fire_authorized, a dwell timer
    counts up to ``engagement_dwell_time_s``.  This endpoint exposes the
    current fraction so the UI can show a countdown progress bar.

    Response schema::

        {
          "active": true,         // true when dwell is running
          "track_id": 5,          // track being dwelled (null when inactive)
          "elapsed_s": 1.23,      // seconds elapsed
          "total_s": 2.0,         // configured dwell duration
          "fraction": 0.615       // elapsed / total [0.0, 1.0]
        }
    """
    pipeline = _get_pipeline()
    if pipeline is None:
        return jsonify({"active": False, "track_id": None,
                        "elapsed_s": 0.0, "total_s": 0.0, "fraction": 0.0})
    return jsonify(pipeline.dwell_status)


@fire_bp.route("/designate", methods=["POST"])
def designate_target():
    """Operator-designate a specific track for engagement.

    Overrides the auto-selected target.  The designation is cleared
    automatically when the track disappears from the scene.

    Body (JSON):
    {
        "track_id": 3,
        "operator_id": "op1"  // optional
    }

    Response:
    {"ok": true, "track_id": 3}
    """
    data = request.get_json(silent=True) or {}
    track_id = data.get("track_id")
    if track_id is None:
        return jsonify({"ok": False, "error": "track_id is required"}), 400
    if not isinstance(track_id, int) or track_id <= 0 or track_id > 99999:
        return jsonify({"ok": False, "error": "track_id must be a positive integer \u2264 99999"}), 400

    operator_id = str(data.get("operator_id", ""))[:64]  # cap at 64 chars
    pipeline = _get_pipeline()
    if pipeline is None:
        return jsonify({"error": "pipeline not running"}), 503

    pipeline.designate_target(track_id, operator_id)

    try:
        from .events import event_bus
        event_bus.emit("target_designated", {
            "track_id": track_id,
            "operator_id": operator_id,
        })
    except Exception:
        pass

    logger.info("designation: track=%d by operator='%s'", track_id, operator_id)
    return jsonify({"ok": True, "track_id": track_id})


@fire_bp.route("/designate", methods=["DELETE"])
def clear_designation():
    """Clear the operator designation, returning to auto-selection.

    Response:
    {"ok": true, "cleared_track_id": 3}  // or null if none was set
    """
    pipeline = _get_pipeline()
    if pipeline is None:
        return jsonify({"error": "pipeline not running"}), 503

    old_id = pipeline.designated_track_id
    pipeline.clear_designation()

    try:
        from .events import event_bus
        event_bus.emit("target_designated", {"track_id": None, "operator_id": ""})
    except Exception:
        pass

    return jsonify({"ok": True, "cleared_track_id": old_id})


@fire_bp.route("/designate", methods=["GET"])
def get_designation():
    """Return current operator designation.

    Response:
    {"track_id": 3, "designated": true}  // or track_id=null if none
    """
    pipeline = _get_pipeline()
    if pipeline is None:
        return jsonify({"track_id": None, "designated": False})

    tid = pipeline.designated_track_id
    return jsonify({"track_id": tid, "designated": tid is not None})


# ---------------------------------------------------------------------------
# Rules of Engagement (ROE) endpoints
# ---------------------------------------------------------------------------


def _get_roe():
    """Return the RoeManager from app extensions, or None."""
    return current_app.extensions.get("roe_manager")


@fire_bp.route("/roe", methods=["GET"])
def list_roe_profiles():
    """List all registered ROE profiles and indicate the active one.

    Response::

        {
          "active_profile": "training",
          "profiles": [
            {
              "name": "training",
              "display_name": "训练模式 (Training)",
              "active": true,
              "fire_enabled": false,
              "min_lock_time_s": 0.0,
              "max_engagement_range_m": 9999.0,
              "nfz_buffer_multiplier": 1.0,
              "require_two_man": false,
              "description": "..."
            },
            ...
          ]
        }
    """
    roe = _get_roe()
    if roe is None:
        return jsonify({"error": "roe_manager not configured"}), 503
    return jsonify({
        "active_profile": roe.active.name,
        "profiles": roe.list_profiles(),
    })


@fire_bp.route("/roe/<name>", methods=["POST"])
def switch_roe_profile(name: str):
    """Switch the active ROE profile.

    Body (optional)::

        {"operator_id": "op1"}

    Response::

        {
          "ok": true,
          "active_profile": "exercise",
          "fire_enabled": true
        }

    Returns 404 if the named profile does not exist.
    """
    roe = _get_roe()
    if roe is None:
        return jsonify({"error": "roe_manager not configured"}), 503
    data = request.get_json(silent=True) or {}
    operator_id = str(data.get("operator_id", ""))
    try:
        profile = roe.switch_profile(name)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404

    logger.info("ROE profile switched to %r by operator='%s'", name, operator_id)
    try:
        from .events import event_bus
        event_bus.emit("roe_profile_changed", {
            "profile": profile.name,
            "fire_enabled": profile.fire_enabled,
            "operator_id": operator_id,
        })
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "active_profile": profile.name,
        "fire_enabled": profile.fire_enabled,
        "require_two_man": profile.require_two_man,
    })
