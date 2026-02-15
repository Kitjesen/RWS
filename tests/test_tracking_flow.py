import tempfile
import unittest
from pathlib import Path

from src.rws_tracking.algebra import (
    CameraModel,
    DistortionCoeffs,
    MountExtrinsics,
    PixelToGimbalTransform,
)
from src.rws_tracking.config import (
    SelectorConfig,
    SystemConfig,
    default_controller_config,
    load_config,
    save_config,
)
from src.rws_tracking.control import TwoAxisGimbalController
from src.rws_tracking.decision.state_machine import TrackState, TrackStateMachine
from src.rws_tracking.hardware import SimulatedGimbalDriver
from src.rws_tracking.perception import (
    PassthroughDetector,
    SimpleIoUTracker,
    WeightedTargetSelector,
)
from src.rws_tracking.pipeline import VisionGimbalPipeline, run_demo
from src.rws_tracking.telemetry import InMemoryTelemetryLogger
from src.rws_tracking.tools.replay import TelemetryReplay
from src.rws_tracking.types import BoundingBox, TargetError, Track

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cam() -> CameraModel:
    return CameraModel(width=1280, height=720, fx=970.0, fy=965.0, cx=640.0, cy=360.0)


def _make_pipeline() -> VisionGimbalPipeline:
    cam = _make_cam()
    transform = PixelToGimbalTransform(cam)
    cfg = default_controller_config()
    return VisionGimbalPipeline(
        detector=PassthroughDetector(),
        tracker=SimpleIoUTracker(),
        selector=WeightedTargetSelector(cam.width, cam.height, config=SelectorConfig()),
        controller=TwoAxisGimbalController(transform=transform, cfg=cfg),
        driver=SimulatedGimbalDriver(),
        telemetry=InMemoryTelemetryLogger(),
    )


# ---------------------------------------------------------------------------
# Coordinate transform tests
# ---------------------------------------------------------------------------


class CoordinateTransformTests(unittest.TestCase):
    def test_boresight_pixel_gives_zero_error(self) -> None:
        cam = _make_cam()
        tf = PixelToGimbalTransform(cam)
        yaw, pitch = tf.pixel_to_angle_error(cam.cx, cam.cy)
        self.assertAlmostEqual(yaw, 0.0, places=6)
        self.assertAlmostEqual(pitch, 0.0, places=6)

    def test_right_of_center_gives_positive_yaw(self) -> None:
        cam = _make_cam()
        tf = PixelToGimbalTransform(cam)
        yaw, pitch = tf.pixel_to_angle_error(cam.cx + 100.0, cam.cy)
        self.assertGreater(yaw, 0.0)
        self.assertAlmostEqual(pitch, 0.0, places=4)

    def test_above_center_gives_positive_pitch(self) -> None:
        cam = _make_cam()
        tf = PixelToGimbalTransform(cam)
        yaw, pitch = tf.pixel_to_angle_error(cam.cx, cam.cy - 80.0)
        self.assertAlmostEqual(yaw, 0.0, places=4)
        self.assertGreater(pitch, 0.0)

    def test_mount_rotation_offsets_error(self) -> None:
        cam = _make_cam()
        mount = MountExtrinsics(yaw_deg=1.5, pitch_deg=-0.8)
        tf = PixelToGimbalTransform(cam, mount)
        yaw, pitch = tf.pixel_to_angle_error(cam.cx, cam.cy)
        self.assertNotAlmostEqual(yaw, 0.0, places=1)

    def test_mount_yaw_direction_correct(self) -> None:
        """mount yaw_deg should produce matching yaw error at optical center."""
        cam = _make_cam()
        for mount_yaw in [5.0, -3.0]:
            mount = MountExtrinsics(yaw_deg=mount_yaw)
            tf = PixelToGimbalTransform(cam, mount)
            yaw, pitch = tf.pixel_to_angle_error(cam.cx, cam.cy)
            self.assertAlmostEqual(yaw, mount_yaw, places=2, msg=f"mount yaw={mount_yaw}")
            self.assertAlmostEqual(pitch, 0.0, places=2)

    def test_mount_pitch_direction_correct(self) -> None:
        """mount pitch_deg should produce matching pitch error at optical center."""
        cam = _make_cam()
        for mount_pitch in [5.0, -3.0]:
            mount = MountExtrinsics(pitch_deg=mount_pitch)
            tf = PixelToGimbalTransform(cam, mount)
            yaw, pitch = tf.pixel_to_angle_error(cam.cx, cam.cy)
            self.assertAlmostEqual(yaw, 0.0, places=2)
            self.assertAlmostEqual(pitch, mount_pitch, places=2, msg=f"mount pitch={mount_pitch}")

    def test_mount_roll_no_boresight_shift(self) -> None:
        """mount roll should NOT shift the boresight (optical center stays zero)."""
        cam = _make_cam()
        mount = MountExtrinsics(roll_deg=10.0)
        tf = PixelToGimbalTransform(cam, mount)
        yaw, pitch = tf.pixel_to_angle_error(cam.cx, cam.cy)
        self.assertAlmostEqual(yaw, 0.0, places=4)
        self.assertAlmostEqual(pitch, 0.0, places=4)

    def test_distortion_model_does_not_crash(self) -> None:
        cam = CameraModel(
            width=1280,
            height=720,
            fx=970.0,
            fy=965.0,
            cx=640.0,
            cy=360.0,
            distortion=DistortionCoeffs(k1=-0.05, k2=0.01),
        )
        tf = PixelToGimbalTransform(cam)
        yaw, pitch = tf.pixel_to_angle_error(700.0, 400.0)
        self.assertIsInstance(yaw, float)

    def test_bbox_center_to_angle_matches_pixel(self) -> None:
        cam = _make_cam()
        tf = PixelToGimbalTransform(cam)
        x, y, w, h = 300.0, 200.0, 100.0, 80.0
        yaw_bbox, pitch_bbox = tf.bbox_center_to_angle_error(x, y, w, h)
        yaw_px, pitch_px = tf.pixel_to_angle_error(x + w / 2, y + h / 2)
        self.assertAlmostEqual(yaw_bbox, yaw_px, places=8)
        self.assertAlmostEqual(pitch_bbox, pitch_px, places=8)


# ---------------------------------------------------------------------------
# Selector tests
# ---------------------------------------------------------------------------


class SelectorTests(unittest.TestCase):
    def test_selector_holds_target_within_min_hold_window(self) -> None:
        selector = WeightedTargetSelector(
            frame_width=1280,
            frame_height=720,
            config=SelectorConfig(min_hold_time_s=0.5, delta_threshold=0.1),
        )
        t0 = 1.0
        track_a = Track(1, BoundingBox(620, 300, 100, 100), 0.9, "person", t0, t0, age_frames=20)
        track_b = Track(2, BoundingBox(640, 320, 100, 100), 0.95, "person", t0, t0, age_frames=20)
        selected = selector.select([track_a], t0)
        self.assertEqual(selected.track_id, 1)
        selected = selector.select([track_a, track_b], t0 + 0.2)
        self.assertEqual(selected.track_id, 1)  # should NOT switch within hold window


# ---------------------------------------------------------------------------
# State machine tests
# ---------------------------------------------------------------------------


class StateMachineTests(unittest.TestCase):
    def test_reaches_lock_and_lost(self) -> None:
        sm = TrackStateMachine(default_controller_config())
        t0 = 1.0
        err = TargetError(timestamp=t0, yaw_error_deg=0.1, pitch_error_deg=0.2, target_id=1)
        self.assertEqual(sm.update(err, t0), TrackState.TRACK)
        self.assertIn(sm.update(err, t0 + 0.5), (TrackState.TRACK, TrackState.LOCK))
        self.assertEqual(sm.update(None, t0 + 0.7), TrackState.LOST)

    def test_lost_to_search_after_timeout(self) -> None:
        cfg = default_controller_config()
        sm = TrackStateMachine(cfg)
        err = TargetError(timestamp=1.0, yaw_error_deg=5.0, pitch_error_deg=3.0, target_id=1)
        sm.update(err, 1.0)
        sm.update(None, 1.5)
        self.assertEqual(sm.state, TrackState.LOST)
        sm.update(None, 1.0 + cfg.lost_timeout_s + 0.1)
        self.assertEqual(sm.state, TrackState.SEARCH)


# ---------------------------------------------------------------------------
# Pipeline demo test
# ---------------------------------------------------------------------------


class DemoTests(unittest.TestCase):
    def test_demo_metrics_have_expected_keys(self) -> None:
        metrics = run_demo(duration_s=2.0, dt_s=0.05)
        self.assertIn("lock_rate", metrics)
        self.assertIn("avg_abs_error_deg", metrics)
        self.assertIn("switches_per_min", metrics)


# ---------------------------------------------------------------------------
# Edge-case / boundary tests
# ---------------------------------------------------------------------------


class EdgeCaseTests(unittest.TestCase):
    def test_empty_frame_does_not_crash(self) -> None:
        pipeline = _make_pipeline()
        output = pipeline.step([], 0.1)
        self.assertIsNone(output.selected_target)

    def test_continuous_empty_frames_reach_search(self) -> None:
        pipeline = _make_pipeline()
        # Feed a target first, then remove it
        frame = [{"bbox": (600, 340, 80, 60), "confidence": 0.9, "class_id": "person"}]
        pipeline.step(frame, 0.0)
        # Now feed empty for 3 seconds
        for i in range(100):
            pipeline.step([], 0.03 * (i + 1))
        state = pipeline.controller.state
        self.assertEqual(state, TrackState.SEARCH)

    def test_extreme_pixel_positions(self) -> None:
        cam = _make_cam()
        tf = PixelToGimbalTransform(cam)
        # Top-left corner
        yaw, pitch = tf.pixel_to_angle_error(0.0, 0.0)
        self.assertLess(yaw, 0.0)
        self.assertGreater(pitch, 0.0)
        # Bottom-right corner
        yaw, pitch = tf.pixel_to_angle_error(float(cam.width), float(cam.height))
        self.assertGreater(yaw, 0.0)
        self.assertLess(pitch, 0.0)

    def test_gimbal_reaches_soft_limit(self) -> None:
        driver = SimulatedGimbalDriver()
        # Command max rate for a long time
        driver.set_yaw_pitch_rate(240.0, 240.0, 0.0)
        fb = driver.get_feedback(100.0)  # 100s at max rate
        self.assertLessEqual(fb.yaw_deg, 160.0)
        self.assertLessEqual(fb.pitch_deg, 75.0)

    def test_rapid_target_switching_is_suppressed(self) -> None:
        from src.rws_tracking.config import SelectorWeights

        selector = WeightedTargetSelector(
            frame_width=1280,
            frame_height=720,
            config=SelectorConfig(
                weights=SelectorWeights(switch_penalty=0.5),
                min_hold_time_s=1.0,
                delta_threshold=0.5,
            ),
        )
        t = 0.0
        tracks_a = [Track(1, BoundingBox(600, 300, 80, 80), 0.8, "person", 0, t, age_frames=30)]
        tracks_b = [
            Track(1, BoundingBox(600, 300, 80, 80), 0.8, "person", 0, t, age_frames=30),
            Track(2, BoundingBox(700, 400, 80, 80), 0.85, "person", 0, t, age_frames=30),
        ]
        selector.select(tracks_a, t)
        switches = 0
        for _i in range(20):
            t += 0.05
            sel = selector.select(tracks_b, t)
            if sel.track_id == 2:
                switches += 1
        self.assertLess(switches, 5)  # should not flip-flop

    def test_velocity_field_propagated(self) -> None:
        selector = WeightedTargetSelector(
            frame_width=1280,
            frame_height=720,
            config=SelectorConfig(),
        )
        track = Track(
            1,
            BoundingBox(600, 300, 80, 80),
            0.9,
            "person",
            0.0,
            0.1,
            age_frames=10,
            velocity_px_per_s=(50.0, -20.0),
        )
        obs = selector.select([track], 0.1)
        self.assertAlmostEqual(obs.velocity_px_per_s[0], 50.0)
        self.assertAlmostEqual(obs.velocity_px_per_s[1], -20.0)


# ---------------------------------------------------------------------------
# Config load/save test
# ---------------------------------------------------------------------------


class ConfigTests(unittest.TestCase):
    def test_save_and_load_roundtrip(self) -> None:
        cfg = SystemConfig()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            path = f.name
        save_config(cfg, path)
        loaded = load_config(path)
        self.assertEqual(loaded.camera.width, cfg.camera.width)
        self.assertAlmostEqual(loaded.controller.yaw_pid.kp, cfg.controller.yaw_pid.kp)
        Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Replay tool test
# ---------------------------------------------------------------------------


class ReplayTests(unittest.TestCase):
    def test_replay_from_logger(self) -> None:
        run_demo(duration_s=2.0, dt_s=0.05)
        # run_demo uses InMemoryTelemetryLogger internally; test replay standalone
        logger = InMemoryTelemetryLogger()
        logger.log("control", 0.1, {"yaw_error_deg": 1.0, "pitch_error_deg": 0.5, "state": 1.0})
        logger.log("control", 0.2, {"yaw_error_deg": 0.3, "pitch_error_deg": 0.1, "state": 2.0})
        replay = TelemetryReplay.from_logger(logger)
        m = replay.metrics()
        self.assertIn("lock_rate", m)
        self.assertAlmostEqual(m["lock_rate"], 0.5)

    def test_replay_from_jsonl(self) -> None:
        logger = InMemoryTelemetryLogger()
        logger.log("control", 1.0, {"yaw_error_deg": 2.0, "pitch_error_deg": 1.0, "state": 1.0})
        logger.log("switch", 1.0, {"track_id": 1.0})
        jsonl = logger.export_jsonl()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        ) as f:
            f.write(jsonl)
            path = f.name
        replay = TelemetryReplay.from_jsonl(path)
        self.assertEqual(len(replay.events), 2)
        Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
