"""
YOLO-Seg + BoT-SORT + Kalman 可视化。
支持实时摄像头或视频文件，可录制推理结果视频。

用法:
  python run_yolo_cam.py                                    # 摄像头
  python run_yolo_cam.py test_videos/xxx.mp4                # 视频文件
  python run_yolo_cam.py test_videos/xxx.mp4 --save         # 视频 + 录制
  python run_yolo_cam.py test_videos/xxx.mp4 --save out.mp4 # 指定输出文件名
  python run_yolo_cam.py --save                             # 摄像头 + 录制

按 q 退出，空格暂停，视频结束自动停止。
录制的视频保存在 output/ 目录下。
"""
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple, Union

import cv2
import numpy as np

from src.rws_tracking.algebra.kalman2d import KalmanCAConfig
from src.rws_tracking.config import SystemConfig, load_config
from src.rws_tracking.perception.yolo_seg_tracker import YoloSegTracker

logger = logging.getLogger(__name__)

# ── 可视化专属配置（不属于系统配置） ──────────────────────
MASK_ALPHA = 0.45                  # mask 叠加透明度
OUTPUT_FPS = 15.0                  # 录制输出帧率
PREDICT_HORIZON_S = 0.5            # 预测未来多长时间
PREDICT_STEPS = 8                  # 预测点数量
# ──────────────────────────────────────────────────────────

_COLOR_PALETTE = [
    (0, 255, 0), (255, 0, 0), (0, 0, 255), (255, 255, 0),
    (0, 255, 255), (255, 0, 255), (128, 255, 0), (0, 128, 255),
    (255, 128, 0), (128, 0, 255), (0, 255, 128), (255, 0, 128),
]


def color_for_id(tid: int) -> Tuple[int, int, int]:
    return _COLOR_PALETTE[tid % len(_COLOR_PALETTE)]


def draw_overlay(
    frame: np.ndarray,
    raw_results: Optional[list],
    tracks: list,
    tracker: YoloSegTracker,
    fps: float,
) -> np.ndarray:
    """绘制所有可视化内容到帧上。"""
    overlay = frame.copy()

    # ── mask overlay ──
    if raw_results is not None:
        for result in raw_results:
            if result.masks is None:
                continue
            masks_data = result.masks.data.cpu().numpy()
            orig_h, orig_w = result.masks.orig_shape
            has_ids = result.boxes.id is not None
            for i in range(masks_data.shape[0]):
                tid = int(result.boxes.id[i].item()) if has_ids else (i + 1)
                color = color_for_id(tid)
                mask = cv2.resize(
                    masks_data[i], (orig_w, orig_h),
                    interpolation=cv2.INTER_LINEAR,
                )
                binary = mask > 0.5
                overlay[binary] = (
                    np.array(color, dtype=np.uint8) * MASK_ALPHA
                    + overlay[binary] * (1.0 - MASK_ALPHA)
                ).astype(np.uint8)
    frame = overlay

    # ── bbox, track ID, Kalman centroid, predicted trail ──
    for trk in tracks:
        color = color_for_id(trk.track_id)
        x, y, w, h = int(trk.bbox.x), int(trk.bbox.y), int(trk.bbox.w), int(trk.bbox.h)
        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

        label = f"ID:{trk.track_id} {trk.class_id} {trk.confidence:.2f}"
        cv2.putText(frame, label, (x, y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

        # Kalman-filtered centroid (red cross)
        if trk.mask_center is not None:
            cx, cy = int(trk.mask_center[0]), int(trk.mask_center[1])
            cv2.drawMarker(frame, (cx, cy), (0, 0, 255),
                           cv2.MARKER_CROSS, 18, 2)

        # Predicted trajectory (parabolic arc — fading dots with connecting line)
        _tracklet = tracker._mot.active_tracks.get(trk.track_id)
        kf = _tracklet.kf if _tracklet is not None else None
        if kf is not None:
            trail = []
            dt_step = PREDICT_HORIZON_S / PREDICT_STEPS
            for step in range(1, PREDICT_STEPS + 1):
                px, py = kf.predict_position(dt_step * step)
                trail.append((int(px), int(py)))
            # Draw connecting polyline (shows curved trajectory)
            if len(trail) >= 2:
                prev = (int(kf.position[0]), int(kf.position[1]))
                for idx_pt, pt in enumerate(trail):
                    brightness = max(200 - idx_pt * 20, 80)
                    cv2.line(frame, prev, pt, (brightness, brightness, brightness), 1)
                    prev = pt
            # Draw dots
            for idx_pt, pt in enumerate(trail):
                radius = max(4 - idx_pt // 2, 2)
                brightness = max(255 - idx_pt * 22, 80)
                cv2.circle(frame, pt, radius, (brightness, brightness, brightness), -1)

        # Velocity arrow
        vx, vy = trk.velocity_px_per_s
        speed = (vx * vx + vy * vy) ** 0.5
        if speed > 10.0:
            start = trk.mask_center or trk.bbox.center
            sx, sy = int(start[0]), int(start[1])
            arrow_len = min(max(speed * 0.25, 40.0), 120.0)
            ex = int(sx + vx / speed * arrow_len)
            ey = int(sy + vy / speed * arrow_len)
            cv2.arrowedLine(frame, (sx, sy), (ex, ey), (0, 255, 255), 2, tipLength=0.25)

    # ── HUD ──
    hud = f"Tracks: {len(tracks)}  FPS: {fps:.1f}  Kalman+BoT-SORT"
    cv2.putText(frame, hud, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 200, 255), 2)

    return frame


def parse_args() -> Tuple[Union[int, str], bool, Optional[str], str]:
    """简单的参数解析（不引入 argparse 依赖）。

    Returns
    -------
    (source, save, save_path, config_path)
    """
    source: Union[int, str] = 0  # 默认摄像头
    save = False
    save_path: Optional[str] = None
    config_path = "config.yaml"

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--save":
            save = True
            # 下一个参数如果不是 flag，则作为输出文件名
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                save_path = args[i + 1]
                i += 1
        elif args[i] == "--config":
            if i + 1 < len(args):
                config_path = args[i + 1]
                i += 1
        elif not args[i].startswith("--"):
            source = args[i]
        i += 1

    return source, save, save_path, config_path


def main() -> None:
    source, do_save, save_path, config_path = parse_args()
    is_video_file = isinstance(source, str)

    # ── 加载系统配置 ──
    if Path(config_path).exists():
        cfg = load_config(config_path)
        print(f"[RWS] 配置已加载: {config_path}")
    else:
        cfg = SystemConfig()
        print(f"[RWS] 配置文件 {config_path} 不存在，使用默认配置")

    det = cfg.detector
    tracker = YoloSegTracker(
        model_path=det.model_path,
        confidence_threshold=det.confidence_threshold,
        nms_iou_threshold=det.nms_iou_threshold,
        tracker=det.tracker,
        class_whitelist=list(det.class_whitelist) if det.class_whitelist else None,
        img_size=det.img_size,
        device=det.device,
        kalman_config=KalmanCAConfig(),
    )

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"ERROR: 打不开视频源 {source}")
        return

    writer = None
    try:
        # 获取视频信息
        video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if is_video_file else -1
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        src_name = source if is_video_file else f"Camera {source}"
        print(f"[RWS] 源: {src_name}  {w}x{h}  {video_fps:.0f}fps", end="")
        if total_frames > 0:
            print(f"  总帧数: {total_frames}  时长: {total_frames/video_fps:.1f}s")
        else:
            print()

        # ── 录制设置 ──
        if do_save:
            os.makedirs("output", exist_ok=True)
            if save_path is None:
                ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                src_tag = os.path.splitext(os.path.basename(source))[0] if is_video_file else "cam"
                save_path = f"output/rws_{src_tag}_{ts_str}.mp4"
            elif not save_path.startswith("output/"):
                save_path = f"output/{save_path}"

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(save_path, fourcc, OUTPUT_FPS, (w, h))
            if writer.isOpened():
                print(f"[RWS] 录制到: {save_path}  ({w}x{h} @{OUTPUT_FPS}fps)")
            else:
                print(f"[RWS] WARNING: 无法创建录制文件 {save_path}")
                writer = None

        # 跳帧
        if is_video_file:
            skip = max(int(video_fps / 6.0) - 1, 0)
            print(f"[RWS] 跳帧: 每 {skip + 1} 帧推理 1 帧")
        else:
            skip = 0

        print("按 q 退出, 空格暂停")

        fps_t0 = time.monotonic()
        frame_count = 0
        read_count = 0
        fps = 0.0

        while True:
            # 跳帧读取
            for _ in range(skip):
                ret = cap.grab()
                if not ret:
                    break
                read_count += 1

            ret, frame = cap.read()
            read_count += 1
            if not ret:
                if is_video_file:
                    print("[RWS] 视频播放完毕")
                break

            ts = time.monotonic()

            # ── 推理 ──
            tracks = tracker.detect_and_track(frame, ts)
            raw_results = tracker.last_raw_results

            # ── 绘制 ──
            frame_count += 1
            elapsed = time.monotonic() - fps_t0
            fps = frame_count / elapsed if elapsed > 0 else 0
            display = draw_overlay(frame, raw_results, tracks, tracker, fps)

            # 视频文件：显示进度
            if is_video_file and total_frames > 0:
                pct = 100 * read_count / total_frames
                video_time = read_count / video_fps
                progress = f"{read_count}/{total_frames} ({pct:.0f}%) t={video_time:.1f}s"
                cv2.putText(display, progress, (10, h - 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)

            # ── 录制 ──
            if writer is not None:
                writer.write(display)

            cv2.imshow("YOLO-Seg + Kalman", display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord(" "):
                print("[PAUSE] 按任意键继续...")
                cv2.waitKey(0)

    finally:
        cap.release()
        if writer is not None:
            writer.release()
            if save_path and os.path.exists(save_path):
                size_mb = os.path.getsize(save_path) / 1024 / 1024
                print(f"[RWS] 录制已保存: {save_path} ({size_mb:.1f} MB, {frame_count} frames)")
        cv2.destroyAllWindows()
        print(f"[Done] 处理帧数: {frame_count}, 平均推理 FPS: {fps:.1f}")


if __name__ == "__main__":
    main()
