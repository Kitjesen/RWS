"""改进的仿真演示 - 显示云台角度和跟踪效果"""

import time

import cv2
import numpy as np

from src.rws_tracking.algebra import CameraModel
from src.rws_tracking.pipeline.app import build_sim_pipeline
from src.rws_tracking.tools.simulation import SimTarget, SyntheticScene


def draw_gimbal_indicator(img, yaw_deg, pitch_deg, max_yaw=160, max_pitch=75):
    """绘制云台角度指示器"""
    h, w = img.shape[:2]

    # 绘制背景框
    cv2.rectangle(img, (w - 250, 10), (w - 10, 150), (40, 40, 40), -1)
    cv2.rectangle(img, (w - 250, 10), (w - 10, 150), (100, 100, 100), 2)

    # 标题
    cv2.putText(
        img, "Gimbal Angle", (w - 240, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2
    )

    # Yaw 指示器
    yaw_bar_x = int(130 * (yaw_deg + max_yaw) / (2 * max_yaw))
    cv2.rectangle(img, (w - 240, 50), (w - 110, 70), (60, 60, 60), -1)
    cv2.rectangle(
        img, (w - 240 + yaw_bar_x - 2, 50), (w - 240 + yaw_bar_x + 2, 70), (0, 255, 255), -1
    )
    cv2.putText(
        img, f"Yaw: {yaw_deg:+.1f}", (w - 240, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1
    )

    # Pitch 指示器
    pitch_bar_x = int(130 * (pitch_deg + 45) / (max_pitch + 45))
    cv2.rectangle(img, (w - 240, 100), (w - 110, 120), (60, 60, 60), -1)
    cv2.rectangle(
        img, (w - 240 + pitch_bar_x - 2, 100), (w - 240 + pitch_bar_x + 2, 120), (255, 255, 0), -1
    )
    cv2.putText(
        img,
        f"Pitch: {pitch_deg:+.1f}",
        (w - 240, 140),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (255, 255, 0),
        1,
    )


def main():
    """运行改进的仿真演示"""
    print("[RWS] 启动改进的仿真测试...")
    print("[提示] 观察右上角的云台角度指示器")
    print("[提示] 云台会转动来保持目标在画面中心")
    print()

    # 创建相机模型
    cam = CameraModel(
        width=1280,
        height=720,
        fx=970.0,
        fy=965.0,
        cx=640.0,
        cy=360.0,
    )

    # 构建仿真 pipeline
    pipeline = build_sim_pipeline(cam)

    # 创建合成场景（较慢的目标，更容易跟踪）
    scene = SyntheticScene(cam.width, cam.height, seed=42)
    scene.add_target(
        SimTarget(
            x=400,
            y=300,
            w=80,
            h=120,
            vx=30,
            vy=20,  # 降低速度
            confidence=0.92,
            class_id="person",
        )
    )

    print("[RWS] 仿真运行中... 按 'q' 退出")

    ts = 0.0
    dt = 0.033  # 30 Hz

    try:
        while ts < 30.0:  # 运行 30 秒
            # 生成合成帧（检测结果）
            detections = scene.step(dt)

            # 创建可视化图像
            display = np.zeros((cam.height, cam.width, 3), dtype=np.uint8)

            # 绘制所有检测到的目标
            for det in detections:
                x, y, w, h = det["bbox"]
                x, y, w, h = int(x), int(y), int(w), int(h)
                color = (80, 80, 80)  # 灰色表示未选中的目标
                cv2.rectangle(display, (x, y), (x + w, y + h), color, 1)

            # Pipeline 处理
            output = pipeline.step(detections, ts)

            # 获取云台反馈（当前角度）
            gimbal_feedback = pipeline.driver.get_feedback(ts)

            # 绘制选中的目标
            if output.selected_target is not None:
                t = output.selected_target
                x, y, w, h = int(t.bbox.x), int(t.bbox.y), int(t.bbox.w), int(t.bbox.h)

                # 绘制边界框（绿色高亮）
                cv2.rectangle(display, (x, y), (x + w, y + h), (0, 255, 0), 3)

                # 绘制目标信息
                label = f"ID:{t.track_id} {t.class_id}"
                cv2.putText(
                    display, label, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2
                )

                # 绘制目标中心到画面中心的连线
                cx, cy = int(t.bbox.center[0]), int(t.bbox.center[1])
                center_x, center_y = cam.width // 2, cam.height // 2
                cv2.line(display, (cx, cy), (center_x, center_y), (0, 255, 255), 2)

                # 绘制目标中心
                cv2.circle(display, (cx, cy), 5, (0, 255, 0), -1)

            # 绘制画面中心准心（红色）
            center_x, center_y = cam.width // 2, cam.height // 2
            cv2.drawMarker(display, (center_x, center_y), (0, 0, 255), cv2.MARKER_CROSS, 30, 3)
            cv2.putText(
                display,
                "Gimbal Aim",
                (center_x + 20, center_y - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 0, 255),
                1,
            )

            # 显示控制命令
            cmd = output.command
            state_names = ["SEARCH", "TRACK", "LOCK", "LOST"]
            state_idx = int(cmd.metadata.get("state", 0))
            state_name = state_names[state_idx] if 0 <= state_idx < 4 else "UNKNOWN"

            # 状态颜色
            state_colors = {
                "SEARCH": (100, 100, 100),
                "TRACK": (0, 255, 255),
                "LOCK": (0, 255, 0),
                "LOST": (0, 0, 255),
            }
            state_color = state_colors.get(state_name, (255, 255, 255))

            # 左侧信息面板
            info_lines = [
                f"State: {state_name}",
                f"Yaw Cmd: {cmd.yaw_rate_cmd_dps:+.1f} dps",
                f"Pitch Cmd: {cmd.pitch_rate_cmd_dps:+.1f} dps",
                f"Time: {ts:.1f}s",
            ]

            for i, line in enumerate(info_lines):
                color = state_color if i == 0 else (200, 200, 200)
                cv2.putText(
                    display, line, (10, 30 + i * 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2
                )

            # 绘制云台角度指示器（右上角）
            draw_gimbal_indicator(display, gimbal_feedback.yaw_deg, gimbal_feedback.pitch_deg)

            # 显示误差信息
            if output.selected_target is not None:
                yaw_err = cmd.metadata.get("yaw_error_deg", 0.0)
                pitch_err = cmd.metadata.get("pitch_error_deg", 0.0)
                cv2.putText(
                    display,
                    f"Error: Y={yaw_err:+.1f} P={pitch_err:+.1f} deg",
                    (10, cam.height - 20),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 255),
                    2,
                )

            # 显示视频帧
            cv2.imshow("RWS Tracking - Gimbal Simulation", display)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

            ts += dt
            time.sleep(dt)

    finally:
        cv2.destroyAllWindows()

        # 显示最终指标
        metrics = pipeline.telemetry.snapshot_metrics()
        print("\n[RWS] 仿真完成，性能指标：")
        print(f"  Lock Rate: {metrics['lock_rate'] * 100:.1f}%")
        print(f"  Avg Error: {metrics['avg_abs_error_deg']:.2f} deg")
        print(f"  Switches: {metrics['switches_per_min']:.1f} /min")


if __name__ == "__main__":
    main()
