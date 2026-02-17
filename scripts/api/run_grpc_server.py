#!/usr/bin/env python3
"""
RWS Tracking gRPC Server Entry Point
=====================================

Start the gRPC server for remote control.

Usage:
    python scripts/run_grpc_server.py
    python scripts/run_grpc_server.py --host 0.0.0.0 --port 50051
    python scripts/run_grpc_server.py --config custom_config.yaml
"""

import argparse
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rws_tracking.api.grpc_server import serve

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main():
    parser = argparse.ArgumentParser(description="RWS Tracking gRPC Server")
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=50051,
        help="Port to bind to (default: 50051)",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=10,
        help="Maximum number of worker threads (default: 10)",
    )

    args = parser.parse_args()

    serve(
        host=args.host,
        port=args.port,
        config_path=args.config,
        max_workers=args.max_workers,
    )


if __name__ == "__main__":
    main()
