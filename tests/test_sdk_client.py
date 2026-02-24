"""Unit tests for TrackingClient (REST SDK).

Uses ``unittest.mock.patch`` to intercept ``requests.get``, ``requests.post``,
and ``requests.delete`` so no live server is required.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from rws_tracking.api.client import TrackingClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(payload: Any, status_code: int = 200) -> MagicMock:
    """Build a fake requests.Response that returns *payload* as JSON."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TrackingClient:
    """A TrackingClient pointed at a fake server (no real network)."""
    return TrackingClient("http://localhost:5000")


@pytest.fixture
def client_with_key() -> TrackingClient:
    """A TrackingClient with an API key."""
    return TrackingClient("http://localhost:5000", api_key="supersecret")


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------


class TestInfrastructure:
    def test_repr(self, client: TrackingClient) -> None:
        assert "localhost:5000" in repr(client)

    def test_context_manager(self) -> None:
        with TrackingClient("http://localhost:5000") as c:
            assert c.base_url == "http://localhost:5000"

    def test_api_key_header_injected(self, client_with_key: TrackingClient) -> None:
        """Verify Authorization header is present when api_key is set."""
        payload = {"status": "ok"}
        with patch("requests.get", return_value=_mock_response(payload)) as mock_get:
            client_with_key.health_check()
            _args, kwargs = mock_get.call_args
            headers = kwargs.get("headers", {})
            assert headers.get("Authorization") == "Bearer supersecret"

    def test_no_api_key_header_absent(self, client: TrackingClient) -> None:
        """When no api_key is set, the Authorization header must not be present."""
        payload = {"status": "ok"}
        with patch("requests.get", return_value=_mock_response(payload)) as mock_get:
            client.health_check()
            _args, kwargs = mock_get.call_args
            headers = kwargs.get("headers", {})
            assert "Authorization" not in headers

    def test_health_check(self, client: TrackingClient) -> None:
        with patch("requests.get", return_value=_mock_response({"status": "ok"})):
            result = client.health_check()
        assert result["status"] == "ok"

    def test_get_status(self, client: TrackingClient) -> None:
        payload = {"running": True, "fps": 29.9}
        with patch("requests.get", return_value=_mock_response(payload)):
            result = client.get_status()
        assert result["running"] is True

    def test_get_telemetry(self, client: TrackingClient) -> None:
        payload = {"metrics": {"fps": 30.0}}
        with patch("requests.get", return_value=_mock_response(payload)):
            result = client.get_telemetry()
        assert "metrics" in result

    def test_update_config_posts_json(self, client: TrackingClient) -> None:
        with patch("requests.post", return_value=_mock_response({"success": True})) as mock_post:
            client.update_config({"pid": {"kp": 1.0}})
            _args, kwargs = mock_post.call_args
            assert kwargs["json"]["pid"]["kp"] == 1.0


# ---------------------------------------------------------------------------
# DELETE method routing
# ---------------------------------------------------------------------------


class TestDeleteRouting:
    def test_delete_request_uses_requests_delete(self, client: TrackingClient) -> None:
        """_request('DELETE', ...) must call requests.delete, not requests.post."""
        with patch("requests.delete", return_value=_mock_response({"ok": True})) as mock_del:
            client.remove_zone("nfz_01")
            assert mock_del.called
            called_url = mock_del.call_args[0][0]
            assert "/api/safety/zones/nfz_01" in called_url

    def test_clear_designation_uses_delete(self, client: TrackingClient) -> None:
        with patch("requests.delete", return_value=_mock_response({"ok": True})) as mock_del:
            client.clear_designation()
            assert mock_del.called
            called_url = mock_del.call_args[0][0]
            assert "/api/fire/designate" in called_url


# ---------------------------------------------------------------------------
# Fire control cycle
# ---------------------------------------------------------------------------


class TestFireControl:
    def test_arm(self, client: TrackingClient) -> None:
        payload = {"state": "ARMED", "operator_id": "op1"}
        with patch("requests.post", return_value=_mock_response(payload)) as mock_post:
            result = client.arm("op1")
            _args, kwargs = mock_post.call_args
            assert kwargs["json"]["operator_id"] == "op1"
        assert result["state"] == "ARMED"

    def test_safe(self, client: TrackingClient) -> None:
        payload = {"state": "SAFE"}
        with patch("requests.post", return_value=_mock_response(payload)):
            result = client.safe()
        assert result["state"] == "SAFE"

    def test_request_fire(self, client: TrackingClient) -> None:
        payload = {"state": "FIRE_REQUESTED", "can_fire": True}
        with patch("requests.post", return_value=_mock_response(payload)) as mock_post:
            result = client.request_fire("op1")
            _args, kwargs = mock_post.call_args
            assert kwargs["json"]["operator_id"] == "op1"
        assert result["can_fire"] is True

    def test_get_fire_status(self, client: TrackingClient) -> None:
        payload = {"state": "ARMED", "can_fire": False, "operator_id": "op1"}
        with patch("requests.get", return_value=_mock_response(payload)):
            result = client.get_fire_status()
        assert result["state"] == "ARMED"

    def test_send_heartbeat(self, client: TrackingClient) -> None:
        payload = {"ok": True, "operator_id": "op1"}
        with patch("requests.post", return_value=_mock_response(payload)) as mock_post:
            result = client.send_heartbeat("op1")
            _args, kwargs = mock_post.call_args
            assert kwargs["json"]["operator_id"] == "op1"
        assert result["ok"] is True

    def test_get_arm_pending(self, client: TrackingClient) -> None:
        payload = {"pending": False}
        with patch("requests.get", return_value=_mock_response(payload)):
            result = client.get_arm_pending()
        assert result["pending"] is False

    def test_confirm_arm(self, client: TrackingClient) -> None:
        payload = {"chain_state": "ARMED", "status": "armed"}
        with patch("requests.post", return_value=_mock_response(payload)) as mock_post:
            result = client.confirm_arm("op2")
            _args, kwargs = mock_post.call_args
            assert kwargs["json"]["operator_id"] == "op2"
        assert "chain_state" in result or "status" in result

    def test_get_roe(self, client: TrackingClient) -> None:
        payload = {"active_profile": "training", "profiles": []}
        with patch("requests.get", return_value=_mock_response(payload)):
            result = client.get_roe()
        assert result["active_profile"] == "training"

    def test_switch_roe_profile(self, client: TrackingClient) -> None:
        payload = {"ok": True, "active_profile": "exercise"}
        with patch("requests.post", return_value=_mock_response(payload)) as mock_post:
            result = client.switch_roe_profile("exercise")
            called_url = mock_post.call_args[0][0]
            assert "/api/fire/roe/exercise" in called_url
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# Target designation
# ---------------------------------------------------------------------------


class TestDesignation:
    def test_designate_target(self, client: TrackingClient) -> None:
        payload = {"ok": True, "track_id": 5}
        with patch("requests.post", return_value=_mock_response(payload)) as mock_post:
            result = client.designate_target(5, "op1")
            _args, kwargs = mock_post.call_args
            assert kwargs["json"]["track_id"] == 5
            assert kwargs["json"]["operator_id"] == "op1"
        assert result["track_id"] == 5

    def test_clear_designation(self, client: TrackingClient) -> None:
        payload = {"ok": True, "cleared_track_id": 5}
        with patch("requests.delete", return_value=_mock_response(payload)):
            result = client.clear_designation()
        assert result["ok"] is True
        assert result["cleared_track_id"] == 5

    def test_get_designation_none(self, client: TrackingClient) -> None:
        payload = {"track_id": None, "designated": False}
        with patch("requests.get", return_value=_mock_response(payload)):
            result = client.get_designation()
        assert result["designated"] is False

    def test_get_designation_active(self, client: TrackingClient) -> None:
        payload = {"track_id": 7, "designated": True}
        with patch("requests.get", return_value=_mock_response(payload)):
            result = client.get_designation()
        assert result["track_id"] == 7


# ---------------------------------------------------------------------------
# Mission management
# ---------------------------------------------------------------------------


class TestMission:
    def test_start_mission(self, client: TrackingClient) -> None:
        payload = {
            "ok": True,
            "session_id": "session_123",
            "profile": "default",
            "camera_source": 0,
            "started_at": "2026-01-01T00:00:00+00:00",
        }
        with patch("requests.post", return_value=_mock_response(payload)) as mock_post:
            result = client.start_mission(profile="default", camera_source=0)
            _args, kwargs = mock_post.call_args
            assert kwargs["json"]["profile"] == "default"
        assert result["ok"] is True
        assert result["session_id"] == "session_123"

    def test_start_mission_force_param(self, client: TrackingClient) -> None:
        """force=True should pass ?force=true as a query parameter."""
        payload = {"ok": True, "session_id": "s"}
        with patch("requests.post", return_value=_mock_response(payload)) as mock_post:
            client.start_mission(force=True)
            _args, kwargs = mock_post.call_args
            assert kwargs.get("params", {}).get("force") == "true"

    def test_end_mission(self, client: TrackingClient) -> None:
        payload = {
            "ok": True,
            "session_id": "session_123",
            "elapsed_s": 120.5,
            "report_path": None,
            "report_url": None,
        }
        with patch("requests.post", return_value=_mock_response(payload)) as mock_post:
            result = client.end_mission("mission complete")
            _args, kwargs = mock_post.call_args
            assert kwargs["json"]["reason"] == "mission complete"
        assert result["ok"] is True

    def test_get_mission_status(self, client: TrackingClient) -> None:
        payload = {"active": True, "profile": "default", "duration_s": 60.0}
        with patch("requests.get", return_value=_mock_response(payload)):
            result = client.get_mission_status()
        assert result["active"] is True


# ---------------------------------------------------------------------------
# No-fire zones (NFZ)
# ---------------------------------------------------------------------------


class TestNFZ:
    def test_list_zones(self, client: TrackingClient) -> None:
        payload = [
            {
                "zone_id": "nfz_01",
                "center_yaw_deg": 45.0,
                "center_pitch_deg": 0.0,
                "radius_deg": 10.0,
                "zone_type": "no_fire",
            }
        ]
        with patch("requests.get", return_value=_mock_response(payload)):
            result = client.list_zones()
        assert result == payload

    def test_add_zone(self, client: TrackingClient) -> None:
        payload = {"ok": True, "zone_id": "nfz_hospital"}
        with patch("requests.post", return_value=_mock_response(payload, 201)) as mock_post:
            result = client.add_zone(
                zone_id="nfz_hospital",
                center_yaw_deg=45.0,
                center_pitch_deg=5.0,
                radius_deg=20.0,
                zone_type="no_fire",
            )
            _args, kwargs = mock_post.call_args
            body = kwargs["json"]
            assert body["zone_id"] == "nfz_hospital"
            assert body["radius_deg"] == 20.0
        assert result["ok"] is True

    def test_remove_zone(self, client: TrackingClient) -> None:
        payload = {"ok": True, "zone_id": "nfz_01"}
        with patch("requests.delete", return_value=_mock_response(payload)) as mock_del:
            result = client.remove_zone("nfz_01")
            called_url = mock_del.call_args[0][0]
            assert called_url.endswith("/api/safety/zones/nfz_01")
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# Threats & health
# ---------------------------------------------------------------------------


class TestThreatsAndHealth:
    def test_get_threats(self, client: TrackingClient) -> None:
        payload = {"threats": [{"track_id": 1, "threat_score": 0.9}]}
        with patch("requests.get", return_value=_mock_response(payload)):
            result = client.get_threats()
        assert len(result["threats"]) == 1

    def test_get_health(self, client: TrackingClient) -> None:
        payload = {"overall": "ok", "subsystems": {}}
        with patch("requests.get", return_value=_mock_response(payload)):
            result = client.get_health()
        assert result["overall"] == "ok"

    def test_run_selftest(self, client: TrackingClient) -> None:
        payload = {"go": True, "checks": []}
        with patch("requests.get", return_value=_mock_response(payload)):
            result = client.run_selftest()
        assert result["go"] is True


# ---------------------------------------------------------------------------
# Replay / AAR
# ---------------------------------------------------------------------------


class TestReplay:
    def test_list_sessions(self, client: TrackingClient) -> None:
        payload = [{"filename": "telemetry.jsonl", "size_bytes": 1024}]
        with patch("requests.get", return_value=_mock_response(payload)):
            result = client.list_sessions()
        assert result[0]["filename"] == "telemetry.jsonl"

    def test_get_session_summary(self, client: TrackingClient) -> None:
        payload = {"event_counts": {"fired": 2}, "duration_s": 120.0}
        with patch("requests.get", return_value=_mock_response(payload)) as mock_get:
            result = client.get_session_summary("telemetry.jsonl")
            called_url = mock_get.call_args[0][0]
            assert "telemetry.jsonl/summary" in called_url
        assert "event_counts" in result


# ---------------------------------------------------------------------------
# SSE stream
# ---------------------------------------------------------------------------


class TestSSEStream:
    def test_stream_events_parses_data_lines(self, client: TrackingClient) -> None:
        """stream_events() should parse 'data: {...}' SSE lines as JSON dicts."""
        raw_lines = [
            "data: " + json.dumps({"type": "heartbeat", "ts": 1.0}),
            "",  # blank line (SSE separator — should be skipped)
            "data: " + json.dumps({"type": "fire_executed"}),
        ]

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_lines.return_value = iter(raw_lines)
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("requests.get", return_value=mock_resp):
            events = list(client.stream_events())

        assert len(events) == 2
        assert events[0]["type"] == "heartbeat"
        assert events[1]["type"] == "fire_executed"

    def test_stream_events_skips_non_data_lines(self, client: TrackingClient) -> None:
        """Lines not starting with 'data:' must be silently ignored."""
        raw_lines = [
            ": keep-alive comment",
            "event: heartbeat",
            "data: " + json.dumps({"type": "ok"}),
        ]

        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_lines.return_value = iter(raw_lines)
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("requests.get", return_value=mock_resp):
            events = list(client.stream_events())

        assert len(events) == 1
        assert events[0]["type"] == "ok"
