"""测试 P2 改进：FileTelemetryLogger、环形缓冲区、优雅退出"""
import json
import tempfile
import unittest
from pathlib import Path

from src.rws_tracking.telemetry import FileTelemetryLogger, InMemoryTelemetryLogger
from src.rws_tracking.pipeline import VisionGimbalPipeline
from src.rws_tracking.hardware import SimulatedGimbalDriver, DriverLimits


class FileTelemetryLoggerTests(unittest.TestCase):
    """测试 FileTelemetryLogger"""

    def test_file_logger_writes_jsonl(self):
        """测试文件日志器写入 JSONL"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl") as f:
            temp_path = f.name

        try:
            # 使用上下文管理器
            with FileTelemetryLogger(temp_path) as logger:
                logger.log("control", 1.0, {"yaw_error_deg": 2.5, "state": 1.0})
                logger.log("control", 2.0, {"yaw_error_deg": 1.2, "state": 2.0})
                logger.log("switch", 2.5, {"track_id": 42.0})

            # 验证文件内容
            with open(temp_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            self.assertEqual(len(lines), 3)

            # 解析第一行
            event1 = json.loads(lines[0])
            self.assertEqual(event1["event_type"], "control")
            self.assertEqual(event1["timestamp"], 1.0)
            self.assertEqual(event1["payload"]["yaw_error_deg"], 2.5)

            # 解析第三行
            event3 = json.loads(lines[2])
            self.assertEqual(event3["event_type"], "switch")
            self.assertEqual(event3["payload"]["track_id"], 42.0)

        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_file_logger_append_mode(self):
        """测试追加模式"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl") as f:
            temp_path = f.name

        try:
            # 第一次写入
            with FileTelemetryLogger(temp_path, append=False) as logger:
                logger.log("control", 1.0, {"state": 0.0})

            # 追加写入
            with FileTelemetryLogger(temp_path, append=True) as logger:
                logger.log("control", 2.0, {"state": 1.0})

            # 验证有两行
            with open(temp_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["timestamp"], 1.0)
            self.assertEqual(json.loads(lines[1])["timestamp"], 2.0)

        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_file_logger_metrics(self):
        """测试文件日志器的指标计算"""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl") as f:
            temp_path = f.name

        try:
            with FileTelemetryLogger(temp_path) as logger:
                logger.log("control", 1.0, {"yaw_error_deg": 5.0, "pitch_error_deg": 3.0, "state": 1.0})
                logger.log("control", 2.0, {"yaw_error_deg": 2.0, "pitch_error_deg": 1.0, "state": 2.0})
                logger.log("control", 3.0, {"yaw_error_deg": 1.0, "pitch_error_deg": 0.5, "state": 2.0})
                logger.log("switch", 2.5, {"track_id": 1.0})

                metrics = logger.snapshot_metrics()

            # 验证指标
            self.assertEqual(metrics["lock_rate"], 2.0 / 3.0)  # 2 个 LOCK / 3 个 control
            self.assertAlmostEqual(metrics["avg_abs_error_deg"], (5.0 + 2.0 + 1.0) / 3.0, places=5)
            self.assertAlmostEqual(metrics["switches_per_min"], 1.0 * 60.0 / 2.0, places=5)  # 1 switch in 2s

        finally:
            Path(temp_path).unlink(missing_ok=True)


class RingBufferTests(unittest.TestCase):
    """测试 InMemoryTelemetryLogger 环形缓冲区"""

    def test_unlimited_buffer(self):
        """测试无限制模式（默认）"""
        logger = InMemoryTelemetryLogger()
        for i in range(100):
            logger.log("control", float(i), {"state": 0.0})

        self.assertEqual(len(logger.events), 100)

    def test_ring_buffer_drops_oldest(self):
        """测试环形缓冲区丢弃最旧事件"""
        logger = InMemoryTelemetryLogger(max_events=10)

        for i in range(20):
            logger.log("control", float(i), {"state": 0.0})

        # 只保留最新 10 个
        self.assertEqual(len(logger.events), 10)
        self.assertEqual(logger.events[0].timestamp, 10.0)  # 最旧的是 10
        self.assertEqual(logger.events[-1].timestamp, 19.0)  # 最新的是 19

    def test_ring_buffer_metrics_still_accurate(self):
        """测试环形缓冲区不影响指标计算"""
        logger = InMemoryTelemetryLogger(max_events=5)

        for i in range(10):
            logger.log("control", float(i), {"yaw_error_deg": 1.0, "state": 2.0})

        # 虽然只保留 5 个事件，但指标应该基于全部 10 个
        metrics = logger.snapshot_metrics()
        self.assertEqual(metrics["lock_rate"], 1.0)  # 全部是 LOCK
        self.assertEqual(len(logger.events), 5)  # 但只保留 5 个


class GimbalDynamicsTests(unittest.TestCase):
    """测试 SimulatedGimbalDriver 动力学模型"""

    def test_inertia_delays_response(self):
        """测试一阶惯性导致响应延迟"""
        # 对比：有惯性 vs 无惯性
        limits_with_inertia = DriverLimits(
            inertia_time_constant_s=0.1,
            static_friction_dps=0.0,
            coulomb_friction_dps=0.0,
            deadband_dps=0.0,
        )
        limits_no_inertia = DriverLimits(
            inertia_time_constant_s=0.0,
            static_friction_dps=0.0,
            coulomb_friction_dps=0.0,
            deadband_dps=0.0,
        )

        driver_inertia = SimulatedGimbalDriver(limits_with_inertia)
        driver_ideal = SimulatedGimbalDriver(limits_no_inertia)

        # 发送相同命令（使用非零起始时间）
        driver_inertia.set_yaw_pitch_rate(100.0, 0.0, 1.0)
        driver_ideal.set_yaw_pitch_rate(100.0, 0.0, 1.0)

        # 短时间后，有惯性的速率应该小于理想响应
        feedback_inertia = driver_inertia.get_feedback(1.05)
        feedback_ideal = driver_ideal.get_feedback(1.05)

        self.assertLess(feedback_inertia.yaw_rate_dps, feedback_ideal.yaw_rate_dps)
        self.assertAlmostEqual(feedback_ideal.yaw_rate_dps, 100.0, delta=0.1)

    def test_static_friction_stops_motion(self):
        """测试静摩擦阻止低速运动"""
        limits = DriverLimits(
            inertia_time_constant_s=0.0,
            static_friction_dps=1.0,
            coulomb_friction_dps=0.0,
        )
        driver = SimulatedGimbalDriver(limits)

        # 发送低于静摩擦阈值的命令
        driver.set_yaw_pitch_rate(0.5, 0.0, 0.0)
        feedback = driver.get_feedback(0.1)

        # 速率应该被静摩擦钳制为 0
        self.assertEqual(feedback.yaw_rate_dps, 0.0)

    def test_coulomb_friction_reduces_speed(self):
        """测试库仑摩擦减速"""
        # 对比：有摩擦 vs 无摩擦，在持续命令下的速率差异
        limits_with_friction = DriverLimits(
            inertia_time_constant_s=0.0,
            static_friction_dps=0.0,
            coulomb_friction_dps=10.0,
            deadband_dps=0.0,
        )
        limits_no_friction = DriverLimits(
            inertia_time_constant_s=0.0,
            static_friction_dps=0.0,
            coulomb_friction_dps=0.0,
            deadband_dps=0.0,
        )

        driver_friction = SimulatedGimbalDriver(limits_with_friction)
        driver_ideal = SimulatedGimbalDriver(limits_no_friction)

        # 发送持续命令（使用非零起始时间）
        driver_friction.set_yaw_pitch_rate(100.0, 0.0, 1.0)
        driver_ideal.set_yaw_pitch_rate(100.0, 0.0, 1.0)

        # 积分一段时间，摩擦力会持续作用
        feedback_friction = driver_friction.get_feedback(1.1)
        feedback_ideal = driver_ideal.get_feedback(1.1)

        # 无摩擦应该达到命令速率 100 dps
        # 有摩擦的实际速率应该小于命令速率（被摩擦力抵消一部分）
        self.assertAlmostEqual(feedback_ideal.yaw_rate_dps, 100.0, delta=0.1)
        self.assertLess(feedback_friction.yaw_rate_dps, feedback_ideal.yaw_rate_dps)
        self.assertGreater(feedback_friction.yaw_rate_dps, 80.0)  # 摩擦力减小了速率


class GracefulShutdownTests(unittest.TestCase):
    """测试优雅退出机制"""

    def test_stop_flag_initially_false(self):
        """测试停止标志初始为 False"""
        from src.rws_tracking.pipeline.app import build_sim_pipeline

        pipeline = build_sim_pipeline()
        self.assertFalse(pipeline.should_stop())

    def test_stop_method_sets_flag(self):
        """测试 stop() 方法设置标志"""
        from src.rws_tracking.pipeline.app import build_sim_pipeline

        pipeline = build_sim_pipeline()
        pipeline.stop()
        self.assertTrue(pipeline.should_stop())

    def test_cleanup_closes_file_logger(self):
        """测试 cleanup() 关闭文件日志"""
        from src.rws_tracking.pipeline.app import build_sim_pipeline

        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl") as f:
            temp_path = f.name

        try:
            file_logger = FileTelemetryLogger(temp_path)
            pipeline = build_sim_pipeline()
            pipeline.telemetry = file_logger

            # 写入一些数据
            file_logger.log("control", 1.0, {"state": 0.0})

            # 调用 cleanup
            pipeline.cleanup()

            # 验证文件已关闭（写入被安全忽略，不崩溃）
            file_logger.log("control", 2.0, {"state": 1.0})  # should not raise

        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_signal_handlers_can_be_installed(self):
        """测试可以安装信号处理器"""
        from src.rws_tracking.pipeline.app import build_sim_pipeline

        pipeline = build_sim_pipeline()
        pipeline.install_signal_handlers()
        self.assertTrue(pipeline._signal_handlers_installed)

        # 重复安装不会出错
        pipeline.install_signal_handlers()
        self.assertTrue(pipeline._signal_handlers_installed)


if __name__ == "__main__":
    unittest.main()
