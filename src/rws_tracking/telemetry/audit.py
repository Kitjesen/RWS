"""Append-only audit log with SHA-256 hash chain.

Every fire-control event is recorded as an :class:`AuditRecord` and
persisted to a JSON-lines file.  Each record contains a ``prev_hash``
(SHA-256 of the previous record) forming a tamper-evident chain that
can be verified with :meth:`AuditLogger.verify_chain`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_GENESIS_HASH = "0" * 64


@dataclass
class AuditRecord:
    """Single audit log entry."""

    seq: int
    timestamp: float
    event_type: str
    operator_id: str
    chain_state: str
    target_id: int | None
    threat_score: float
    distance_m: float
    fire_authorized: bool
    blocked_reason: str
    prev_hash: str
    record_hash: str


def _compute_hash(record_dict: dict) -> str:
    """SHA-256 of the record JSON (without the ``record_hash`` field)."""
    d = {k: v for k, v in record_dict.items() if k != "record_hash"}
    raw = json.dumps(d, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


class AuditLogger:
    """Append-only audit logger with SHA-256 chain integrity.

    Parameters
    ----------
    log_path : str | Path
        Path to the JSON-lines audit file.  Created if it does not
        exist; appended to if it does.
    """

    def __init__(self, log_path: str | Path) -> None:
        self._path = Path(log_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._records: list[AuditRecord] = []
        self._seq = 0
        self._prev_hash = _GENESIS_HASH

        # Load existing records to continue the chain.
        if self._path.exists():
            self._load_existing()

    def _load_existing(self) -> None:
        with open(self._path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                rec = AuditRecord(**d)
                self._records.append(rec)
                self._seq = rec.seq + 1
                self._prev_hash = rec.record_hash

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log(
        self,
        event_type: str,
        operator_id: str,
        chain_state: str,
        target_id: int | None = None,
        threat_score: float = 0.0,
        distance_m: float = 0.0,
        fire_authorized: bool = False,
        blocked_reason: str = "",
    ) -> AuditRecord:
        """Append a new audit record and persist it."""
        rec_dict = {
            "seq": self._seq,
            "timestamp": time.time(),
            "event_type": event_type,
            "operator_id": operator_id,
            "chain_state": chain_state,
            "target_id": target_id,
            "threat_score": threat_score,
            "distance_m": distance_m,
            "fire_authorized": fire_authorized,
            "blocked_reason": blocked_reason,
            "prev_hash": self._prev_hash,
            "record_hash": "",
        }
        rec_dict["record_hash"] = _compute_hash(rec_dict)

        record = AuditRecord(**rec_dict)
        self._records.append(record)

        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(record), separators=(",", ":")))
            fh.write("\n")

        self._prev_hash = record.record_hash
        self._seq += 1
        return record

    def verify_chain(self) -> tuple[bool, str]:
        """Verify SHA-256 chain integrity.

        Returns
        -------
        tuple[bool, str]
            ``(True, "")`` if the chain is valid, otherwise
            ``(False, error_message)``.
        """
        prev_hash = _GENESIS_HASH
        for rec in self._records:
            if rec.prev_hash != prev_hash:
                return (
                    False,
                    f"seq {rec.seq}: prev_hash mismatch "
                    f"(expected {prev_hash}, got {rec.prev_hash})",
                )
            expected = _compute_hash(asdict(rec))
            if rec.record_hash != expected:
                return (
                    False,
                    f"seq {rec.seq}: record_hash mismatch "
                    f"(expected {expected}, got {rec.record_hash})",
                )
            prev_hash = rec.record_hash
        return (True, "")

    def get_recent(self, n: int = 50) -> list[AuditRecord]:
        """Return the *n* most recent records (newest last)."""
        return self._records[-n:]
