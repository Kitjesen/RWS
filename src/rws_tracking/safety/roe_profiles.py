"""Rules of Engagement (ROE) profile system.

Profiles define the operational constraints under which the weapon system may
engage.  Three built-in profiles cover the most common operational contexts:

  training  — Maximum restrictions.  Fire is always blocked (dry-fire only).
              Used for operator training and system testing.

  exercise  — Reduced restrictions.  Engagement is allowed in a
              simulation/exercise context. Shorter lock time, wider NFZ
              margins.

  live      — Full operational rules.  Maximum safety checks enforced.
              Longest lock time, tightest NFZ margins, two-man rule
              recommended.

Custom profiles can be added at runtime via ``RoeManager.add_profile()``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RoeProfile:
    """A single Rules of Engagement profile.

    Attributes
    ----------
    name:
        Machine-readable identifier (used in API calls).
    display_name:
        Human-readable label (may include unicode / locale strings).
    fire_enabled:
        When ``False`` the pipeline will suppress the actual fire command even
        if the shooting chain reports ``can_fire=True`` (dry-fire / training
        mode).
    min_lock_time_s:
        Minimum continuous LOCK duration before fire is authorised.  Should be
        consistent with ``SafetyInterlockConfig.min_lock_time_s`` but is
        enforced independently so that ROE changes take effect immediately
        without rebuilding the safety manager.
    max_engagement_range_m:
        Targets beyond this range will not be engaged regardless of threat
        score.
    nfz_buffer_multiplier:
        Multiplier applied to the no-fire zone buffer radius at query time.
        ``1.0`` = normal radius, ``2.0`` = double the caution margin.
    require_two_man:
        When ``True`` the ``ShootingChain`` two-man rule must be enabled before
        the chain is allowed to arm.
    description:
        Short human-readable description shown in the UI.
    """

    name: str
    display_name: str
    fire_enabled: bool
    min_lock_time_s: float
    max_engagement_range_m: float
    nfz_buffer_multiplier: float
    require_two_man: bool
    description: str = ""


# ---------------------------------------------------------------------------
# Built-in profiles
# ---------------------------------------------------------------------------

BUILTIN_PROFILES: dict[str, RoeProfile] = {
    "training": RoeProfile(
        name="training",
        display_name="训练模式 (Training)",
        fire_enabled=False,
        min_lock_time_s=0.0,
        max_engagement_range_m=9999.0,
        nfz_buffer_multiplier=1.0,
        require_two_man=False,
        description=(
            "Dry-fire only. All engagement outputs suppressed. "
            "Safe for operator training and system integration testing."
        ),
    ),
    "exercise": RoeProfile(
        name="exercise",
        display_name="演习模式 (Exercise)",
        fire_enabled=True,
        min_lock_time_s=1.0,
        max_engagement_range_m=200.0,
        nfz_buffer_multiplier=1.5,
        require_two_man=False,
        description=(
            "Exercise / simulation context. Engagement enabled with relaxed "
            "constraints and extended NFZ caution margin."
        ),
    ),
    "live": RoeProfile(
        name="live",
        display_name="实战模式 (Live)",
        fire_enabled=True,
        min_lock_time_s=2.0,
        max_engagement_range_m=100.0,
        nfz_buffer_multiplier=2.0,
        require_two_man=True,
        description=(
            "Live operations. Maximum safety constraints enforced. "
            "Two-man arming rule required."
        ),
    ),
}


# ---------------------------------------------------------------------------
# ROE manager
# ---------------------------------------------------------------------------


class RoeManager:
    """Manages the active ROE profile and provides fire-permission queries.

    Parameters
    ----------
    initial_profile:
        Name of the profile to activate at construction time.
        Must be a key in ``BUILTIN_PROFILES`` or a custom profile added via
        ``add_profile()``.  Defaults to ``"training"`` (safest).

    Usage
    -----
    ::

        roe = RoeManager("training")
        roe.is_fire_enabled()   # False — dry-fire mode
        roe.switch_profile("exercise")
        roe.is_fire_enabled()   # True
    """

    def __init__(self, initial_profile: str = "training") -> None:
        self._profiles: dict[str, RoeProfile] = dict(BUILTIN_PROFILES)
        if initial_profile not in self._profiles:
            raise ValueError(
                f"Unknown initial ROE profile: {initial_profile!r}. "
                f"Available: {list(self._profiles)}"
            )
        self._active: RoeProfile = self._profiles[initial_profile]
        logger.info(
            "ROE initialised: profile=%s fire_enabled=%s",
            self._active.name,
            self._active.fire_enabled,
        )

    # ------------------------------------------------------------------
    # Profile management
    # ------------------------------------------------------------------

    @property
    def active(self) -> RoeProfile:
        """The currently active ``RoeProfile``."""
        return self._active

    def switch_profile(self, name: str) -> RoeProfile:
        """Switch to the named profile and return it.

        Raises
        ------
        ValueError
            If *name* is not a registered profile.
        """
        if name not in self._profiles:
            raise ValueError(
                f"Unknown ROE profile: {name!r}. "
                f"Available: {list(self._profiles)}"
            )
        old = self._active.name
        self._active = self._profiles[name]
        logger.warning(
            "ROE profile changed: %s -> %s (fire_enabled=%s require_two_man=%s)",
            old,
            name,
            self._active.fire_enabled,
            self._active.require_two_man,
        )
        return self._active

    def add_profile(self, profile: RoeProfile) -> None:
        """Register a custom ROE profile.

        Custom profiles can extend or override built-in profiles.  The built-in
        ``training`` / ``exercise`` / ``live`` names can be overridden but this
        is not recommended.
        """
        self._profiles[profile.name] = profile
        logger.info("ROE custom profile registered: %s", profile.name)

    def list_profiles(self) -> list[dict]:
        """Return a list of profile summary dicts suitable for JSON serialisation."""
        return [
            {
                "name": p.name,
                "display_name": p.display_name,
                "active": p.name == self._active.name,
                "fire_enabled": p.fire_enabled,
                "min_lock_time_s": p.min_lock_time_s,
                "max_engagement_range_m": p.max_engagement_range_m,
                "nfz_buffer_multiplier": p.nfz_buffer_multiplier,
                "require_two_man": p.require_two_man,
                "description": p.description,
            }
            for p in self._profiles.values()
        ]

    # ------------------------------------------------------------------
    # Fire-permission helpers
    # ------------------------------------------------------------------

    def is_fire_enabled(self) -> bool:
        """Return ``True`` only when the active profile permits actual fire."""
        return self._active.fire_enabled
