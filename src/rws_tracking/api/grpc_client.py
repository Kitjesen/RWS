"""
gRPC Client for RWS Tracking System
====================================

Provides a Python client for controlling the tracking system via gRPC.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterator

import grpc

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


class TrackingGrpcClient:
    """
    gRPC client for RWS Tracking API.

    Parameters
    ----------
    host : str
        Server host (default: "localhost")
    port : int
        Server port (default: 50051)
    timeout : float
        Request timeout in seconds (default: 5.0)
    """

    def __init__(self, host: str = "localhost", port: int = 50051, timeout: float = 5.0):
        self.address = f"{host}:{port}"
        self.timeout = timeout
        self.channel = grpc.insecure_channel(self.address)
        self.stub = tracking_pb2_grpc.TrackingServiceStub(self.channel)
        logger.info(f"gRPC client connected to {self.address}")

    def close(self):
        """Close the gRPC channel."""
        self.channel.close()
        logger.info("gRPC channel closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def health_check(self) -> dict[str, Any]:
        """
        Check if server is running.

        Returns
        -------
        dict
            Health status
        """
        try:
            request = tracking_pb2.HealthCheckRequest()
            response = self.stub.HealthCheck(request, timeout=self.timeout)
            return {"status": response.status, "service": response.service}
        except grpc.RpcError as e:
            logger.error(f"HealthCheck failed: {e}")
            return {"error": str(e)}

    def start_tracking(self, camera_source: int | str = 0) -> dict[str, Any]:
        """
        Start tracking.

        Parameters
        ----------
        camera_source : int or str
            Camera device ID (0 for default) or video file path

        Returns
        -------
        dict
            Response with success status
        """
        try:
            request = tracking_pb2.StartTrackingRequest()
            if isinstance(camera_source, int):
                request.camera_id = camera_source
            else:
                request.video_path = camera_source

            response = self.stub.StartTracking(request, timeout=self.timeout)
            return {
                "success": response.success,
                "message": response.message,
                "error": response.error if response.error else None,
            }
        except grpc.RpcError as e:
            logger.error(f"StartTracking failed: {e}")
            return {"success": False, "error": str(e)}

    def stop_tracking(self) -> dict[str, Any]:
        """
        Stop tracking.

        Returns
        -------
        dict
            Response with success status
        """
        try:
            request = tracking_pb2.StopTrackingRequest()
            response = self.stub.StopTracking(request, timeout=self.timeout)
            return {
                "success": response.success,
                "message": response.message,
                "error": response.error if response.error else None,
            }
        except grpc.RpcError as e:
            logger.error(f"StopTracking failed: {e}")
            return {"success": False, "error": str(e)}

    def get_status(self) -> dict[str, Any]:
        """
        Get current tracking status.

        Returns
        -------
        dict
            Status including:
            - running: bool
            - frame_count: int
            - fps: float
            - gimbal: dict with yaw_deg, pitch_deg, etc.
        """
        try:
            request = tracking_pb2.GetStatusRequest()
            response = self.stub.GetStatus(request, timeout=self.timeout)

            return {
                "running": response.running,
                "frame_count": response.frame_count,
                "error_count": response.error_count,
                "last_error": response.last_error if response.last_error else None,
                "fps": response.fps,
                "gimbal": {
                    "yaw_deg": response.gimbal.yaw_deg,
                    "pitch_deg": response.gimbal.pitch_deg,
                    "yaw_rate_dps": response.gimbal.yaw_rate_dps,
                    "pitch_rate_dps": response.gimbal.pitch_rate_dps,
                },
            }
        except grpc.RpcError as e:
            logger.error(f"GetStatus failed: {e}")
            return {"error": str(e)}

    def set_gimbal_position(self, yaw_deg: float, pitch_deg: float) -> dict[str, Any]:
        """
        Set gimbal position (absolute).

        Parameters
        ----------
        yaw_deg : float
            Target yaw angle in degrees
        pitch_deg : float
            Target pitch angle in degrees

        Returns
        -------
        dict
            Response with success status
        """
        try:
            request = tracking_pb2.SetGimbalPositionRequest(
                yaw_deg=yaw_deg, pitch_deg=pitch_deg
            )
            response = self.stub.SetGimbalPosition(request, timeout=self.timeout)

            result = {
                "success": response.success,
                "error": response.error if response.error else None,
            }

            if response.HasField("target"):
                result["target"] = {
                    "yaw_deg": response.target.yaw_deg,
                    "pitch_deg": response.target.pitch_deg,
                }

            if response.HasField("current"):
                result["current"] = {
                    "yaw_deg": response.current.yaw_deg,
                    "pitch_deg": response.current.pitch_deg,
                }

            return result
        except grpc.RpcError as e:
            logger.error(f"SetGimbalPosition failed: {e}")
            return {"success": False, "error": str(e)}

    def set_gimbal_rate(self, yaw_rate_dps: float, pitch_rate_dps: float) -> dict[str, Any]:
        """
        Set gimbal rate (velocity control).

        Parameters
        ----------
        yaw_rate_dps : float
            Yaw rate in degrees per second
        pitch_rate_dps : float
            Pitch rate in degrees per second

        Returns
        -------
        dict
            Response with success status
        """
        try:
            request = tracking_pb2.SetGimbalRateRequest(
                yaw_rate_dps=yaw_rate_dps, pitch_rate_dps=pitch_rate_dps
            )
            response = self.stub.SetGimbalRate(request, timeout=self.timeout)

            result = {
                "success": response.success,
                "error": response.error if response.error else None,
            }

            if response.HasField("command"):
                result["command"] = {
                    "yaw_rate_dps": response.command.yaw_rate_dps,
                    "pitch_rate_dps": response.command.pitch_rate_dps,
                }

            return result
        except grpc.RpcError as e:
            logger.error(f"SetGimbalRate failed: {e}")
            return {"success": False, "error": str(e)}

    def get_telemetry(self) -> dict[str, Any]:
        """
        Get telemetry metrics.

        Returns
        -------
        dict
            Telemetry data including tracking metrics
        """
        try:
            request = tracking_pb2.GetTelemetryRequest()
            response = self.stub.GetTelemetry(request, timeout=self.timeout)

            return {
                "success": response.success,
                "error": response.error if response.error else None,
                "metrics": dict(response.metrics),
            }
        except grpc.RpcError as e:
            logger.error(f"GetTelemetry failed: {e}")
            return {"success": False, "error": str(e)}

    def update_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Update configuration (requires restart to apply).

        Parameters
        ----------
        config : dict
            Configuration dictionary

        Returns
        -------
        dict
            Response with success status
        """
        try:
            config_json = json.dumps(config)
            request = tracking_pb2.UpdateConfigRequest(config_json=config_json)
            response = self.stub.UpdateConfig(request, timeout=self.timeout)

            return {
                "success": response.success,
                "message": response.message,
                "error": response.error if response.error else None,
            }
        except grpc.RpcError as e:
            logger.error(f"UpdateConfig failed: {e}")
            return {"success": False, "error": str(e)}

    def stream_status(self, update_rate_hz: float = 10.0) -> Iterator[dict[str, Any]]:
        """
        Stream status updates in real-time.

        Parameters
        ----------
        update_rate_hz : float
            Desired update rate in Hz (default: 10.0)

        Yields
        ------
        dict
            Status updates with timestamp, running, frame_count, fps, gimbal
        """
        try:
            request = tracking_pb2.StreamStatusRequest(update_rate_hz=update_rate_hz)
            for update in self.stub.StreamStatus(request):
                yield {
                    "timestamp": update.timestamp,
                    "running": update.running,
                    "frame_count": update.frame_count,
                    "fps": update.fps,
                    "gimbal": {
                        "yaw_deg": update.gimbal.yaw_deg,
                        "pitch_deg": update.gimbal.pitch_deg,
                        "yaw_rate_dps": update.gimbal.yaw_rate_dps,
                        "pitch_rate_dps": update.gimbal.pitch_rate_dps,
                    },
                }
        except grpc.RpcError as e:
            logger.error(f"StreamStatus failed: {e}")
            yield {"error": str(e)}
