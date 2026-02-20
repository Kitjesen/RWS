from .pipeline import PipelineOutputs, VisionGimbalPipeline

__all__ = [
    "PipelineOutputs",
    "VisionGimbalPipeline",
    "build_sim_pipeline",
    "build_yolo_pipeline",
    "build_yolo_seg_pipeline",
    "build_pipeline_from_config",
    "run_camera_demo",
    "run_demo",
    "MultiGimbalPipeline",
    "GimbalUnit",
    "MultiGimbalOutputs",
]


def __getattr__(name: str):
    """Lazy imports to avoid pulling in cv2 / ultralytics at module level."""
    _app_names = {
        "build_sim_pipeline",
        "build_yolo_pipeline",
        "build_yolo_seg_pipeline",
        "build_pipeline_from_config",
        "run_camera_demo",
        "run_demo",
    }
    _multi_names = {
        "MultiGimbalPipeline": "multi_gimbal_pipeline",
        "GimbalUnit": "multi_gimbal_pipeline",
        "MultiGimbalOutputs": "multi_gimbal_pipeline",
    }
    if name in _app_names:
        from . import app
        return getattr(app, name)
    if name in _multi_names:
        import importlib
        mod = importlib.import_module(f".{_multi_names[name]}", __package__)
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
