"""
RWS Tracking API
================

REST and gRPC APIs for controlling the RWS tracking system from external devices.

REST API Usage:
    from rws_tracking.api import TrackingAPI, run_api_server, TrackingClient

    # Server
    api = TrackingAPI()
    run_api_server(api, host="0.0.0.0", port=5000)

    # Client
    client = TrackingClient("http://localhost:5000")
    client.start_tracking()

gRPC API Usage:
    from rws_tracking.api import run_grpc_server, TrackingGrpcClient

    # Server
    run_grpc_server(host="0.0.0.0", port=50051)

    # Client
    client = TrackingGrpcClient(host="localhost", port=50051)
    client.start_tracking()
"""

from .server import TrackingAPI, run_api_server
from .client import TrackingClient

# gRPC imports (optional, only if protobuf files are generated)
try:
    from .grpc_client import TrackingGrpcClient
    from .grpc_server import serve as run_grpc_server
    _GRPC_AVAILABLE = True
except ImportError:
    _GRPC_AVAILABLE = False
    TrackingGrpcClient = None
    run_grpc_server = None

__all__ = [
    "TrackingAPI",
    "run_api_server",
    "TrackingClient",
    "TrackingGrpcClient",
    "run_grpc_server",
]
