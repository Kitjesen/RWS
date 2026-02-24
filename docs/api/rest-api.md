# RWS REST API Reference

This document describes every HTTP endpoint exposed by the RWS REST server
(default: `http://0.0.0.0:5000`).

Start the server with:

```bash
python scripts/api/run_rest_server.py
```

---

## Authentication

When the environment variable `RWS_API_KEY` is set, the server enforces Bearer
token authentication on all requests.

**Header format:**

```
Authorization: Bearer <token>
```

**Exempt paths** (always accessible without a token, regardless of
`RWS_API_KEY`):

| Path | Reason |
|---|---|
| `GET /api/health` | Monitoring / liveness probe |
| `GET /api/events` | SSE stream — long-lived connection |
| `GET /metrics` | Prometheus scrape |
| `GET /api/video/*` | MJPEG streaming |

All other paths return `401 Unauthorized` if the token is missing or incorrect.

---

## Rate Limiting

Fire-control endpoints (`/api/fire/*`) are rate-limited to **30 requests per
minute per client IP address** using a token-bucket algorithm.

When the limit is exceeded the server returns:

```
HTTP 429 Too Many Requests
{"error": "Rate limit exceeded"}
```

All other endpoint groups are not rate-limited at the server level.

---

## Common Response Conventions

Most mutation endpoints return a JSON body with a `success` (bool) or `ok`
(bool) field.

**Success:**

```json
{"success": true, "message": "..."}
```

**Error:**

```json
{"success": false, "error": "Human-readable description"}
```

Standard HTTP error codes used throughout:

| Code | Meaning |
|---|---|
| `400` | Missing or invalid request body field |
| `401` | Authentication required (Bearer token missing or wrong) |
| `403` | Action not permitted in current state |
| `404` | Resource not found |
| `409` | Conflict — precondition not met (e.g., already running) |
| `424` | Failed Dependency — self-test check(s) failed |
| `429` | Rate limit exceeded |
| `500` | Unexpected server-side error |
| `501` | Not Implemented |
| `503` | Component not available (pipeline not running, etc.) |

---

## Core Endpoints

### GET /api/health

Liveness probe. Always returns `200` if the server process is alive.
Authentication-exempt.

**Response:**

```json
{
  "status": "ok",
  "service": "rws-tracking"
}
```

---

### GET /api/status

Return current pipeline status, gimbal position, and rolling telemetry metrics.

**Response (pipeline not running):**

```json
{
  "running": false,
  "frame_count": 0,
  "error_count": 0,
  "last_error": null,
  "fps": 0.0
}
```

**Response (pipeline running):**

```json
{
  "running": true,
  "frame_count": 4210,
  "error_count": 0,
  "last_error": null,
  "fps": 29.8,
  "state": "LOCK",
  "yaw_deg": 12.4,
  "pitch_deg": -3.1,
  "yaw_error_deg": 0.05,
  "pitch_error_deg": -0.02,
  "lock_rate": 0.87,
  "avg_abs_error_deg": 0.34,
  "switches_per_min": 1.2,
  "gimbal": {
    "yaw_deg": 12.4,
    "pitch_deg": -3.1,
    "yaw_rate_dps": 0.8,
    "pitch_rate_dps": -0.3
  }
}
```

| Field | Type | Description |
|---|---|---|
| `running` | bool | Whether the pipeline thread is active |
| `frame_count` | int | Cumulative frames processed |
| `error_count` | int | Cumulative frame processing errors |
| `last_error` | string\|null | Last error message |
| `fps` | float | Estimated current frame rate |
| `state` | string | Track state machine state: `SEARCH`, `TRACK`, `LOCK`, or `LOST` |
| `yaw_deg` | float | Current gimbal yaw position (degrees) |
| `pitch_deg` | float | Current gimbal pitch position (degrees) |
| `yaw_error_deg` | float | Current yaw tracking error (degrees) |
| `pitch_error_deg` | float | Current pitch tracking error (degrees) |
| `lock_rate` | float | Fraction of recent frames in LOCK state |
| `avg_abs_error_deg` | float | Rolling average absolute tracking error (degrees) |
| `switches_per_min` | float | Target-switch rate |
| `gimbal` | object | Gimbal feedback (position + rate), duplicated for chart consumers |

---

### POST /api/tracking/start

Start the tracking pipeline. Alias: `POST /api/start`.

**Request body (JSON):**

```json
{
  "camera_source": 0
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `camera_source` | int or string | `0` | Camera device index or video file path |

**Response (success):**

```json
{"success": true, "message": "Tracking started"}
```

**Response (already running — 200):**

```json
{"success": false, "error": "Already running"}
```

**Errors:** `500` if camera cannot be opened.

---

### POST /api/tracking/stop

Stop the tracking pipeline. Alias: `POST /api/stop`.

**Response (success):**

```json
{"success": true, "message": "Tracking stopped"}
```

**Response (not running — 200):**

```json
{"success": false, "error": "Not running"}
```

---

### GET /api/threats

Return the current threat assessment list produced by `ThreatAssessor`.

**Response:**

```json
{
  "pipeline_active": true,
  "threats": [
    {
      "track_id": 5,
      "priority_rank": 1,
      "threat_score": 0.8721,
      "distance_score": 0.7400,
      "velocity_score": 0.3100,
      "class_score": 0.4000,
      "heading_score": 0.5000,
      "class_id": "person",
      "distance_m": 45.2
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `pipeline_active` | bool | Whether the pipeline is running |
| `threats[].track_id` | int | BoT-SORT track ID |
| `threats[].priority_rank` | int | 1 = highest priority |
| `threats[].threat_score` | float | Composite threat score [0, 1] |
| `threats[].distance_score` | float | Component: proximity contribution |
| `threats[].velocity_score` | float | Component: approach speed contribution |
| `threats[].class_score` | float | Component: target class contribution |
| `threats[].heading_score` | float | Component: heading-toward-camera contribution |
| `threats[].class_id` | string | YOLO class label (e.g. `"person"`) |
| `threats[].distance_m` | float | Fused range estimate (metres); `0.0` if unknown |

---

### GET /api/telemetry

Return a snapshot of rolling telemetry metrics from the pipeline.

**Response (pipeline running):**

```json
{
  "success": true,
  "metrics": {
    "lock_rate": 0.87,
    "avg_abs_error_deg": 0.34,
    "switches_per_min": 1.2
  }
}
```

**Response (pipeline not running — 200):**

```json
{"success": false, "error": "Pipeline not initialized"}
```

---

### GET /api/config

Return the current effective PID configuration loaded from `config.yaml`.

**Response:**

```json
{
  "pid": {
    "yaw":   {"kp": 5.0, "ki": 0.2, "kd": 0.1},
    "pitch": {"kp": 4.5, "ki": 0.1, "kd": 0.08}
  }
}
```

**Errors:** `503` if the config cannot be loaded.

---

### POST /api/config

Update live configuration. Certain sections are hot-applied to the running
pipeline without a restart; others are stored and require a restart.

**Hot-applied sections (no restart needed):**

| Key | Description |
|---|---|
| `pid.yaw` / `pid.pitch` | PID gains (`kp`, `ki`, `kd`) |
| `selector` | Target selector weights (`confidence`, `size`, `center_proximity`, `track_age`, `class_weight`) |
| `safety_zones` | Add or remove NFZ zones (see below) |

**Request body examples:**

```json
{
  "pid": {
    "yaw": {"kp": 6.0, "ki": 0.3},
    "pitch": {"kp": 5.0}
  }
}
```

```json
{
  "safety_zones": {
    "action": "add",
    "zone": {
      "zone_id": "nfz_east",
      "center_yaw_deg": 90.0,
      "center_pitch_deg": 0.0,
      "radius_deg": 15.0,
      "zone_type": "no_fire"
    }
  }
}
```

```json
{
  "safety_zones": {"action": "remove", "zone_id": "nfz_east"}
}
```

**Response:**

```json
{
  "success": true,
  "message": "Hot-applied: pid.yaw, pid.pitch",
  "hot_applied": ["pid.yaw", "pid.pitch"],
  "stored": []
}
```

**Errors:** `400` if no body is provided.

---

### POST /api/gimbal/position

Command the gimbal to an absolute angular position using an internal
proportional controller.

**Request body:**

```json
{"yaw_deg": 10.0, "pitch_deg": 5.0}
```

**Response:**

```json
{
  "success": true,
  "target":  {"yaw_deg": 10.0, "pitch_deg": 5.0},
  "current": {"yaw_deg": 9.8,  "pitch_deg": 4.9}
}
```

**Errors:** `400` missing fields; `503` pipeline not initialized.

---

### POST /api/gimbal/rate

Command the gimbal at an angular rate (velocity control, degrees per second).

**Request body:**

```json
{"yaw_rate_dps": 20.0, "pitch_rate_dps": 10.0}
```

**Response:**

```json
{
  "success": true,
  "command": {"yaw_rate_dps": 20.0, "pitch_rate_dps": 10.0}
}
```

**Errors:** `400` missing fields; `503` pipeline not initialized.

---

## Video

### GET /api/video/feed

MJPEG video stream of the annotated camera feed. Streams indefinitely;
disconnect to stop.

**Response MIME type:** `multipart/x-mixed-replace; boundary=frame`

Authentication-exempt.

**Usage in a browser:**

```html
<img src="http://host:5000/api/video/feed" />
```

**Errors:** `503` if video streaming is disabled in config.

---

### GET /api/video/snapshot

Return a single JPEG frame from the current annotated feed.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `quality` | int | (from config) | JPEG quality [1, 95] |

**Response MIME type:** `image/jpeg`

**Response headers:**

| Header | Value |
|---|---|
| `X-Timestamp` | Frame capture monotonic timestamp (float, seconds) |

Authentication-exempt.

**Errors:** `503` if no frame is available yet; `500` if JPEG encoding fails.

---

### GET /api/video/config

Return the current video stream configuration.

**Response:**

```json
{
  "enabled": true,
  "jpeg_quality": 85,
  "max_fps": 30,
  "scale_factor": 1.0,
  "annotate_detections": true,
  "annotate_tracks": true,
  "annotate_crosshair": true
}
```

---

## Fire Control

All `/api/fire/*` endpoints are subject to the 30 req/min per-IP rate limit.

### GET /api/fire/status

Return the current fire chain state.

**Response (chain configured):**

```json
{
  "state": "armed",
  "can_fire": false,
  "operator_id": "op1"
}
```

**Response (chain not configured):**

```json
{"state": "not_configured", "can_fire": false}
```

**State values:** `safe`, `armed`, `fire_authorized`, `fire_requested`,
`fired`, `cooldown`, `not_configured`.

---

### POST /api/fire/arm

Transition the fire chain from `SAFE` to `ARMED`.

**Request body:**

```json
{"operator_id": "op1"}
```

**Response (success):**

```json
{"state": "armed", "operator_id": "op1"}
```

**Errors:**

| Code | Condition |
|---|---|
| `400` | `operator_id` is missing or empty |
| `409` | Chain is not in `SAFE` state; cannot arm |
| `503` | `ShootingChain` not configured |

---

### POST /api/fire/safe

Return the fire chain to `SAFE` from any state.

**Request body (optional):**

```json
{"reason": "operator abort"}
```

**Response:**

```json
{"state": "safe"}
```

**Errors:** `503` if chain not configured.

---

### POST /api/fire/request

Submit a human fire request. Succeeds only when the chain is in
`FIRE_AUTHORIZED` state (safety interlock cleared and target locked).

**Request body:**

```json
{"operator_id": "op1"}
```

**Response (success):**

```json
{"state": "fire_requested", "can_fire": true}
```

**Errors:**

| Code | Condition |
|---|---|
| `400` | `operator_id` is missing |
| `403` | Chain is not in `FIRE_AUTHORIZED` state |
| `503` | Chain not configured |

---

### POST /api/fire/heartbeat

Refresh the operator deadman heartbeat. Must be called at least once every
10 seconds to prevent the `OperatorWatchdog` from forcing the chain to `SAFE`.

**Request body:**

```json
{"operator_id": "op1"}
```

**Response:**

```json
{"ok": true, "operator_id": "op1"}
```

**Errors:** `400` if `operator_id` is missing.

---

### GET /api/fire/report

Generate and download an HTML mission debrief report from the audit log.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `mission` | string | `"Mission Debrief"` | Report title shown in the HTML |

**Response MIME type:** `text/html`

**Response header:** `Content-Disposition: inline; filename=mission_report.html`

**Errors:** `503` if `AuditLogger` not configured.

---

### GET /api/fire/dwell

Return the engagement dwell timer status. While a target is held in `LOCK`
with fire authorization, a dwell timer counts toward `engagement_dwell_time_s`.
When the timer completes, `execute_fire()` is called automatically.

**Response:**

```json
{
  "active": true,
  "track_id": 5,
  "elapsed_s": 1.23,
  "total_s": 2.0,
  "fraction": 0.615
}
```

| Field | Type | Description |
|---|---|---|
| `active` | bool | `true` while dwell is counting |
| `track_id` | int\|null | Track being dwelled; `null` when inactive |
| `elapsed_s` | float | Elapsed dwell time (seconds) |
| `total_s` | float | Configured dwell duration (seconds) |
| `fraction` | float | `elapsed_s / total_s`, range [0.0, 1.0] |

**Response (pipeline not running):**

```json
{"active": false, "track_id": null, "elapsed_s": 0.0, "total_s": 0.0, "fraction": 0.0}
```

---

### POST /api/fire/designate

Operator-designate a specific track for engagement, overriding the
auto-selected target. The designation is cleared automatically when the track
disappears.

**Request body:**

```json
{"track_id": 3, "operator_id": "op1"}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `track_id` | int | Yes | BoT-SORT track ID to designate |
| `operator_id` | string | No | Operator identifier (for audit log) |

**Response:**

```json
{"ok": true, "track_id": 3}
```

**Errors:** `400` missing or non-integer `track_id`; `503` pipeline not running.

Emits SSE event `target_designated`.

---

### DELETE /api/fire/designate

Clear the operator designation and return to automatic target selection.

**Response:**

```json
{"ok": true, "cleared_track_id": 3}
```

`cleared_track_id` is `null` if no designation was active.

**Errors:** `503` pipeline not running.

Emits SSE event `target_designated` with `track_id: null`.

---

### GET /api/fire/designate

Return the current operator designation status.

**Response:**

```json
{"track_id": 3, "designated": true}
```

`track_id` is `null` and `designated` is `false` when no designation is active.

---

### POST /api/fire/iff/mark_friendly

Add a track ID to the operator IFF (Identification Friend or Foe) whitelist.
Whitelisted tracks are excluded from engagement.

**Request body:**

```json
{"track_id": 3}
```

**Response:**

```json
{"ok": true, "track_id": 3, "action": "marked_friendly"}
```

**Errors:** `400` missing or non-integer `track_id`; `503` `IFFChecker` not configured.

---

### POST /api/fire/iff/unmark_friendly

Remove a track ID from the IFF whitelist.

**Request body:**

```json
{"track_id": 3}
```

**Response:**

```json
{"ok": true, "track_id": 3, "action": "unmarked_friendly"}
```

**Errors:** `400` missing or non-integer `track_id`; `503` `IFFChecker` not configured.

---

### GET /api/fire/iff/status

Return all operator-designated friendly track IDs.

**Response:**

```json
{"friendly_track_ids": [3, 7]}
```

**Errors:** `503` if `IFFChecker` not configured.

---

### GET /api/fire/clips

List all saved fire-event video clip files.

**Response:**

```json
[
  {
    "filename": "fire_20240315_142301.mp4",
    "size_bytes": 2097152,
    "timestamp": 1710506581.0
  }
]
```

Results are sorted most-recent first. Returns an empty array if no clips
directory is configured or the directory does not exist.

---

### GET /api/fire/clips/{filename}

Download a fire-event clip file.

`filename` must be a bare filename with no directory separators or `..`
components.

**Response MIME type:** `application/octet-stream` (file download)

**Errors:**

| Code | Condition |
|---|---|
| `400` | Filename contains path traversal characters |
| `404` | Clip file not found |
| `503` | Clips directory not configured |

---

## Mission

### GET /api/mission/status

Return current mission state.

**Response (no active mission):**

```json
{
  "active": false,
  "profile": null,
  "started_at": null,
  "started_at_str": null,
  "camera_source": 0,
  "session_id": null,
  "targets_engaged": 0,
  "last_report_path": null,
  "elapsed_s": 0.0
}
```

**Response (mission active, pipeline running):**

```json
{
  "active": true,
  "profile": "urban_cqb",
  "started_at": 1710506581.3,
  "started_at_str": "2024-03-15T14:23:01.300000",
  "camera_source": 0,
  "session_id": "Alpha-1_20240315_142301",
  "targets_engaged": 2,
  "last_report_path": null,
  "elapsed_s": 47.3,
  "fire_chain_state": "armed",
  "lifecycle": {
    "total_seen": 5,
    "active": 2,
    "neutralized": 1,
    "by_state": {"DETECTED": 2, "ARCHIVED": 3}
  }
}
```

---

### POST /api/mission/start

Start a new mission session. Resets the lifecycle manager, forces the fire
chain to `SAFE`, then starts the tracking pipeline.

**Request body (all fields optional):**

```json
{
  "profile": "urban_cqb",
  "camera_source": 0,
  "mission_name": "Alpha-1"
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `profile` | string | none | Named mission profile to load from `profiles/` |
| `camera_source` | int or string | `0` | Camera device index or video file path |
| `mission_name` | string | auto-generated | Display name used in session ID and reports |

**Response:**

```json
{
  "ok": true,
  "session_id": "Alpha-1_20240315_142301",
  "profile": "urban_cqb",
  "camera_source": 0,
  "started_at": "2024-03-15T14:23:01.300000"
}
```

**Errors:**

| Code | Condition |
|---|---|
| `404` | Named profile not found |
| `409` | A mission is already active |
| `500` | Tracking pipeline failed to start |
| `503` | `tracking_api` not configured |

Emits SSE event `mission_started`.

---

### POST /api/mission/end

End the active mission. Forces the fire chain to `SAFE`, stops the pipeline,
and generates an HTML debrief report if any events were audited.

**Request body (optional):**

```json
{"reason": "mission complete"}
```

**Response:**

```json
{
  "ok": true,
  "session_id": "Alpha-1_20240315_142301",
  "elapsed_s": 312.5,
  "report_path": "logs/reports/Alpha-1_20240315_142301_report.html",
  "report_url": "/api/mission/report/Alpha-1_20240315_142301_report.html"
}
```

`report_path` and `report_url` are `null` if no audited events exist.

**Errors:** `409` if no mission is active.

Emits SSE event `mission_ended`.

---

### GET /api/mission/report/{filename}

Serve a generated HTML mission report from `logs/reports/`.

**Response MIME type:** `text/html`

**Errors:** `400` path traversal attempt; `404` report not found.

---

## Safety Zones

No-fire zones (NFZ) are circular exclusion zones in gimbal angle space. The
safety manager checks every pipeline step whether the current aim point falls
inside any active zone; if it does, fire is blocked.

Zone definitions are persisted to `logs/nfz_zones.json` and reloaded
automatically on server startup.

### GET /api/safety/zones

List all currently active no-fire zones.

**Response:**

```json
[
  {
    "zone_id": "nfz_hospital",
    "center_yaw_deg": 45.0,
    "center_pitch_deg": 5.0,
    "radius_deg": 20.0,
    "zone_type": "no_fire"
  }
]
```

Returns an empty array if no safety manager is configured or no zones exist.

---

### GET /api/safety/zones/{zone_id}

Retrieve a single zone by its ID.

**Response:** Same object shape as one element of the list above.

**Errors:** `404` zone not found; `503` safety manager not configured.

---

### POST /api/safety/zones

Add a new no-fire zone. Takes effect on the next pipeline step.
Persists to `logs/nfz_zones.json`.

**Request body:**

```json
{
  "zone_id": "nfz_hospital",
  "center_yaw_deg": 45.0,
  "center_pitch_deg": 5.0,
  "radius_deg": 20.0,
  "zone_type": "no_fire"
}
```

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `center_yaw_deg` | float | Yes | [-180, 180] | Zone centre yaw (degrees) |
| `center_pitch_deg` | float | Yes | [-90, 90] | Zone centre pitch (degrees) |
| `radius_deg` | float | Yes | (0, 180] | Exclusion radius (degrees) |
| `zone_id` | string | No | — | Unique identifier; auto-generated if omitted |
| `zone_type` | string | No | — | Default `"no_fire"` |

**Response `201 Created`:**

```json
{"ok": true, "zone_id": "nfz_hospital"}
```

**Errors:** `400` missing required field or out-of-range value; `503` safety
manager not configured.

Emits SSE event `nfz_added`.

---

### DELETE /api/safety/zones/{zone_id}

Remove a zone by ID. Takes effect on the next pipeline step.
Updates `logs/nfz_zones.json`.

**Response:**

```json
{"ok": true, "zone_id": "nfz_hospital"}
```

**Errors:** `404` zone not found; `503` safety manager not configured.

Emits SSE event `nfz_removed`.

---

## Health

### GET /api/health/subsystems

Return per-subsystem health status from the `HealthMonitor`.

**Response:**

```json
{
  "overall": "ok",
  "subsystems": {
    "pipeline":    {"status": "ok"},
    "detector":    {"status": "ok"},
    "tracker":     {"status": "degraded"},
    "controller":  {"status": "ok"},
    "driver":      {"status": "ok"}
  }
}
```

`overall` is `"ok"` when all subsystems are healthy, `"degraded"` when at least
one is degraded but none have failed, and `"failed"` when any subsystem has
failed. Returns `"unknown"` if the `HealthMonitor` is not available.

---

### GET /api/config/profiles

List available named mission profiles from the `profiles/` directory.

**Response:**

```json
{
  "profiles": ["default", "urban_cqb", "open_field"],
  "current": "default"
}
```

---

### POST /api/config/profile/{name}

Switch the active configuration profile.

**Response:**

```json
{"status": "ok", "profile": "urban_cqb"}
```

**Errors:** `404` profile not found.

---

## Self-Test

### GET /api/selftest

Run all pre-mission subsystem checks synchronously and return a go/no-go
verdict. Target latency is under 2 seconds. Returns `200` if all checks pass,
`424` if any check fails.

**Checks performed:**

| Name | What is verified |
|---|---|
| `pipeline_imports` | All critical modules can be imported |
| `shooting_chain` | `ShootingChain` is accessible and reports its current state |
| `audit_logger` | `AuditLogger` can write a record and verify the SHA-256 chain |
| `health_monitor` | `HealthMonitor` is accessible and accepts a heartbeat |
| `lifecycle_manager` | `TargetLifecycleManager` is accessible and returns a summary |
| `logs_dir_writable` | `logs/` directory exists and is writable |
| `config_valid` | Config module is importable |

**Response `200` (all pass):**

```json
{
  "go": true,
  "timestamp": 1710506581.3,
  "passed": 7,
  "failed": 0,
  "checks": [
    {
      "name": "pipeline_imports",
      "status": "pass",
      "message": "all critical imports OK",
      "elapsed_ms": 12.4
    }
  ]
}
```

**Response `424` (one or more fail):**

Same shape; `go` is `false`, failed entries have `"status": "fail"` and
`"message"` contains the exception text.

---

### GET /api/selftest/summary

Return the result of the most recent self-test run without re-running checks.

**Response:** Same shape as `GET /api/selftest`.

**Errors:** `404` if no self-test has been run yet in this server process.

---

## Metrics

### GET /metrics

Prometheus text format (exposition format 0.0.4). Compatible with Grafana and
any Prometheus scrape target. Authentication-exempt.

**Response MIME type:** `text/plain; version=0.0.4`

**Gauges exposed:**

| Metric name | Labels | Description |
|---|---|---|
| `rws_tracks_total` | — | Number of active tracks |
| `rws_threat_score` | `track_id` | Composite threat score per track |
| `rws_fire_chain_state` | — | Encoded fire chain state (see below) |
| `rws_shots_fired_total` | — | Cumulative shots fired this session |
| `rws_lifecycle_by_state` | `state` | Target count per lifecycle state |
| `rws_health_subsystem` | `name` | Per-subsystem health (see below) |
| `rws_operator_heartbeat_age_s` | — | Seconds since last operator heartbeat |
| `rws_pipeline_fps` | — | Estimated pipeline frames per second |
| `rws_gimbal_yaw_deg` | — | Current gimbal yaw position (degrees) |
| `rws_gimbal_pitch_deg` | — | Current gimbal pitch position (degrees) |
| `rws_yaw_error_deg` | — | Current yaw tracking error (degrees) |
| `rws_pitch_error_deg` | — | Current pitch tracking error (degrees) |

**`rws_fire_chain_state` encoding:**

| Value | State |
|---|---|
| `-1` | not configured |
| `0` | safe |
| `1` | armed |
| `2` | fire_authorized |
| `3` | fire_requested |
| `4` | fired |
| `5` | cooldown |

**`rws_health_subsystem` encoding:**

| Value | Status |
|---|---|
| `0` | unknown |
| `1` | ok |
| `2` | degraded |
| `3` | failed |

---

## Replay / After-Action Review

### GET /api/replay/sessions

List all telemetry session files (`*.jsonl`) in the `logs/` directory, sorted
by modification time (most recent first). Each entry includes a lightweight
summary of its contents.

**Response:**

```json
[
  {
    "filename": "telemetry.jsonl",
    "size_bytes": 102400,
    "modified_at": 1710506700.0,
    "event_count": 3421,
    "duration_s": 120.5,
    "start_ts": 1710506580.0,
    "end_ts": 1710506700.5,
    "counts_by_type": {"track": 3200, "fired": 3, "state_change": 218}
  }
]
```

Returns an empty array if the `logs/` directory does not exist.

---

### GET /api/replay/sessions/{filename}

Return events from a session file with optional filtering. `filename` must end
with `.jsonl` and must not contain path separators or `..`.

**Query parameters:**

| Parameter | Type | Default | Description |
|---|---|---|---|
| `event_type` | string (repeatable) | all types | Filter to one or more event types |
| `from_ts` | float | `0.0` | Exclude events before this Unix timestamp |
| `to_ts` | float | `+∞` | Exclude events after this Unix timestamp |
| `limit` | int | `5000` | Maximum events to return (hard cap: 50000) |

**Response:**

```json
{
  "filename": "telemetry.jsonl",
  "total_events": 3421,
  "returned_events": 1200,
  "events": [
    {"event_type": "fired", "timestamp": 1710506600.1, "data": {}},
    {"event_type": "track", "timestamp": 1710506600.2, "data": {}}
  ]
}
```

Events are returned in chronological order.

**Errors:** `400` invalid filename; `404` session not found.

---

### GET /api/replay/sessions/{filename}/summary

Return summary statistics for a session without fetching all event data.
Useful for populating session cards in the UI.

**Response:**

```json
{
  "filename": "telemetry.jsonl",
  "event_count": 3421,
  "duration_s": 120.5,
  "start_ts": 1710506580.0,
  "end_ts": 1710506700.5,
  "counts_by_type": {"track": 3200, "fired": 3}
}
```

**Errors:** `400` invalid filename; `404` session not found.

---

## Multi-Gimbal

### GET /api/multi/status

Returns the multi-gimbal pipeline status.

**Note:** `MultiGimbalPipeline` is implemented but not yet wired to the HTTP
server. This endpoint always returns `501 Not Implemented`.

**Response `501`:**

```json
{
  "available": false,
  "gimbals": 0,
  "message": "MultiGimbalPipeline is implemented but not yet wired to HTTP server.",
  "usage": "Instantiate MultiGimbalPipeline directly in scripts/. See pipeline/multi_gimbal_pipeline.py."
}
```

---

## Server-Sent Events

### GET /api/events

Long-lived Server-Sent Events stream. The connection remains open until the
client disconnects or the server shuts down. Authentication-exempt.

**Response MIME type:** `text/event-stream`

**Response headers set by server:**

| Header | Value |
|---|---|
| `Cache-Control` | `no-cache` |
| `X-Accel-Buffering` | `no` (disables nginx buffering) |
| `Connection` | `keep-alive` |

**Wire format (RFC 8895):**

```
event: fire_executed
data: {"track_id": 3, "timestamp": 1710506600.12}
id: 42

```

On connect the server immediately sends a `connected` event:

```
event: connected
data: {"message": "SSE stream open"}
id: 0

```

A `heartbeat` event is emitted every 15 seconds to keep the connection alive.

**JavaScript usage:**

```javascript
const es = new EventSource('/api/events');
es.addEventListener('fire_executed', e => {
    const payload = JSON.parse(e.data);
    console.log('fired at track', payload.track_id);
});
```

---

### SSE Event Reference

| Event type | Emitted when | Data fields |
|---|---|---|
| `connected` | Client connects to `/api/events` | `message` (string) |
| `heartbeat` | Every 15 seconds | `ts` (float — Unix time) |
| `fire_chain_state` | `ShootingChain` state transition | `state` (string), `operator_id` (string) |
| `fire_executed` | A round is fired | `track_id` (int), `timestamp` (float) |
| `threat_detected` | New track with high threat score | _(payload from pipeline)_ |
| `target_neutralized` | Target marked neutralised by lifecycle manager | _(payload from pipeline)_ |
| `target_designated` | Operator designates or clears a target | `track_id` (int\|null), `operator_id` (string) |
| `health_degraded` | Subsystem health drops to degraded or failed | _(payload from health monitor)_ |
| `safety_triggered` | Safety interlock blocks a fire command | _(payload from safety manager)_ |
| `operator_timeout` | Operator watchdog deadman timeout fires | _(payload from watchdog)_ |
| `mission_started` | `POST /api/mission/start` succeeds | `session_id` (string), `profile` (string\|null), `ts` (float) |
| `mission_ended` | `POST /api/mission/end` completes | `session_id` (string), `elapsed_s` (float), `report_path` (string\|null), `ts` (float) |
| `config_reloaded` | `config.yaml` file watcher detects a change | `hot_applied` (array of strings), `message` (string) |
| `nfz_added` | No-fire zone added via `POST /api/safety/zones` | `zone_id` (string), `center_yaw_deg` (float), `center_pitch_deg` (float), `radius_deg` (float) |
| `nfz_removed` | No-fire zone deleted via `DELETE /api/safety/zones/{id}` | `zone_id` (string) |

> Slow subscribers whose per-connection queue (256 events) fills up are silently
> dropped. Reconnect to re-subscribe.
