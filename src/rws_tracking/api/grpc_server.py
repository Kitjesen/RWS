"""
gRPC Server for RWS Tracking System
====================================

Provides gRPC endpoints for controlling the tracking system.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from concurrent import futures

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

    def StreamFrames(
        self, request: tracking_pb2.StreamFramesRequest, context: grpc.ServicerContext
    ) -> Iterator[tracking_pb2.VideoFrame]:
        """Stream annotated video frames via gRPC."""
        max_fps = request.max_fps if request.max_fps > 0 else 15.0
        interval = 1.0 / max_fps

        logger.info(f"Starting gRPC video stream at {max_fps} Hz")

        try:
            while context.is_active():
                # Get latest frame from buffer
                result = self.api._frame_buffer.get_latest(timeout=2.0)
                if result is None:
                    continue

                frame, ts = result

                # Fast rate limiting
                now = time.monotonic()
                if now - getattr(self, "_last_frame_sent", 0) < interval:
                    continue
                self._last_frame_sent = now

                # Encode to JPEG
                encoder = self.api._video_cfg
                import cv2
                encode_param = [cv2.IMWRITE_JPEG_QUALITY, request.jpeg_quality if request.jpeg_quality > 0 else encoder.jpeg_quality]

                # Handle scaling
                scale = request.scale_factor if request.scale_factor > 0 else encoder.scale_factor
                if 0 < scale < 1.0:
                    h, w = frame.shape[:2]
                    frame = cv2.resize(frame, (int(w * scale), int(h * scale)))

                h, w = frame.shape[:2]
                success, encoded = cv2.imencode(".jpg", frame, encode_param)
                if not success:
                    continue

                # Build target overlays metadata
                targets = []
                if request.annotate:
                    for track in self.api._last_tracks:
                        vx, vy = getattr(track, "velocity_px_per_s", (0.0, 0.0))
                        bbox = getattr(track, "bbox", None)
                        if bbox is None:
                            continue

                        targets.append(tracking_pb2.DetectedTarget(
                            track_id=track.track_id,
                            class_id=track.class_id,
                            confidence=track.confidence,
                            bbox=tracking_pb2.BoundingBoxMsg(
                                x=bbox.x, y=bbox.y, w=bbox.w, h=bbox.h
                            ),
                            velocity_x=vx,
                            velocity_y=vy,
                            is_selected=(track.track_id == self.api._selected_target_id)
                        ))

                yield tracking_pb2.VideoFrame(
                    timestamp=ts,
                    jpeg_data=encoded.tobytes(),
                    width=w,
                    height=h,
                    frame_number=self.api.frame_count,
                    targets=targets
                )

        except Exception as e:
            logger.error(f"StreamFrames error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))

    def GetSafetyStatus(
        self, request: tracking_pb2.GetSafetyStatusRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.GetSafetyStatusResponse:
        """Get safety status."""
        try:
            if not self.api.pipeline or not self.api.pipeline._safety_manager:
                return tracking_pb2.GetSafetyStatusResponse(fire_authorized=False, blocked_reason="Safety manager not enabled")

            # Since SafetyManager is evaluated per-frame, we might not have a global state getter easily accessible,
            # but we can poll the Interlock and NFZ manager.
            sm = self.api.pipeline._safety_manager
            fb = self.api.pipeline.driver.get_feedback(time.monotonic())
            nfz_res = sm._nfz.check(fb.yaw_deg, fb.pitch_deg)
            inter_res = sm._interlock.check()

            fire_authorized = inter_res.authorized and not nfz_res.fire_blocked
            reasons = []
            if nfz_res.fire_blocked: reasons.append(f"NFZ:{nfz_res.active_zone_id}")
            reasons.extend(inter_res.blocked_reasons)

            return tracking_pb2.GetSafetyStatusResponse(
                fire_authorized=fire_authorized,
                blocked_reason="; ".join(reasons),
                active_zone=nfz_res.active_zone_id or "",
                operator_override=inter_res.operator_auth,
                emergency_stop=inter_res.emergency_stop
            )
        except Exception as e:
            logger.error(f"GetSafetyStatus error: {e}")
            return tracking_pb2.GetSafetyStatusResponse(fire_authorized=False, blocked_reason=str(e))

    def SetOperatorAuth(
        self, request: tracking_pb2.SetOperatorAuthRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.SetOperatorAuthResponse:
        try:
            if self.api.pipeline and self.api.pipeline._safety_manager:
                self.api.pipeline._safety_manager.set_operator_auth(request.authorized)
            return tracking_pb2.SetOperatorAuthResponse(success=True)
        except Exception as e:
            return tracking_pb2.SetOperatorAuthResponse(success=False, error=str(e))

    def EmergencyStop(
        self, request: tracking_pb2.EmergencyStopRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.EmergencyStopResponse:
        try:
            if self.api.pipeline and self.api.pipeline._safety_manager:
                self.api.pipeline._safety_manager.set_emergency_stop(request.activate)
                if request.activate:
                    self.api.set_gimbal_rate(0.0, 0.0) # Stop movement
            return tracking_pb2.EmergencyStopResponse(success=True, emergency_stop_active=request.activate)
        except Exception as e:
            return tracking_pb2.EmergencyStopResponse(success=False, error=str(e))

    def GetThreatAssessment(
        self, request: tracking_pb2.GetThreatAssessmentRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.GetThreatAssessmentResponse:
        try:
            response = tracking_pb2.GetThreatAssessmentResponse()
            if self.api.pipeline and self.api.pipeline._engagement_queue:
                for t in self.api.pipeline._engagement_queue.queue:
                    response.threats.append(tracking_pb2.ThreatTarget(
                        track_id=t.track_id,
                        threat_score=t.threat_score,
                        distance_score=t.distance_score,
                        velocity_score=t.velocity_score,
                        class_score=t.class_score,
                        heading_score=t.heading_score,
                        priority_rank=t.priority_rank
                    ))
            return response
        except Exception as e:
            logger.error(f"GetThreatAssessment error: {e}")
            return tracking_pb2.GetThreatAssessmentResponse()

    # -------------------------------------------------------------------------
    # Fire control
    # -------------------------------------------------------------------------

    def _get_shooting_chain(self):
        """Return the ShootingChain from the live pipeline, or None."""
        pipeline = getattr(self.api, "pipeline", None)
        if pipeline is None:
            return None
        return getattr(pipeline, "_shooting_chain", None)

    def ArmSystem(
        self, request: tracking_pb2.ArmRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.FireControlResponse:
        """Transition ShootingChain SAFE -> ARMED."""
        chain = self._get_shooting_chain()
        if chain is None:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Shooting chain not available")
            return tracking_pb2.FireControlResponse(success=False, message="not_available")
        operator_id = getattr(request, "operator_id", "") or "grpc_operator"
        if not operator_id:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("operator_id required")
            return tracking_pb2.FireControlResponse(success=False, message="operator_id required")
        try:
            ok = chain.arm(operator_id)
            if not ok:
                context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
                msg = f"cannot arm from state {chain.state.value}"
                context.set_details(msg)
                return tracking_pb2.FireControlResponse(
                    success=False, state=chain.state.value, message=msg
                )
            return tracking_pb2.FireControlResponse(
                success=True,
                state=chain.state.value,
                can_fire=chain.can_fire,
                operator_id=operator_id,
            )
        except Exception as e:
            logger.error(f"ArmSystem error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.FireControlResponse(success=False, message=str(e))

    def SafeSystem(
        self, request: tracking_pb2.SafeRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.FireControlResponse:
        """Return ShootingChain to SAFE state."""
        chain = self._get_shooting_chain()
        if chain is None:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Shooting chain not available")
            return tracking_pb2.FireControlResponse(success=False, message="not_available")
        try:
            reason = getattr(request, "reason", "") or ""
            chain.safe(reason)
            return tracking_pb2.FireControlResponse(
                success=True,
                state=chain.state.value,
                can_fire=chain.can_fire,
            )
        except Exception as e:
            logger.error(f"SafeSystem error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.FireControlResponse(success=False, message=str(e))

    def RequestFire(
        self, request: tracking_pb2.RequestFireRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.FireControlResponse:
        """Human fire request — transitions FIRE_AUTHORIZED -> FIRE_REQUESTED."""
        chain = self._get_shooting_chain()
        if chain is None:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Shooting chain not available")
            return tracking_pb2.FireControlResponse(success=False, message="not_available")
        operator_id = getattr(request, "operator_id", "") or ""
        if not operator_id:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("operator_id required")
            return tracking_pb2.FireControlResponse(success=False, message="operator_id required")
        try:
            ok = chain.request_fire(operator_id)
            if not ok:
                context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
                msg = f"cannot request fire from state {chain.state.value}"
                context.set_details(msg)
                return tracking_pb2.FireControlResponse(
                    success=False, state=chain.state.value, message=msg
                )
            return tracking_pb2.FireControlResponse(
                success=True,
                state=chain.state.value,
                can_fire=chain.can_fire,
                operator_id=operator_id,
            )
        except Exception as e:
            logger.error(f"RequestFire error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.FireControlResponse(success=False, message=str(e))

    def GetFireStatus(
        self, request: tracking_pb2.GetFireStatusRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.FireControlResponse:
        """Return current fire chain state without making any transition."""
        chain = self._get_shooting_chain()
        if chain is None:
            return tracking_pb2.FireControlResponse(
                success=True, state="not_configured", can_fire=False
            )
        try:
            return tracking_pb2.FireControlResponse(
                success=True,
                state=chain.state.value,
                can_fire=chain.can_fire,
                operator_id=getattr(chain, "operator_id", "") or "",
            )
        except Exception as e:
            logger.error(f"GetFireStatus error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.FireControlResponse(success=False, message=str(e))

    def OperatorHeartbeat(
        self, request: tracking_pb2.OperatorHeartbeatRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.OperatorHeartbeatResponse:
        """Refresh operator heartbeat to prevent watchdog timeout."""
        operator_id = getattr(request, "operator_id", "") or ""
        if not operator_id:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("operator_id required")
            return tracking_pb2.OperatorHeartbeatResponse(ok=False, operator_id="")
        try:
            pipeline = getattr(self.api, "pipeline", None)
            if pipeline is not None:
                sm = getattr(pipeline, "_safety_manager", None)
                if sm is not None and hasattr(sm, "interlock"):
                    sm.interlock.operator_heartbeat()
                watchdog = getattr(pipeline, "_operator_watchdog", None)
                if watchdog is not None:
                    watchdog.heartbeat(operator_id)
            return tracking_pb2.OperatorHeartbeatResponse(ok=True, operator_id=operator_id)
        except Exception as e:
            logger.error(f"OperatorHeartbeat error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.OperatorHeartbeatResponse(ok=False, operator_id=operator_id)

    def DesignateTarget(
        self, request: tracking_pb2.DesignateTargetRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.DesignateTargetResponse:
        """Operator-designate a specific track for engagement (C2 override)."""
        pipeline = getattr(self.api, "pipeline", None)
        if pipeline is None:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Pipeline not running")
            return tracking_pb2.DesignateTargetResponse(ok=False)
        track_id = getattr(request, "track_id", 0)
        operator_id = getattr(request, "operator_id", "") or ""
        try:
            pipeline.designate_target(track_id, operator_id)
            logger.info(f"gRPC designation: track={track_id} operator='{operator_id}'")
            return tracking_pb2.DesignateTargetResponse(
                ok=True, track_id=track_id, designated=True
            )
        except Exception as e:
            logger.error(f"DesignateTarget error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.DesignateTargetResponse(ok=False)

    def ClearDesignation(
        self, request: tracking_pb2.ClearDesignationRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.DesignateTargetResponse:
        """Clear operator designation, returning to auto-selection."""
        pipeline = getattr(self.api, "pipeline", None)
        if pipeline is None:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Pipeline not running")
            return tracking_pb2.DesignateTargetResponse(ok=False)
        try:
            old_id = getattr(pipeline, "designated_track_id", None)
            pipeline.clear_designation()
            return tracking_pb2.DesignateTargetResponse(
                ok=True,
                track_id=0,
                designated=False,
                cleared_track_id=str(old_id) if old_id is not None else "",
            )
        except Exception as e:
            logger.error(f"ClearDesignation error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.DesignateTargetResponse(ok=False)

    def GetDesignation(
        self, request: tracking_pb2.GetDesignationRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.DesignateTargetResponse:
        """Return current operator designation status."""
        pipeline = getattr(self.api, "pipeline", None)
        if pipeline is None:
            return tracking_pb2.DesignateTargetResponse(ok=True, track_id=0, designated=False)
        try:
            tid = getattr(pipeline, "designated_track_id", None)
            return tracking_pb2.DesignateTargetResponse(
                ok=True,
                track_id=tid if tid is not None else 0,
                designated=tid is not None,
            )
        except Exception as e:
            logger.error(f"GetDesignation error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.DesignateTargetResponse(ok=False)

    # -------------------------------------------------------------------------
    # Mission management
    # -------------------------------------------------------------------------

    def StartMission(
        self, request: tracking_pb2.StartMissionRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.MissionResponse:
        """Start a new mission session."""
        import datetime
        pipeline = getattr(self.api, "pipeline", None)
        profile_name = getattr(request, "profile", "") or ""
        camera_source = getattr(request, "camera_source", 0)
        mission_name = getattr(request, "mission_name", "") or (
            f"Mission-{datetime.datetime.now():%Y%m%d-%H%M%S}"
        )
        try:
            # Load profile if specified
            if profile_name:
                from ..config.profiles import ProfileManager
                try:
                    pm = ProfileManager()
                    pm.load_profile(profile_name)
                    logger.info(f"mission: loaded profile '{profile_name}'")
                except (FileNotFoundError, ValueError) as exc:
                    context.set_code(grpc.StatusCode.NOT_FOUND)
                    context.set_details(str(exc))
                    return tracking_pb2.MissionResponse(
                        ok=False, error=f"Profile '{profile_name}' not found: {exc}"
                    )

            # Reset lifecycle + safe the chain for fresh session
            if pipeline is not None:
                lm = getattr(pipeline, "_lifecycle_manager", None)
                if lm is not None:
                    lm.reset()
                chain = getattr(pipeline, "_shooting_chain", None)
                if chain is not None:
                    chain.safe("mission_start")

            result = self.api.start_tracking(camera_source)
            if not result.get("success"):
                context.set_code(grpc.StatusCode.INTERNAL)
                err = result.get("error", "Failed to start tracking")
                context.set_details(err)
                return tracking_pb2.MissionResponse(ok=False, error=err)

            session_id = (
                f"{mission_name.replace(' ', '_')}_"
                f"{datetime.datetime.now():%Y%m%d_%H%M%S}"
            )
            logger.info(f"mission START (gRPC): session={session_id} profile={profile_name}")
            return tracking_pb2.MissionResponse(
                ok=True,
                session_id=session_id,
                message=f"Mission started: {session_id}",
            )
        except Exception as e:
            logger.error(f"StartMission error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.MissionResponse(ok=False, error=str(e))

    def EndMission(
        self, request: tracking_pb2.EndMissionRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.MissionResponse:
        """End the active mission and generate a debrief report."""
        import time as _time
        from pathlib import Path
        pipeline = getattr(self.api, "pipeline", None)
        try:
            # Auto-safe the fire chain before stopping
            if pipeline is not None:
                chain = getattr(pipeline, "_shooting_chain", None)
                if chain is not None:
                    chain.safe("mission_end")

            self.api.stop_tracking()

            # Generate audit report if audit logger has records
            report_path = None
            report_url = None
            if pipeline is not None:
                audit = getattr(pipeline, "_audit_logger", None)
                if audit is not None and getattr(audit, "_records", None):
                    from ..telemetry.report import generate_report
                    report_dir = Path("logs/reports")
                    report_dir.mkdir(parents=True, exist_ok=True)
                    ts_label = f"mission_{int(_time.time())}"
                    report_file = report_dir / f"{ts_label}_report.html"
                    generate_report(audit, mission_name=ts_label, output_path=str(report_file))
                    report_path = str(report_file)
                    report_url = f"/api/mission/report/{report_file.name}"
                    logger.info(f"mission: report written to {report_path}")

            logger.info("mission END (gRPC)")
            return tracking_pb2.MissionResponse(
                ok=True,
                message="Mission ended",
                report_path=report_path or "",
                report_url=report_url or "",
            )
        except Exception as e:
            logger.error(f"EndMission error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.MissionResponse(ok=False, error=str(e))

    def GetMissionStatus(
        self, request: tracking_pb2.GetMissionStatusRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.MissionStatusResponse:
        """Return current mission status from the live pipeline."""
        pipeline = getattr(self.api, "pipeline", None)
        try:
            status = self.api.get_status()
            fire_chain_state = ""
            if pipeline is not None:
                chain = getattr(pipeline, "_shooting_chain", None)
                if chain is not None:
                    fire_chain_state = chain.state.value
            return tracking_pb2.MissionStatusResponse(
                active=status.get("running", False),
                fire_chain_state=fire_chain_state,
            )
        except Exception as e:
            logger.error(f"GetMissionStatus error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.MissionStatusResponse()

    # -------------------------------------------------------------------------
    # Safety zone CRUD (No-Fire Zones)
    # -------------------------------------------------------------------------

    def _get_safety_manager(self):
        """Return the SafetyManager from the live pipeline, or None."""
        pipeline = getattr(self.api, "pipeline", None)
        if pipeline is None:
            return None
        return getattr(pipeline, "_safety_manager", None)

    def ListZones(
        self, request: tracking_pb2.ListZonesRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.ListZonesResponse:
        """List all active no-fire zones."""
        sm = self._get_safety_manager()
        if sm is None:
            return tracking_pb2.ListZonesResponse()
        try:
            zones = sm._nfz.zones
            zone_msgs = [
                tracking_pb2.SafetyZoneMsg(
                    zone_id=z.zone_id,
                    center_yaw_deg=z.center_yaw_deg,
                    center_pitch_deg=z.center_pitch_deg,
                    radius_deg=z.radius_deg,
                    zone_type=z.zone_type,
                    found=True,
                )
                for z in zones
            ]
            return tracking_pb2.ListZonesResponse(zones=zone_msgs)
        except Exception as e:
            logger.error(f"ListZones error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.ListZonesResponse()

    def AddZone(
        self, request: tracking_pb2.AddZoneRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.ZoneResponse:
        """Add a new no-fire zone to the running pipeline."""
        import uuid
        sm = self._get_safety_manager()
        if sm is None:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Safety manager not available")
            return tracking_pb2.ZoneResponse(ok=False, error="safety manager not available")
        try:
            center_yaw = float(request.center_yaw_deg)
            center_pitch = float(request.center_pitch_deg)
            radius = float(request.radius_deg)
        except (TypeError, ValueError) as exc:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(str(exc))
            return tracking_pb2.ZoneResponse(ok=False, error=str(exc))

        # Validate ranges (mirror safety_routes.py constraints)
        if radius <= 0 or radius > 180:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("radius_deg must be in (0, 180]")
            return tracking_pb2.ZoneResponse(ok=False, error="radius_deg must be in (0, 180]")
        if not (-180.0 <= center_yaw <= 180.0):
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("center_yaw_deg must be in [-180, 180]")
            return tracking_pb2.ZoneResponse(
                ok=False, error="center_yaw_deg must be in [-180, 180]"
            )
        if not (-90.0 <= center_pitch <= 90.0):
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("center_pitch_deg must be in [-90, 90]")
            return tracking_pb2.ZoneResponse(
                ok=False, error="center_pitch_deg must be in [-90, 90]"
            )

        zone_id = str(request.zone_id) if request.zone_id else f"nfz_{uuid.uuid4().hex[:8]}"
        zone_type = str(request.zone_type) if request.zone_type else "no_fire"

        try:
            from ..types import SafetyZone
            zone = SafetyZone(
                zone_id=zone_id,
                center_yaw_deg=center_yaw,
                center_pitch_deg=center_pitch,
                radius_deg=radius,
                zone_type=zone_type,
            )
            sm.add_no_fire_zone(zone)
            logger.info(
                f"NFZ added via gRPC: id={zone_id} yaw={center_yaw:.1f} "
                f"pitch={center_pitch:.1f} r={radius:.1f}"
            )
            return tracking_pb2.ZoneResponse(ok=True, zone_id=zone_id)
        except Exception as e:
            logger.error(f"AddZone error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.ZoneResponse(ok=False, error=str(e))

    def RemoveZone(
        self, request: tracking_pb2.RemoveZoneRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.ZoneResponse:
        """Remove a no-fire zone by ID."""
        sm = self._get_safety_manager()
        if sm is None:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Safety manager not available")
            return tracking_pb2.ZoneResponse(ok=False, error="safety manager not available")
        zone_id = getattr(request, "zone_id", "") or ""
        if not zone_id:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("zone_id required")
            return tracking_pb2.ZoneResponse(ok=False, error="zone_id required")
        try:
            removed = sm.remove_no_fire_zone(zone_id)
            if not removed:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"zone '{zone_id}' not found")
                return tracking_pb2.ZoneResponse(
                    ok=False, zone_id=zone_id, error=f"zone '{zone_id}' not found"
                )
            logger.info(f"NFZ removed via gRPC: id={zone_id}")
            return tracking_pb2.ZoneResponse(ok=True, zone_id=zone_id)
        except Exception as e:
            logger.error(f"RemoveZone error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.ZoneResponse(ok=False, error=str(e))

    def GetZone(
        self, request: tracking_pb2.GetZoneRequest, context: grpc.ServicerContext
    ) -> tracking_pb2.SafetyZoneMsg:
        """Get a specific no-fire zone by ID."""
        sm = self._get_safety_manager()
        if sm is None:
            context.set_code(grpc.StatusCode.UNAVAILABLE)
            context.set_details("Safety manager not available")
            return tracking_pb2.SafetyZoneMsg(found=False, error="safety manager not available")
        zone_id = getattr(request, "zone_id", "") or ""
        try:
            zone = sm._nfz._zones.get(zone_id)
            if zone is None:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"zone '{zone_id}' not found")
                return tracking_pb2.SafetyZoneMsg(
                    found=False, error=f"zone '{zone_id}' not found"
                )
            return tracking_pb2.SafetyZoneMsg(
                zone_id=zone.zone_id,
                center_yaw_deg=zone.center_yaw_deg,
                center_pitch_deg=zone.center_pitch_deg,
                radius_deg=zone.radius_deg,
                zone_type=zone.zone_type,
                found=True,
            )
        except Exception as e:
            logger.error(f"GetZone error: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return tracking_pb2.SafetyZoneMsg(found=False, error=str(e))


# Backward-compat alias
TrackingGrpcServer = TrackingServicer


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
  Core:
    HealthCheck          - Health check
    StartTracking        - Start tracking
    StopTracking         - Stop tracking
    GetStatus            - Get status
    SetGimbalPosition    - Set gimbal position
    SetGimbalRate        - Set gimbal rate
    GetTelemetry         - Get telemetry
    UpdateConfig         - Update config
    StreamStatus         - Stream status updates
    StreamFrames         - Stream annotated video frames
  Safety:
    GetSafetyStatus      - Get safety/NFZ status
    SetOperatorAuth      - Set operator authorization
    EmergencyStop        - Emergency stop control
    GetThreatAssessment  - Get ranked threat queue
  Fire Control:
    ArmSystem            - Arm shooting chain (SAFE -> ARMED)
    SafeSystem           - Return to SAFE state
    RequestFire          - Human fire request
    GetFireStatus        - Get current fire chain state
    OperatorHeartbeat    - Refresh operator heartbeat
    DesignateTarget      - Designate specific target (C2 override)
    ClearDesignation     - Clear designation (return to auto)
    GetDesignation       - Get current designation status
  Mission:
    StartMission         - Start a new mission session
    EndMission           - End mission and generate report
    GetMissionStatus     - Get current mission status
  Safety Zones (NFZ CRUD):
    ListZones            - List all active no-fire zones
    AddZone              - Add a new no-fire zone
    RemoveZone           - Remove a zone by ID
    GetZone              - Get one zone by ID

Server is running. Press Ctrl+C to stop.
""")

    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        logger.info("Shutting down gRPC server...")
        server.stop(grace=5.0)
        logger.info("Server stopped")
