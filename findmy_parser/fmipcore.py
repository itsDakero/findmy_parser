"""Parse fmipcore cache inventory files (Items.data, Devices.data, ...).

    /private/var/mobile/Library/Caches/com.apple.findmy.fmipcore/
        Items.data      <- AirTags and third-party Find My accessories
        Devices.data    <- Apple devices on the same iCloud account
        ItemGroups.data
        SafeLocations.data
        FamilyMembers.data
        Owner.data

Unlike `.record` files, no real fixture of these was available to verify
against, so the field-name mapping below is best-effort: it tries a short
list of plausible key names per attribute (drawn from the task's stated
background plus public Find My forensics write-ups) and always keeps the
untouched source dict on `Tracker.raw` so nothing is lost if a guess is
wrong. Treat `name`/`emoji`/`serial_number`/`model`/last-known-location
as unconfirmed convenience fields, not a verified schema.

Only `identifier` is treated as load-bearing, per the task's background
("Each entry has an identifier (a UUID) ...").
"""

from __future__ import annotations

import json
import plistlib
from pathlib import Path
from typing import Any, Optional

from .models import Tracker
from .sniff import detect_format

# Maps a known fmipcore cache filename to the Tracker.source_kind it
# produces. Files not in this map still parse (source_kind falls back to
# the lowercased filename stem) since PA exports may rename or duplicate
# a file (e.g. "Items 2.data").
FILENAME_SOURCE_KIND = {
    "Items.data": "item",
    "Devices.data": "device",
    "ItemGroups.data": "item_group",
    "SafeLocations.data": "safe_location",
    "FamilyMembers.data": "family_member",
    "Owner.data": "owner",
}

# Trackers that can own a BeaconEstimatedLocation history: AirTags/items
# and paired Apple devices. The other fmipcore files (groups, safe
# locations, family members, the account owner) are not beacon-bearing.
LOCATABLE_SOURCE_KINDS = frozenset({"item", "device"})

_IDENTIFIER_KEYS = ("identifier",)
_NAME_KEYS = ("name",)
_EMOJI_KEYS = ("emoji",)
_SERIAL_KEYS = ("serialNumber", "serialNo", "serial")
_MODEL_KEYS = ("model", "modelName", "productType", "deviceModel", "modelDisplayName")
_LOCATION_KEYS = ("location",)
_LAT_KEYS = ("latitude", "lat")
_LON_KEYS = ("longitude", "lon", "lng")


class InventoryParseError(ValueError):
    """An fmipcore inventory payload could not be parsed as plist or JSON."""


def is_fmipcore_filename(name: str) -> bool:
    """True if `name` looks like an fmipcore cache inventory filename.

    Used by discovery.py to recognise these files by name anywhere under
    the input root (PA exports may not preserve the original directory
    layout). Matches the exact known names case-insensitively, plus any
    "*.data" file as a fallback for unlisted/renamed variants.
    """
    if name in FILENAME_SOURCE_KIND:
        return True
    lowered = name.lower()
    if lowered in {k.lower() for k in FILENAME_SOURCE_KIND}:
        return True
    return lowered.endswith(".data")


def _source_kind_for_filename(name: str) -> str:
    if name in FILENAME_SOURCE_KIND:
        return FILENAME_SOURCE_KIND[name]
    for known_name, kind in FILENAME_SOURCE_KIND.items():
        if name.lower() == known_name.lower():
            return kind
    stem = Path(name).stem
    return stem.lower() if stem else "unknown"


def parse_inventory_bytes(data: bytes, *, source_file: str) -> list[Tracker]:
    """Parse one fmipcore `.data` file's raw bytes into zero or more Trackers."""
    fmt = detect_format(data)
    if fmt in ("bplist", "xml_plist"):
        try:
            payload = plistlib.loads(data)
        except Exception as exc:
            raise InventoryParseError(f"{source_file}: could not parse plist: {exc}") from exc
    elif fmt == "json":
        try:
            payload = json.loads(data)
        except Exception as exc:
            raise InventoryParseError(f"{source_file}: could not parse JSON: {exc}") from exc
    else:
        raise InventoryParseError(
            f"{source_file}: unrecognised format (not bplist, XML plist, or JSON)"
        )

    entries = _extract_entries(payload)
    source_kind = _source_kind_for_filename(Path(source_file).name)

    trackers = []
    for entry in entries:
        tracker = _tracker_from_entry(entry, source_kind=source_kind, source_file=source_file)
        if tracker is not None:
            trackers.append(tracker)
    return trackers


def parse_inventory_file(path: Path) -> list[Tracker]:
    """Read and parse a single fmipcore inventory file from disk (read-only)."""
    data = path.read_bytes()
    return parse_inventory_bytes(data, source_file=str(path))


def _extract_entries(payload: Any) -> list[dict]:
    """Normalise a decoded payload into a list of entry dicts.

    The on-disk shape isn't confirmed (could be a bare list, or a dict
    wrapping the list under some key), so this tries, in order: a bare
    list of dicts; a dict wrapping a list of dicts under any key; a
    single dict that itself looks like one entry.
    """
    if isinstance(payload, list):
        return [e for e in payload if isinstance(e, dict)]

    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list) and all(isinstance(e, dict) for e in value) and value:
                return value
        if any(key in payload for key in _IDENTIFIER_KEYS):
            return [payload]

    return []


def _tracker_from_entry(entry: dict, *, source_kind: str, source_file: str) -> Optional[Tracker]:
    identifier = _first(entry, _IDENTIFIER_KEYS)
    if not identifier:
        return None

    location = _first(entry, _LOCATION_KEYS)
    lat = lon = None
    if isinstance(location, dict):
        lat = _as_float(_first(location, _LAT_KEYS))
        lon = _as_float(_first(location, _LON_KEYS))

    return Tracker(
        identifier=str(identifier),
        name=_first(entry, _NAME_KEYS),
        emoji=_first(entry, _EMOJI_KEYS),
        serial_number=_first(entry, _SERIAL_KEYS),
        model=_first(entry, _MODEL_KEYS),
        last_known_latitude=lat,
        last_known_longitude=lon,
        source_kind=source_kind,
        source_file=source_file,
        raw=entry,
    )


def _first(entry: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in entry and entry[key] is not None:
            return entry[key]
    return None


def _as_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
