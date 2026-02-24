"""
REST API Server for RWS Tracking System
========================================

Provides HTTP endpoints for controlling the tracking system,
including video streaming (MJPEG), safety management, and threat assessment.
"""

from __future__ import annotations

import hmac
import logging
import os
import threading
import time
from dataclasses import asdict
from typing import Any

import numpy as np
from flask import Flask, Response, jsonify, request
from flask_cors import CORS

from ..config import SystemConfig, load_config
from ..hardware.imu_interface import BodyMotionProvider
from ..pipeline import VisionGimbalPipeline, build_pipeline_from_config
from ..types import BodyState
from .video_stream import (
    FrameAnnotator,
    FrameBuffer,
    MJPEGStreamer,
    VideoStreamConfig,
)

logger = logging.getLogger(__name__)


class _RateLimiter:
    """Simple per-key token-bucket rate limiter backed by a threading.Lock.

    Each key (e.g. a client IP address) gets its own bucket.  The bucket is
    refilled on every call based on elapsed wall time, so no background thread
    is required.

    Parameters
    ----------
    max_requests:
        Maximum number of requests allowed within *window_s* seconds.
    window_s:
        Rolling window duration in seconds.
    """

    def __init__(self, max_requests: int, window_s: float) -> None:
        self._max = max_requests
        self._window = window_s
        self._lock = threading.Lock()
        # key → (tokens_remaining: float, last_refill_time: float)
        self._buckets: dict[str, tuple[float, float]] = {}

    def is_allowed(self, key: str) -> bool:
        """Return True if the request is within the rate limit, False if exceeded."""
        now = time.monotonic()
        with self._lock:
            tokens, last_refill = self._buckets.get(key, (float(self._max), now))

            # Refill tokens proportionally to elapsed time.
            elapsed = now - last_refill
            refill = elapsed * (self._max / self._window)
            tokens = min(float(self._max), tokens + refill)

            if tokens >= 1.0:
                tokens -= 1.0
                self._buckets[key] = (tokens, now)
                return True

            # Not enough tokens — record the attempt without consuming.
            self._buckets[key] = (tokens, now)
            return False


# Rate limiter for fire-control endpoints: 30 requests/minute per IP.
_fire_rate_limiter = _RateLimiter(max_requests=30, window_s=60.0)

# Rate limiter for mission lifecycle endpoints: 5 req/min per IP.
_mission_rate_limiter = _RateLimiter(max_requests=5, window_s=60.0)

# Rate limiter for config update endpoint: 10 req/min per IP.
_config_rate_limiter = _RateLimiter(max_requests=10, window_s=60.0)


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
        video_config: VideoStreamConfig | None = None,
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

        # Video streaming
        self._video_cfg = video_config or VideoStreamConfig(enabled=True)
        self._frame_buffer = FrameBuffer(max_size=self._video_cfg.buffer_size)
        self._annotator = FrameAnnotator(self._video_cfg)
        self._mjpeg_streamer = MJPEGStreamer(self._frame_buffer, self._video_cfg)

        # Last known tracks/threats for annotation and API responses
        self._last_tracks: list = []
        self._selected_target_id: int | None = None
        self._last_threat_assessments: list = []

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
            metrics = self.pipeline.telemetry.snapshot_metrics()
            status.update({
                # Decision state (SEARCH / TRACK / LOCK / LOST)
                "state": self.pipeline._last_track_state,
                # Gimbal position at root level (Flutter chart reads these)
                "yaw_deg": feedback.yaw_deg,
                "pitch_deg": feedback.pitch_deg,
                # Per-frame tracking errors for the real-time error chart
                "yaw_error_deg": self.pipeline._last_yaw_error_deg,
                "pitch_error_deg": self.pipeline._last_pitch_error_deg,
                # Rolling telemetry metrics
                "lock_rate": metrics.get("lock_rate", 0.0),
                "avg_abs_error_deg": metrics.get("avg_abs_error_deg", 0.0),
                "switches_per_min": metrics.get("switches_per_min", 0.0),
                # Full gimbal feedback also available nested
                "gimbal": {
                    "yaw_deg": feedback.yaw_deg,
                    "pitch_deg": feedback.pitch_deg,
                    "yaw_rate_dps": feedback.yaw_rate_dps,
                    "pitch_rate_dps": feedback.pitch_rate_dps,
                },
            })

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
        """Update configuration with live hot-reload support.

        Supports hot-updating the following sections without restart:
        - ``pid``: PID gains (yaw/pitch kp, ki, kd)
        - ``selector``: Target selector weights
        - ``safety_zones``: Add/remove no-fire zones

        Other config keys are stored but require a restart to take effect.
        """
        try:
            applied: list[str] = []

            # --- Hot-reload PID parameters ---
            if "pid" in config_dict and self.pipeline is not None:
                pid_data = config_dict["pid"]
                ctrl = self.pipeline.controller
                for axis in ("yaw", "pitch"):
                    axis_data = pid_data.get(axis)
                    if axis_data is None:
                        continue
                    pid_obj = ctrl._yaw_pid if axis == "yaw" else ctrl._pitch_pid
                    for param in ("kp", "ki", "kd"):
                        if param in axis_data:
                            pid_obj.cfg = type(pid_obj.cfg)(
                                **{
                                    **{
                                        f.name: getattr(pid_obj.cfg, f.name)
                                        for f in pid_obj.cfg.__dataclass_fields__.values()
                                    },
                                    param: float(axis_data[param]),
                                }
                            )
                    applied.append(f"pid.{axis}")

            # --- Hot-reload selector weights ---
            if "selector" in config_dict and self.pipeline is not None:
                sel_data = config_dict["selector"]
                sel = self.pipeline.selector
                if hasattr(sel, "_cfg") and hasattr(sel._cfg, "weights"):
                    weights = sel._cfg.weights
                    for key in ("confidence", "size", "center_proximity", "track_age", "class_weight"):
                        if key in sel_data:
                            setattr(weights, key, float(sel_data[key]))
                    applied.append("selector")

            # --- Hot-reload safety zones ---
            if "safety_zones" in config_dict and self.pipeline is not None:
                zones_data = config_dict["safety_zones"]
                sm = self.pipeline._safety_manager
                if sm is not None:
                    from ..types import SafetyZone
                    if zones_data.get("action") == "add" and "zone" in zones_data:
                        z = zones_data["zone"]
                        sm.add_no_fire_zone(SafetyZone(**z))
                        applied.append("safety_zones.add")
                    elif zones_data.get("action") == "remove" and "zone_id" in zones_data:
                        sm.remove_no_fire_zone(zones_data["zone_id"])
                        applied.append("safety_zones.remove")

            # --- Store remaining keys for restart-required updates ---
            stored: list[str] = []
            for key, value in config_dict.items():
                if key not in ("pid", "selector", "safety_zones"):
                    if hasattr(self.config, key):
                        setattr(self.config, key, value)
                        stored.append(key)

            msg_parts = []
            if applied:
                msg_parts.append(f"Hot-applied: {', '.join(applied)}")
            if stored:
                msg_parts.append(f"Stored (restart to apply): {', '.join(stored)}")

            return {
                "success": True,
                "message": "; ".join(msg_parts) if msg_parts else "No changes applied",
                "hot_applied": applied,
                "stored": stored,
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
                outputs = self.pipeline.step(frame, ts)

                self.frame_count += 1
                self.last_frame_time = ts

                # Update tracking info for video stream
                if hasattr(outputs, 'tracks'):
                    self._last_tracks = outputs.tracks
                elif hasattr(outputs, 'all_targets'):
                    self._last_tracks = outputs.all_targets

                if outputs.selected_target is not None:
                    self._selected_target_id = outputs.selected_target.track_id
                else:
                    self._selected_target_id = None

                # Store threat assessments for /api/threats endpoint
                self._last_threat_assessments = getattr(outputs, "threat_assessments", [])

                # Push annotated frame to video buffer
                if self._video_cfg.enabled:
                    state_text = f"FPS:{1.0 / max(ts - self.last_frame_time, 0.001):.0f} F:{self.frame_count}"
                    # Collect active safety zones for NFZ visualization.
                    safety_zones = None
                    try:
                        sm = getattr(self.pipeline, "_safety_manager", None)
                        if sm is not None:
                            safety_zones = list(sm._nfz.zones)
                    except Exception:
                        pass
                    annotated = self._annotator.annotate(
                        frame,
                        tracks=self._last_tracks,
                        selected_id=self._selected_target_id,
                        safety_zones=safety_zones,
                        status_text=state_text,
                    )
                    self._frame_buffer.push(annotated, ts)

                    # Record frame to clip if recording is active.
                    try:
                        from .video_record_routes import record_frame
                        record_frame(annotated)
                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"Error in tracking loop: {e}")
                self.error_count += 1
                self.last_error = str(e)

        logger.info("Tracking loop stopped")


def _wire_pipeline_extensions(app: Flask, api: "TrackingAPI") -> None:
    """Wire pipeline sub-components into app.extensions so Blueprint routes can access them.

    Called both at app creation (if pipeline is already running) and after
    each successful start_tracking() call so that fire/safety routes work
    immediately without requiring a server restart.
    """
    pipeline = api.pipeline
    if pipeline is None:
        return

    for attr, key in [
        ("_shooting_chain", "shooting_chain"),
        ("_audit_logger", "audit_logger"),
        ("_health_monitor", "health_monitor"),
        ("_safety_manager", "safety_manager"),
        ("_iff_checker", "iff_checker"),
        ("_roe_manager", "roe_manager"),
    ]:
        obj = getattr(pipeline, attr, None)
        if obj is not None:
            app.extensions[key] = obj

    # Start operator watchdog once when shooting_chain becomes available.
    if "shooting_chain" in app.extensions and "operator_watchdog" not in app.extensions:
        try:
            from ..safety.watchdog import OperatorWatchdog
            watchdog = OperatorWatchdog(
                app.extensions["shooting_chain"],
                timeout_s=getattr(api, "_operator_timeout_s", 10.0),
            )
            watchdog.start()
            app.extensions["operator_watchdog"] = watchdog
        except Exception as exc:
            logger.warning("Could not start operator watchdog: %s", exc)

    # Load persisted NFZ zones into the live safety manager (if available).
    if "safety_manager" in app.extensions:
        try:
            from .safety_routes import load_persisted_zones
            load_persisted_zones(app.extensions["safety_manager"])
        except Exception as exc:
            logger.warning("Could not load persisted NFZ zones: %s", exc)


def create_flask_app(api: TrackingAPI) -> Flask:
    """Create Flask application with API endpoints."""
    app = Flask(__name__)
    CORS(app)  # Enable CORS for cross-origin requests

    # ------------------------------------------------------------------
    # Optional Bearer token authentication middleware
    # ------------------------------------------------------------------
    _api_key: str | None = os.environ.get("RWS_API_KEY") or None

    # Paths that are always accessible without a token (monitoring/streaming).
    # These are read-only or infrastructure endpoints that must remain open.
    _AUTH_EXEMPT_EXACT = frozenset([
        "/api/health",
        "/api/events",
        "/metrics",
        "/api/status",
        "/api/selftest",
        "/api/telemetry",
        "/api/threats",
    ])
    _AUTH_EXEMPT_PREFIXES = (
        "/api/health/",   # sub-health routes
        "/api/video/",    # MJPEG stream + snapshot
    )

    # Only apply auth to mutating (non-GET) requests or sensitive paths.
    # GET-only read endpoints are implicitly exempt when the method is GET.
    _AUTH_REQUIRED_PREFIXES = (
        "/api/fire/",
        "/api/mission/",
        "/api/config",
        "/api/safety/",
        "/api/gimbal/",
    )

    if _api_key is not None:
        logger.info("RWS API: Bearer token authentication is ENABLED.")

        @app.before_request
        def _check_auth():
            path = request.path
            method = request.method

            # Always exempt: monitoring, SSE stream, video feed, read-only status.
            if path in _AUTH_EXEMPT_EXACT:
                return None
            for prefix in _AUTH_EXEMPT_PREFIXES:
                if path.startswith(prefix):
                    return None

            # Only enforce auth on mutating methods or explicitly sensitive paths.
            # Pure GET requests to non-sensitive paths are allowed without auth.
            needs_auth = False
            if method != "GET":
                for prefix in _AUTH_REQUIRED_PREFIXES:
                    if path.startswith(prefix):
                        needs_auth = True
                        break
            else:
                # GET /api/fire/* is already secured by fire chain state; allow.
                # GET /api/config and GET /api/safety/* are read-only; allow.
                needs_auth = False

            if not needs_auth:
                return None

            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[len("Bearer "):]
                if hmac.compare_digest(token, _api_key):
                    return None

            return jsonify({"error": "Unauthorized"}), 401

    # Expose rate limiters via app.extensions so blueprints can access them
    # without a circular import.
    app.extensions["fire_rate_limiter"] = _fire_rate_limiter
    app.extensions["mission_rate_limiter"] = _mission_rate_limiter
    app.extensions["config_rate_limiter"] = _config_rate_limiter

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
        if result.get("success"):
            _wire_pipeline_extensions(app, api)
        return jsonify(result)

    @app.route("/api/stop", methods=["POST"])
    def stop():
        """Stop tracking."""
        result = api.stop_tracking()
        return jsonify(result)

    # Flutter dashboard uses /api/tracking/start and /api/tracking/stop.
    @app.route("/api/tracking/start", methods=["POST"])
    def tracking_start():
        """Alias for /api/start — used by Flutter dashboard."""
        return start()

    @app.route("/api/tracking/stop", methods=["POST"])
    def tracking_stop():
        """Alias for /api/stop — used by Flutter dashboard."""
        return stop()

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

    @app.route("/api/config", methods=["GET"])
    def get_config():
        """Return the current effective configuration (PID, selector, etc.)."""
        from ..config.loader import load_config
        try:
            cfg = load_config(api.config_path)
            ctrl = cfg.controller
            if ctrl is None:
                return jsonify({"error": "No controller config"}), 503
            return jsonify({
                "pid": {
                    "yaw":   {"kp": ctrl.yaw_pid.kp,   "ki": ctrl.yaw_pid.ki,   "kd": ctrl.yaw_pid.kd},
                    "pitch": {"kp": ctrl.pitch_pid.kp, "ki": ctrl.pitch_pid.ki, "kd": ctrl.pitch_pid.kd},
                }
            })
        except Exception as exc:
            return jsonify({"error": str(exc)}), 503

    @app.route("/api/config", methods=["POST"])
    def update_config():
        """Update configuration."""
        limiter = app.extensions.get("config_rate_limiter")
        if limiter is not None:
            key = request.remote_addr or "unknown"
            if not limiter.is_allowed(key):
                return jsonify({"success": False, "error": "Rate limit exceeded"}), 429

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No config data provided"}), 400

        result = api.update_config(data)
        return jsonify(result)

    # ------------------------------------------------------------------
    # Video streaming endpoints
    # ------------------------------------------------------------------

    @app.route("/api/video/feed")
    def video_feed():
        """MJPEG video stream endpoint.

        Usage in browser: <img src="http://host:port/api/video/feed" />
        """
        if not api._video_cfg.enabled:
            return jsonify({"error": "Video streaming is disabled"}), 503

        return Response(
            api._mjpeg_streamer.generate(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    @app.route("/api/video/snapshot")
    def video_snapshot():
        """Get a single JPEG snapshot of the current frame."""
        result = api._frame_buffer.get_latest(timeout=2.0)
        if result is None:
            return jsonify({"error": "No frame available"}), 503

        import cv2

        frame, ts = result
        quality = int(request.args.get("quality", api._video_cfg.jpeg_quality))
        encode_param = [cv2.IMWRITE_JPEG_QUALITY, quality]
        success, encoded = cv2.imencode(".jpg", frame, encode_param)
        if not success:
            return jsonify({"error": "Encoding failed"}), 500

        return Response(
            encoded.tobytes(),
            mimetype="image/jpeg",
            headers={"X-Timestamp": str(ts)},
        )

    @app.route("/api/video/config", methods=["GET"])
    def video_config():
        """Get current video stream configuration."""
        cfg = api._video_cfg
        return jsonify({
            "enabled": cfg.enabled,
            "jpeg_quality": cfg.jpeg_quality,
            "max_fps": cfg.max_fps,
            "scale_factor": cfg.scale_factor,
            "annotate_detections": cfg.annotate_detections,
            "annotate_tracks": cfg.annotate_tracks,
            "annotate_crosshair": cfg.annotate_crosshair,
        })

    @app.route("/api/threats", methods=["GET"])
    def get_threats():
        """Return current threat assessment list (from ThreatAssessor).

        Response shape:
        {
          "threats": [
            {"track_id": 1, "threat_score": 0.85, "priority_rank": 1,
             "distance_score": 0.7, "velocity_score": 0.3,
             "class_score": 0.4, "heading_score": 0.5, "class_id": "person",
             "distance_m": 45.2},
            ...
          ]
        }
        """
        threats_out = []
        # Merge threat assessment with track info (class_id comes from Track)
        track_class: dict[int, str] = {
            t.track_id: t.class_id for t in api._last_tracks
        }
        dist_cache: dict[int, float] = getattr(api, "_distance_cache", {})
        if not hasattr(api, "_distance_cache"):
            # Try to get from pipeline if available
            if api.pipeline and hasattr(api.pipeline, "_distance_cache"):
                dist_cache = api.pipeline._distance_cache

        for ta in api._last_threat_assessments:
            threats_out.append({
                "track_id": ta.track_id,
                "threat_score": round(ta.threat_score, 4),
                "priority_rank": ta.priority_rank,
                "distance_score": round(ta.distance_score, 4),
                "velocity_score": round(ta.velocity_score, 4),
                "class_score": round(ta.class_score, 4),
                "heading_score": round(ta.heading_score, 4),
                "class_id": track_class.get(ta.track_id, "unknown"),
                "distance_m": round(dist_cache.get(ta.track_id, 0.0), 1),
            })
        return jsonify({
            "threats": threats_out,
            "pipeline_active": api.running and api.pipeline is not None,
        })

    # Wire pipeline components into Flask extensions so Blueprint routes can access them.
    # (pipeline may be None at startup; _wire_pipeline_extensions is also called after
    # each successful start_tracking() so routes work immediately.)
    _wire_pipeline_extensions(app, api)

    # Fire control routes
    from .fire_routes import fire_bp
    app.register_blueprint(fire_bp)

    from .health_routes import health_bp
    app.register_blueprint(health_bp)

    # Mission controller routes
    app.extensions["tracking_api"] = api
    from .mission_routes import mission_bp
    app.register_blueprint(mission_bp)

    # Prometheus metrics endpoint
    from .metrics_routes import metrics_bp
    app.register_blueprint(metrics_bp)

    # System self-test
    from .selftest_routes import selftest_bp
    app.register_blueprint(selftest_bp)

    # Real-time SSE event stream
    from .events import events_bp, event_bus
    app.register_blueprint(events_bp)
    event_bus.start()

    # Session replay / after-action review
    from .replay_routes import replay_bp
    app.register_blueprint(replay_bp)

    # No-fire zone CRUD
    from .safety_routes import safety_bp
    app.register_blueprint(safety_bp)

    # Multi-gimbal pipeline status (stub — pipeline not yet wired to HTTP)
    from .multi_routes import multi_bp
    app.register_blueprint(multi_bp)

    # Video clip recording
    from .video_record_routes import record_bp
    app.register_blueprint(record_bp)

    # Config file watcher — hot-reload config.yaml into live PID/selector params.
    try:
        from ..tools.config_reload import ConfigReloader
        from .events import event_bus as _eb

        def _on_config_reload(new_cfg) -> None:
            """Translate a fresh SystemConfig into update_config() dict."""
            ctrl = new_cfg.controller
            if ctrl is None:
                return
            update_dict: dict = {
                "pid": {
                    "yaw": {
                        "kp": ctrl.yaw_pid.kp,
                        "ki": ctrl.yaw_pid.ki,
                        "kd": ctrl.yaw_pid.kd,
                    },
                    "pitch": {
                        "kp": ctrl.pitch_pid.kp,
                        "ki": ctrl.pitch_pid.ki,
                        "kd": ctrl.pitch_pid.kd,
                    },
                }
            }
            result = api.update_config(update_dict)
            try:
                _eb.emit("config_reloaded", {
                    "hot_applied": result.get("hot_applied", []),
                    "message": result.get("message", ""),
                })
            except Exception:
                pass
            logger.info("config_reload: %s", result.get("message", ""))

        _config_reloader = ConfigReloader(
            config_path=api.config_path,
            callback=_on_config_reload,
            check_interval=2.0,
        )
        _config_reloader.start()
        app.extensions["config_reloader"] = _config_reloader
        logger.info("Config file watcher started: %s", api.config_path)
    except Exception as exc:
        logger.warning("Could not start config file watcher: %s", exc)

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
