"""
REST API Server for RWS Tracking System
========================================

Provides HTTP endpoints for controlling the tracking system.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict
from typing import Any

import numpy as np
from flask import Flask, jsonify, request
from flask_cors import CORS

from ..config import SystemConfig, load_config
from ..hardware.imu_interface import BodyMotionProvider
from ..pipeline import VisionGimbalPipeline, build_pipeline_from_config
from ..types import BodyState

logger = logging.getLogger(__name__)


class TrackingAPI:
    """
    REST API wrapper for VisionGimbalPipeline.

    Provides endpoints for:
    - Starting/stopping tracking
    - Getting current status
    - Controlling gimbal manually
    - Updating configuration
    - Getting telemetry data
    """

    def __init__(
        self,
        config_path: str = "config.yaml",
        body_provider: BodyMotionProvider | None = None,
    ):
        self.config_path = config_path
        self.config = load_config(config_path)
        self.body_provider = body_provider

        self.pipeline: VisionGimbalPipeline | None = None
        self.running = False
        self.thread: threading.Thread | None = None
        self.camera = None

        # Status tracking
        self.last_frame_time = 0.0
        self.frame_count = 0
        self.error_count = 0
        self.last_error: str | None = None

    def start_tracking(self, camera_source: int | str = 0) -> dict[str, Any]:
        """Start the tracking pipeline."""
        if self.running:
            return {"success": False, "error": "Already running"}

        try:
            import cv2

            # Initialize camera
            self.camera = cv2.VideoCapture(camera_source)
            if not self.camera.isOpened():
                return {"success": False, "error": f"Cannot open camera {camera_source}"}

            # Build pipeline
            self.pipeline = build_pipeline_from_config(self.config, self.body_provider)
            self.pipeline.install_signal_handlers()

            # Start tracking thread
            self.running = True
            self.thread = threading.Thread(target=self._tracking_loop, daemon=True)
            self.thread.start()

            logger.info(f"Tracking started with camera source: {camera_source}")
            return {"success": True, "message": "Tracking started"}

        except Exception as e:
            logger.error(f"Failed to start tracking: {e}")
            return {"success": False, "error": str(e)}

    def stop_tracking(self) -> dict[str, Any]:
        """Stop the tracking pipeline."""
        if not self.running:
            return {"success": False, "error": "Not running"}

        try:
            self.running = False
            if self.pipeline:
                self.pipeline.stop()

            if self.thread:
                self.thread.join(timeout=5.0)

            if self.camera:
                self.camera.release()
                self.camera = None

            if self.pipeline:
                self.pipeline.cleanup()
                self.pipeline = None

            logger.info("Tracking stopped")
            return {"success": True, "message": "Tracking stopped"}

        except Exception as e:
            logger.error(f"Failed to stop tracking: {e}")
            return {"success": False, "error": str(e)}

    def get_status(self) -> dict[str, Any]:
        """Get current tracking status."""
        status = {
            "running": self.running,
            "frame_count": self.frame_count,
            "error_count": self.error_count,
            "last_error": self.last_error,
            "fps": 0.0,
        }

        if self.running and self.last_frame_time > 0:
            elapsed = time.monotonic() - self.last_frame_time
            if elapsed > 0:
                status["fps"] = 1.0 / elapsed

        if self.pipeline:
            feedback = self.pipeline.driver.get_feedback(time.monotonic())
            status["gimbal"] = {
                "yaw_deg": feedback.yaw_deg,
                "pitch_deg": feedback.pitch_deg,
                "yaw_rate_dps": feedback.yaw_rate_dps,
                "pitch_rate_dps": feedback.pitch_rate_dps,
            }

        return status

    def set_gimbal_position(self, yaw_deg: float, pitch_deg: float) -> dict[str, Any]:
        """Set gimbal position (absolute)."""
        if not self.pipeline:
            return {"success": False, "error": "Pipeline not initialized"}

        try:
            # Convert to rate command (simple P controller)
            feedback = self.pipeline.driver.get_feedback(time.monotonic())
            yaw_error = yaw_deg - feedback.yaw_deg
            pitch_error = pitch_deg - feedback.pitch_deg

            # Simple proportional control
            kp = 5.0
            yaw_rate = np.clip(kp * yaw_error, -180, 180)
            pitch_rate = np.clip(kp * pitch_error, -180, 180)

            self.pipeline.driver.set_yaw_pitch_rate(yaw_rate, pitch_rate, time.monotonic())

            return {
                "success": True,
                "target": {"yaw_deg": yaw_deg, "pitch_deg": pitch_deg},
                "current": {"yaw_deg": feedback.yaw_deg, "pitch_deg": feedback.pitch_deg},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def set_gimbal_rate(self, yaw_rate_dps: float, pitch_rate_dps: float) -> dict[str, Any]:
        """Set gimbal rate (velocity control)."""
        if not self.pipeline:
            return {"success": False, "error": "Pipeline not initialized"}

        try:
            self.pipeline.driver.set_yaw_pitch_rate(
                yaw_rate_dps, pitch_rate_dps, time.monotonic()
            )
            return {
                "success": True,
                "command": {"yaw_rate_dps": yaw_rate_dps, "pitch_rate_dps": pitch_rate_dps},
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_telemetry(self) -> dict[str, Any]:
        """Get telemetry metrics."""
        if not self.pipeline:
            return {"success": False, "error": "Pipeline not initialized"}

        try:
            metrics = self.pipeline.telemetry.snapshot_metrics()
            return {"success": True, "metrics": metrics}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def update_config(self, config_dict: dict[str, Any]) -> dict[str, Any]:
        """Update configuration (requires restart)."""
        try:
            # Validate and update config
            # This is a simplified version - you may want more validation
            for key, value in config_dict.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)

            return {
                "success": True,
                "message": "Config updated (restart required to apply)",
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _tracking_loop(self):
        """Main tracking loop (runs in separate thread)."""
        import cv2

        logger.info("Tracking loop started")

        while self.running and not self.pipeline.should_stop():
            try:
                ret, frame = self.camera.read()
                if not ret:
                    logger.warning("Failed to read frame")
                    self.error_count += 1
                    continue

                ts = time.monotonic()
                self.pipeline.step(frame, ts)

                self.frame_count += 1
                self.last_frame_time = ts

            except Exception as e:
                logger.error(f"Error in tracking loop: {e}")
                self.error_count += 1
                self.last_error = str(e)

        logger.info("Tracking loop stopped")


def create_flask_app(api: TrackingAPI) -> Flask:
    """Create Flask application with API endpoints."""
    app = Flask(__name__)
    CORS(app)  # Enable CORS for cross-origin requests

    @app.route("/api/health", methods=["GET"])
    def health():
        """Health check endpoint."""
        return jsonify({"status": "ok", "service": "rws-tracking"})

    @app.route("/api/start", methods=["POST"])
    def start():
        """Start tracking."""
        data = request.get_json() or {}
        camera_source = data.get("camera_source", 0)
        result = api.start_tracking(camera_source)
        return jsonify(result)

    @app.route("/api/stop", methods=["POST"])
    def stop():
        """Stop tracking."""
        result = api.stop_tracking()
        return jsonify(result)

    @app.route("/api/status", methods=["GET"])
    def status():
        """Get current status."""
        result = api.get_status()
        return jsonify(result)

    @app.route("/api/gimbal/position", methods=["POST"])
    def set_position():
        """Set gimbal position."""
        data = request.get_json()
        if not data or "yaw_deg" not in data or "pitch_deg" not in data:
            return jsonify({"success": False, "error": "Missing yaw_deg or pitch_deg"}), 400

        result = api.set_gimbal_position(data["yaw_deg"], data["pitch_deg"])
        return jsonify(result)

    @app.route("/api/gimbal/rate", methods=["POST"])
    def set_rate():
        """Set gimbal rate."""
        data = request.get_json()
        if not data or "yaw_rate_dps" not in data or "pitch_rate_dps" not in data:
            return jsonify({
                "success": False,
                "error": "Missing yaw_rate_dps or pitch_rate_dps"
            }), 400

        result = api.set_gimbal_rate(data["yaw_rate_dps"], data["pitch_rate_dps"])
        return jsonify(result)

    @app.route("/api/telemetry", methods=["GET"])
    def telemetry():
        """Get telemetry data."""
        result = api.get_telemetry()
        return jsonify(result)

    @app.route("/api/config", methods=["POST"])
    def update_config():
        """Update configuration."""
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No config data provided"}), 400

        result = api.update_config(data)
        return jsonify(result)

    return app


def run_api_server(
    api: TrackingAPI | None = None,
    host: str = "0.0.0.0",
    port: int = 5000,
    debug: bool = False,
) -> None:
    """
    Run the API server.

    Parameters
    ----------
    api : TrackingAPI, optional
        API instance. If None, creates a new one.
    host : str
        Host to bind to (default: "0.0.0.0" for all interfaces)
    port : int
        Port to bind to (default: 5000)
    debug : bool
        Enable Flask debug mode
    """
    if api is None:
        api = TrackingAPI()

    app = create_flask_app(api)

    logger.info(f"Starting RWS Tracking API server on {host}:{port}")
    app.run(host=host, port=port, debug=debug)
