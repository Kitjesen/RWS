"""API客户端单元测试。"""

from unittest.mock import MagicMock, patch

import pytest


class TestTrackingClient:
    @pytest.fixture
    def client(self):
        from src.rws_tracking.api.client import TrackingClient
        c = TrackingClient("http://localhost:5000")
        return c

    @patch("requests.get")
    def test_get_status(self, mock_get, client):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"running": False, "frame_count": 0}),
        )
        status = client.get_status()
        assert "running" in status

    @patch("requests.post")
    def test_start_tracking(self, mock_post, client):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"success": True}),
        )
        result = client.start_tracking()
        assert result["success"]

    @patch("requests.post")
    def test_stop_tracking(self, mock_post, client):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"success": True}),
        )
        result = client.stop_tracking()
        assert result["success"]

    @patch("requests.post")
    def test_update_config(self, mock_post, client):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"success": True}),
        )
        result = client.update_config({"pid": {"yaw": {"kp": 8.0}}})
        assert result["success"]

    @patch("requests.get")
    def test_connection_error(self, mock_get, client):
        import requests
        mock_get.side_effect = requests.ConnectionError("refused")
        result = client.get_status()
        assert not result["success"]
