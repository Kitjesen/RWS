from __future__ import annotations

import logging
from pathlib import Path

from flask import Blueprint, current_app, jsonify

logger = logging.getLogger(__name__)

health_bp = Blueprint("health_ext", __name__)


def _get_monitor():
    monitor = current_app.extensions.get("health_monitor")
    if monitor is not None:
        return monitor
    api = current_app.extensions.get("tracking_api")
    if api is not None:
        pipeline = getattr(api, "pipeline", None)
        if pipeline is not None:
            return getattr(pipeline, "_health_monitor", None)
    return None


def _get_profile_manager():
    return current_app.extensions.get("profile_manager")


@health_bp.route("/api/health/subsystems", methods=["GET"])
def get_subsystem_health():
    monitor = _get_monitor()
    if monitor is None:
        return jsonify({"overall": "unknown", "subsystems": {}}), 200
    return jsonify({
        "overall": monitor.overall_status(),
        "subsystems": monitor.get_status(),
    })


@health_bp.route("/api/config/profiles", methods=["GET"])
def list_profiles():
    pm = _get_profile_manager()
    profiles_dir = Path("profiles")
    if pm is None:
        from ..config.profiles import ProfileManager
        pm = ProfileManager(profiles_dir)
    return jsonify({
        "profiles": pm.list_profiles(),
        "current": pm.current_profile,
    })


@health_bp.route("/api/config/profile/<name>", methods=["POST"])
def switch_profile(name: str):
    pm = _get_profile_manager()
    profiles_dir = Path("profiles")
    if pm is None:
        from ..config.profiles import ProfileManager
        pm = ProfileManager(profiles_dir)
    try:
        pm.load_profile(name)
        return jsonify({"status": "ok", "profile": name})
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
