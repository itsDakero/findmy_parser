"""Shared row-building logic for the CSV/JSON/KML writers.

Kept here (rather than duplicated in each writer) since all three output
formats need the same tracker+fix join; each writer only differs in how
it serialises the resulting rows.
"""

from __future__ import annotations

import datetime
from typing import Any, Iterator

from ..beacons import content_hash
from ..discovery import DiscoveryResult

FIELDNAMES = [
    "tracker_id",
    "tracker_name",
    "tracker_emoji",
    "tracker_serial_number",
    "tracker_model",
    "tracker_source_kind",
    "latitude",
    "longitude",
    "horizontal_accuracy",
    "timestamp_utc",
    "timestamp_raw",
    "scan_date_utc",
    "scan_date_raw",
    "content_hash",
    "source_file",
]


def iter_rows(result: DiscoveryResult) -> Iterator[dict]:
    """One row per location fix, tracker-major then chronological.

    Every row carries the source file path (forensic traceability) and
    both the converted and raw timestamp values.
    """
    for fix in result.all_fixes():
        tracker = result.trackers.get(fix.tracker_id)
        yield {
            "tracker_id": fix.tracker_id,
            "tracker_name": tracker.name if tracker else None,
            "tracker_emoji": tracker.emoji if tracker else None,
            "tracker_serial_number": tracker.serial_number if tracker else None,
            "tracker_model": tracker.model if tracker else None,
            "tracker_source_kind": tracker.source_kind if tracker else "unknown",
            "latitude": fix.latitude,
            "longitude": fix.longitude,
            "horizontal_accuracy": fix.horizontal_accuracy,
            "timestamp_utc": fix.timestamp_utc,
            "timestamp_raw": _stringify_raw(fix.timestamp_raw),
            "scan_date_utc": fix.scan_date_utc,
            "scan_date_raw": _stringify_raw(fix.scan_date_raw),
            "content_hash": content_hash(fix),
            "source_file": fix.source_file,
        }


def _stringify_raw(value: Any) -> Any:
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value
