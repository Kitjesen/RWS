"""
gRPC Server for RWS Tracking System
====================================

Provides gRPC endpoints for controlling the tracking system.
"""

from __future__ import annotations

import json
import logging
import time
from concurrent import futures
from typing import Iterator

import grpc

from ..hardware.imu_interface import BodyMotionProvider
from .server import TrackingAPI

# Import generated protobuf code
try:
    from . import tracking_pb2, tracking_pb2_grpc
except ImportError:
    raise ImportError(
        "gRPC protobuf files not generated. Run: "
        "python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. "
        "src/rws_tracking/api/tracking.proto"
    )

logger = logging.getLogger(__name__)


class TrackingServicer(tracking_pb2_grpc.TrackingServiceServicer):
    """
    gRPC servicer implementation for RWS Tracking.

    Wraps the TrackingAPI class to provide gRPC interface.
    """

    def __init__(
        self,
        config_path: str = "config.yaml",
        body_provider: BodyMotionProvider | None = None,
    ):
        self.api = TrackingAPI(config_path, body_provider)
        logger.info("TrackingServicer initialized")

    def HealthCheck(
        self, request: tracking_pb2.HealthCheckRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.HealthCheckResponse:
        """Health check endpoint."""
        return tracking_pb2.HealthCheckResponse(status="ok", service="rws-tracking")

    def StartTracking(
        self, request: tracking_pb2.StartTrackingRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.StartTrackingResponse:
        """Start tracking."""
        try:
            # Determine camera source
            if request.HasField("camera_id"):
                camera_source = request.camera_id
            elif request.HasField("video_path"):
                camera_source = request.video_path
            else:
                camera_source = 0  # Default

            result = self.api.start_tracking(camera_source)

            return tracking_pb2.StartTrackingResponse(
                success=result.get("success", False),
                message=result.get("message", ""),
                error=result.get("error", ""),
            )
        except Exception as e:
            logger.error(f"StartTracking error: {e}")
            return tracking_pb2.StartTrackingResponse(
                success=False, error=str(e)
            )

    def StopTracking(
        self, request: tracking_pb2.StopTrackingRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.StopTrackingResponse:
        """Stop tracking."""
        try:
            result = self.api.stop_tracking()
            return tracking_pb2.StopTrackingResponse(
                success=result.get("success", False),
                message=result.get("message", ""),
                error=result.get("error", ""),
            )
        except Exception as e:
            logger.error(f"StopTracking error: {e}")
            return tracking_pb2.StopTrackingResponse(
                success=False, error=str(e)
            )

    def GetStatus(
        self, request: tracking_pb2.GetStatusRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.GetStatusResponse:
        """Get current status."""
        try:
            status = self.api.get_status()

            # Build gimbal state
            gimbal_data = status.get("gimbal", {})
            gimbal = tracking_pb2.GimbalState(
                yaw_deg=gimbal_data.get("yaw_deg", 0.0),
                pitch_deg=gimbal_data.get("pitch_deg", 0.0),
                yaw_rate_dps=gimbal_data.get("yaw_rate_dps", 0.0),
                pitch_rate_dps=gimbal_data.get("pitch_rate_dps", 0.0),
            )

            return tracking_pb2.GetStatusResponse(
                running=status.get("running", False),
                frame_count=status.get("frame_count", 0),
                error_count=status.get("error_count", 0),
                last_error=status.get("last_error") or "",
                fps=status.get("fps", 0.0),
                gimbal=gimbal,
            )
        except Exception as e:
            logger.error(f"GetStatus error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.GetStatusResponse()

    def SetGimbalPosition(
        self,
        request: tracking_pb2.SetGimbalPositionRequest,
        context: grpc.ServicerContext,
    ) -> tracking_pb2.SetGimbalPositionResponse:
        """Set gimbal position."""
        try:
            result = self.api.set_gimbal_position(request.yaw_deg, request.pitch_deg)

            response = tracking_pb2.SetGimbalPositionResponse(
                success=result.get("success", False),
                error=result.get("error", ""),
            )

            if "target" in result:
                response.target.CopyFrom(
                    tracking_pb2.GimbalPosition(
                        yaw_deg=result["target"]["yaw_deg"],
                        pitch_deg=result["target"]["pitch_deg"],
                    )
                )

            if "current" in result:
                response.current.CopyFrom(
                    tracking_pb2.GimbalPosition(
                        yaw_deg=result["current"]["yaw_deg"],
                        pitch_deg=result["current"]["pitch_deg"],
                    )
                )

            return response
        except Exception as e:
            logger.error(f"SetGimbalPosition error: {e}")
            return tracking_pb2.SetGimbalPositionResponse(
                success=False, error=str(e)
            )

    def SetGimbalRate(
        self, request: tracking_pb2.SetGimbalRateRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.SetGimbalRateResponse:
        """Set gimbal rate."""
        try:
            result = self.api.set_gimbal_rate(request.yaw_rate_dps, request.pitch_rate_dps)

            response = tracking_pb2.SetGimbalRateResponse(
                success=result.get("success", False),
                error=result.get("error", ""),
            )

            if "command" in result:
                response.command.CopyFrom(
                    tracking_pb2.GimbalRate(
                        yaw_rate_dps=result["command"]["yaw_rate_dps"],
                        pitch_rate_dps=result["command"]["pitch_rate_dps"],
                    )
                )

            return response
        except Exception as e:
            logger.error(f"SetGimbalRate error: {e}")
            return tracking_pb2.SetGimbalRateResponse(
                success=False, error=str(e)
            )

    def GetTelemetry(
        self, request: tracking_pb2.GetTelemetryRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.GetTelemetryResponse:
        """Get telemetry."""
        try:
            result = self.api.get_telemetry()

            if not result.get("success", False):
                return tracking_pb2.GetTelemetryResponse(
                    success=False, error=result.get("error", "")
                )

            metrics = result.get("metrics", {})
            return tracking_pb2.GetTelemetryResponse(
                success=True, metrics=metrics
            )
        except Exception as e:
            logger.error(f"GetTelemetry error: {e}")
            return tracking_pb2.GetTelemetryResponse(
                success=False, error=str(e)
            )

    def UpdateConfig(
        self, request: tracking_pb2.UpdateConfigRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.UpdateConfigResponse:
        """Update configuration."""
        try:
            config_dict = json.loads(request.config_json)
            result = self.api.update_config(config_dict)

            return tracking_pb2.UpdateConfigResponse(
                success=result.get("success", False),
                message=result.get("message", ""),
                error=result.get("error", ""),
            )
        except json.JSONDecodeError as e:
            return tracking_pb2.UpdateConfigResponse(
                success=False, error=f"Invalid JSON: {e}"
            )
        except Exception as e:
            logger.error(f"UpdateConfig error: {e}")
            return tracking_pb2.UpdateConfigResponse(
                success=False, error=str(e)
            )

    def StreamStatus(
        self, request: tracking_pb2.StreamStatusRequest, context: grpc.ServicerContext
    ) -> Iterator[tracking_pb2.StatusUpdate]:
        """Stream status updates."""
        update_rate_hz = request.update_rate_hz if request.update_rate_hz > 0 else 10.0
        interval = 1.0 / update_rate_hz

        logger.info(f"Starting status stream at {update_rate_hz} Hz")

        try:
            while context.is_active():
                status = self.api.get_status()

                # Build gimbal state
                gimbal_data = status.get("gimbal", {})
                gimbal = tracking_pb2.GimbalState(
                    yaw_deg=gimbal_data.get("yaw_deg", 0.0),
                    pitch_deg=gimbal_data.get("pitch_deg", 0.0),
                    yaw_rate_dps=gimbal_data.get("yaw_rate_dps", 0.0),
                    pitch_rate_dps=gimbal_data.get("pitch_rate_dps", 0.0),
                )

                update = tracking_pb2.StatusUpdate(
                    timestamp=time.time(),
                    running=status.get("running", False),
                    frame_count=status.get("frame_count", 0),
                    fps=status.get("fps", 0.0),
                    gimbal=gimbal,
                )

                yield update
                time.sleep(interval)

        except Exception as e:
            logger.error(f"StreamStatus error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))


def serve(
    host: str = "0.0.0.0",
    port: int = 50051,
    config_path: str = "config.yaml",
    body_provider: BodyMotionProvider | None = None,
    max_workers: int = 10,
) -> None:
    """
    Start the gRPC server.

    Parameters
    ----------
    host : str
        Host to bind to (default: "0.0.0.0")
    port : int
        Port to bind to (default: 50051)
    config_path : str
        Path to configuration file
    body_provider : BodyMotionProvider, optional
        Body motion provider for IMU integration
    max_workers : int
        Maximum number of worker threads
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers))
    servicer = TrackingServicer(config_path, body_provider)
    tracking_pb2_grpc.add_TrackingServiceServicer_to_server(servicer, server)

    server_address = f"{host}:{port}"
    server.add_insecure_port(server_address)

    logger.info(f"Starting gRPC server on {server_address}")
    server.start()

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║           RWS Tracking gRPC Server                           ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝

Server Address: {server_address}
Max Workers:    {max_workers}
Config:         {config_path}

gRPC Methods:
  HealthCheck          - Health check
  StartTracking        - Start tracking
  StopTracking         - Stop tracking
  GetStatus            - Get status
  SetGimbalPosition    - Set gimbal position
  SetGimbalRate        - Set gimbal rate
  GetTelemetry         - Get telemetry
  UpdateConfig         - Update config
  StreamStatus         - Stream status updates

Server is running. Press Ctrl+C to stop.
""")

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("Shutting down gRPC server...")
        server.stop(grace=5.0)
        logger.info("Server stopped")
