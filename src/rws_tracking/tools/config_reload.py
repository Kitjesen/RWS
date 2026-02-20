"""Configuration hot-reload support using file watching."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable

from ..config import SystemConfig, load_config

logger = logging.getLogger(__name__)


class ConfigReloader:
    """Watches config file and reloads on changes.

    Example usage:
    ```python
    def on_config_change(new_config: SystemConfig):
        print(f"Config updated: PID Kp = {new_config.controller.yaw_pid.kp}")
        pipeline.update_config(new_config)

    reloader = ConfigReloader(
        config_path="config.yaml",
        callback=on_config_change
    )
    reloader.start()

    # ... run pipeline ...

    reloader.stop()
    ```
    """

    def __init__(
        self,
        config_path: str | Path,
        callback: Callable[[SystemConfig], None],
        check_interval: float = 1.0,
    ):
        """Initialize config reloader.

        Parameters
        ----------
        config_path : str | Path
            Path to config YAML file
        callback : Callable[[SystemConfig], None]
            Function to call when config changes
        check_interval : float
            How often to check for changes (seconds)
        """
        self.config_path = Path(config_path)
        self.callback = callback
        self.check_interval = check_interval

        self._last_mtime: float | None = None
        self._running = False
        self._thread: threading.Thread | None = None

        logger.info("ConfigReloader initialized: %s", self.config_path)

    def start(self) -> None:
        """Start watching config file."""
        if self._running:
            logger.warning("ConfigReloader already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        logger.info("ConfigReloader started")

    def stop(self) -> None:
        """Stop watching config file."""
        if not self._running:
            return

        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        logger.info("ConfigReloader stopped")

    def _watch_loop(self) -> None:
        """Main watch loop (runs in background thread)."""
        while self._running:
            try:
                self._check_and_reload()
            except Exception as e:
                logger.error("Error in config watch loop: %s", e)

            time.sleep(self.check_interval)

    def _check_and_reload(self) -> None:
        """Check if config file changed and reload if needed."""
        if not self.config_path.exists():
            logger.warning("Config file not found: %s", self.config_path)
            return

        try:
            current_mtime = self.config_path.stat().st_mtime

            if self._last_mtime is None:
                # First check, just record mtime
                self._last_mtime = current_mtime
                return

            if current_mtime > self._last_mtime:
                logger.info("Config file changed, reloading...")
                self._last_mtime = current_mtime

                # Small delay to ensure file write is complete
                time.sleep(0.1)

                # Load new config
                new_config = load_config(str(self.config_path))

                # Call callback
                self.callback(new_config)

                logger.info("Config reloaded successfully")

        except Exception as e:
            logger.error("Failed to reload config: %s", e)


class ConfigServer:
    """HTTP API for runtime config updates.

    Provides REST endpoints for updating configuration without file editing.

    Example usage:
    ```python
    server = ConfigServer(pipeline, port=8080)
    server.start()

    # Client can now POST to:
    # - http://localhost:8080/config/pid
    # - http://localhost:8080/config/selector
    # - http://localhost:8080/config/controller
    ```

    Example client request:
    ```bash
    curl -X POST http://localhost:8080/config/pid \\
      -H "Content-Type: application/json" \\
      -d '{"axis": "yaw", "kp": 6.0, "ki": 0.5, "kd": 0.4}'
    ```
    """

    def __init__(self, pipeline, port: int = 8080, host: str = "0.0.0.0"):
        """Initialize config server.

        Parameters
        ----------
        pipeline : VisionGimbalPipeline
            Pipeline instance to update
        port : int
            HTTP port (default: 8080)
        host : str
            Bind address (default: 0.0.0.0)
        """
        self.pipeline = pipeline
        self.port = port
        self.host = host
        self._app = None
        self._server_thread: threading.Thread | None = None

        try:
            from flask import Flask  # noqa: F401

            self._flask_available = True
        except ImportError:
            logger.warning(
                "Flask not installed. ConfigServer requires Flask. Install with: pip install flask"
            )
            self._flask_available = False

        if self._flask_available:
            self._setup_app()

    def _setup_app(self) -> None:
        """Setup Flask app and routes."""
        from flask import Flask, jsonify, request

        app = Flask(__name__)

        @app.route("/health", methods=["GET"])
        def health():
            return jsonify({"status": "ok", "pipeline": "running"})

        @app.route("/config/pid", methods=["POST"])
        def update_pid():
            """Update PID parameters at runtime.

            Request body:
            {
                "axis": "yaw" | "pitch",
                "kp": float,
                "ki": float,
                "kd": float
            }
            """
            try:
                data = request.json
                axis = data.get("axis", "yaw")

                ctrl = self.pipeline.controller
                if axis == "yaw":
                    pid_obj = ctrl._yaw_pid
                elif axis == "pitch":
                    pid_obj = ctrl._pitch_pid
                else:
                    return jsonify({"error": f"Invalid axis: {axis}"}), 400

                # Build updated config via dataclass replace
                from dataclasses import fields as dc_fields

                cfg = pid_obj.cfg
                updates = {}
                for param in ("kp", "ki", "kd"):
                    if param in data:
                        updates[param] = float(data[param])

                if updates:
                    new_cfg = type(cfg)(
                        **{
                            f.name: updates.get(f.name, getattr(cfg, f.name))
                            for f in dc_fields(cfg)
                        }
                    )
                    pid_obj.cfg = new_cfg

                logger.info(
                    "PID updated via API: %s axis, Kp=%.2f Ki=%.2f Kd=%.2f",
                    axis,
                    pid_obj.cfg.kp,
                    pid_obj.cfg.ki,
                    pid_obj.cfg.kd,
                )

                return jsonify(
                    {
                        "status": "ok",
                        "axis": axis,
                        "kp": pid_obj.cfg.kp,
                        "ki": pid_obj.cfg.ki,
                        "kd": pid_obj.cfg.kd,
                    }
                )

            except Exception as e:
                logger.error("Failed to update PID: %s", e)
                return jsonify({"error": str(e)}), 500

        @app.route("/config/selector", methods=["POST"])
        def update_selector():
            """Update selector weights.

            Request body:
            {
                "confidence": float,
                "size": float,
                "center_proximity": float,
                "track_age": float,
                "class_weight": float
            }
            """
            try:
                data = request.json
                weights = self.pipeline.selector._cfg.weights

                if "confidence" in data:
                    weights.confidence = float(data["confidence"])
                if "size" in data:
                    weights.size = float(data["size"])
                if "center_proximity" in data:
                    weights.center_proximity = float(data["center_proximity"])
                if "track_age" in data:
                    weights.track_age = float(data["track_age"])
                if "class_weight" in data:
                    weights.class_weight = float(data["class_weight"])

                logger.info("Selector weights updated via API")

                return jsonify(
                    {
                        "status": "ok",
                        "weights": {
                            "confidence": weights.confidence,
                            "size": weights.size,
                            "center_proximity": weights.center_proximity,
                            "track_age": weights.track_age,
                            "class_weight": weights.class_weight,
                        },
                    }
                )

            except Exception as e:
                logger.error("Failed to update selector: %s", e)
                return jsonify({"error": str(e)}), 500

        @app.route("/metrics", methods=["GET"])
        def get_metrics():
            """Get current telemetry metrics."""
            try:
                metrics = self.pipeline.telemetry.snapshot_metrics()
                return jsonify(metrics)
            except Exception as e:
                logger.error("Failed to get metrics: %s", e)
                return jsonify({"error": str(e)}), 500

        self._app = app

    def start(self) -> None:
        """Start HTTP server in background thread."""
        if not self._flask_available:
            logger.error("Cannot start ConfigServer: Flask not installed")
            return

        def run_server():
            self._app.run(host=self.host, port=self.port, debug=False)

        self._server_thread = threading.Thread(target=run_server, daemon=True)
        self._server_thread.start()

        logger.info("ConfigServer started on http://%s:%d", self.host, self.port)
        logger.info("Available endpoints:")
        logger.info("  GET  /health")
        logger.info("  POST /config/pid")
        logger.info("  POST /config/selector")
        logger.info("  GET  /metrics")

    def stop(self) -> None:
        """Stop HTTP server."""
        # Flask doesn't provide easy shutdown in threaded mode
        # In production, use proper WSGI server (gunicorn, waitress)
        logger.info("ConfigServer stop requested (requires process restart)")
