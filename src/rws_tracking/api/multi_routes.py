"""Multi-gimbal pipeline REST endpoints."""

from flask import Blueprint, jsonify

multi_bp = Blueprint("multi", __name__, url_prefix="/api/multi")


@multi_bp.route("/status", methods=["GET"])
def status():
    """Return multi-gimbal pipeline status.

    The MultiGimbalPipeline is not yet wired to the HTTP server.
    Returns 501 Not Implemented with usage instructions.
    """
    return jsonify({
        "available": False,
        "message": (
            "MultiGimbalPipeline is implemented but not yet wired to HTTP server."
        ),
        "usage": (
            "Instantiate MultiGimbalPipeline directly in scripts/. "
            "See pipeline/multi_gimbal_pipeline.py."
        ),
        "gimbals": 0,
    }), 501
