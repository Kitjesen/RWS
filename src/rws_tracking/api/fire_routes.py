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

logger = logging.getLogger(__name__)

fire_bp = Blueprint("fire", __name__, url_prefix="/api/fire")


def _get_chain():
    """Get ShootingChain from app extensions, or None."""
    return current_app.extensions.get("shooting_chain")


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
    """ARM the system.  Body: {"operator_id": "op1"}"""
    chain = _get_chain()
    if chain is None:
        return jsonify({"error": "shooting_chain not configured"}), 503
    data = request.get_json(silent=True) or {}
    operator_id = data.get("operator_id", "")
    if not operator_id:
        return jsonify({"error": "operator_id required"}), 400
    ok = chain.arm(operator_id)
    if not ok:
        return jsonify({
            "error": f"cannot arm from state {chain.state.value}",
        }), 409
    return jsonify({"state": chain.state.value, "operator_id": operator_id})


@fire_bp.route("/safe", methods=["POST"])
def make_safe():
    """Return to SAFE.  Body: {"reason": "optional"}"""
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
    iff = current_app.extensions.get("iff_checker")
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
    iff = current_app.extensions.get("iff_checker")
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
    iff = current_app.extensions.get("iff_checker")
    if iff is None:
        return jsonify({"error": "iff_checker not configured"}), 503
    return jsonify({"friendly_track_ids": iff.friendly_track_ids})


@fire_bp.route("/heartbeat", methods=["POST"])
def operator_heartbeat():
    """Refresh operator heartbeat.  Body: {"operator_id": "op1"}

    Calls safety_manager.interlock.operator_heartbeat() if available.
    """
    data = request.get_json(silent=True) or {}
    operator_id = data.get("operator_id", "")
    if not operator_id:
        return jsonify({"error": "operator_id required"}), 400

    sm = current_app.extensions.get("safety_manager")
    if sm is not None and hasattr(sm, "interlock"):
        sm.interlock.operator_heartbeat()

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


def _parse_timestamp_from_filename(name: str) -> float:
    """Extract a float timestamp from a clip filename.

    Clip filenames follow the pattern ``<label>_<ts_int>_<ts_frac>.mp4`` where
    the timestamp seconds were formatted as ``{ts:.3f}`` with the ``.``
    replaced by ``_``.  For example ``fire_1708123456_789.mp4`` encodes
    ``1708123456.789``.

    Falls back to 0.0 if no numeric pattern is found.
    """
    stem = Path(name).stem  # strip extension
    # Match the last two numeric groups separated by _ that look like
    # <integer>_<3-digit-fraction>
    m = _TS_RE.search(stem)
    if m:
        try:
            return float(f"{m.group(1)}.{m.group(2)}")
        except ValueError:
            pass
    return 0.0


_TS_RE = __import__("re").compile(r"_(\d+)_(\d{3})$")
