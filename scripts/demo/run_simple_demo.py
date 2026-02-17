"""
Quick-start entry points.

Usage:
    python run_demo.py              # synthetic scene (no camera needed)
    python run_demo.py --camera     # live camera + YOLO11n
    python run_demo.py --camera --source 1 --classes person car
"""
from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="RWS Vision-Gimbal Tracking Demo")
    parser.add_argument("--camera", action="store_true", help="Use live camera + YOLO11n")
    parser.add_argument("--source", type=int, default=0, help="Camera index (default 0)")
    parser.add_argument("--model", type=str, default="yolo11n.pt", help="YOLO weight file")
    parser.add_argument("--classes", nargs="*", default=["person"], help="Class whitelist")
    parser.add_argument("--duration", type=float, default=12.0, help="Simulation duration (s)")
    args = parser.parse_args()

    if args.camera:
        from src.rws_tracking.pipeline import run_camera_demo

        run_camera_demo(
            source=args.source,
            model_path=args.model,
            class_whitelist=tuple(args.classes),
            show_window=True,
        )
    else:
        from src.rws_tracking.pipeline import run_demo

        metrics = run_demo(duration_s=args.duration, dt_s=0.03)
        print("Telemetry metrics:")
        for k, v in metrics.items():
            print(f"  {k}: {v:.4f}")


if __name__ == "__main__":
    main()
