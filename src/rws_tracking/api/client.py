"""
Python Client for RWS Tracking API
===================================

Provides a simple Python client for controlling the tracking system remotely.

Example:
    client = TrackingClient("http://192.168.1.100:5000")
    client.start_tracking(camera_source=0)
    status = client.get_status()
    client.set_gimbal_position(yaw_deg=10.0, pitch_deg=5.0)
    client.stop_tracking()
"""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)


class TrackingClient:
    """
    Python client for RWS Tracking API.

    Parameters
    ----------
    base_url : str
        Base URL of the API server (e.g., "http://192.168.1.100:5000")
    timeout : float
        Request timeout in seconds (default: 5.0)
    """

    def __init__(self, base_url: str, timeout: float = 5.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(
        self, method: str, endpoint: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make HTTP request to API."""
        url = f"{self.base_url}{endpoint}"
        try:
            if method == "GET":
                response = requests.get(url, timeout=self.timeout)
            elif method == "POST":
                response = requests.post(url, json=json, timeout=self.timeout)
            else:
                raise ValueError(f"Unsupported method: {method}")

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            return {"success": False, "error": str(e)}

    def health_check(self) -> dict[str, Any]:
        """Check if API server is running."""
        return self._request("GET", "/api/health")

    def start_tracking(self, camera_source: int | str = 0) -> dict[str, Any]:
        """
        Start tracking.

        Parameters
        ----------
        camera_source : int or str
            Camera source (0 for default camera, or video file path)

        Returns
        -------
        dict
            Response with success status
        """
        return self._request("POST", "/api/start", {"camera_source": camera_source})

    def stop_tracking(self) -> dict[str, Any]:
        """Stop tracking."""
        return self._request("POST", "/api/stop")

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
        return self._request("GET", "/api/status")

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
        return self._request(
            "POST", "/api/gimbal/position", {"yaw_deg": yaw_deg, "pitch_deg": pitch_deg}
        )

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
        return self._request(
            "POST",
            "/api/gimbal/rate",
            {"yaw_rate_dps": yaw_rate_dps, "pitch_rate_dps": pitch_rate_dps},
        )

    def get_telemetry(self) -> dict[str, Any]:
        """
        Get telemetry metrics.

        Returns
        -------
        dict
            Telemetry data including tracking metrics
        """
        return self._request("GET", "/api/telemetry")

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
        return self._request("POST", "/api/config", config)
