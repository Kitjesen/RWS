"""Flask Blueprint for fire-control REST endpoints.

The :class:`~rws_tracking.safety.shooting_chain.ShootingChain` instance
must be stored as ``current_app.extensions['shooting_chain']`` by the
caller that creates the Flask app.
"""

from __future__ import annotations

import logging

from flask import Blueprint, Response, current_app, jsonify, request

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
