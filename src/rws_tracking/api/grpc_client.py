"""
gRPC Client for RWS Tracking System
====================================

Provides a Python client for controlling the tracking system via gRPC (port
50051).  All 29 service RPCs defined in ``tracking.proto`` are covered.

Example::

    with TrackingGrpcClient("192.168.1.100", 50051) as c:
        c.health_check()
        c.arm_system("op1")
        c.request_fire("op1")
        c.safe_system()
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import grpc

# Import generated protobuf code
try:
    from . import tracking_pb2, tracking_pb2_grpc
except ImportError as err:
    raise ImportError(
        "gRPC protobuf files not generated. Run: "
        "python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. "
        "src/rws_tracking/api/tracking.proto"
    ) from err

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
        logger.info("gRPC client connected to %s", self.address)

    def close(self) -> None:
        """Close the gRPC channel."""
        self.channel.close()
        logger.info("gRPC channel closed")

    def __enter__(self) -> TrackingGrpcClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"TrackingGrpcClient(address={self.address!r})"

    # ------------------------------------------------------------------
    # Infrastructure / basic control
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """Check if the server is running.

        Returns
        -------
        dict
            ``{"status": str, "service": str}``.
        """
        try:
            request = tracking_pb2.HealthCheckRequest()
            response = self.stub.HealthCheck(request, timeout=self.timeout)
            return {"status": response.status, "service": response.service}
        except grpc.RpcError as e:
            logger.error("HealthCheck failed: %s", e)
            return {"error": str(e)}

    def start_tracking(self, camera_source: int | str = 0) -> dict[str, Any]:
        """Start tracking.

        Parameters
        ----------
        camera_source : int or str
            Camera device ID (0 for default) or video file path.

        Returns
        -------
        dict
            Response with ``success`` flag.
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
            logger.error("StartTracking failed: %s", e)
            return {"success": False, "error": str(e)}

    def stop_tracking(self) -> dict[str, Any]:
        """Stop tracking.

        Returns
        -------
        dict
            Response with ``success`` flag.
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
            logger.error("StopTracking failed: %s", e)
            return {"success": False, "error": str(e)}

    def get_status(self) -> dict[str, Any]:
        """Get current tracking status.

        Returns
        -------
        dict
            Status including ``running``, ``frame_count``, ``fps``, and
            ``gimbal`` sub-dict.
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
            logger.error("GetStatus failed: %s", e)
            return {"error": str(e)}

    def set_gimbal_position(self, yaw_deg: float, pitch_deg: float) -> dict[str, Any]:
        """Set gimbal to an absolute position.

        Parameters
        ----------
        yaw_deg : float
            Target yaw angle in degrees.
        pitch_deg : float
            Target pitch angle in degrees.

        Returns
        -------
        dict
            Response with ``success`` flag and optional ``target`` / ``current``
            position fields.
        """
        try:
            request = tracking_pb2.SetGimbalPositionRequest(yaw_deg=yaw_deg, pitch_deg=pitch_deg)
            response = self.stub.SetGimbalPosition(request, timeout=self.timeout)

            result: dict[str, Any] = {
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
            logger.error("SetGimbalPosition failed: %s", e)
            return {"success": False, "error": str(e)}

    def set_gimbal_rate(self, yaw_rate_dps: float, pitch_rate_dps: float) -> dict[str, Any]:
        """Set gimbal velocity (rate control).

        Parameters
        ----------
        yaw_rate_dps : float
            Yaw rate in degrees per second.
        pitch_rate_dps : float
            Pitch rate in degrees per second.

        Returns
        -------
        dict
            Response with ``success`` flag and optional ``command`` sub-dict.
        """
        try:
            request = tracking_pb2.SetGimbalRateRequest(
                yaw_rate_dps=yaw_rate_dps, pitch_rate_dps=pitch_rate_dps
            )
            response = self.stub.SetGimbalRate(request, timeout=self.timeout)

            result: dict[str, Any] = {
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
            logger.error("SetGimbalRate failed: %s", e)
            return {"success": False, "error": str(e)}

    def get_telemetry(self) -> dict[str, Any]:
        """Get telemetry metrics.

        Returns
        -------
        dict
            ``{"success": bool, "metrics": dict[str, float]}``.
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
            logger.error("GetTelemetry failed: %s", e)
            return {"success": False, "error": str(e)}

    def update_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Update configuration.

        Parameters
        ----------
        config : dict
            Configuration dictionary (JSON-serialised before sending).

        Returns
        -------
        dict
            Response with ``success`` flag.
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
            logger.error("UpdateConfig failed: %s", e)
            return {"success": False, "error": str(e)}

    def stream_status(self, update_rate_hz: float = 10.0) -> Iterator[dict[str, Any]]:
        """Stream status updates in real-time.

        Parameters
        ----------
        update_rate_hz : float
            Desired update rate in Hz (default: 10.0).

        Yields
        ------
        dict
            Status updates with ``timestamp``, ``running``, ``frame_count``,
            ``fps``, and ``gimbal``.
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
            logger.error("StreamStatus failed: %s", e)
            yield {"error": str(e)}

    def stream_frames(
        self,
        max_fps: float = 15.0,
        scale_factor: float = 0.5,
        jpeg_quality: int = 70,
        annotate: bool = True,
    ) -> Iterator[dict[str, Any]]:
        """Stream annotated video frames as JPEG bytes.

        Parameters
        ----------
        max_fps : float
            Desired frame rate (default: 15.0 Hz).
        scale_factor : float
            Resolution scale factor in the range 0–1 (default: 0.5).
        jpeg_quality : int
            JPEG encoding quality 1–100 (default: 70).
        annotate : bool
            Include detection / track overlays when True.

        Yields
        ------
        dict
            Each frame dict with ``timestamp``, ``jpeg_data`` (bytes),
            ``width``, ``height``, ``frame_number``, and ``targets`` list.
        """
        try:
            request = tracking_pb2.StreamFramesRequest(
                max_fps=max_fps,
                scale_factor=scale_factor,
                jpeg_quality=jpeg_quality,
                annotate=annotate,
            )
            for frame in self.stub.StreamFrames(request):
                targets = [
                    {
                        "track_id": t.track_id,
                        "class_id": t.class_id,
                        "confidence": t.confidence,
                        "bbox": {
                            "x": t.bbox.x,
                            "y": t.bbox.y,
                            "w": t.bbox.w,
                            "h": t.bbox.h,
                        },
                        "velocity_x": t.velocity_x,
                        "velocity_y": t.velocity_y,
                        "is_selected": t.is_selected,
                    }
                    for t in frame.targets
                ]
                yield {
                    "timestamp": frame.timestamp,
                    "jpeg_data": frame.jpeg_data,
                    "width": frame.width,
                    "height": frame.height,
                    "frame_number": frame.frame_number,
                    "targets": targets,
                }
        except grpc.RpcError as e:
            logger.error("StreamFrames failed: %s", e)
            yield {"error": str(e)}

    # ------------------------------------------------------------------
    # Fire control
    # ------------------------------------------------------------------

    def arm_system(self, operator_id: str) -> dict[str, Any]:
        """Arm the shooting chain (SAFE -> ARMED).

        Parameters
        ----------
        operator_id : str
            Identifier of the operator performing the arm action.

        Returns
        -------
        dict
            ``{"success": bool, "state": str, "can_fire": bool, ...}``.
        """
        try:
            request = tracking_pb2.ArmRequest(operator_id=operator_id)
            response = self.stub.ArmSystem(request, timeout=self.timeout)
            return {
                "success": response.success,
                "state": response.state,
                "can_fire": response.can_fire,
                "message": response.message,
                "operator_id": response.operator_id,
            }
        except grpc.RpcError as e:
            logger.error("ArmSystem failed: %s", e)
            return {"success": False, "error": str(e)}

    def safe_system(self, reason: str = "") -> dict[str, Any]:
        """Return the shooting chain to SAFE state.

        Parameters
        ----------
        reason : str
            Optional free-text reason for the safe action.

        Returns
        -------
        dict
            Fire chain state after the action.
        """
        try:
            request = tracking_pb2.SafeRequest(reason=reason)
            response = self.stub.SafeSystem(request, timeout=self.timeout)
            return {
                "success": response.success,
                "state": response.state,
                "can_fire": response.can_fire,
                "message": response.message,
                "operator_id": response.operator_id,
            }
        except grpc.RpcError as e:
            logger.error("SafeSystem failed: %s", e)
            return {"success": False, "error": str(e)}

    def request_fire(self, operator_id: str) -> dict[str, Any]:
        """Submit a manual fire request (FIRE_AUTHORIZED -> FIRE_REQUESTED).

        Parameters
        ----------
        operator_id : str
            Identifier of the operator requesting fire.

        Returns
        -------
        dict
            Fire chain state and ``can_fire`` flag.
        """
        try:
            request = tracking_pb2.RequestFireRequest(operator_id=operator_id)
            response = self.stub.RequestFire(request, timeout=self.timeout)
            return {
                "success": response.success,
                "state": response.state,
                "can_fire": response.can_fire,
                "message": response.message,
                "operator_id": response.operator_id,
            }
        except grpc.RpcError as e:
            logger.error("RequestFire failed: %s", e)
            return {"success": False, "error": str(e)}

    def get_fire_status(self) -> dict[str, Any]:
        """Get the current fire chain state.

        Returns
        -------
        dict
            ``{"success": bool, "state": str, "can_fire": bool, ...}``.
        """
        try:
            request = tracking_pb2.GetFireStatusRequest()
            response = self.stub.GetFireStatus(request, timeout=self.timeout)
            return {
                "success": response.success,
                "state": response.state,
                "can_fire": response.can_fire,
                "message": response.message,
                "operator_id": response.operator_id,
            }
        except grpc.RpcError as e:
            logger.error("GetFireStatus failed: %s", e)
            return {"success": False, "error": str(e)}

    def send_heartbeat(self, operator_id: str) -> dict[str, Any]:
        """Send an operator heartbeat to prevent watchdog timeout.

        Parameters
        ----------
        operator_id : str
            Identifier of the active operator.

        Returns
        -------
        dict
            ``{"ok": bool, "operator_id": str}``.
        """
        try:
            request = tracking_pb2.OperatorHeartbeatRequest(operator_id=operator_id)
            response = self.stub.OperatorHeartbeat(request, timeout=self.timeout)
            return {
                "ok": response.ok,
                "operator_id": response.operator_id,
            }
        except grpc.RpcError as e:
            logger.error("OperatorHeartbeat failed: %s", e)
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Target designation
    # ------------------------------------------------------------------

    def designate_target(self, track_id: int, operator_id: str = "") -> dict[str, Any]:
        """Operator-designate a specific track for engagement (C2 override).

        Parameters
        ----------
        track_id : int
            Track ID to designate.
        operator_id : str
            Optional operator identifier for logging.

        Returns
        -------
        dict
            ``{"ok": bool, "track_id": int, "designated": bool}``.
        """
        try:
            request = tracking_pb2.DesignateTargetRequest(
                track_id=track_id, operator_id=operator_id
            )
            response = self.stub.DesignateTarget(request, timeout=self.timeout)
            return {
                "ok": response.ok,
                "track_id": response.track_id,
                "designated": response.designated,
            }
        except grpc.RpcError as e:
            logger.error("DesignateTarget failed: %s", e)
            return {"ok": False, "error": str(e)}

    def clear_designation(self) -> dict[str, Any]:
        """Clear the operator designation and return to auto-selection.

        Returns
        -------
        dict
            ``{"ok": bool, "track_id": int, "designated": bool,
            "cleared_track_id": str}``.
        """
        try:
            request = tracking_pb2.ClearDesignationRequest()
            response = self.stub.ClearDesignation(request, timeout=self.timeout)
            return {
                "ok": response.ok,
                "track_id": response.track_id,
                "designated": response.designated,
                "cleared_track_id": response.cleared_track_id,
            }
        except grpc.RpcError as e:
            logger.error("ClearDesignation failed: %s", e)
            return {"ok": False, "error": str(e)}

    def get_designation(self) -> dict[str, Any]:
        """Get the current operator designation status.

        Returns
        -------
        dict
            ``{"ok": bool, "track_id": int, "designated": bool}``.
        """
        try:
            request = tracking_pb2.GetDesignationRequest()
            response = self.stub.GetDesignation(request, timeout=self.timeout)
            return {
                "ok": response.ok,
                "track_id": response.track_id,
                "designated": response.designated,
            }
        except grpc.RpcError as e:
            logger.error("GetDesignation failed: %s", e)
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Mission management
    # ------------------------------------------------------------------

    def start_mission(
        self,
        profile: str = "",
        camera_source: int = 0,
        mission_name: str = "",
    ) -> dict[str, Any]:
        """Start a new mission session.

        Parameters
        ----------
        profile : str
            Named mission profile to load.
        camera_source : int
            Camera device index.
        mission_name : str
            Optional human-readable display name.

        Returns
        -------
        dict
            ``{"ok": bool, "session_id": str, "message": str, ...}``.
        """
        try:
            request = tracking_pb2.StartMissionRequest(
                profile=profile,
                camera_source=camera_source,
                mission_name=mission_name,
            )
            response = self.stub.StartMission(request, timeout=self.timeout)
            return {
                "ok": response.ok,
                "session_id": response.session_id,
                "message": response.message,
                "error": response.error if response.error else None,
                "elapsed_s": response.elapsed_s,
                "report_path": response.report_path,
                "report_url": response.report_url,
            }
        except grpc.RpcError as e:
            logger.error("StartMission failed: %s", e)
            return {"ok": False, "error": str(e)}

    def end_mission(self, reason: str = "") -> dict[str, Any]:
        """End the active mission and generate a debrief report.

        Parameters
        ----------
        reason : str
            Optional free-text reason for ending the mission.

        Returns
        -------
        dict
            ``{"ok": bool, "session_id": str, "elapsed_s": float,
            "report_path": str, "report_url": str}``.
        """
        try:
            request = tracking_pb2.EndMissionRequest(reason=reason)
            response = self.stub.EndMission(request, timeout=self.timeout)
            return {
                "ok": response.ok,
                "session_id": response.session_id,
                "message": response.message,
                "error": response.error if response.error else None,
                "elapsed_s": response.elapsed_s,
                "report_path": response.report_path,
                "report_url": response.report_url,
            }
        except grpc.RpcError as e:
            logger.error("EndMission failed: %s", e)
            return {"ok": False, "error": str(e)}

    def get_mission_status(self) -> dict[str, Any]:
        """Get the current mission state.

        Returns
        -------
        dict
            ``{"active": bool, "session_id": str, "profile": str,
            "started_at": str, "elapsed_s": float, "targets_engaged": int,
            "fire_chain_state": str}``.
        """
        try:
            request = tracking_pb2.GetMissionStatusRequest()
            response = self.stub.GetMissionStatus(request, timeout=self.timeout)
            return {
                "active": response.active,
                "session_id": response.session_id,
                "profile": response.profile,
                "started_at": response.started_at,
                "elapsed_s": response.elapsed_s,
                "targets_engaged": response.targets_engaged,
                "fire_chain_state": response.fire_chain_state,
            }
        except grpc.RpcError as e:
            logger.error("GetMissionStatus failed: %s", e)
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    def get_safety_status(self) -> dict[str, Any]:
        """Get safety interlock status from the SafetyManager.

        Returns
        -------
        dict
            ``{"fire_authorized": bool, "blocked_reason": str,
            "active_zone": str, "operator_override": bool,
            "emergency_stop": bool}``.
        """
        try:
            request = tracking_pb2.GetSafetyStatusRequest()
            response = self.stub.GetSafetyStatus(request, timeout=self.timeout)
            return {
                "fire_authorized": response.fire_authorized,
                "blocked_reason": response.blocked_reason,
                "active_zone": response.active_zone,
                "operator_override": response.operator_override,
                "emergency_stop": response.emergency_stop,
            }
        except grpc.RpcError as e:
            logger.error("GetSafetyStatus failed: %s", e)
            return {"error": str(e)}

    def set_operator_auth(self, authorized: bool) -> dict[str, Any]:
        """Set operator authorization flag on the safety interlock.

        Parameters
        ----------
        authorized : bool
            True to grant authorization, False to revoke it.

        Returns
        -------
        dict
            ``{"success": bool, "error": str | None}``.
        """
        try:
            request = tracking_pb2.SetOperatorAuthRequest(authorized=authorized)
            response = self.stub.SetOperatorAuth(request, timeout=self.timeout)
            return {
                "success": response.success,
                "error": response.error if response.error else None,
            }
        except grpc.RpcError as e:
            logger.error("SetOperatorAuth failed: %s", e)
            return {"success": False, "error": str(e)}

    def emergency_stop(self, activate: bool) -> dict[str, Any]:
        """Activate or release the hardware emergency stop.

        Parameters
        ----------
        activate : bool
            True to engage the e-stop, False to release it.

        Returns
        -------
        dict
            ``{"success": bool, "emergency_stop_active": bool}``.
        """
        try:
            request = tracking_pb2.EmergencyStopRequest(activate=activate)
            response = self.stub.EmergencyStop(request, timeout=self.timeout)
            return {
                "success": response.success,
                "emergency_stop_active": response.emergency_stop_active,
                "error": response.error if response.error else None,
            }
        except grpc.RpcError as e:
            logger.error("EmergencyStop failed: %s", e)
            return {"success": False, "error": str(e)}

    def get_threat_assessment(self) -> dict[str, Any]:
        """Get the current threat assessment list from the ThreatAssessor.

        Returns
        -------
        dict
            ``{"threats": list}`` where each entry contains ``track_id``,
            ``threat_score``, ``priority_rank``, and component scores.
        """
        try:
            request = tracking_pb2.GetThreatAssessmentRequest()
            response = self.stub.GetThreatAssessment(request, timeout=self.timeout)
            threats = [
                {
                    "track_id": t.track_id,
                    "threat_score": t.threat_score,
                    "distance_score": t.distance_score,
                    "velocity_score": t.velocity_score,
                    "class_score": t.class_score,
                    "heading_score": t.heading_score,
                    "priority_rank": t.priority_rank,
                }
                for t in response.threats
            ]
            return {"threats": threats}
        except grpc.RpcError as e:
            logger.error("GetThreatAssessment failed: %s", e)
            return {"threats": [], "error": str(e)}

    # ------------------------------------------------------------------
    # Safety zones (No-Fire Zones)
    # ------------------------------------------------------------------

    def list_zones(self) -> dict[str, Any]:
        """List all active no-fire zones.

        Returns
        -------
        dict
            ``{"zones": list}`` where each entry is a zone descriptor dict.
        """
        try:
            request = tracking_pb2.ListZonesRequest()
            response = self.stub.ListZones(request, timeout=self.timeout)
            zones = [
                {
                    "zone_id": z.zone_id,
                    "center_yaw_deg": z.center_yaw_deg,
                    "center_pitch_deg": z.center_pitch_deg,
                    "radius_deg": z.radius_deg,
                    "zone_type": z.zone_type,
                }
                for z in response.zones
            ]
            return {"zones": zones}
        except grpc.RpcError as e:
            logger.error("ListZones failed: %s", e)
            return {"zones": [], "error": str(e)}

    def add_zone(
        self,
        zone_id: str,
        center_yaw_deg: float,
        center_pitch_deg: float,
        radius_deg: float,
        zone_type: str = "no_fire",
    ) -> dict[str, Any]:
        """Add a new no-fire zone.

        Parameters
        ----------
        zone_id : str
            Unique identifier for the zone (auto-generated on the server when
            empty).
        center_yaw_deg : float
            Zone centre yaw angle in degrees.
        center_pitch_deg : float
            Zone centre pitch angle in degrees.
        radius_deg : float
            Exclusion radius in degrees.
        zone_type : str
            Zone type string, default ``"no_fire"``.

        Returns
        -------
        dict
            ``{"ok": bool, "zone_id": str}``.
        """
        try:
            request = tracking_pb2.AddZoneRequest(
                zone_id=zone_id,
                center_yaw_deg=center_yaw_deg,
                center_pitch_deg=center_pitch_deg,
                radius_deg=radius_deg,
                zone_type=zone_type,
            )
            response = self.stub.AddZone(request, timeout=self.timeout)
            return {
                "ok": response.ok,
                "zone_id": response.zone_id,
                "error": response.error if response.error else None,
            }
        except grpc.RpcError as e:
            logger.error("AddZone failed: %s", e)
            return {"ok": False, "error": str(e)}

    def remove_zone(self, zone_id: str) -> dict[str, Any]:
        """Remove a no-fire zone by its ID.

        Parameters
        ----------
        zone_id : str
            Zone identifier to remove.

        Returns
        -------
        dict
            ``{"ok": bool, "zone_id": str}``.
        """
        try:
            request = tracking_pb2.RemoveZoneRequest(zone_id=zone_id)
            response = self.stub.RemoveZone(request, timeout=self.timeout)
            return {
                "ok": response.ok,
                "zone_id": response.zone_id,
                "error": response.error if response.error else None,
            }
        except grpc.RpcError as e:
            logger.error("RemoveZone failed: %s", e)
            return {"ok": False, "error": str(e)}

    def get_zone(self, zone_id: str) -> dict[str, Any]:
        """Get a specific no-fire zone by its ID.

        Parameters
        ----------
        zone_id : str
            Zone identifier to look up.

        Returns
        -------
        dict
            Zone descriptor dict.  ``found`` is False when the zone does not
            exist.
        """
        try:
            request = tracking_pb2.GetZoneRequest(zone_id=zone_id)
            response = self.stub.GetZone(request, timeout=self.timeout)
            return {
                "zone_id": response.zone_id,
                "center_yaw_deg": response.center_yaw_deg,
                "center_pitch_deg": response.center_pitch_deg,
                "radius_deg": response.radius_deg,
                "zone_type": response.zone_type,
                "found": response.found,
                "error": response.error if response.error else None,
            }
        except grpc.RpcError as e:
            logger.error("GetZone failed: %s", e)
            return {"found": False, "error": str(e)}
