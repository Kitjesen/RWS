"""Allow ``python -m src.rws_tracking.tools.sim`` to launch SIL."""
from .run_sil import parse_args, run_sil

args = parse_args()
run_sil(
    pattern=args.pattern,
    duration_s=args.duration,
    control_hz=args.hz,
    use_yolo=args.yolo,
    model_path=args.model,
    device=args.device,
    show=args.show,
)
