from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

BENCHMARK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCHMARK_DIR.parent.parent.parent
sys.path.insert(0, str(BENCHMARK_DIR))
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from benchmark_metrics import markdown_comparison_table  # noqa: E402
from run_pose_activity_demo import TRACKING_PRESETS, run_activity_demo  # noqa: E402


DEFAULT_OUTPUT_DIR = Path(r'D:\inovxio\brain\tmp\pose_preset_customer_compare')


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, default=BENCHMARK_DIR / 'test_people.mp4')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument('--presets', nargs='+', choices=tuple(TRACKING_PRESETS), default=['balanced', 'crowd-recall'])
    parser.add_argument('--tracking-backend', choices=('seg',), default='seg')
    parser.add_argument('--pose-model', type=str, default='yolo11s-pose.pt')
    parser.add_argument('--device', type=str, default='')
    parser.add_argument('--max-frames', type=int, default=None)
    parser.add_argument('--skip-transcode', action='store_true')
    parser.add_argument('--keep-raw', action='store_true')
    return parser.parse_args()


def _build_demo_args(
    video: Path,
    output: Path,
    preset: str,
    tracking_backend: str,
    pose_model: str,
    device: str,
    max_frames: int | None,
) -> argparse.Namespace:
    return argparse.Namespace(
        video=video,
        output=output,
        tracking_backend=tracking_backend,
        tracking_preset=preset,
        tracking_model=None,
        rtdetr_model='rtdetr-l.pt',
        pose_model=pose_model,
        imgsz=None,
        tracking_confidence=None,
        tracking_low_confidence=None,
        tracking_max_detections=None,
        pose_confidence=0.18,
        rtdetr_track_activation=0.20,
        rtdetr_lost_track_buffer=45,
        rtdetr_match_threshold=0.75,
        rtdetr_min_consecutive_frames=1,
        w_skeleton=0.06,
        skeleton_gate=1.2,
        kp_visibility_thresh=0.2,
        hold_frames=4,
        show_ghosts=False,
        bbox_alpha=1.0,
        pose_iou_threshold=0.2,
        show_predicted=False,
        min_display_age=3,
        show_traces=False,
        trace_length=8,
        min_trace_age=8,
        trace_jump_factor=1.0,
        min_trace_iou=0.3,
        device=device,
        max_frames=max_frames,
    )


def _transcode_h264(input_path: Path, output_path: Path) -> bool:
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg is None:
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        '-y',
        '-i',
        str(input_path),
        '-c:v',
        'libx264',
        '-preset',
        'slow',
        '-crf',
        '18',
        '-pix_fmt',
        'yuv420p',
        '-movflags',
        '+faststart',
        str(output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    return completed.returncode == 0 and output_path.exists()


def _build_report(
    video_path: Path,
    artifacts: list[dict[str, str]],
    generated_at: str,
) -> str:
    by_name = {artifact['name']: artifact for artifact in artifacts}
    balanced = by_name['balanced']
    crowd = by_name['crowd-recall']
    people_delta = crowd['metrics']['average_people_per_frame'] - balanced['metrics']['average_people_per_frame']
    latency_delta = crowd['metrics']['average_frame_latency_ms'] - balanced['metrics']['average_frame_latency_ms']
    unique_id_delta = crowd['metrics']['unique_ids'] - balanced['metrics']['unique_ids']

    lines = [
        '# Pose Preset Customer Comparison',
        '',
        f'- Generated: {generated_at}',
        f'- Source video: {video_path}',
        '',
        '## Recommendation',
        '',
        '- Default profile: `balanced`. It keeps lower `Unique IDs` and lower frame latency on this video, so it is the safer default for customer demos.',
        f'- Crowd profile: `crowd-recall`. It shows `{people_delta:.2f}` more people per frame on average, but it also adds `{unique_id_delta}` more `Unique IDs` and `{latency_delta:.1f} ms` more average frame latency.',
        '',
        '## Metrics',
        '',
        markdown_comparison_table([balanced['summary'], crowd['summary']]),
        '',
        '## Outputs',
        '',
    ]
    for artifact in artifacts:
        if artifact['raw_video']:
            lines.append(f"- `{artifact['name']}` raw: `{artifact['raw_video']}`")
        lines.append(f"- `{artifact['name']}` customer: `{artifact['customer_video']}`")
    return '\n'.join(lines) + '\n'


def main() -> int:
    args = _parse_args()
    if not args.video.exists():
        raise SystemExit(f'Video not found: {args.video}')

    output_dir = args.output_dir / args.video.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts: list[dict[str, object]] = []
    for preset in args.presets:
        raw_video = output_dir / f'{args.video.stem}_{preset}_raw.mp4'
        customer_video = output_dir / f'{args.video.stem}_{preset}_h264.mp4'
        demo_args = _build_demo_args(
            video=args.video,
            output=raw_video,
            preset=preset,
            tracking_backend=args.tracking_backend,
            pose_model=args.pose_model,
            device=args.device,
            max_frames=args.max_frames,
        )
        result = run_activity_demo(demo_args)
        final_video = raw_video
        raw_video_ref: str | None = str(raw_video)
        if not args.skip_transcode:
            if _transcode_h264(raw_video, customer_video):
                final_video = customer_video
        if not args.keep_raw and final_video != raw_video and raw_video.exists():
            raw_video.unlink()
            raw_video_ref = None
        artifacts.append(
            {
                'name': preset,
                'raw_video': raw_video_ref,
                'customer_video': str(final_video),
                'metrics': asdict(result.metrics),
                'summary': result.metrics,
            }
        )

    generated_at = datetime.now().astimezone().isoformat(timespec='seconds')
    report_path = output_dir / 'pose_preset_comparison_report.md'
    report_path.write_text(_build_report(args.video, artifacts, generated_at), encoding='utf-8')

    json_path = output_dir / 'pose_preset_comparison_metrics.json'
    json_ready = []
    for artifact in artifacts:
        json_ready.append(
            {
                'name': artifact['name'],
                'raw_video': artifact['raw_video'],
                'customer_video': artifact['customer_video'],
                'metrics': artifact['metrics'],
            }
        )
    json_path.write_text(json.dumps(json_ready, ensure_ascii=False, indent=2), encoding='utf-8')

    print('\n' + '=' * 72)
    print('POSE PRESET COMPARISON COMPLETE')
    print('=' * 72)
    print(f'Report : {report_path}')
    print(f'Metrics: {json_path}')
    for artifact in artifacts:
        print(f"{artifact['name']}: {artifact['customer_video']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())