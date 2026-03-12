from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class ProfileManager:
    """Loads and switches between named YAML mission profiles.

    Each profile is a YAML file in the profiles directory.
    """

    def __init__(self, profiles_dir: str | Path = "profiles"):
        self._dir = Path(profiles_dir)
        self._current: str | None = None

    def list_profiles(self) -> list[str]:
        """Return sorted list of available profile names."""
        if not self._dir.exists():
            return []
        return sorted(p.stem for p in self._dir.glob("*.yaml"))

    def get_profile_path(self, name: str) -> Path:
        return self._dir / f"{name}.yaml"

    def profile_exists(self, name: str) -> bool:
        return self.get_profile_path(name).exists()

    def load_profile(self, name: str):
        """Load and return a SystemConfig from a named profile.

        Returns the loaded SystemConfig, raises FileNotFoundError
        if not found.
        """
        from .loader import load_config

        path = self.get_profile_path(name)
        if not path.exists():
            raise FileNotFoundError(f"Profile '{name}' not found at {path}")
        cfg = load_config(str(path))
        self._current = name
        logger.info("loaded mission profile: %s", name)
        return cfg

    @property
    def current_profile(self) -> str | None:
        return self._current
