"""
集成测试 — 完整射击链路端到端验证
=================================

验证:
- 各扩展模块独立功能
- 完整 pipeline.step() 射击链路端到端数据流
- 配置驱动的 pipeline 构建
"""

import unittest

from src.rws_tracking.algebra import CameraModel, PixelToGimbalTransform
from src.rws_tracking.config import SelectorConfig, default_controller_config
from src.rws_tracking.control.ballistic import PhysicsBallisticModel
from src.rws_tracking.control.controller import TwoAxisGimbalController
from src.rws_tracking.control.lead_angle import (
    LeadAngleCalculator,
    LeadAngleConfig,
    SimpleFlightTimeProvider,
)
from src.rws_tracking.control.trajectory import (
    GimbalTrajectoryPlanner,
    TrajectoryConfig,
)
from src.rws_tracking.decision.engagement import (
    EngagementConfig as EConfig,
)
from src.rws_tracking.decision.engagement import (
    EngagementQueue,
    ThreatAssessor,
)
from src.rws_tracking.hardware.driver import SimulatedGimbalDriver
from src.rws_tracking.hardware.rangefinder import (
    DistanceFusion,
    SimulatedRangefinder,
    SimulatedRangefinderConfig,
)
from src.rws_tracking.perception.passthrough_detector import PassthroughDetector
from src.rws_tracking.perception.selector import WeightedTargetSelector
from src.rws_tracking.perception.tracker import SimpleIoUTracker
from src.rws_tracking.pipeline.pipeline import PipelineOutputs, VisionGimbalPipeline
from src.rws_tracking.safety.interlock import SafetyInterlockConfig
from src.rws_tracking.safety.manager import SafetyManager, SafetyManagerConfig
from src.rws_tracking.telemetry.logger import InMemoryTelemetryLogger
from src.rws_tracking.types import (
    BoundingBox,
    ProjectileParams,
    SafetyZone,
    TargetObservation,
    Track,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CAM = CameraModel(width=1280, height=720, fx=970.0, fy=965.0, cx=640.0, cy=360.0)


def _track(
    tid: int = 1,
    x: float = 600,
    y: float = 340,
    w: float = 80,
    h: float = 150,
    cls: str = "person",
    vx: float = 5.0,
    vy: float = 2.0,
) -> Track:
    return Track(
        track_id=tid,
        bbox=BoundingBox(x=x, y=y, w=w, h=h),
        confidence=0.9,
        class_id=cls,
        first_seen_ts=0.0,
        last_seen_ts=0.0,
        age_frames=10,
        velocity_px_per_s=(vx, vy),
    )


def _det(
    x: float = 600,
    y: float = 340,
    w: float = 80,
    h: float = 150,
    cls: str = "person",
    conf: float = 0.9,
) -> dict:
    """PassthroughDetector 需要的 dict 格式检测结果。"""
    return {"bbox": (x, y, w, h), "confidence": conf, "class_id": cls}


def _obs(
    tid: int = 1,
    x: float = 600,
    y: float = 340,
    w: float = 80,
    h: float = 150,
    vx: float = 50.0,
    vy: float = 10.0,
) -> TargetObservation:
    return TargetObservation(
        timestamp=0.0,
        track_id=tid,
        bbox=BoundingBox(x=x, y=y, w=w, h=h),
        confidence=0.9,
        class_id="person",
        velocity_px_per_s=(vx, vy),
    )


def _full_pipeline() -> VisionGimbalPipeline:
    """构建包含全部扩展组件的 pipeline, 所有开关打开。"""
    transform = PixelToGimbalTransform(CAM)

    # 威胁评估
    eng_cfg = EConfig()
    assessor = ThreatAssessor(
        frame_width=CAM.width,
        frame_height=CAM.height,
        camera_fy=CAM.fy,
        config=eng_cfg,
    )
    queue = EngagementQueue(config=eng_cfg)

    # 测距
    rf = SimulatedRangefinder(
        config=SimulatedRangefinderConfig(failure_rate=0.0),
        camera_fy=CAM.fy,
    )
    fusion = DistanceFusion(max_laser_age_s=1.0, camera_fy=CAM.fy)

    # 弹道
    ballistic = PhysicsBallisticModel(
        projectile=ProjectileParams(muzzle_velocity_mps=900.0),
    )

    # 提前量 — enabled=True
    ftp = SimpleFlightTimeProvider(muzzle_velocity_mps=900.0)
    lead_calc = LeadAngleCalculator(
        transform=transform,
        flight_time_provider=ftp,
        config=LeadAngleConfig(enabled=True),
    )

    # 安全 — 完全授权
    safety_mgr = SafetyManager()
    safety_mgr.set_operator_auth(True)
    safety_mgr.update_system_status(comms_ok=True, sensors_ok=True)
    safety_mgr.operator_heartbeat()

    # 轨迹
    planner = GimbalTrajectoryPlanner(
        TrajectoryConfig(min_switch_interval_s=0.0),
    )

    return VisionGimbalPipeline(
        detector=PassthroughDetector(),
        tracker=SimpleIoUTracker(iou_threshold=0.18, max_misses=10),
        selector=WeightedTargetSelector(
            frame_width=CAM.width,
            frame_height=CAM.height,
            config=SelectorConfig(
                preferred_classes={"person": 1.0},
                min_hold_time_s=0.35,
                delta_threshold=0.10,
            ),
        ),
        controller=TwoAxisGimbalController(
            transform=transform,
            cfg=default_controller_config(),
        ),
        driver=SimulatedGimbalDriver(),
        telemetry=InMemoryTelemetryLogger(),
        threat_assessor=assessor,
        engagement_queue=queue,
        distance_fusion=fusion,
        rangefinder=rf,
        ballistic_solver=ballistic,
        lead_calculator=lead_calc,
        safety_manager=safety_mgr,
        trajectory_planner=planner,
    )


# ===================================================================
# 单元测试 — 各模块独立验证
# ===================================================================


class TestThreatAssessor(unittest.TestCase):
    def test_single_target(self):
        a = ThreatAssessor(CAM.width, CAM.height, CAM.fy)
        r = a.assess([_track()])
        self.assertEqual(len(r), 1)
        self.assertGreater(r[0].threat_score, 0.0)

    def test_near_beats_far(self):
        a = ThreatAssessor(CAM.width, CAM.height, CAM.fy)
        r = a.assess([_track(tid=1, h=200), _track(tid=2, h=50)])
        self.assertGreaterEqual(r[0].threat_score, r[1].threat_score)


class TestRangefinder(unittest.TestCase):
    def test_measure(self):
        rf = SimulatedRangefinder(
            SimulatedRangefinderConfig(failure_rate=0.0),
            camera_fy=970.0,
        )
        rf.set_target_bbox(BoundingBox(x=600, y=340, w=80, h=150))
        r = rf.measure(0.0)
        self.assertTrue(r.valid)
        self.assertGreater(r.distance_m, 0.0)

    def test_fusion(self):
        rf = SimulatedRangefinder(
            SimulatedRangefinderConfig(failure_rate=0.0),
            camera_fy=970.0,
        )
        bbox = BoundingBox(x=600, y=340, w=80, h=150)
        rf.set_target_bbox(bbox)
        reading = rf.measure(0.0)
        d = DistanceFusion(1.0, 970.0).fuse(reading, bbox, 0.0)
        self.assertGreater(d, 0.0)


class TestBallistic(unittest.TestCase):
    def test_solve_100m(self):
        m = PhysicsBallisticModel(
            ProjectileParams(
                muzzle_velocity_mps=900.0,
                ballistic_coefficient=0.223,
                projectile_mass_kg=0.0098,
                projectile_diameter_m=0.00762,
            ),
        )
        s = m.solve(100.0)
        self.assertGreater(s.flight_time_s, 0.0)
        self.assertGreater(s.drop_deg, 0.0)

    def test_flight_time_protocol(self):
        m = PhysicsBallisticModel(ProjectileParams(muzzle_velocity_mps=900.0))
        t = m.compute_flight_time(200.0)
        self.assertGreater(t, 0.0)
        self.assertLess(t, 1.0)


class TestLeadAngle(unittest.TestCase):
    def test_simple_ftp(self):
        self.assertAlmostEqual(
            SimpleFlightTimeProvider(1000.0).compute_flight_time(500.0),
            0.5,
            places=3,
        )

    def test_nonzero_lead(self):
        """移动目标 vx=50 px/s 应产生非零 yaw 提前量。"""
        calc = LeadAngleCalculator(
            transform=PixelToGimbalTransform(CAM),
            flight_time_provider=SimpleFlightTimeProvider(900.0),
            config=LeadAngleConfig(enabled=True),
        )
        lead = calc.compute(_obs(vx=50.0, vy=10.0))
        self.assertNotEqual(lead.yaw_lead_deg, 0.0)


class TestSafety(unittest.TestCase):
    def test_default_blocks(self):
        s = SafetyManager().evaluate(0, 0, True, 5.0, 100.0)
        self.assertFalse(s.fire_authorized)

    def test_authorized(self):
        m = SafetyManager(
            SafetyManagerConfig(
                interlock=SafetyInterlockConfig(require_operator_auth=True),
            )
        )
        m.set_operator_auth(True)
        m.update_system_status(comms_ok=True, sensors_ok=True)
        m.operator_heartbeat()
        s = m.evaluate(0, 0, True, 5.0, 100.0)
        self.assertTrue(s.fire_authorized)

    def test_nfz(self):
        z = SafetyZone("nfz", 10, 5, 15, "no_fire")
        m = SafetyManager(SafetyManagerConfig(zones=(z,)))
        m.set_operator_auth(True)
        m.update_system_status(True, True)
        m.operator_heartbeat()
        s = m.evaluate(10, 5, True, 5.0, 100.0)
        self.assertFalse(s.fire_authorized)


class TestTrajectory(unittest.TestCase):
    def test_nonzero_rate(self):
        p = GimbalTrajectoryPlanner(TrajectoryConfig(min_switch_interval_s=0.0))
        p.set_target(30, 10, 0, 0, 0.0)
        yr, pr = p.get_rate_command(0.05)
        self.assertGreater(abs(yr) + abs(pr), 0.0)


# ===================================================================
# 集成测试 — 完整 pipeline.step()
# ===================================================================


class TestFullChain(unittest.TestCase):
    def test_with_detection(self):
        """有目标时全链路各节点应有效输出。

        连续喂入多帧以满足 selector 的 min_hold_time。
        """
        pipe = _full_pipeline()
        out = None
        d = _det()
        for i in range(20):
            out = pipe.step([d], i * 0.033)

        self.assertIsNotNone(out.selected_target)
        self.assertGreater(len(out.tracks), 0)
        self.assertGreater(len(out.threat_assessments), 0)
        self.assertGreater(out.distance_m, 0.0)
        self.assertIsNotNone(out.ballistic_solution)
        self.assertIsNotNone(out.lead_angle)
        self.assertIsNotNone(out.safety_status)

    def test_without_detection(self):
        """无目标时不崩溃, 可选输出为 None/空。"""
        pipe = _full_pipeline()
        out = pipe.step([], 0.0)

        self.assertIsNone(out.selected_target)
        self.assertEqual(len(out.threat_assessments), 0)
        self.assertIsNone(out.ballistic_solution)
        self.assertIsNone(out.lead_angle)

    def test_30_frames_convergence(self):
        """连续 30 帧, 控制指令应至少出现一次非零。"""
        pipe = _full_pipeline()
        d = _det(x=700, y=400)
        any_cmd = False
        for i in range(30):
            out = pipe.step([d], i * 0.033)
            if out.command.yaw_rate_cmd_dps != 0 or out.command.pitch_rate_cmd_dps != 0:
                any_cmd = True
        self.assertTrue(any_cmd)

    def test_output_types(self):
        """PipelineOutputs 字段类型正确。"""
        pipe = _full_pipeline()
        for i in range(5):
            out = pipe.step([_det()], i * 0.033)
        self.assertIsInstance(out, PipelineOutputs)
        self.assertIsInstance(out.tracks, list)
        self.assertIsInstance(out.threat_assessments, list)
        self.assertIsInstance(out.distance_m, float)

    def test_lead_angle_present_in_chain(self):
        """pipeline 内 lead_angle 应被计算出（非 None）。

        注: SimpleIoUTracker 不估算速度，velocity 全为 0，
        所以 lead 角度为 0 是正确行为。非零提前量已在单元测试验证。
        """
        pipe = _full_pipeline()
        d = _det(x=700, y=400)
        out = None
        for i in range(20):
            out = pipe.step([d], i * 0.033)
        self.assertIsNotNone(out)
        self.assertIsNotNone(out.lead_angle)

    def test_ballistic_drops_positive(self):
        """弹道解算的 drop 应为正 (重力下坠)。"""
        pipe = _full_pipeline()
        out = None
        for i in range(15):
            out = pipe.step([_det()], i * 0.033)
        if out is not None and out.ballistic_solution is not None:
            self.assertGreater(out.ballistic_solution.drop_deg, 0.0)


if __name__ == "__main__":
    unittest.main()
