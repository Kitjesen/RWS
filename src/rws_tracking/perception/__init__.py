"""Perception module -- re-exports from qp-perception standalone package."""

from .appearance_gallery import AppearanceGallery, GalleryConfig
from .cmc import CameraMotionCompensator
from .fusion_mot import FusionMOT, FusionMOTConfig
from .fusion_seg_tracker import FusionSegTracker
from .interfaces import Detector, TargetSelector, Tracker
from .multi_target import TargetAllocator, TargetAssignment
from .multi_target_selector import WeightedMultiTargetSelector
from .passthrough_detector import PassthroughDetector
from .reid_extractor import ReIDConfig, ReIDExtractor
from .selector import WeightedTargetSelector
from .tracker import SimpleIoUTracker
from .yolo_detector import YoloDetector
from .yolo_seg_tracker import YoloSegTracker

__all__ = [
    "AppearanceGallery",
    "CameraMotionCompensator",
    "Detector",
    "FusionMOT",
    "FusionMOTConfig",
    "FusionSegTracker",
    "GalleryConfig",
    "PassthroughDetector",
    "ReIDConfig",
    "ReIDExtractor",
    "SimpleIoUTracker",
    "TargetSelector",
    "Tracker",
    "WeightedTargetSelector",
    "YoloDetector",
    "YoloSegTracker",
    "WeightedMultiTargetSelector",
    "TargetAllocator",
    "TargetAssignment",
]
