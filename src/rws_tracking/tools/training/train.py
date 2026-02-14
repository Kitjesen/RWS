"""
YOLO 微调训练脚本
================

用法：
    # 默认参数（读 dataset/data.yaml，基于 yolo11n.pt 微调）
    python -m src.rws_tracking.tools.training.train

    # 自定义参数
    python -m src.rws_tracking.tools.training.train \
        --data   dataset/data.yaml \
        --model  yolo11n.pt \
        --epochs 100 \
        --batch  16 \
        --imgsz  640 \
        --device 0 \
        --name   rws_finetune

训练结果保存到：
    runs/<name>/weights/best.pt   ← 最优权重
    runs/<name>/weights/last.pt   ← 最后一轮权重

训练完成后，把 best.pt 路径填入 config.yaml → detector.model_path 即可接入 pipeline。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fine-tune YOLO11n on a custom dataset for RWS target tracking."
    )
    parser.add_argument(
        "--data",
        type=str,
        default="dataset/data.yaml",
        help="Path to data.yaml (default: dataset/data.yaml)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="yolo11n.pt",
        help="Base model to fine-tune from (default: yolo11n.pt, auto-downloads)",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=100,
        help="Number of training epochs (default: 100)",
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=16,
        help="Batch size (default: 16, reduce if GPU OOM)",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="Input image size (default: 640)",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="",
        help="Device: '0' for GPU 0, 'cpu' for CPU, '' for auto-select (default: auto)",
    )
    parser.add_argument(
        "--name",
        type=str,
        default="rws_finetune",
        help="Experiment name, results saved to runs/<name>/ (default: rws_finetune)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume training from last checkpoint (runs/<name>/weights/last.pt)",
    )
    parser.add_argument(
        "--freeze",
        type=int,
        default=0,
        help="Number of backbone layers to freeze (0 = train all, 10 = freeze backbone). "
             "Freezing backbone is recommended when dataset is small (<200 images).",
    )
    return parser.parse_args()


def validate_dataset(data_path: str) -> None:
    """Pre-flight check: make sure data.yaml and image dirs exist."""
    p = Path(data_path)
    if not p.exists():
        print(f"[ERROR] data.yaml not found: {p.resolve()}")
        print("        请先准备好数据集，参考 dataset/README.md")
        sys.exit(1)

    # Quick sanity check on image dirs
    import yaml  # type: ignore[import-untyped]

    with open(p, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    root = Path(cfg.get("path", p.parent))
    for split in ("train", "val"):
        img_dir = root / cfg.get(split, f"images/{split}")
        if not img_dir.exists():
            print(f"[ERROR] Image directory not found: {img_dir}")
            sys.exit(1)
        count = len(list(img_dir.glob("*.jpg")) + list(img_dir.glob("*.png")))
        if count == 0:
            print(f"[WARNING] No images found in {img_dir}")
            print(f"          请把 {split} 图片放进去再训练")
            sys.exit(1)
        print(f"  {split}: {count} images  ← {img_dir}")


def main() -> None:
    args = parse_args()

    print("=" * 60)
    print("  RWS YOLO Fine-Tuning")
    print("=" * 60)
    print(f"  data:    {args.data}")
    print(f"  model:   {args.model}")
    print(f"  epochs:  {args.epochs}")
    print(f"  batch:   {args.batch}")
    print(f"  imgsz:   {args.imgsz}")
    print(f"  device:  {args.device or 'auto'}")
    print(f"  name:    {args.name}")
    print(f"  freeze:  {args.freeze} layers")
    print(f"  resume:  {args.resume}")
    print("=" * 60)

    # --- Validate dataset ---
    print("\n[1/3] Validating dataset...")
    validate_dataset(args.data)

    # --- Load model ---
    print("\n[2/3] Loading base model...")
    from ultralytics import YOLO  # type: ignore[import-untyped]

    if args.resume:
        ckpt = Path("runs") / args.name / "weights" / "last.pt"
        if not ckpt.exists():
            print(f"[ERROR] Resume checkpoint not found: {ckpt}")
            sys.exit(1)
        model = YOLO(str(ckpt))
        print(f"  Resuming from {ckpt}")
    else:
        model = YOLO(args.model)
        print(f"  Base model loaded: {args.model}")

    # --- Train ---
    print("\n[3/3] Starting training...\n")
    model.train(
        data=args.data,
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device or None,
        project="runs",
        name=args.name,
        exist_ok=True,
        freeze=args.freeze if args.freeze > 0 else None,
        # Data augmentation (ultralytics defaults are good, override here if needed)
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,
        flipud=0.0,       # 上下翻转（目标一般不倒置，关掉）
        fliplr=0.5,        # 左右翻转
        mosaic=1.0,         # 马赛克增强
        mixup=0.1,          # mixup 增强
    )

    # --- Done ---
    best_pt = Path("runs") / args.name / "weights" / "best.pt"
    print("\n" + "=" * 60)
    print("  Training complete!")
    print(f"  Best weights: {best_pt.resolve()}")
    print()
    print("  Next step — 把路径填入 config.yaml:")
    print(f'    detector.model_path: "{best_pt}"')
    print("=" * 60)


if __name__ == "__main__":
    main()
