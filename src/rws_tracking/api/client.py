"""
Python Client for RWS Tracking API
===================================

Provides a Python client for controlling the tracking system remotely via the
REST API (port 5000).

Example::

    client = TrackingClient("http://192.168.1.100:5000")
    client.start_tracking(camera_source=0)
    status = client.get_status()
    client.set_gimbal_position(yaw_deg=10.0, pitch_deg=5.0)
    client.stop_tracking()

    # Context-manager usage
    with TrackingClient("http://192.168.1.100:5000", api_key="secret") as c:
        c.arm("op1")
        c.request_fire("op1")
        c.safe()
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterator

import requests

logger = logging.getLogger(__name__)


class TrackingClient:
    """
    Python client for RWS Tracking REST API.

    Parameters
    ----------
    base_url : str
        Base URL of the API server (e.g., "http://192.168.1.100:5000")
    timeout : float
        Request timeout in seconds (default: 5.0)
    api_key : str or None
        Optional bearer token.  When set, every request includes the header
        ``Authorization: Bearer <api_key>``.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 5.0,
        api_key: str | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._api_key = api_key

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        """Build common request headers."""
        h: dict[str, str] = {}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    def _request(
        self,
        method: str,
        endpoint: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an HTTP request to the API and return the JSON response dict.

        Parameters
        ----------
        method : str
            HTTP method: "GET", "POST", or "DELETE".
        endpoint : str
            API path, e.g. ``/api/fire/arm``.
        json : dict or None
            Request body (for POST/DELETE with a body).
        params : dict or None
            URL query parameters.
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._headers()
        try:
            if method == "GET":
                response = requests.get(
                    url, headers=headers, params=params, timeout=self.timeout
                )
            elif method == "POST":
                response = requests.post(
                    url, headers=headers, json=json, params=params, timeout=self.timeout
                )
            elif method == "DELETE":
                response = requests.delete(
                    url, headers=headers, json=json, params=params, timeout=self.timeout
                )
            else:
                raise ValueError(f"Unsupported method: {method}")

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error("Request failed: %s", e)
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "TrackingClient":
        """Support ``with TrackingClient(...) as c:`` usage."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """No-op exit — kept for symmetry with the gRPC client."""

    def __repr__(self) -> str:
        return f"TrackingClient(base_url={self.base_url!r})"

    # ------------------------------------------------------------------
    # Infrastructure / basic control
    # ------------------------------------------------------------------

    def health_check(self) -> dict[str, Any]:
        """Check if the API server is running.

        Returns
        -------
        dict
            ``{"status": "ok"}`` on success.
        """
        return self._request("GET", "/api/health")

    def start_tracking(self, camera_source: int | str = 0) -> dict[str, Any]:
        """Start tracking.

        Parameters
        ----------
        camera_source : int or str
            Camera device index (0 for the default camera) or a video file path.

        Returns
        -------
        dict
            Response with ``success`` flag.
        """
        return self._request("POST", "/api/start", {"camera_source": camera_source})

    def stop_tracking(self) -> dict[str, Any]:
        """Stop tracking.

        Returns
        -------
        dict
            Response with ``success`` flag.
        """
        return self._request("POST", "/api/stop")

    def get_status(self) -> dict[str, Any]:
        """Get current tracking status.

        Returns
        -------
        dict
            Status including ``running``, ``frame_count``, ``fps``, and
            ``gimbal`` sub-dict with ``yaw_deg`` / ``pitch_deg``.
        """
        return self._request("GET", "/api/status")

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
            Response with ``success`` flag.
        """
        return self._request(
            "POST", "/api/gimbal/position", {"yaw_deg": yaw_deg, "pitch_deg": pitch_deg}
        )

    def set_gimbal_rate(
        self, yaw_rate_dps: float, pitch_rate_dps: float
    ) -> dict[str, Any]:
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
            Response with ``success`` flag.
        """
        return self._request(
            "POST",
            "/api/gimbal/rate",
            {"yaw_rate_dps": yaw_rate_dps, "pitch_rate_dps": pitch_rate_dps},
        )

    def get_telemetry(self) -> dict[str, Any]:
        """Get telemetry metrics.

        Returns
        -------
        dict
            Telemetry data including tracking metrics.
        """
        return self._request("GET", "/api/telemetry")

    def update_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Update runtime configuration (hot-reload; no restart needed for PID/selector).

        Parameters
        ----------
        config : dict
            Configuration dictionary with keys to update.

        Returns
        -------
        dict
            Response with ``success`` flag.
        """
        return self._request("POST", "/api/config", config)

    # ------------------------------------------------------------------
    # SSE event stream
    # ------------------------------------------------------------------

    def stream_events(self) -> Iterator[dict[str, Any]]:
        """Stream real-time server-sent events from ``GET /api/events``.

        Parses ``data:`` lines as JSON and yields each event dict.  The
        generator runs until the connection is closed or a network error
        occurs.

        Yields
        ------
        dict
            Each parsed SSE event payload.  An ``{"error": ...}`` dict is
            yielded on parse failure and iteration continues.
        """
        url = f"{self.base_url}/api/events"
        headers = {**self._headers(), "Accept": "text/event-stream"}
        try:
            with requests.get(url, headers=headers, stream=True, timeout=None) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    if line.startswith("data:"):
                        raw = line[len("data:"):].strip()
                        try:
                            yield json.loads(raw)
                        except json.JSONDecodeError as exc:
                            yield {"error": f"json decode error: {exc}", "raw": raw}
        except requests.exceptions.RequestException as exc:
            logger.error("stream_events error: %s", exc)
            yield {"error": str(exc)}

    # ------------------------------------------------------------------
    # Fire control
    # ------------------------------------------------------------------

    def arm(self, operator_id: str) -> dict[str, Any]:
        """Arm the shooting chain (SAFE -> ARMED).

        Parameters
        ----------
        operator_id : str
            Identifier of the operator performing the arm action.

        Returns
        -------
        dict
            Fire chain state after the action.
        """
        return self._request("POST", "/api/fire/arm", {"operator_id": operator_id})

    def safe(self, operator_id: str = "operator") -> dict[str, Any]:
        """Return the shooting chain to SAFE state.

        Parameters
        ----------
        operator_id : str
            Optional reason / operator ID passed as ``reason`` body field.

        Returns
        -------
        dict
            Fire chain state after the action.
        """
        return self._request("POST", "/api/fire/safe", {"reason": operator_id})

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
        return self._request(
            "POST", "/api/fire/request", {"operator_id": operator_id}
        )

    def get_fire_status(self) -> dict[str, Any]:
        """Get the current fire chain state.

        Returns
        -------
        dict
            ``{"state": str, "can_fire": bool, "operator_id": str}``.
        """
        return self._request("GET", "/api/fire/status")

    def send_heartbeat(self, operator_id: str) -> dict[str, Any]:
        """Send an operator heartbeat to prevent watchdog timeout.

        The OperatorWatchdog forces the chain to SAFE if no heartbeat is
        received within 10 seconds.

        Parameters
        ----------
        operator_id : str
            Identifier of the active operator.

        Returns
        -------
        dict
            ``{"ok": true, "operator_id": str}``.
        """
        return self._request(
            "POST", "/api/fire/heartbeat", {"operator_id": operator_id}
        )

    def get_arm_pending(self) -> dict[str, Any]:
        """Poll two-man rule arm-pending status.

        Returns
        -------
        dict
            ``{"pending": bool}`` with extra fields when a request is pending.
        """
        return self._request("GET", "/api/fire/arm/pending")

    def confirm_arm(self, operator_id: str) -> dict[str, Any]:
        """Second-operator confirmation for the two-man arming rule.

        Parameters
        ----------
        operator_id : str
            Identifier of the confirming operator (must differ from initiator).

        Returns
        -------
        dict
            Fire chain state after the confirmation.
        """
        return self._request(
            "POST", "/api/fire/arm/confirm", {"operator_id": operator_id}
        )

    def get_roe(self) -> dict[str, Any]:
        """List all registered Rules of Engagement profiles.

        Returns
        -------
        dict
            ``{"active_profile": str, "profiles": list}``.
        """
        return self._request("GET", "/api/fire/roe")

    def switch_roe_profile(self, name: str) -> dict[str, Any]:
        """Switch the active ROE profile by name.

        Parameters
        ----------
        name : str
            Name of the ROE profile to activate.

        Returns
        -------
        dict
            ``{"ok": bool, "active_profile": str, "fire_enabled": bool}``.
        """
        return self._request("POST", f"/api/fire/roe/{name}")

    # ------------------------------------------------------------------
    # Target designation
    # ------------------------------------------------------------------

    def designate_target(
        self, track_id: int, operator_id: str = ""
    ) -> dict[str, Any]:
        """Operator-designate a specific track for engagement (C2 override).

        Overrides the auto-selector.  The designation is cleared automatically
        when the track disappears from the scene.

        Parameters
        ----------
        track_id : int
            Track ID to designate.
        operator_id : str
            Optional operator identifier for logging.

        Returns
        -------
        dict
            ``{"ok": bool, "track_id": int}``.
        """
        return self._request(
            "POST",
            "/api/fire/designate",
            {"track_id": track_id, "operator_id": operator_id},
        )

    def clear_designation(self) -> dict[str, Any]:
        """Clear the operator designation and return to auto-selection.

        Returns
        -------
        dict
            ``{"ok": bool, "cleared_track_id": int | None}``.
        """
        return self._request("DELETE", "/api/fire/designate")

    def get_designation(self) -> dict[str, Any]:
        """Get the current operator designation status.

        Returns
        -------
        dict
            ``{"track_id": int | None, "designated": bool}``.
        """
        return self._request("GET", "/api/fire/designate")

    # ------------------------------------------------------------------
    # Mission management
    # ------------------------------------------------------------------

    def start_mission(
        self,
        profile: str = "default",
        camera_source: int = 0,
        force: bool = False,
    ) -> dict[str, Any]:
        """Start a new mission session.

        Runs a preflight check before starting.  Pass ``force=True`` to skip
        the preflight (for automated tests only).

        Parameters
        ----------
        profile : str
            Named mission profile to load (e.g. ``"urban_cqb"``).
        camera_source : int
            Camera device index.
        force : bool
            Skip preflight check when True.

        Returns
        -------
        dict
            ``{"ok": bool, "session_id": str, ...}`` on success.
        """
        params = {"force": "true"} if force else None
        return self._request(
            "POST",
            "/api/mission/start",
            {"profile": profile, "camera_source": camera_source},
            params=params,
        )

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
            "report_path": str | None, "report_url": str | None}``.
        """
        return self._request("POST", "/api/mission/end", {"reason": reason})

    def get_mission_status(self) -> dict[str, Any]:
        """Get the current mission state.

        Returns
        -------
        dict
            Mission state including ``active``, ``profile``, ``duration_s``,
            ``targets_engaged``, ``shots_fired``, and ``fire_chain_state``.
        """
        return self._request("GET", "/api/mission/status")

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    def get_safety_status(self) -> dict[str, Any]:
        """Get safety interlock status from the SafetyManager.

        Returns
        -------
        dict
            ``{"fire_authorized": bool, "blocked_reason": str, ...}``.
        """
        return self._request("GET", "/api/safety/status")

    def set_operator_auth(self, authorized: bool) -> dict[str, Any]:
        """Set operator authorization flag on the safety interlock.

        Parameters
        ----------
        authorized : bool
            True to grant authorization, False to revoke it.

        Returns
        -------
        dict
            Response with ``success`` flag.
        """
        return self._request(
            "POST", "/api/safety/operator-auth", {"authorized": authorized}
        )

    def emergency_stop(self, activate: bool) -> dict[str, Any]:
        """Activate or release the hardware emergency stop.

        Parameters
        ----------
        activate : bool
            True to engage the e-stop, False to release it.

        Returns
        -------
        dict
            Response with ``success`` and ``emergency_stop_active`` fields.
        """
        return self._request(
            "POST", "/api/safety/emergency-stop", {"activate": activate}
        )

    def list_zones(self) -> dict[str, Any]:
        """List all active no-fire zones.

        Returns
        -------
        dict
            List of zone dicts under the ``zones`` key (or a raw list for
            backward compatibility with the server response).
        """
        return self._request("GET", "/api/safety/zones")

    def add_zone(
        self,
        zone_id: str,
        center_yaw_deg: float,
        center_pitch_deg: float,
        radius_deg: float,
        zone_type: str = "no_fire",
    ) -> dict[str, Any]:
        """Add a new no-fire zone.

        Changes take effect on the very next pipeline step.

        Parameters
        ----------
        zone_id : str
            Unique identifier for the zone (e.g. ``"nfz_hospital"``).
        center_yaw_deg : float
            Zone centre yaw angle in degrees (range: -180 to 180).
        center_pitch_deg : float
            Zone centre pitch angle in degrees (range: -90 to 90).
        radius_deg : float
            Exclusion radius in degrees (must be positive and <= 180).
        zone_type : str
            Zone type string, default ``"no_fire"``.

        Returns
        -------
        dict
            ``{"ok": bool, "zone_id": str}``.
        """
        return self._request(
            "POST",
            "/api/safety/zones",
            {
                "zone_id": zone_id,
                "center_yaw_deg": center_yaw_deg,
                "center_pitch_deg": center_pitch_deg,
                "radius_deg": radius_deg,
                "zone_type": zone_type,
            },
        )

    def remove_zone(self, zone_id: str) -> dict[str, Any]:
        """Remove a no-fire zone by its ID.

        Parameters
        ----------
        zone_id : str
            Zone identifier to remove.

        Returns
        -------
        dict
            ``{"ok": bool, "zone_id": str}`` or error dict if not found.
        """
        return self._request("DELETE", f"/api/safety/zones/{zone_id}")

    # ------------------------------------------------------------------
    # Threats & health
    # ------------------------------------------------------------------

    def get_threats(self) -> dict[str, Any]:
        """Get the current threat assessment list from the ThreatAssessor.

        Returns
        -------
        dict
            ``{"threats": list, "pipeline_active": bool}`` where each threat
            entry contains ``track_id``, ``threat_score``, ``priority_rank``, etc.
        """
        return self._request("GET", "/api/threats")

    def get_health(self) -> dict[str, Any]:
        """Get per-subsystem health monitor status.

        Returns
        -------
        dict
            ``{"overall": str, "subsystems": dict}``.
        """
        return self._request("GET", "/api/health/subsystems")

    def run_selftest(self) -> dict[str, Any]:
        """Run the pre-mission self-test on all subsystems.

        Returns
        -------
        dict
            Self-test result with ``go`` flag and per-check statuses.
        """
        return self._request("GET", "/api/selftest")

    # ------------------------------------------------------------------
    # Replay / After-Action Review
    # ------------------------------------------------------------------

    def list_sessions(self) -> dict[str, Any]:
        """List all saved telemetry session files.

        Returns
        -------
        dict
            List of session file descriptors.
        """
        return self._request("GET", "/api/replay/sessions")

    def get_session_summary(self, filename: str) -> dict[str, Any]:
        """Get a lightweight summary for a session file without all raw events.

        Parameters
        ----------
        filename : str
            Bare filename (e.g. ``"telemetry.jsonl"``), not a full path.

        Returns
        -------
        dict
            Event-count-by-type and duration statistics.
        """
        return self._request("GET", f"/api/replay/sessions/{filename}/summary")
