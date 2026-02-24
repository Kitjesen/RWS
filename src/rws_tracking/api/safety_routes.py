"""No-fire zone CRUD REST API.

Operators can add, remove, and list safety no-fire zones at runtime without
restarting the server.  All changes take effect on the very next pipeline
step (the SafetyManager is wired directly into the running pipeline).

Routes
------
GET    /api/safety/zones          — list all active no-fire zones
POST   /api/safety/zones          — add a new zone
DELETE /api/safety/zones/<zone_id> — remove a zone by ID
GET    /api/safety/zones/<zone_id> — get one zone by ID
"""

from __future__ import annotations

import json
import logging
import os
import uuid

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

safety_bp = Blueprint("safety", __name__, url_prefix="/api/safety")

_NFZ_PERSIST_PATH = os.path.join("logs", "nfz_zones.json")


def _save_zones(sm) -> None:
    """Atomically persist the current NFZ zone list to disk.

    Uses a write-to-temp-then-rename pattern so the file is never partially
    written even if the process is killed mid-write.
    """
    try:
        zones_data = [
            {
                "zone_id": z.zone_id,
                "center_yaw_deg": z.center_yaw_deg,
                "center_pitch_deg": z.center_pitch_deg,
                "radius_deg": z.radius_deg,
                "zone_type": z.zone_type,
            }
            for z in sm._nfz.zones
        ]
        os.makedirs(os.path.dirname(_NFZ_PERSIST_PATH), exist_ok=True)
        tmp = _NFZ_PERSIST_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(zones_data, f, indent=2)
        os.replace(tmp, _NFZ_PERSIST_PATH)
        logger.debug("NFZ: persisted %d zones to %s", len(zones_data), _NFZ_PERSIST_PATH)
    except Exception as exc:
        logger.warning("NFZ: failed to persist zones: %s", exc)


def load_persisted_zones(safety_manager) -> int:
    """Load zones from the persist file into *safety_manager*.

    Returns the number of zones loaded (0 if file missing or on error).
    Called once at server startup after the pipeline is built.
    """
    if not os.path.exists(_NFZ_PERSIST_PATH):
        return 0
    try:
        with open(_NFZ_PERSIST_PATH, encoding="utf-8") as f:
            zones_data = json.load(f)
        from ..types import SafetyZone
        loaded = 0
        for z in zones_data:
            safety_manager.add_no_fire_zone(SafetyZone(**z))
            loaded += 1
        logger.info("NFZ: loaded %d persisted zones from %s", loaded, _NFZ_PERSIST_PATH)
        return loaded
    except Exception as exc:
        logger.warning("NFZ: failed to load persisted zones: %s", exc)
        return 0


def _get_safety_manager():
    """Return the SafetyManager from app extensions, falling back to the live pipeline."""
    sm = current_app.extensions.get("safety_manager")
    if sm is not None:
        return sm
    api = current_app.extensions.get("tracking_api")
    if api is not None:
        pipeline = getattr(api, "pipeline", None)
        if pipeline is not None:
            return getattr(pipeline, "_safety_manager", None)
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@safety_bp.route("/zones", methods=["GET"])
def list_zones():
    """Return all active no-fire zones.

    Response::

        [
          {
            "zone_id": "nfz_01",
            "center_yaw_deg": 45.0,
            "center_pitch_deg": 0.0,
            "radius_deg": 15.0,
            "zone_type": "no_fire"
          },
          ...
        ]
    """
    sm = _get_safety_manager()
    if sm is None:
        return jsonify([])

    zones = sm._nfz.zones  # NoFireZoneManager.zones property
    return jsonify([
        {
            "zone_id": z.zone_id,
            "center_yaw_deg": z.center_yaw_deg,
            "center_pitch_deg": z.center_pitch_deg,
            "radius_deg": z.radius_deg,
            "zone_type": z.zone_type,
        }
        for z in zones
    ])


@safety_bp.route("/zones/<zone_id>", methods=["GET"])
def get_zone(zone_id: str):
    """Get a specific no-fire zone by ID.

    Returns 404 if not found.
    """
    sm = _get_safety_manager()
    if sm is None:
        return jsonify({"error": "safety manager not configured"}), 503

    zone = sm._nfz._zones.get(zone_id)
    if zone is None:
        return jsonify({"error": f"zone '{zone_id}' not found"}), 404

    return jsonify({
        "zone_id": zone.zone_id,
        "center_yaw_deg": zone.center_yaw_deg,
        "center_pitch_deg": zone.center_pitch_deg,
        "radius_deg": zone.radius_deg,
        "zone_type": zone.zone_type,
    })


@safety_bp.route("/zones", methods=["POST"])
def add_zone():
    """Add a new no-fire zone.

    Body (JSON)::

        {
            "zone_id": "nfz_hospital",    // optional; auto-generated if omitted
            "center_yaw_deg": 45.0,
            "center_pitch_deg": 5.0,
            "radius_deg": 20.0,
            "zone_type": "no_fire"        // optional, default "no_fire"
        }

    Response::

        {"ok": true, "zone_id": "nfz_hospital"}
    """
    sm = _get_safety_manager()
    if sm is None:
        return jsonify({"error": "safety manager not configured"}), 503

    data = request.get_json(silent=True) or {}

    # Validate required fields.
    try:
        center_yaw = float(data["center_yaw_deg"])
        center_pitch = float(data["center_pitch_deg"])
        radius = float(data["radius_deg"])
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({
            "error": f"Missing or invalid field: {exc}. "
                     "Required: center_yaw_deg, center_pitch_deg, radius_deg"
        }), 400

    if radius <= 0:
        return jsonify({"error": "radius_deg must be positive"}), 400
    if radius > 180:
        return jsonify({"error": "radius_deg must not exceed 180"}), 400
    if not (-180.0 <= center_yaw <= 180.0):
        return jsonify({"error": "center_yaw_deg must be in [-180, 180]"}), 400
    if not (-90.0 <= center_pitch <= 90.0):
        return jsonify({"error": "center_pitch_deg must be in [-90, 90]"}), 400

    zone_id = str(data.get("zone_id") or f"nfz_{uuid.uuid4().hex[:8]}")
    zone_type = str(data.get("zone_type", "no_fire"))

    from ..types import SafetyZone
    zone = SafetyZone(
        zone_id=zone_id,
        center_yaw_deg=center_yaw,
        center_pitch_deg=center_pitch,
        radius_deg=radius,
        zone_type=zone_type,
    )
    sm.add_no_fire_zone(zone)
    _save_zones(sm)

    # Emit SSE notification.
    try:
        from .events import event_bus
        event_bus.emit("nfz_added", {
            "zone_id": zone_id,
            "center_yaw_deg": center_yaw,
            "center_pitch_deg": center_pitch,
            "radius_deg": radius,
        })
    except Exception:
        pass

    logger.info(
        "NFZ added: id=%s yaw=%.1f pitch=%.1f r=%.1f",
        zone_id, center_yaw, center_pitch, radius,
    )
    return jsonify({"ok": True, "zone_id": zone_id}), 201


@safety_bp.route("/zones/<zone_id>", methods=["DELETE"])
def remove_zone(zone_id: str):
    """Remove a no-fire zone by ID.

    Returns 404 if the zone does not exist.
    """
    sm = _get_safety_manager()
    if sm is None:
        return jsonify({"error": "safety manager not configured"}), 503

    removed = sm.remove_no_fire_zone(zone_id)
    if not removed:
        return jsonify({"error": f"zone '{zone_id}' not found"}), 404

    _save_zones(sm)

    # Emit SSE notification.
    try:
        from .events import event_bus
        event_bus.emit("nfz_removed", {"zone_id": zone_id})
    except Exception:
        pass

    logger.info("NFZ removed: id=%s", zone_id)
    return jsonify({"ok": True, "zone_id": zone_id})
