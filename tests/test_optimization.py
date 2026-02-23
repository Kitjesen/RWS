"""优化参数的测试 - 提高 Lock Rate"""
import pytest
pytestmark = pytest.mark.skip(reason="manual benchmark only, not a unit test")

import time
import cv2
import numpy as np

from src.rws_tracking.pipeline.app import build_sim_pipeline
from src.rws_tracking.tools.simulation import SimTarget, SyntheticScene
from src.rws_tracking.algebra import CameraModel
from src.rws_tracking.config import GimbalControllerConfig, PIDConfig


def test_with_params(kp_yaw, kp_pitch, target_speed, duration=15.0):
    """测试不同参数组合"""
    print(f"\n{'='*60}")
    print(f"测试参数：")
    print(f"  Yaw Kp: {kp_yaw}")
    print(f"  Pitch Kp: {kp_pitch}")
    print(f"  目标速度: {target_speed} px/s")
    print(f"  持续时间: {duration}s")
    print(f"{'='*60}\n")

    # 创建相机模型
    cam = CameraModel(
        width=1280, height=720,
        fx=970.0, fy=965.0,
        cx=640.0, cy=360.0,
    )

    # 构建 pipeline（使用自定义 PID 参数）
    from src.rws_tracking.algebra import PixelToGimbalTransform
    from src.rws_tracking.control import TwoAxisGimbalController
    from src.rws_tracking.hardware import SimulatedGimbalDriver
    from src.rws_tracking.perception import PassthroughDetector, SimpleIoUTracker, WeightedTargetSelector
    from src.rws_tracking.telemetry import InMemoryTelemetryLogger
    from src.rws_tracking.pipeline import VisionGimbalPipeline
    from src.rws_tracking.config import SelectorConfig

    transform = PixelToGimbalTransform(cam)

    # 自定义 PID 配置
    controller_cfg = GimbalControllerConfig(
        yaw_pid=PIDConfig(
            kp=kp_yaw, ki=0.5, kd=0.4,
            integral_limit=40.0, output_limit=180.0,
            derivative_lpf_alpha=0.4,
            feedforward_kv=0.8,
        ),
        pitch_pid=PIDConfig(
            kp=kp_pitch, ki=0.45, kd=0.4,
            integral_limit=40.0, output_limit=180.0,
            derivative_lpf_alpha=0.4,
            feedforward_kv=0.75,
        ),
        command_lpf_alpha=0.75,
        lock_error_threshold_deg=1.2,  # 放宽锁定条件
        lock_hold_time_s=0.3,
        latency_compensation_s=0.033,
    )

    pipeline = VisionGimbalPipeline(
        detector=PassthroughDetector(),
        tracker=SimpleIoUTracker(iou_threshold=0.18, max_misses=10),
        selector=WeightedTargetSelector(
            frame_width=cam.width,
            frame_height=cam.height,
            config=SelectorConfig(
                preferred_classes={"person": 1.0},
                min_hold_time_s=0.35,
                delta_threshold=0.10,
            ),
        ),
        controller=TwoAxisGimbalController(transform=transform, cfg=controller_cfg),
        driver=SimulatedGimbalDriver(),
        telemetry=InMemoryTelemetryLogger(),
    )

    # 创建合成场景（单个目标，可控速度）
    scene = SyntheticScene(cam.width, cam.height, seed=42)
    scene.add_target(SimTarget(
        x=400, y=300, w=80, h=120,
        vx=target_speed, vy=target_speed * 0.6,
        confidence=0.92, class_id="person"
    ))

    ts = 0.0
    dt = 0.033  # 30 Hz

    # 运行测试
    while ts < duration:
        detections = scene.step(dt)
        pipeline.step(detections, ts)
        ts += dt

    # 获取结果
    metrics = pipeline.telemetry.snapshot_metrics()

    print(f"\n结果：")
    print(f"  Lock Rate:  {metrics['lock_rate']*100:6.2f}%")
    print(f"  Avg Error:  {metrics['avg_abs_error_deg']:6.2f} deg")
    print(f"  Switches:   {metrics['switches_per_min']:6.2f} /min")

    return metrics


def main():
    """运行多组参数测试"""
    print("="*60)
    print("RWS 参数优化测试")
    print("="*60)
    print("\n目标：找到最佳 PID 参数，提高 Lock Rate\n")

    results = []

    # 测试 1：默认参数 + 慢速目标
    print("\n[测试 1] 默认参数 + 慢速目标")
    m1 = test_with_params(kp_yaw=5.0, kp_pitch=5.5, target_speed=15, duration=15.0)
    results.append(("默认参数+慢速", m1))

    # 测试 2：增大 Kp + 慢速目标
    print("\n[测试 2] 增大 Kp + 慢速目标")
    m2 = test_with_params(kp_yaw=8.0, kp_pitch=8.5, target_speed=15, duration=15.0)
    results.append(("大Kp+慢速", m2))

    # 测试 3：增大 Kp + 中速目标
    print("\n[测试 3] 增大 Kp + 中速目标")
    m3 = test_with_params(kp_yaw=8.0, kp_pitch=8.5, target_speed=25, duration=15.0)
    results.append(("大Kp+中速", m3))

    # 测试 4：超大 Kp + 中速目标
    print("\n[测试 4] 超大 Kp + 中速目标")
    m4 = test_with_params(kp_yaw=12.0, kp_pitch=12.5, target_speed=25, duration=15.0)
    results.append(("超大Kp+中速", m4))

    # 汇总结果
    print("\n" + "="*60)
    print("测试结果汇总")
    print("="*60)
    print(f"\n{'配置':<15} {'Lock Rate':<12} {'Avg Error':<12} {'Switches':<12}")
    print("-"*60)

    for name, metrics in results:
        print(f"{name:<15} {metrics['lock_rate']*100:>10.2f}%  "
              f"{metrics['avg_abs_error_deg']:>10.2f} deg  "
              f"{metrics['switches_per_min']:>10.2f} /min")

    # 找出最佳配置
    best_idx = max(range(len(results)), key=lambda i: results[i][1]['lock_rate'])
    best_name, best_metrics = results[best_idx]

    print("\n" + "="*60)
    print(f"最佳配置: {best_name}")
    print(f"  Lock Rate: {best_metrics['lock_rate']*100:.2f}%")
    print(f"  Avg Error: {best_metrics['avg_abs_error_deg']:.2f} deg")
    print("="*60)


if __name__ == "__main__":
    main()
