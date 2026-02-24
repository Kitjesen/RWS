"""仪表盘单元测试 — mock cv2。"""

from unittest.mock import patch

import numpy as np
import pytest

from src.rws_tracking.telemetry.logger import InMemoryTelemetryLogger


@pytest.fixture
def logger_with_data():
    logger = InMemoryTelemetryLogger()
    for i in range(30):
        t = i * 0.033
        logger.log("control", t, {
            "yaw_error_deg": 5.0 - i * 0.15,
            "pitch_error_deg": 3.0 - i * 0.1,
            "yaw_cmd_dps": 20.0 - i * 0.5,
            "pitch_cmd_dps": 10.0 - i * 0.3,
            "state": 2.0 if i > 15 else 1.0,
        })
    return logger


class TestRealtimeDashboard:
    def test_init(self, logger_with_data):
        from src.rws_tracking.tools.dashboard import RealtimeDashboard
        d = RealtimeDashboard(logger_with_data)
        assert d._width == 800
        assert d._height == 600

    def test_update_pulls_events(self, logger_with_data):
        from src.rws_tracking.tools.dashboard import RealtimeDashboard
        d = RealtimeDashboard(logger_with_data)
        d.update(1.0)
        assert len(d._history) > 0

    def test_render_returns_image(self, logger_with_data):
        from src.rws_tracking.tools.dashboard import RealtimeDashboard
        d = RealtimeDashboard(logger_with_data)
        d.update(1.0)
        img = d.render()
        assert isinstance(img, np.ndarray)
        assert img.shape == (600, 800, 3)

    def test_render_empty(self):
        logger = InMemoryTelemetryLogger()
        from src.rws_tracking.tools.dashboard import RealtimeDashboard
        d = RealtimeDashboard(logger)
        img = d.render()
        assert img.shape == (600, 800, 3)

    def test_custom_size(self, logger_with_data):
        from src.rws_tracking.tools.dashboard import RealtimeDashboard
        d = RealtimeDashboard(logger_with_data, width=400, height=300)
        img = d.render()
        assert img.shape == (300, 400, 3)

    @patch("cv2.imshow")
    def test_show(self, mock_imshow, logger_with_data):
        from src.rws_tracking.tools.dashboard import RealtimeDashboard
        d = RealtimeDashboard(logger_with_data)
        d.update(1.0)
        d.show("test")
        mock_imshow.assert_called_once()

    def test_state_machine_visualization(self, logger_with_data):
        from src.rws_tracking.tools.dashboard import RealtimeDashboard
        d = RealtimeDashboard(logger_with_data)
        d.update(1.0)
        canvas = np.zeros((600, 800, 3), dtype=np.uint8)
        d._draw_state_machine(canvas, 0, 300, 400, 300)
        # Should not crash

    def test_metrics_visualization(self, logger_with_data):
        from src.rws_tracking.tools.dashboard import RealtimeDashboard
        d = RealtimeDashboard(logger_with_data)
        d.update(1.0)
        canvas = np.zeros((600, 800, 3), dtype=np.uint8)
        d._draw_metrics(canvas, 400, 300, 400, 300)

    def test_error_plot_few_events(self):
        logger = InMemoryTelemetryLogger()
        logger.log("control", 0.0, {"yaw_error_deg": 1.0, "pitch_error_deg": 0.5, "state": 1.0})
        from src.rws_tracking.tools.dashboard import RealtimeDashboard
        d = RealtimeDashboard(logger)
        d.update(0.0)
        canvas = np.zeros((600, 800, 3), dtype=np.uint8)
        d._draw_error_plot(canvas, 0, 0, 400, 300)

    def test_command_plot_few_events(self):
        logger = InMemoryTelemetryLogger()
        logger.log("control", 0.0, {"yaw_cmd_dps": 10.0, "pitch_cmd_dps": 5.0, "state": 1.0})
        from src.rws_tracking.tools.dashboard import RealtimeDashboard
        d = RealtimeDashboard(logger)
        d.update(0.0)
        canvas = np.zeros((600, 800, 3), dtype=np.uint8)
        d._draw_command_plot(canvas, 400, 0, 400, 300)
