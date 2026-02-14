"""Synthetic scene and target motion simulation for offline testing."""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import List


@dataclass
class SimTarget:
    x: float
    y: float
    w: float
    h: float
    vx: float
    vy: float
    confidence: float
    class_id: str


class SyntheticScene:
    def __init__(self, width: int, height: int, seed: int = 42) -> None:
        self.width = width
        self.height = height
        self.rng = random.Random(seed)
        self.targets: List[SimTarget] = []

    def add_target(self, target: SimTarget) -> None:
        self.targets.append(target)

    def step(self, dt: float) -> List[dict]:
        out = []
        for t in self.targets:
            t.x += t.vx * dt
            t.y += t.vy * dt
            if t.x < 0 or t.x + t.w > self.width:
                t.vx *= -1.0
                t.x = min(max(t.x, 0.0), self.width - t.w)
            if t.y < 0 or t.y + t.h > self.height:
                t.vy *= -1.0
                t.y = min(max(t.y, 0.0), self.height - t.h)
            noisy_x = t.x + self.rng.uniform(-1.5, 1.5)
            noisy_y = t.y + self.rng.uniform(-1.5, 1.5)
            out.append({
                "bbox": (noisy_x, noisy_y, t.w, t.h),
                "confidence": max(0.05, min(0.99, t.confidence + self.rng.uniform(-0.02, 0.02))),
                "class_id": t.class_id,
            })
        return out
