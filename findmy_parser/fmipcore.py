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

Real-world fmipcore `.data` files have been observed to be NSKeyedArchiver-
wrapped bplists rather than a plain plist/JSON structure - `plistlib` alone
parses the raw `$objects`/`$top` table but doesn't dereference it or
reassemble NSDictionary/NSArray/NSDate from their archived form. Detected
via the `$archiver` key and decoded with the vendored `ccl_bplist` (see
`findmy_parser/_vendor/NOTICE.md`) before the field-name guessing above
ever runs.
"""

from __future__ import annotations

import io
import json
import plistlib
from pathlib import Path
from typing import Any, Optional

from ._vendor import ccl_bplist
from .models import Tracker

_NSKEYEDARCHIVER_MARKERS = ("NSKeyedArchiver", "NRKeyedArchiver")
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

# identifier/name/serialNumber/location/productType confirmed against a
# real Items.data entry (7-entry top-level list); emoji is not among that
# entry's keys (kept as a candidate anyway - preserved via `raw` either way).
# Items.data keys its entries by `identifier`; Devices.data uses `baUUID`
# for the beacon-associated UUID (iLEAPP's findMyCaches.py treats the two
# as one ID space). Both are collected so correlation can match whichever
# one a BeaconEstimatedLocation folder is actually named after.
_IDENTIFIER_KEYS = ("identifier", "baUUID")
_NAME_KEYS = ("name",)
_EMOJI_KEYS = ("emoji",)
_SERIAL_KEYS = ("serialNumber", "serialNo", "serial")
_LOCATION_KEYS = ("location",)
_LAT_KEYS = ("latitude", "lat")
_LON_KEYS = ("longitude", "lon", "lng")

# The model name is nested three levels deep - productType.productInformation.modelName -
# not a flat string field (confirmed against real data). "model"/"deviceModel"/
# "modelDisplayName" are kept as flat fallbacks for schemas that don't nest it
# this way (e.g. an unconfirmed possible difference in Devices.data).
_PRODUCT_TYPE_KEYS = ("productType",)
_PRODUCT_INFORMATION_KEYS = ("productInformation",)
_MODEL_NAME_KEYS = ("modelName",)
_FLAT_MODEL_FALLBACK_KEYS = ("model", "deviceModel", "modelDisplayName")


class InventoryParseError(ValueError):
    """An fmipcore inventory payload could not be parsed as plist or JSON."""


def is_fmipcore_filename(name: str) -> bool:
    """True if `name` looks like an fmipcore cache inventory filename.

    Used by discovery.py to recognise these files by name anywhere under
    the input root (PA exports may not preserve the original directory
    layout, and confirmed against real exports commonly append a suffix,
    e.g. "Devices.data.decrypted" rather than "Devices.data" exactly - so
    this matches a known name as a *substring*, not just an exact name or
    a ".data" suffix, mirroring how .record files are matched).
    """
    lowered = name.lower()
    if any(known_name.lower() in lowered for known_name in FILENAME_SOURCE_KIND):
        return True
    return ".data" in lowered


def _source_kind_for_filename(name: str) -> str:
    lowered = name.lower()
    for known_name, kind in FILENAME_SOURCE_KIND.items():
        if known_name.lower() in lowered:
            return kind
    stem = Path(name).stem
    return stem.lower() if stem else "unknown"


def parse_inventory_bytes(data: bytes, *, source_file: str) -> list[Tracker]:
    """Parse one fmipcore `.data` file's raw bytes into zero or more Trackers."""
    fmt = detect_format(data)
    if fmt == "bplist":
        payload = _load_bplist_payload(data, source_file)
    elif fmt == "xml_plist":
        try:
            payload = plistlib.loads(data)
        except Exception as exc:
            raise InventoryParseError(f"{source_file}: could not parse plist: {exc}") from exc
        if isinstance(payload, dict) and payload.get("$archiver") in _NSKEYEDARCHIVER_MARKERS:
            # ccl_bplist only reads the binary bplist container format, so
            # an XML-format NSKeyedArchiver can't be decoded here - fail
            # loudly rather than silently returning the raw $objects/$top
            # wrapper, which _extract_entries() would misread as empty.
            raise InventoryParseError(
                f"{source_file}: NSKeyedArchiver-wrapped XML plist is not supported "
                "(only the binary bplist form is)"
            )
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


def _load_bplist_payload(data: bytes, source_file: str) -> Any:
    """Parse binary plist bytes, transparently decoding an NSKeyedArchiver wrapper.

    `plistlib` alone is used first purely to detect the `$archiver` marker
    cheaply (it happily parses the raw, un-dereferenced structure without
    error). If present, the same bytes are re-parsed from scratch with
    ccl_bplist, whose UID/`$objects` representation is not compatible with
    plistlib's - the two parsers can't be mixed, so this re-parses rather
    than reusing the first pass's result.
    """
    try:
        payload = plistlib.loads(data)
    except Exception as exc:
        raise InventoryParseError(f"{source_file}: could not parse plist: {exc}") from exc

    if not (isinstance(payload, dict) and payload.get("$archiver") in _NSKEYEDARCHIVER_MARKERS):
        return payload

    try:
        ccl_bplist.set_object_converter(ccl_bplist.NSKeyedArchiver_common_objects_convertor)
        raw = ccl_bplist.load(io.BytesIO(data))
        return ccl_bplist.deserialise_NsKeyedArchiver(raw)
    except Exception as exc:
        raise InventoryParseError(
            f"{source_file}: detected NSKeyedArchiver wrapper but could not decode it: {exc}"
        ) from exc


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

    # Every other ID this entry carries, so a beacon folder keyed by the
    # non-primary one still correlates.
    alt_identifiers = tuple(
        str(entry[key])
        for key in _IDENTIFIER_KEYS
        if key in entry and entry[key] is not None and str(entry[key]) != str(identifier)
    )

    location = _first(entry, _LOCATION_KEYS)
    lat = lon = None
    if isinstance(location, dict):
        lat = _as_float(_first(location, _LAT_KEYS))
        lon = _as_float(_first(location, _LON_KEYS))

    return Tracker(
        identifier=str(identifier),
        alt_identifiers=alt_identifiers,
        name=_first(entry, _NAME_KEYS),
        emoji=_first(entry, _EMOJI_KEYS),
        serial_number=_first(entry, _SERIAL_KEYS),
        model=_extract_model(entry),
        last_known_latitude=lat,
        last_known_longitude=lon,
        source_kind=source_kind,
        source_file=source_file,
        raw=entry,
    )


def _extract_model(entry: dict) -> Optional[str]:
    """Model name lives at productType.productInformation.modelName."""
    product_type = _first(entry, _PRODUCT_TYPE_KEYS)
    if isinstance(product_type, dict):
        product_information = _first(product_type, _PRODUCT_INFORMATION_KEYS)
        if isinstance(product_information, dict):
            model_name = _first(product_information, _MODEL_NAME_KEYS)
            if model_name:
                return str(model_name)
    return _first(entry, _FLAT_MODEL_FALLBACK_KEYS)


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
