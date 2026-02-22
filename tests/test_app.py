"""Pipeline app 构建函数单元测试。"""

import dataclasses
from unittest.mock import MagicMock, patch

import pytest

from src.rws_tracking.algebra import CameraModel
from src.rws_tracking.config import SystemConfig, load_config
from src.rws_tracking.pipeline.app import (
    build_sim_pipeline,
    camera_model_from_config,
    default_camera_model,
)


class TestCameraModelFromConfig:
    def test_default(self):
        cam = default_camera_model()
        assert cam.width == 1280
        assert cam.height == 720
        assert cam.fx > 0

    def test_from_config(self):
        from src.rws_tracking.config import CameraConfig
        cfg = CameraConfig(width=640, height=480, fx=500.0, fy=500.0, cx=320.0, cy=240.0)
        cam = camera_model_from_config(cfg)
        assert cam.width == 640
        assert cam.fx == 500.0

    def test_with_distortion(self):
        from src.rws_tracking.config import CameraConfig
        cfg = CameraConfig(distortion_k1=0.1, distortion_k2=0.01)
        cam = camera_model_from_config(cfg)
        assert cam.distortion is not None

    def test_no_distortion(self):
        from src.rws_tracking.config import CameraConfig
        cfg = CameraConfig()
        cam = camera_model_from_config(cfg)
        assert cam.distortion is None


class TestBuildSimPipeline:
    def test_builds(self):
        p = build_sim_pipeline()
        assert p is not None
        assert p.detector is not None
        assert p.controller is not None

    def test_with_custom_camera(self):
        cam = CameraModel(width=640, height=480, fx=500.0, fy=500.0, cx=320.0, cy=240.0)
        p = build_sim_pipeline(cam)
        assert p is not None


class TestBuildPipelineFromConfig:
    def test_default_config(self):
        from src.rws_tracking.pipeline.app import build_pipeline_from_config
        cfg = SystemConfig()
        with patch("src.rws_tracking.pipeline.app.YoloSegTracker") as mock_yolo:
            mock_yolo.return_value = MagicMock()
            p = build_pipeline_from_config(cfg)
        assert p is not None

    def test_with_safety_enabled(self, tmp_path):
        from src.rws_tracking.pipeline.app import build_pipeline_from_config
        cfg = SystemConfig()
        cfg.safety = dataclasses.replace(cfg.safety, enabled=True)
        with patch("src.rws_tracking.pipeline.app.YoloSegTracker") as mock_yolo:
            mock_yolo.return_value = MagicMock()
            p = build_pipeline_from_config(cfg)
        assert p._safety_manager is not None

    def test_with_engagement_enabled(self):
        from src.rws_tracking.pipeline.app import build_pipeline_from_config
        cfg = SystemConfig()
        cfg.engagement = dataclasses.replace(cfg.engagement, enabled=True)
        with patch("src.rws_tracking.pipeline.app.YoloSegTracker") as mock_yolo:
            mock_yolo.return_value = MagicMock()
            p = build_pipeline_from_config(cfg)
        assert p._threat_assessor is not None

    def test_with_trajectory_enabled(self):
        from src.rws_tracking.pipeline.app import build_pipeline_from_config
        cfg = SystemConfig()
        cfg.trajectory = dataclasses.replace(cfg.trajectory, enabled=True)
        with patch("src.rws_tracking.pipeline.app.YoloSegTracker") as mock_yolo:
            mock_yolo.return_value = MagicMock()
            p = build_pipeline_from_config(cfg)
        assert p._trajectory_planner is not None

    def test_with_rangefinder_enabled(self):
        from src.rws_tracking.pipeline.app import build_pipeline_from_config
        cfg = SystemConfig()
        cfg.rangefinder = dataclasses.replace(cfg.rangefinder, enabled=True)
        with patch("src.rws_tracking.pipeline.app.YoloSegTracker") as mock_yolo:
            mock_yolo.return_value = MagicMock()
            p = build_pipeline_from_config(cfg)
        assert p._rangefinder is not None

    def test_with_lead_angle_enabled(self):
        from src.rws_tracking.pipeline.app import build_pipeline_from_config
        cfg = SystemConfig()
        cfg.lead_angle = dataclasses.replace(cfg.lead_angle, enabled=True)
        with patch("src.rws_tracking.pipeline.app.YoloSegTracker") as mock_yolo:
            mock_yolo.return_value = MagicMock()
            p = build_pipeline_from_config(cfg)
        assert p._lead_calculator is not None

    def test_with_projectile_and_lead(self):
        from src.rws_tracking.pipeline.app import build_pipeline_from_config
        cfg = SystemConfig()
        cfg.projectile = dataclasses.replace(cfg.projectile, enabled=True)
        cfg.lead_angle = dataclasses.replace(cfg.lead_angle, enabled=True)
        with patch("src.rws_tracking.pipeline.app.YoloSegTracker") as mock_yolo:
            mock_yolo.return_value = MagicMock()
            p = build_pipeline_from_config(cfg)
        assert p._ballistic_solver is not None
        assert p._lead_calculator is not None

    def test_with_video_stream_enabled(self):
        from src.rws_tracking.pipeline.app import build_pipeline_from_config
        cfg = SystemConfig()
        cfg.video_stream = dataclasses.replace(cfg.video_stream, enabled=True)
        with patch("src.rws_tracking.pipeline.app.YoloSegTracker") as mock_yolo:
            mock_yolo.return_value = MagicMock()
            p = build_pipeline_from_config(cfg)
        assert p._frame_buffer is not None
