"""Multi-gimbal pipeline REST endpoints."""

from flask import Blueprint, jsonify

multi_bp = Blueprint("multi", __name__, url_prefix="/api/multi")


@multi_bp.route("/status", methods=["GET"])
def status():
    """Return multi-gimbal pipeline availability and usage information.

    MultiGimbalPipeline is fully implemented but requires direct instantiation —
    each gimbal unit needs its own camera feed which is not yet managed by the
    HTTP server.  Returns HTTP 200 with ``available: false`` so clients can
    programmatically check without treating the response as an error.
    """
    return jsonify(
        {
            "available": False,
            "reason": (
                "MultiGimbalPipeline requires direct instantiation — "
                "see scripts/demo/multi_target_demo.py"
            ),
            "gimbal_units": 0,
            "documentation": {
                "python_example": (
                    "from rws_tracking.pipeline.multi_gimbal_pipeline import "
                    "MultiGimbalPipeline, GimbalUnit"
                ),
                "allocator": "Hungarian algorithm (scipy.optimize.linear_sum_assignment)",
                "max_gimbals": "N (configurable)",
                "selector": "WeightedMultiTargetSelector (top-N by threat score)",
            },
        }
    ), 200
