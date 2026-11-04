"""Core data types shared by every parsing module.

Kept free of I/O: nothing in here opens a file, and nothing sizes its
fields around a particular output format. That keeps this module safe to
import from the iLEAPP artifact module as well as the standalone CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class Tracker:
    """One entry from Items.data, Devices.data, or another fmipcore inventory file.

    ``identifier`` is the UUID that ties this tracker to its
    BeaconEstimatedLocation folder and, therefore, to zero or more
    LocationFix records.
    """

    identifier: str
    alt_identifiers: tuple[str, ...] = ()
    """Other IDs this entry carries that a beacon folder might be keyed by.

    Devices.data uses `baUUID` for the beacon-associated UUID while
    Items.data uses `identifier`; iLEAPP's own findMyCaches.py treats the
    two as one ID space. Correlation indexes a tracker under all of them,
    since which one matches a BeaconEstimatedLocation folder varies.
    """
    name: Optional[str] = None
    emoji: Optional[str] = None
    serial_number: Optional[str] = None
    model: Optional[str] = None
    last_known_latitude: Optional[float] = None
    last_known_longitude: Optional[float] = None
    pairing_date_utc: Optional[str] = None
    """When the beacon was paired to the account, ISO 8601 UTC.

    From OwnedBeacons/SharedBeacons `pairingDate` (confirmed present in a
    real export). Often evidentially significant: it bounds when a tracker
    entered the account, independently of any location fix.
    """
    pairing_date_raw: Any = None
    battery_level: Optional[float] = None
    """OwnedBeacons `batteryLevel`, as stored (observed as a 0-1 fraction)."""
    source_kind: str = "unknown"  # "item" | "device" | ... (see fmipcore.FILENAME_SOURCE_KIND)
    source_file: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


UNKNOWN_TRACKER = Tracker(identifier="", name=None, source_kind="unknown")
"""Sentinel used where a caller needs a placeholder rather than None."""


@dataclass(frozen=True)
class LocationFix:
    """One parsed ``.record`` beacon location fix.

    Only ``associatedBeacon``, ``latitude``, ``longitude``,
    ``horizontalAccuracy``, ``timestamp``, and ``scanDate`` are confirmed
    against real fixture data. ``confidence``, ``status``, and any other
    keys observed in a given file are preserved verbatim in ``raw`` rather
    than promoted to named fields, since their presence/type has not been
    confirmed.
    """

    tracker_id: str
    latitude: Optional[float]
    longitude: Optional[float]
    horizontal_accuracy: Optional[float]
    timestamp_utc: Optional[str]
    timestamp_raw: Any
    scan_date_utc: Optional[str]
    scan_date_raw: Any
    source_file: str
    raw: dict[str, Any] = field(default_factory=dict)

    def sort_key(self) -> tuple:
        # Fixes without any usable timestamp sort last, not first.
        return (self.timestamp_utc is None, self.timestamp_utc or "")
