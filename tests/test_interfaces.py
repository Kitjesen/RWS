"""接口协议单元测试 — 验证各模块接口定义。"""

import pytest

from src.rws_tracking.control.interfaces import GimbalController
from src.rws_tracking.decision.interfaces import EngagementQueueProtocol, ThreatAssessorProtocol
from src.rws_tracking.hardware.interfaces import CompositeGimbalDriver, GimbalAxisDriver, GimbalDriver
from src.rws_tracking.perception.interfaces import Detector, TargetSelector, Tracker
from src.rws_tracking.telemetry.interfaces import TelemetryLogger


class TestProtocolsExist:
    """验证所有协议/接口类可以被导入。"""

    def test_gimbal_controller(self):
        assert GimbalController is not None

    def test_gimbal_driver(self):
        assert GimbalDriver is not None

    def test_gimbal_axis_driver(self):
        assert GimbalAxisDriver is not None

    def test_composite_gimbal_driver(self):
        assert CompositeGimbalDriver is not None

    def test_detector(self):
        assert Detector is not None

    def test_tracker(self):
        assert Tracker is not None

    def test_target_selector(self):
        assert TargetSelector is not None

    def test_telemetry_logger(self):
        assert TelemetryLogger is not None

    def test_threat_assessor(self):
        assert ThreatAssessorProtocol is not None

    def test_engagement_queue(self):
        assert EngagementQueueProtocol is not None


class TestGimbalControllerInterface:
    def test_has_compute_method(self):
        assert hasattr(GimbalController, "compute_command")

    def test_has_reset_method(self):
        assert hasattr(GimbalController, "reset")


class TestDetectorInterface:
    def test_has_detect_method(self):
        assert hasattr(Detector, "detect")


class TestTrackerInterface:
    def test_has_update_method(self):
        assert hasattr(Tracker, "update")


class TestTargetSelectorInterface:
    def test_has_select_method(self):
        assert hasattr(TargetSelector, "select")
