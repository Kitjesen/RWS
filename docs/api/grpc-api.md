# RWS gRPC API Reference

## Overview

The RWS gRPC API exposes the full capability of the tracking system over a
binary, HTTP/2 channel. It is the preferred interface for high-performance
clients (C++, Go, embedded systems) and for any use case that requires
real-time server-streaming (status, video frames).

| Property | Value |
|---|---|
| Endpoint | `0.0.0.0:50051` (configurable) |
| Proto package | `rws_tracking` |
| Proto file | `src/rws_tracking/api/tracking.proto` |
| Transport | gRPC over insecure HTTP/2 (TLS optional — see Security section) |
| Total RPCs | 29 |
| Streaming RPCs | 2 (server-streaming): `StreamStatus`, `StreamFrames` |
| Max worker threads | 10 (default) |

---

## Quick Start

### 1. Install dependencies

```bash
pip install grpcio grpcio-tools protobuf
```

### 2. Generate Python stubs

```bash
cd src/rws_tracking/api
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. tracking.proto
```

This produces:
- `tracking_pb2.py` — compiled message definitions
- `tracking_pb2_grpc.py` — service stub and servicer base class

### 3. Start the gRPC server

```bash
python scripts/api/run_grpc_server.py   # binds 0.0.0.0:50051
```

### 4. Connect from Python

```python
import grpc
from rws_tracking.api import tracking_pb2, tracking_pb2_grpc

channel = grpc.insecure_channel("localhost:50051")
stub = tracking_pb2_grpc.TrackingServiceStub(channel)

# Health check
resp = stub.HealthCheck(tracking_pb2.HealthCheckRequest())
print(resp.status, resp.service)   # "ok"  "rws-tracking"

# Start tracking from camera 0
resp = stub.StartTracking(
    tracking_pb2.StartTrackingRequest(camera_id=0)
)
print(resp.success, resp.message)

# Poll status
status = stub.GetStatus(tracking_pb2.GetStatusRequest())
print(f"fps={status.fps:.1f}  yaw={status.gimbal.yaw_deg:.2f}")

# Stream status at 20 Hz
for update in stub.StreamStatus(
    tracking_pb2.StreamStatusRequest(update_rate_hz=20.0)
):
    print(f"[{update.timestamp:.3f}] fps={update.fps:.1f}")
    # break when done

channel.close()
```

---

## Service: TrackingService

### Core Tracking

---

#### `HealthCheck`

```
HealthCheck(HealthCheckRequest) → HealthCheckResponse
```

Lightweight liveness probe. Always returns `status="ok"` when the server
process is alive. Does not verify that tracking is running.

**Request fields:** _(none)_

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `status` | string | Always `"ok"` |
| `service` | string | Always `"rws-tracking"` |

**gRPC errors:** none — this RPC never sets a non-OK status code.

---

#### `StartTracking`

```
StartTracking(StartTrackingRequest) → StartTrackingResponse
```

Initialise the camera, detector, tracker, and pipeline loop. The camera source
is provided as a `oneof`: either an integer device index or a file path string.
If neither field is set, device `0` is used.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `camera_id` | int32 (oneof) | OpenCV device index (e.g. `0`) |
| `video_path` | string (oneof) | Path or URL to a video file |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `success` | bool | `true` on successful start |
| `message` | string | Human-readable confirmation |
| `error` | string | Non-empty on failure |

**gRPC errors:** Returns `INTERNAL` (via response `error` field, not status
code) on unexpected exceptions.

---

#### `StopTracking`

```
StopTracking(StopTrackingRequest) → StopTrackingResponse
```

Stop the pipeline loop and release the camera. Safe to call when tracking is
not running.

**Request fields:** _(none)_

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `success` | bool | `true` when stopped successfully |
| `message` | string | Human-readable confirmation |
| `error` | string | Non-empty on failure |

**gRPC errors:** Exceptions are caught; `error` field is populated.

---

#### `GetStatus`

```
GetStatus(GetStatusRequest) → GetStatusResponse
```

Single-shot snapshot of pipeline and gimbal state.

**Request fields:** _(none)_

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `running` | bool | Whether the pipeline loop is active |
| `frame_count` | int64 | Total frames processed since start |
| `error_count` | int64 | Accumulated error count |
| `last_error` | string | Most recent error message, or empty |
| `fps` | double | Measured frames-per-second |
| `gimbal` | GimbalState | Current gimbal position and rate |

**gRPC errors:** `INTERNAL` with details on unexpected exception.

---

#### `StreamStatus`

```
StreamStatus(StreamStatusRequest) → stream StatusUpdate
```

Server-streaming RPC. Yields `StatusUpdate` messages at approximately the
requested rate until the client cancels or the connection drops.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `update_rate_hz` | double | Desired update frequency (default: `10.0`) |

**Response stream fields (StatusUpdate):**

| Field | Type | Description |
|---|---|---|
| `timestamp` | double | Unix epoch seconds (float) |
| `running` | bool | Pipeline running state |
| `frame_count` | int64 | Frames processed |
| `fps` | double | Current frames-per-second |
| `gimbal` | GimbalState | Current gimbal position and rate |

**gRPC errors:** `INTERNAL` on exception; stream terminates.

---

#### `StreamFrames`

```
StreamFrames(StreamFramesRequest) → stream VideoFrame
```

Server-streaming RPC. Yields JPEG-encoded annotated video frames from the
pipeline's internal ring buffer. Rate-limited by `max_fps`; frames are
silently dropped when the encoder cannot keep up.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `max_fps` | double | Maximum frame rate to send (default: `15.0`) |
| `scale_factor` | double | Resolution scale factor `(0, 1]` (default: `0.5`) |
| `jpeg_quality` | int32 | JPEG compression quality `1–100` (default: `70`) |
| `annotate` | bool | If `true`, populate `targets` with detected track metadata |

**Response stream fields (VideoFrame):**

| Field | Type | Description |
|---|---|---|
| `timestamp` | double | Unix epoch seconds of frame capture |
| `jpeg_data` | bytes | JPEG-encoded frame payload |
| `width` | int32 | Frame width in pixels (after scaling) |
| `height` | int32 | Frame height in pixels (after scaling) |
| `frame_number` | int64 | Pipeline frame counter |
| `targets` | repeated DetectedTarget | Detected tracks (only when `annotate=true`) |

**gRPC errors:** `INTERNAL` on encode failure or unexpected exception; stream
terminates.

---

### Gimbal Control

---

#### `SetGimbalPosition`

```
SetGimbalPosition(SetGimbalPositionRequest) → SetGimbalPositionResponse
```

Command the gimbal to a specific absolute position. The controller applies
limits from `driver_limits` in `config.yaml`.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `yaw_deg` | double | Target yaw angle in degrees |
| `pitch_deg` | double | Target pitch angle in degrees |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `success` | bool | `true` on success |
| `error` | string | Non-empty on failure |
| `target` | GimbalPosition | The commanded position (after clamping) |
| `current` | GimbalPosition | Current position reported by driver |

**gRPC errors:** Exceptions caught; `error` field populated.

---

#### `SetGimbalRate`

```
SetGimbalRate(SetGimbalRateRequest) → SetGimbalRateResponse
```

Set gimbal angular velocity. Also used internally by `EmergencyStop` to
command zero rate.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `yaw_rate_dps` | double | Yaw angular velocity in degrees per second |
| `pitch_rate_dps` | double | Pitch angular velocity in degrees per second |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `success` | bool | `true` on success |
| `error` | string | Non-empty on failure |
| `command` | GimbalRate | The rate command actually sent to the driver |

**gRPC errors:** Exceptions caught; `error` field populated.

---

### Configuration

---

#### `UpdateConfig`

```
UpdateConfig(UpdateConfigRequest) → UpdateConfigResponse
```

Apply a partial configuration update at runtime. The payload must be a
JSON-encoded object. Keys correspond to sections in `config.yaml`. The server
merges the update into the live configuration; hot-reload applies immediately.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `config_json` | string | JSON-encoded configuration delta |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `success` | bool | `true` on success |
| `message` | string | Confirmation or informational text |
| `error` | string | Non-empty on failure; also set on JSON parse error |

**gRPC errors:** `error` field is set (not gRPC status code) for
`JSONDecodeError` and other exceptions.

---

#### `GetTelemetry`

```
GetTelemetry(GetTelemetryRequest) → GetTelemetryResponse
```

Retrieve the latest telemetry metrics from the in-memory logger. Returns
numeric key-value pairs (frame latency, PID error, detection count, etc.).

**Request fields:** _(none)_

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `success` | bool | `false` when telemetry is unavailable |
| `error` | string | Non-empty when `success=false` |
| `metrics` | map\<string, double\> | Named metric values |

**gRPC errors:** Exceptions caught; `success=false` and `error` populated.

---

### Safety & Health

---

#### `GetSafetyStatus`

```
GetSafetyStatus(GetSafetyStatusRequest) → GetSafetyStatusResponse
```

Query the current state of the `SafetyInterlock` and `NoFireZoneManager`.
Evaluated against the latest driver feedback (current gimbal position).

**Request fields:** _(none)_

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `fire_authorized` | bool | `true` when interlock is clear AND gimbal is outside all NFZ |
| `blocked_reason` | string | Semicolon-separated reasons why fire is blocked, or empty |
| `active_zone` | string | ID of the NFZ currently containing the gimbal, or empty |
| `operator_override` | bool | `true` when operator authorization condition is satisfied |
| `emergency_stop` | bool | `true` when emergency stop is latched |

**gRPC errors:** Returns `fire_authorized=false` with `blocked_reason`
populated on any exception; no gRPC status code set.

---

#### `SetOperatorAuth`

```
SetOperatorAuth(SetOperatorAuthRequest) → SetOperatorAuthResponse
```

Set or clear the operator authorization flag on the `SafetyInterlock`.
This is one of the seven conditions that must be satisfied for fire to be
authorized. Superseded by the `ShootingChain.arm()` path for fire control
(see `ArmSystem`).

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `authorized` | bool | `true` to authorize, `false` to revoke |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `success` | bool | `true` on success |
| `error` | string | Non-empty on failure |

**gRPC errors:** Exceptions caught; `error` populated.

---

#### `EmergencyStop`

```
EmergencyStop(EmergencyStopRequest) → EmergencyStopResponse
```

Engage or release the emergency stop latch. When `activate=true`, the safety
manager latches the E-stop flag AND commands `SetGimbalRate(0, 0)` to halt
all motion immediately. When `activate=false`, the latch is released.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `activate` | bool | `true` to engage, `false` to release |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `success` | bool | `true` on success |
| `emergency_stop_active` | bool | Reflects the `activate` value sent |
| `error` | string | Non-empty on failure |

**gRPC errors:** Exceptions caught; `error` populated.

---

### Threat Assessment

---

#### `GetThreatAssessment`

```
GetThreatAssessment(GetThreatAssessmentRequest) → GetThreatAssessmentResponse
```

Return the current ranked threat queue from the `EngagementQueue`. Each entry
is a scored track, ordered by composite threat score descending. Only active
(non-neutralized) targets appear.

**Request fields:** _(none)_

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `threats` | repeated ThreatTarget | Ordered list of scored threats |

**ThreatTarget fields:**

| Field | Type | Description |
|---|---|---|
| `track_id` | int32 | Tracker-assigned track ID |
| `threat_score` | float | Composite weighted threat score |
| `distance_score` | float | Component: proximity contribution |
| `velocity_score` | float | Component: approach-rate contribution |
| `class_score` | float | Component: target class threat weight |
| `heading_score` | float | Component: heading-toward-sensor contribution |
| `priority_rank` | int32 | 1-based rank (1 = highest priority) |

**gRPC errors:** Returns empty `threats` list on exception; no gRPC status
code set.

---

### Fire Control

The fire control RPCs manipulate the `ShootingChain` state machine, which
has the following states:

```
SAFE → ARMED → FIRE_AUTHORIZED → FIRE_REQUESTED → FIRED → COOLDOWN → SAFE
```

The `OperatorWatchdog` runs in a daemon thread and forces the chain back to
`SAFE` if no heartbeat is received for more than 10 seconds.

---

#### `ArmSystem`

```
ArmSystem(ArmRequest) → FireControlResponse
```

Transition the `ShootingChain` from `SAFE` to `ARMED`. `operator_id` is
mandatory — it is recorded in the `AuditLogger`.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `operator_id` | string | **Required.** Identifies the arming operator |

**Response fields (FireControlResponse):**

| Field | Type | Description |
|---|---|---|
| `success` | bool | `true` when transition succeeded |
| `state` | string | Current `ShootingChain` state value |
| `can_fire` | bool | `true` when the chain's `can_fire` property is set |
| `message` | string | Human-readable detail or error text |
| `operator_id` | string | Echoes the requesting operator ID |

**gRPC errors:**

| Code | Condition |
|---|---|
| `UNAVAILABLE` | No pipeline or shooting chain configured |
| `INVALID_ARGUMENT` | `operator_id` is empty |
| `FAILED_PRECONDITION` | Current state does not allow arming |
| `INTERNAL` | Unexpected exception |

---

#### `SafeSystem`

```
SafeSystem(SafeRequest) → FireControlResponse
```

Return the `ShootingChain` to `SAFE` from any state. Idempotent — always
succeeds even if already `SAFE`. The optional `reason` string is logged.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `reason` | string | Optional. Reason for returning to safe state |

**Response fields:** See `FireControlResponse` above.

**gRPC errors:**

| Code | Condition |
|---|---|
| `UNAVAILABLE` | No pipeline or shooting chain configured |
| `INTERNAL` | Unexpected exception |

---

#### `RequestFire`

```
RequestFire(RequestFireRequest) → FireControlResponse
```

Human fire confirmation — transitions the chain from `FIRE_AUTHORIZED` to
`FIRE_REQUESTED`. The pipeline's next `step()` call will detect `can_fire=true`
and call `execute_fire()`, which writes an `AuditLogger` record.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `operator_id` | string | **Required.** Human confirmation of fire request |

**Response fields:** See `FireControlResponse` above.

**gRPC errors:**

| Code | Condition |
|---|---|
| `UNAVAILABLE` | No pipeline or shooting chain configured |
| `INVALID_ARGUMENT` | `operator_id` is empty |
| `FAILED_PRECONDITION` | Chain not in `FIRE_AUTHORIZED` state |
| `INTERNAL` | Unexpected exception |

---

#### `GetFireStatus`

```
GetFireStatus(GetFireStatusRequest) → FireControlResponse
```

Read-only query of the current `ShootingChain` state. Makes no transitions.
Returns `state="not_configured"` when no pipeline is running.

**Request fields:** _(none)_

**Response fields:** See `FireControlResponse` above. `operator_id` reflects
the last operator that interacted with the chain.

**gRPC errors:** `INTERNAL` on unexpected exception.

---

#### `OperatorHeartbeat`

```
OperatorHeartbeat(OperatorHeartbeatRequest) → OperatorHeartbeatResponse
```

Reset the `OperatorWatchdog` timer. Must be called at least once every 10
seconds while the system is armed. If the watchdog times out, the chain is
forced to `SAFE` regardless of pipeline state.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `operator_id` | string | **Required.** Identifies the active operator |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `ok` | bool | `true` on success |
| `operator_id` | string | Echoes the requesting operator ID |

**gRPC errors:**

| Code | Condition |
|---|---|
| `INVALID_ARGUMENT` | `operator_id` is empty |
| `INTERNAL` | Unexpected exception |

---

#### `DesignateTarget`

```
DesignateTarget(DesignateTargetRequest) → DesignateTargetResponse
```

C2 override: designate a specific track for engagement. Bypasses the
`WeightedTargetSelector` auto-selection logic. Persists until explicitly
cleared with `ClearDesignation`.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `track_id` | int32 | **Required.** Tracker-assigned ID of the target to designate |
| `operator_id` | string | Optional. Logged for audit trail |

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `ok` | bool | `true` on success |
| `track_id` | int32 | Designated track ID |
| `designated` | bool | `true` when a designation is now active |
| `cleared_track_id` | string | Unused by this RPC (see `ClearDesignation`) |

**gRPC errors:**

| Code | Condition |
|---|---|
| `UNAVAILABLE` | Pipeline is not running |
| `INTERNAL` | Unexpected exception |

---

#### `ClearDesignation`

```
ClearDesignation(ClearDesignationRequest) → DesignateTargetResponse
```

Remove the operator designation. The `WeightedTargetSelector` resumes
automatic target selection on the next pipeline step.

**Request fields:** _(none)_

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `ok` | bool | `true` on success |
| `track_id` | int32 | `0` (no designation active) |
| `designated` | bool | `false` |
| `cleared_track_id` | string | String representation of the previous track ID, or empty |

**gRPC errors:**

| Code | Condition |
|---|---|
| `UNAVAILABLE` | Pipeline is not running |
| `INTERNAL` | Unexpected exception |

---

#### `GetDesignation`

```
GetDesignation(GetDesignationRequest) → DesignateTargetResponse
```

Read-only query of the current operator designation state.

**Request fields:** _(none)_

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `ok` | bool | `true` on success |
| `track_id` | int32 | Currently designated track ID, or `0` if none |
| `designated` | bool | `true` when a designation is active |

**gRPC errors:** `INTERNAL` on unexpected exception.

---

### Mission Management

---

#### `StartMission`

```
StartMission(StartMissionRequest) → MissionResponse
```

Begin a new mission session. The method:
1. Optionally loads a named mission profile via `ProfileManager`.
2. Resets the `TargetLifecycleManager` (clears all previously tracked targets).
3. Forces the `ShootingChain` to `SAFE` for a clean start.
4. Starts tracking via `StartTracking`.
5. Returns a server-generated `session_id`.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `profile` | string | Optional. Named mission profile to load from `ProfileManager` |
| `camera_source` | int32 | Camera device index (default `0`) |
| `mission_name` | string | Optional display name; auto-generated if empty |

**Response fields (MissionResponse):**

| Field | Type | Description |
|---|---|---|
| `ok` | bool | `true` on success |
| `session_id` | string | Server-generated session identifier |
| `message` | string | Confirmation or informational text |
| `error` | string | Non-empty on failure |
| `elapsed_s` | double | Session duration in seconds (not set at start) |
| `report_path` | string | Not set at start |
| `report_url` | string | Not set at start |

**gRPC errors:**

| Code | Condition |
|---|---|
| `NOT_FOUND` | Named profile does not exist |
| `INTERNAL` | Tracking failed to start or unexpected exception |

---

#### `EndMission`

```
EndMission(EndMissionRequest) → MissionResponse
```

End the active mission. The method:
1. Forces the `ShootingChain` to `SAFE`.
2. Stops tracking.
3. Generates an HTML mission debrief report from `AuditLogger` records (if
   any events were recorded). The report is written to `logs/reports/`.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `reason` | string | Optional. Reason for ending the mission |

**Response fields (MissionResponse):**

| Field | Type | Description |
|---|---|---|
| `ok` | bool | `true` on success |
| `message` | string | Confirmation |
| `error` | string | Non-empty on failure |
| `report_path` | string | Filesystem path of generated HTML report, or empty |
| `report_url` | string | REST URL to retrieve the report (e.g. `/api/mission/report/<name>.html`), or empty |

**gRPC errors:** `INTERNAL` on unexpected exception.

---

#### `GetMissionStatus`

```
GetMissionStatus(GetMissionStatusRequest) → MissionStatusResponse
```

Lightweight status query for a running mission. Does not require a session ID.

**Request fields:** _(none)_

**Response fields (MissionStatusResponse):**

| Field | Type | Description |
|---|---|---|
| `active` | bool | `true` when the pipeline is running |
| `session_id` | string | Current session ID (not populated by current implementation) |
| `profile` | string | Active profile name (not populated by current implementation) |
| `started_at` | string | ISO-8601 start timestamp (not populated by current implementation) |
| `elapsed_s` | double | Elapsed time in seconds (not populated by current implementation) |
| `targets_engaged` | int32 | Count of neutralized targets (not populated by current implementation) |
| `fire_chain_state` | string | Current `ShootingChain` state value, or empty |

**gRPC errors:** `INTERNAL` on unexpected exception.

---

### Safety Zone CRUD (No-Fire Zones)

No-Fire Zones (NFZ) are circular regions in gimbal-angle space. The system
blocks fire authorization when the gimbal is inside any active zone. Zones
take effect on the next pipeline `step()` call after being added.

All four RPCs require the pipeline to be running and `SafetyManager` to be
configured. If the safety manager is not available, `UNAVAILABLE` is returned.

---

#### `ListZones`

```
ListZones(ListZonesRequest) → ListZonesResponse
```

Return all currently active no-fire zones.

**Request fields:** _(none)_

**Response fields:**

| Field | Type | Description |
|---|---|---|
| `zones` | repeated SafetyZoneMsg | All active zones; empty list when none |

**gRPC errors:** `INTERNAL` on unexpected exception; returns empty list.

---

#### `AddZone`

```
AddZone(AddZoneRequest) → ZoneResponse
```

Add a new no-fire zone. If `zone_id` is omitted, the server generates one
with the format `nfz_<8-hex-chars>`.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `zone_id` | string | Optional. Client-specified zone ID; auto-generated if empty |
| `center_yaw_deg` | double | Zone center yaw angle in degrees (`[-180, 180]`) |
| `center_pitch_deg` | double | Zone center pitch angle in degrees (`[-90, 90]`) |
| `radius_deg` | double | Zone radius in degrees (`(0, 180]`) |
| `zone_type` | string | Optional. Defaults to `"no_fire"` |

**Response fields (ZoneResponse):**

| Field | Type | Description |
|---|---|---|
| `ok` | bool | `true` on success |
| `zone_id` | string | The ID of the created zone |
| `error` | string | Non-empty on failure |

**gRPC errors:**

| Code | Condition |
|---|---|
| `UNAVAILABLE` | Safety manager not available |
| `INVALID_ARGUMENT` | `radius_deg` not in `(0, 180]`; `center_yaw_deg` not in `[-180, 180]`; `center_pitch_deg` not in `[-90, 90]`; or non-numeric values |
| `INTERNAL` | Unexpected exception |

---

#### `RemoveZone`

```
RemoveZone(RemoveZoneRequest) → ZoneResponse
```

Remove an active no-fire zone by its ID.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `zone_id` | string | **Required.** ID of the zone to remove |

**Response fields (ZoneResponse):**

| Field | Type | Description |
|---|---|---|
| `ok` | bool | `true` on success |
| `zone_id` | string | The ID of the removed zone |
| `error` | string | Non-empty on failure |

**gRPC errors:**

| Code | Condition |
|---|---|
| `UNAVAILABLE` | Safety manager not available |
| `INVALID_ARGUMENT` | `zone_id` is empty |
| `NOT_FOUND` | No zone with the given ID exists |
| `INTERNAL` | Unexpected exception |

---

#### `GetZone`

```
GetZone(GetZoneRequest) → SafetyZoneMsg
```

Retrieve a single no-fire zone by ID.

**Request fields:**

| Field | Type | Description |
|---|---|---|
| `zone_id` | string | **Required.** ID of the zone to retrieve |

**Response fields (SafetyZoneMsg):**

| Field | Type | Description |
|---|---|---|
| `zone_id` | string | Zone ID |
| `center_yaw_deg` | double | Zone center yaw in degrees |
| `center_pitch_deg` | double | Zone center pitch in degrees |
| `radius_deg` | double | Zone radius in degrees |
| `zone_type` | string | Zone type string (e.g. `"no_fire"`) |
| `found` | bool | `true` when the zone was found |
| `error` | string | Non-empty when `found=false` |

**gRPC errors:**

| Code | Condition |
|---|---|
| `UNAVAILABLE` | Safety manager not available |
| `NOT_FOUND` | No zone with the given ID exists |
| `INTERNAL` | Unexpected exception |

---

## Message Types

### Common / Shared

#### `GimbalState`
| Field | Type | Description |
|---|---|---|
| `yaw_deg` | double | Current yaw angle in degrees |
| `pitch_deg` | double | Current pitch angle in degrees |
| `yaw_rate_dps` | double | Current yaw angular velocity (deg/s) |
| `pitch_rate_dps` | double | Current pitch angular velocity (deg/s) |

#### `GimbalPosition`
| Field | Type | Description |
|---|---|---|
| `yaw_deg` | double | Yaw angle in degrees |
| `pitch_deg` | double | Pitch angle in degrees |

#### `GimbalRate`
| Field | Type | Description |
|---|---|---|
| `yaw_rate_dps` | double | Yaw angular velocity in deg/s |
| `pitch_rate_dps` | double | Pitch angular velocity in deg/s |

#### `BoundingBoxMsg`
| Field | Type | Description |
|---|---|---|
| `x` | float | Left edge of bounding box in pixels |
| `y` | float | Top edge of bounding box in pixels |
| `w` | float | Width of bounding box in pixels |
| `h` | float | Height of bounding box in pixels |

#### `DetectedTarget`
| Field | Type | Description |
|---|---|---|
| `track_id` | int32 | Tracker-assigned track ID |
| `class_id` | string | Detector class label |
| `confidence` | float | Detection confidence score `[0, 1]` |
| `bbox` | BoundingBoxMsg | Bounding box in pixel coordinates |
| `velocity_x` | float | Horizontal velocity in pixels per second |
| `velocity_y` | float | Vertical velocity in pixels per second |
| `is_selected` | bool | `true` when this track is the current engagement target |

#### `ThreatTarget`
| Field | Type | Description |
|---|---|---|
| `track_id` | int32 | Tracker-assigned track ID |
| `threat_score` | float | Composite weighted threat score |
| `distance_score` | float | Proximity component |
| `velocity_score` | float | Approach-rate component |
| `class_score` | float | Target class threat weight component |
| `heading_score` | float | Heading-toward-sensor component |
| `priority_rank` | int32 | 1-based rank (1 = highest priority) |

### Fire Control Messages

#### `FireControlResponse`
| Field | Type | Description |
|---|---|---|
| `success` | bool | `true` when the requested transition succeeded |
| `state` | string | Current `ShootingChain` state (e.g. `"ARMED"`, `"SAFE"`) |
| `can_fire` | bool | `true` when the chain's `can_fire` property is set |
| `message` | string | Human-readable detail or error text |
| `operator_id` | string | Operator that performed the action |

#### `ArmRequest`
| Field | Type | Description |
|---|---|---|
| `operator_id` | string | Required. Identifies the arming operator |

#### `SafeRequest`
| Field | Type | Description |
|---|---|---|
| `reason` | string | Optional. Reason for returning to safe |

#### `RequestFireRequest`
| Field | Type | Description |
|---|---|---|
| `operator_id` | string | Required. Human confirmation of fire request |

#### `OperatorHeartbeatRequest` / `OperatorHeartbeatResponse`
| Field | Type | Description |
|---|---|---|
| `operator_id` | string | Identifies the active operator |
| `ok` | bool | (response) `true` on success |

#### `DesignateTargetRequest`
| Field | Type | Description |
|---|---|---|
| `track_id` | int32 | Tracker ID of target to designate |
| `operator_id` | string | Optional. Audit trail identifier |

#### `DesignateTargetResponse`
| Field | Type | Description |
|---|---|---|
| `ok` | bool | `true` on success |
| `track_id` | int32 | Designated track ID; `0` means none |
| `designated` | bool | `true` when a designation is active |
| `cleared_track_id` | string | (ClearDesignation only) Previous track ID as string |

### Mission Messages

#### `StartMissionRequest`
| Field | Type | Description |
|---|---|---|
| `profile` | string | Optional mission profile name |
| `camera_source` | int32 | Camera device index (default `0`) |
| `mission_name` | string | Optional display name |

#### `MissionResponse`
| Field | Type | Description |
|---|---|---|
| `ok` | bool | `true` on success |
| `session_id` | string | Server-generated session identifier |
| `message` | string | Confirmation or informational text |
| `error` | string | Non-empty on failure |
| `elapsed_s` | double | Session duration in seconds |
| `report_path` | string | Filesystem path of generated HTML report |
| `report_url` | string | REST URL to retrieve the report |

#### `MissionStatusResponse`
| Field | Type | Description |
|---|---|---|
| `active` | bool | `true` when the pipeline is running |
| `session_id` | string | Current session ID |
| `profile` | string | Active profile name |
| `started_at` | string | ISO-8601 start timestamp |
| `elapsed_s` | double | Elapsed time in seconds |
| `targets_engaged` | int32 | Count of neutralized targets |
| `fire_chain_state` | string | Current `ShootingChain` state value |

### Safety Zone Messages

#### `SafetyZoneMsg`
| Field | Type | Description |
|---|---|---|
| `zone_id` | string | Zone identifier |
| `center_yaw_deg` | double | Zone center yaw in degrees |
| `center_pitch_deg` | double | Zone center pitch in degrees |
| `radius_deg` | double | Zone radius in degrees |
| `zone_type` | string | Zone type (e.g. `"no_fire"`) |
| `found` | bool | `false` when zone lookup returned no result |
| `error` | string | Non-empty when an error occurred |

#### `ZoneResponse`
| Field | Type | Description |
|---|---|---|
| `ok` | bool | `true` on success |
| `zone_id` | string | The affected zone ID |
| `error` | string | Non-empty on failure |

---

## Comparison with REST API

| gRPC Method | REST Equivalent | Notes |
|---|---|---|
| `HealthCheck` | `GET /health` | — |
| `StartTracking` | `POST /api/mission/start` | REST combines profile load + start |
| `StopTracking` | `POST /api/mission/end` (partial) | REST also generates report |
| `GetStatus` | `GET /api/status` | — |
| `StreamStatus` | `GET /api/events` (SSE) | gRPC provides binary framing; REST uses text SSE |
| `StreamFrames` | `GET /video_feed` (MJPEG) | gRPC provides per-frame metadata; MJPEG does not |
| `SetGimbalPosition` | _(no direct equivalent)_ | REST does not expose raw gimbal position control |
| `SetGimbalRate` | _(no direct equivalent)_ | REST does not expose raw gimbal rate control |
| `UpdateConfig` | _(hot-reload only)_ | REST has no explicit config update endpoint |
| `GetTelemetry` | `GET /metrics` (Prometheus) | gRPC returns key-value map; REST returns Prometheus text |
| `GetSafetyStatus` | `GET /api/safety/status` (implicit) | — |
| `SetOperatorAuth` | _(via fire chain)_ | REST uses `POST /api/fire/arm` |
| `EmergencyStop` | _(no direct equivalent)_ | REST has no explicit E-stop endpoint |
| `GetThreatAssessment` | `GET /api/threats` | — |
| `ArmSystem` | `POST /api/fire/arm` | — |
| `SafeSystem` | `POST /api/fire/safe` (implied) | — |
| `RequestFire` | `POST /api/fire/request` | — |
| `GetFireStatus` | `GET /api/fire/status` (implied) | — |
| `OperatorHeartbeat` | `POST /api/fire/heartbeat` | — |
| `DesignateTarget` | `POST /api/fire/designate` | — |
| `ClearDesignation` | `DELETE /api/fire/designate` | — |
| `GetDesignation` | `GET /api/fire/designate` | — |
| `StartMission` | `POST /api/mission/start` | — |
| `EndMission` | `POST /api/mission/end` | — |
| `GetMissionStatus` | `GET /api/mission/status` (implied) | — |
| `ListZones` | `GET /api/safety/zones` | — |
| `AddZone` | `POST /api/safety/zones` | — |
| `RemoveZone` | `DELETE /api/safety/zones/<id>` | — |
| `GetZone` | _(no direct equivalent)_ | REST does not expose single-zone GET |

---

## Code Generation for Other Languages

### C++

```bash
protoc -I src/rws_tracking/api \
    --cpp_out=. \
    --grpc_out=. \
    --plugin=protoc-gen-grpc=$(which grpc_cpp_plugin) \
    src/rws_tracking/api/tracking.proto
```

### Go

```bash
protoc -I src/rws_tracking/api \
    --go_out=. \
    --go-grpc_out=. \
    src/rws_tracking/api/tracking.proto
```

---

## Security

The server binds with `add_insecure_port` by default. For production
deployment over untrusted networks:

```python
# Server-side TLS
private_key = open("server.key", "rb").read()
certificate = open("server.crt", "rb").read()
credentials = grpc.ssl_server_credentials([(private_key, certificate)])
server.add_secure_port("0.0.0.0:50051", credentials)

# Client-side TLS
root_certs = open("ca.crt", "rb").read()
credentials = grpc.ssl_channel_credentials(root_certificates=root_certs)
channel = grpc.secure_channel("host:50051", credentials)
```

Additional hardening recommendations:
- Restrict port 50051 via firewall to trusted operator subnets only.
- Add gRPC interceptors for token-based authentication.
- Enable gRPC compression (`grpc.Compression.Gzip`) for video frame streams
  over bandwidth-constrained links.

---

## Troubleshooting

| Symptom | Likely Cause | Resolution |
|---|---|---|
| `ImportError: cannot import name 'tracking_pb2'` | Stubs not generated | Run `grpc_tools.protoc` command from Quick Start |
| `StatusCode.UNAVAILABLE` on fire control RPCs | Pipeline not running | Call `StartTracking` or `StartMission` first |
| `StatusCode.FAILED_PRECONDITION` on `ArmSystem` | Chain not in `SAFE` state | Call `SafeSystem` first, then re-arm |
| `StatusCode.INVALID_ARGUMENT` on `AddZone` | Out-of-range coordinates or radius | Check field constraints in `AddZone` section |
| `StatusCode.NOT_FOUND` on `StartMission` | Profile name does not exist | Check available profiles in `ProfileManager` |
| Stream terminates immediately | Frame buffer empty (no camera) | Ensure tracking is running with a valid camera source |
| Watchdog forces chain to SAFE | `OperatorHeartbeat` not called within 10 s | Send heartbeat at ≥ 0.1 Hz while armed |
