"""MuJoCo SIL integration tests."""

import unittest

try:
    import mujoco

    MUJOCO_AVAILABLE = True
except ImportError:
    MUJOCO_AVAILABLE = False

from src.rws_tracking.tools.sim.mujoco_env import BaseDisturbance, MujocoEnv, TargetMotion
from src.rws_tracking.tools.sim.run_sil import _MujocoBodyMotionProvider, build_sil_pipeline


@unittest.skipIf(not MUJOCO_AVAILABLE, "mujoco not installed")
class MujocoEnvTests(unittest.TestCase):
    def test_env_create_and_close(self) -> None:
        env = MujocoEnv()
        self.assertGreater(env.timestep, 0.0)
        env.close()

    def test_target_position_updates(self) -> None:
        motion = TargetMotion(
            pattern="linear", start_pos=(5.0, 0.0, 1.5), velocity_mps=(1.0, 0.0, 0.0)
        )
        env = MujocoEnv(target_motion=motion)
        env.step(100)
        pos = env.get_target_position()
        self.assertGreater(pos[0], 5.0)
        env.close()

    def test_reset_restores_initial_state(self) -> None:
        env = MujocoEnv()
        env.step(50)
        env.reset()
        self.assertAlmostEqual(env.time, 0.0, places=6)
        env.close()


class GroundTruthDetectorTests(unittest.TestCase):
    def test_ground_truth_produces_detection(self) -> None:
        env = MujocoEnv()
        env.step(10)
        frame = env.camera.render()
        from src.rws_tracking.tools.sim.ground_truth_detector import GroundTruthDetector

        det = GroundTruthDetector(
            model=env.model,
            data=env.data,
            image_width=env.camera.width,
            image_height=env.camera.height,
        )
        detections = det.detect(frame, env.time)
        self.assertGreater(len(detections), 0)
        self.assertGreater(detections[0].confidence, 0.0)
        env.close()


class SILClosedLoopTests(unittest.TestCase):
    def test_static_target_achieves_lock(self) -> None:
        motion = TargetMotion(pattern="static", start_pos=(5.0, 0.0, 1.5))
        env = MujocoEnv(target_motion=motion)
        pipeline = build_sil_pipeline(env)
        control_dt = 1.0 / 30.0
        steps_per_frame = max(1, int(round(control_dt / env.timestep)))
        for _ in range(90):  # 3 seconds at 30Hz
            env.step(steps_per_frame)
            frame = env.camera.render()
            pipeline.step(frame, env.time)
        metrics = pipeline.telemetry.snapshot_metrics()
        self.assertGreater(metrics["lock_rate"], 0.0)
        env.close()

    def test_circle_target_tracks(self) -> None:
        motion = TargetMotion(
            pattern="circle", center=(5.0, 0.0, 1.5), radius_m=2.0, omega_dps=25.0
        )
        env = MujocoEnv(target_motion=motion)
        pipeline = build_sil_pipeline(env)
        control_dt = 1.0 / 30.0
        steps_per_frame = max(1, int(round(control_dt / env.timestep)))
        for _ in range(60):  # 2 seconds
            env.step(steps_per_frame)
            frame = env.camera.render()
            pipeline.step(frame, env.time)
        metrics = pipeline.telemetry.snapshot_metrics()
        self.assertLess(metrics["avg_abs_error_deg"], 20.0)
        env.close()


class BodyMotionSILTests(unittest.TestCase):
    def test_body_motion_does_not_crash(self) -> None:
        motion = TargetMotion(pattern="static", start_pos=(5.0, 0.0, 1.5))
        dist = BaseDisturbance()
        env = MujocoEnv(target_motion=motion, base_disturbance=dist)
        body_provider = _MujocoBodyMotionProvider(env)
        pipeline = build_sil_pipeline(env, body_provider=body_provider)
        control_dt = 1.0 / 30.0
        steps_per_frame = max(1, int(round(control_dt / env.timestep)))
        for _ in range(60):
            env.step(steps_per_frame)
            frame = env.camera.render()
            pipeline.step(frame, env.time)
        bs = env.get_body_state()
        self.assertIsNotNone(bs)
        env.close()


if __name__ == "__main__":
    unittest.main()
