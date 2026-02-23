"""PID调参工具单元测试。"""

import pytest

from src.rws_tracking.algebra import CameraModel
from src.rws_tracking.config import GimbalControllerConfig, PIDConfig
from src.rws_tracking.tools.tuning import grid_search_pid


class TestGridSearchPID:
    @pytest.fixture
    def cam(self):
        return CameraModel(width=1280, height=720, fx=970.0, fy=965.0, cx=640.0, cy=360.0)

    @pytest.fixture
    def base_cfg(self):
        pid = PIDConfig(kp=5.0, ki=0.3, kd=0.2)
        return GimbalControllerConfig(yaw_pid=pid, pitch_pid=pid)

    def test_returns_config_and_score(self, base_cfg, cam):
        cfg, score = grid_search_pid(base_cfg, cam, duration_s=2.0, dt_s=0.05)
        assert isinstance(cfg, GimbalControllerConfig)
        assert isinstance(score, float)

    def test_tuned_kp_positive(self, base_cfg, cam):
        cfg, _ = grid_search_pid(base_cfg, cam, duration_s=2.0, dt_s=0.05)
        assert cfg.yaw_pid.kp > 0
        assert cfg.pitch_pid.kp > 0

    def test_score_finite(self, base_cfg, cam):
        _, score = grid_search_pid(base_cfg, cam, duration_s=2.0, dt_s=0.05)
        assert score < float("inf")
