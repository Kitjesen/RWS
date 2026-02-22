"""IFF — Identification Friend-or-Foe safety filter.

Acts as a hard block in the fire decision chain: any target identified as
friendly results in fire_authorized=False for that target regardless of
other safety conditions.

Two identification modes:
1. **class_whitelist** : tracks whose class_id is in friendly_classes are
   automatically classified as friendly.
2. **track_id_whitelist** : specific track IDs designated as friendly by the
   operator at runtime (e.g. via the API).

Both lists are evaluated on every call to ``check()``.  A track is friendly
if it matches *either* list.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from ..types.perception import Track

logger = logging.getLogger(__name__)


@dataclass
class IFFResult:
    """Result of an IFF check for a single track.

    Attributes
    ----------
    track_id : int
        ID of the checked track.
    is_friend : bool
        True if the track has been identified as friendly.
    confidence : float
        Confidence of the identification in [0.0, 1.0].
    reason : str
        Human-readable explanation for the classification.
    """

    track_id: int
    is_friend: bool
    confidence: float
    reason: str


class IFFChecker:
    """Identification Friend-or-Foe filter.

    Two modes:
    1. ``class_whitelist``  : tracks whose ``class_id`` is in
       *friendly_classes* are classified as friends.
    2. ``track_id_whitelist``: specific track IDs marked as friendly by the
       operator (managed via :meth:`add_friendly_track` /
       :meth:`remove_friendly_track`).

    Any track marked as friend causes ``fire_authorized=False`` for that
    target in the pipeline.

    Thread-safety
    -------------
    The track-ID whitelist is protected by a ``threading.Lock`` so that
    API-layer calls from a different thread cannot race with the pipeline's
    ``step()`` thread.
    """

    def __init__(
        self,
        friendly_classes: frozenset[str] | set[str] = frozenset(),
        track_id_whitelist: set[int] | None = None,
    ) -> None:
        """
        Parameters
        ----------
        friendly_classes : frozenset[str] | set[str]
            Set of class_id strings that are considered friendly.
            Defaults to an empty frozenset (disabled).
        track_id_whitelist : set[int] | None
            Initial set of track IDs treated as friendly.
            Defaults to an empty set.
        """
        self._friendly_classes: frozenset[str] = frozenset(friendly_classes)
        self._lock = threading.Lock()
        self._track_id_whitelist: set[int] = (
            set(track_id_whitelist) if track_id_whitelist is not None else set()
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, tracks: list[Track]) -> dict[int, IFFResult]:
        """Run IFF check on a list of tracks.

        Parameters
        ----------
        tracks : list[Track]
            Tracks from the current perception frame.

        Returns
        -------
        dict[int, IFFResult]
            Mapping of track_id -> IFFResult for every track in *tracks*.
            Non-friendly tracks have ``is_friend=False``.
        """
        with self._lock:
            current_whitelist = set(self._track_id_whitelist)

        results: dict[int, IFFResult] = {}
        for track in tracks:
            tid = track.track_id

            # Check track-ID whitelist first (operator-designated).
            if tid in current_whitelist:
                results[tid] = IFFResult(
                    track_id=tid,
                    is_friend=True,
                    confidence=1.0,
                    reason=f"track_id {tid} is operator-designated friendly",
                )
                logger.debug("IFF: track %d flagged FRIEND (track_id whitelist)", tid)
                continue

            # Check class-based whitelist.
            if track.class_id in self._friendly_classes:
                results[tid] = IFFResult(
                    track_id=tid,
                    is_friend=True,
                    confidence=track.confidence,
                    reason=(
                        f"class_id '{track.class_id}' is in friendly_classes"
                        f" (conf={track.confidence:.2f})"
                    ),
                )
                logger.debug(
                    "IFF: track %d class '%s' flagged FRIEND", tid, track.class_id
                )
                continue

            # Not identified as friendly.
            results[tid] = IFFResult(
                track_id=tid,
                is_friend=False,
                confidence=track.confidence,
                reason="not in any friendly list",
            )

        return results

    def add_friendly_track(self, track_id: int) -> None:
        """Designate a track ID as friendly at runtime.

        Parameters
        ----------
        track_id : int
            Track ID to add to the operator whitelist.
        """
        with self._lock:
            self._track_id_whitelist.add(track_id)
        logger.info("IFF: track %d added to friendly whitelist", track_id)

    def remove_friendly_track(self, track_id: int) -> None:
        """Remove a track ID from the friendly whitelist.

        Parameters
        ----------
        track_id : int
            Track ID to remove.  No-op if not present.
        """
        with self._lock:
            self._track_id_whitelist.discard(track_id)
        logger.info("IFF: track %d removed from friendly whitelist", track_id)

    def is_friendly(self, track_id: int) -> bool:
        """Return True if *track_id* is currently in the operator whitelist.

        Note: this does *not* check class-based friendliness — for that,
        call :meth:`check` with the relevant Track object.

        Parameters
        ----------
        track_id : int
            Track ID to query.
        """
        with self._lock:
            return track_id in self._track_id_whitelist

    @property
    def friendly_track_ids(self) -> list[int]:
        """Snapshot of the current operator-designated friendly track IDs."""
        with self._lock:
            return sorted(self._track_id_whitelist)

    @property
    def friendly_classes(self) -> frozenset[str]:
        """The class-based friendly class set (immutable)."""
        return self._friendly_classes
