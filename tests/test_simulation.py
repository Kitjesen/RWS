"""仿真场景单元测试。"""

import pytest

from src.rws_tracking.tools.simulation import (
    SimTarget,
    SyntheticScene,
    WorldCoordinateScene,
    WorldSimTarget,
)


class TestSimTarget:
    def test_creation(self):
        t = SimTarget(cx=640, cy=360, w=80, h=150, vx=10, vy=5, confidence=0.9, class_id="person")
        assert t.cx == 640
        assert t.class_id == "person"

    def test_step(self):
        t = SimTarget(cx=100, cy=100, w=50, h=50, vx=100, vy=50)
        t.step(1.0)
        assert abs(t.cx - 200) < 1.0
        assert abs(t.cy - 150) < 1.0


class TestSyntheticScene:
    @pytest.fixture
    def scene(self):
        s = SyntheticScene(width=1280, height=720, seed=42)
        s.add_target(
            SimTarget(cx=640, cy=360, w=80, h=150, vx=10, vy=5, confidence=0.9, class_id="person")
        )
        return s

    def test_step_returns_detections(self, scene):
        dets = scene.step(0.033)
        assert len(dets) >= 1

    def test_target_moves(self, scene):
        d1 = scene.step(0.033)
        d2 = scene.step(0.033)
        if d1 and d2:
            assert d1[0].bbox.x != d2[0].bbox.x or d1[0].bbox.y != d2[0].bbox.y

    def test_empty_scene(self):
        s = SyntheticScene(width=1280, height=720)
        dets = s.step(0.033)
        assert dets == []

    def test_multiple_targets(self):
        s = SyntheticScene(width=1280, height=720)
        s.add_target(SimTarget(cx=200, cy=200, w=50, h=50, vx=0, vy=0))
        s.add_target(SimTarget(cx=800, cy=400, w=50, h=50, vx=0, vy=0))
        dets = s.step(0.033)
        assert len(dets) == 2

    def test_out_of_bounds_removed(self):
        s = SyntheticScene(width=100, height=100)
        s.add_target(SimTarget(cx=50, cy=50, w=20, h=20, vx=10000, vy=0))
        s.step(1.0)
        dets = s.step(0.033)
        assert len(dets) == 0


class TestWorldCoordinateScene:
    @pytest.fixture
    def scene(self):
        s = WorldCoordinateScene(
            cam_width=1280,
            cam_height=720,
            fx=970.0,
            fy=965.0,
            cx=640.0,
            cy=360.0,
            seed=42,
        )
        s.add_target(
            WorldSimTarget(
                world_yaw_deg=5.0,
                world_pitch_deg=2.0,
                vel_yaw_dps=2.0,
                vel_pitch_dps=1.0,
                bbox_width=75,
                bbox_height=100,
                confidence=0.92,
                class_id="person",
            )
        )
        return s

    def test_step_returns_detections(self, scene):
        dets = scene.step(0.033, 0.0, 0.0)
        assert len(dets) >= 1

    def test_gimbal_rotation_affects_detection(self, scene):
        d1 = scene.step(0.033, 0.0, 0.0)
        scene2 = WorldCoordinateScene(
            cam_width=1280,
            cam_height=720,
            fx=970.0,
            fy=965.0,
            cx=640.0,
            cy=360.0,
            seed=42,
        )
        scene2.add_target(
            WorldSimTarget(
                world_yaw_deg=5.0,
                world_pitch_deg=2.0,
                vel_yaw_dps=2.0,
                vel_pitch_dps=1.0,
                bbox_width=75,
                bbox_height=100,
            )
        )
        d2 = scene2.step(0.033, 50.0, 0.0)
        # With gimbal rotated 50 deg, target should be at different pixel position
        if d1 and d2:
            assert d1[0].bbox.x != d2[0].bbox.x

    def test_empty_scene(self):
        s = WorldCoordinateScene(
            cam_width=1280, cam_height=720, fx=970.0, fy=965.0, cx=640.0, cy=360.0
        )
        dets = s.step(0.033, 0.0, 0.0)
        assert dets == []

    def test_target_out_of_fov(self):
        s = WorldCoordinateScene(
            cam_width=1280, cam_height=720, fx=970.0, fy=965.0, cx=640.0, cy=360.0
        )
        s.add_target(
            WorldSimTarget(
                world_yaw_deg=90.0,
                world_pitch_deg=0.0,
                bbox_width=75,
                bbox_height=100,
            )
        )
        dets = s.step(0.033, 0.0, 0.0)
        assert len(dets) == 0  # target outside FOV
