#!/usr/bin/env python3
"""
RWS Tracking API Server Entry Point
====================================

Start the REST API server for remote control.

Usage:
    python scripts/run_api_server.py
    python scripts/run_api_server.py --host 0.0.0.0 --port 5000
    python scripts/run_api_server.py --config custom_config.yaml
"""

import argparse
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rws_tracking.api import TrackingAPI, run_api_server

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main():
    parser = argparse.ArgumentParser(description="RWS Tracking API Server")
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5000,
        help="Port to bind to (default: 5000)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode",
    )

    args = parser.parse_args()

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║              RWS Tracking API Server                         ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝

Configuration:
  Host:   {args.host}
  Port:   {args.port}
  Config: {args.config}
  Debug:  {args.debug}

API Endpoints:
  GET  /api/health              - Health check
  POST /api/start               - Start tracking
  POST /api/stop                - Stop tracking
  GET  /api/status              - Get status
  POST /api/gimbal/position     - Set gimbal position
  POST /api/gimbal/rate         - Set gimbal rate
  GET  /api/telemetry           - Get telemetry
  POST /api/config              - Update config

Starting server...
""")

    api = TrackingAPI(config_path=args.config)
    run_api_server(api, host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
