"""Controller mode REST API.

Allows operators to switch between PID and MPC axis controllers at runtime.
The change takes effect on the next pipeline (re)start — the running pipeline
is not modified in-place, avoiding race conditions during active tracking.

Routes
------
GET  /api/controller/mode        — current mode + available options
POST /api/controller/mode        — set mode ('pid' | 'mpc')
GET  /api/controller/mpc/config  — current MPC tuning parameters
POST /api/controller/mpc/config  — update MPC tuning parameters
"""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

controller_bp = Blueprint("controller", __name__, url_prefix="/api/controller")

_VALID_MODES = {"pid", "mpc"}


def _get_api():
    """Return the TrackingAPI instance from Flask app extensions."""
    return current_app.extensions.get("tracking_api")


# ---------------------------------------------------------------------------
# Mode read/write
# ---------------------------------------------------------------------------


@controller_bp.get("/mode")
def get_mode():
    """Return current controller mode and available options."""
    api = _get_api()
    mode = getattr(api, "_controller_mode", "pid") if api else "pid"
    return jsonify(
        {
            "mode": mode,
            "available": sorted(_VALID_MODES),
            "requires_restart": True,  # Change takes effect on next pipeline start
        }
    )


@controller_bp.post("/mode")
def set_mode():
    """Set controller mode.  Takes effect on next pipeline (re)start.

    Body (JSON): ``{"mode": "pid" | "mpc"}``
    """
    api = _get_api()
    if api is None:
        return jsonify({"error": "API not available"}), 503

    body = request.get_json(silent=True) or {}
    mode = str(body.get("mode", "")).lower()
    if mode not in _VALID_MODES:
        return jsonify(
            {"error": f"Invalid mode '{mode}'. Must be one of {sorted(_VALID_MODES)}"}
        ), 400

    old_mode = getattr(api, "_controller_mode", "pid")
    api._controller_mode = mode  # type: ignore[attr-defined]

    logger.info("Controller mode: %s → %s", old_mode, mode)
    return jsonify(
        {
            "ok": True,
            "mode": mode,
            "previous": old_mode,
            "requires_restart": True,
        }
    )


# ---------------------------------------------------------------------------
# MPC config read/write
# ---------------------------------------------------------------------------


@controller_bp.get("/mpc/config")
def get_mpc_config():
    """Return current MPC tuning parameters from config."""
    api = _get_api()
    if api is None:
        return jsonify({"error": "API not available"}), 503

    cfg = getattr(api, "_cfg", None)
    if cfg is None:
        return jsonify({"error": "Config not loaded"}), 503

    mpc_cfg = getattr(cfg.controller, "mpc", None)
    if mpc_cfg is None:
        return jsonify({})

    import dataclasses

    return jsonify(dataclasses.asdict(mpc_cfg))


@controller_bp.post("/mpc/config")
def set_mpc_config():
    """Update MPC tuning parameters (persists to in-memory config for next start).

    Body: subset of MPCConfig fields, e.g. ``{"q_error": 200, "r_effort": 0.5}``
    """
    api = _get_api()
    if api is None:
        return jsonify({"error": "API not available"}), 503

    cfg = getattr(api, "_cfg", None)
    if cfg is None:
        return jsonify({"error": "Config not loaded"}), 503

    body = request.get_json(silent=True) or {}
    _NUM_FIELDS = {
        "horizon",
        "q_error",
        "r_effort",
        "q_terminal",
        "integral_limit",
        "output_limit",
        "ki",
        "derivative_lpf_alpha",
        "feedforward_kv",
        "plant_dt",
    }

    import dataclasses

    old_mpc = getattr(cfg.controller, "mpc", None)
    if old_mpc is None:
        from ..config.control import MPCConfig

        old_mpc = MPCConfig()

    old_dict = dataclasses.asdict(old_mpc)
    updated = {
        k: float(v) if k != "horizon" else int(v) for k, v in body.items() if k in _NUM_FIELDS
    }
    if not updated:
        return jsonify({"error": "No valid fields provided", "valid": sorted(_NUM_FIELDS)}), 400

    old_dict.update(updated)
    from ..config.control import MPCConfig

    new_mpc = MPCConfig(**old_dict)

    # Replace mpc field in the frozen controller config via dataclass replace
    new_ctrl_cfg = dataclasses.replace(cfg.controller, mpc=new_mpc)
    # Replace controller field in the frozen system config
    new_cfg = dataclasses.replace(cfg, controller=new_ctrl_cfg)
    api._cfg = new_cfg  # type: ignore[attr-defined]

    logger.info("MPC config updated: %s", updated)
    return jsonify({"ok": True, "updated": updated, "mpc": dataclasses.asdict(new_mpc)})
