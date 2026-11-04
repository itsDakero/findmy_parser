"""Parse the searchpartyd folders that describe beacons themselves.

    .../com.apple.icloud.searchpartyd/
        BeaconEstimatedLocation/<UUID>/*.record   <- location fixes
        OwnedBeacons/<UUID>.record                <- beacons owned by this account
        SharedBeacons/<UUID>.record               <- beacons shared with this account
        BeaconNamingRecord/<UUID>/*.record        <- friendly naming info

Every one of these is named `*.record`, so the *folder* a file sits under
is what distinguishes a location fix from beacon metadata - the filename
alone can't. `classify_record_path()` does that, and matters a lot: without
it, an `OwnedBeacons/<UUID>.record` gets parsed as if it were a location
fix and lands in the output as a coordinate-less junk row.

These are keyed by the same beacon UUID as BeaconEstimatedLocation, which
makes them a far more reliable source of a tracker's friendly name than
fmipcore's `Items.data`/`Devices.data` (whose `identifier` may or may not
be the same UUID at all).

The exact key names inside these files are NOT confirmed against real
data - a short list of plausible candidates is tried per attribute and
the untouched source dict is always kept on `raw`, same defensive
approach as fmipcore.py.
"""

from __future__ import annotations

import json
import plistlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .sniff import detect_format

LOCATION_DIR = "beaconestimatedlocation"

# Folder name (lowercased) -> the metadata kind it holds.
METADATA_DIRS = {
    "ownedbeacons": "owned_beacon",
    "sharedbeacons": "shared_beacon",
    "beaconnamingrecord": "naming_record",
}

# Which metadata kind wins when more than one names the same beacon.
# A naming record is purpose-built for exactly this, so it outranks the
# ownership records.
METADATA_PRIORITY = {"naming_record": 3, "owned_beacon": 2, "shared_beacon": 1}

_NAME_KEYS = ("name", "displayName", "label", "beaconName", "title")
_EMOJI_KEYS = ("emoji", "icon", "glyph")
_MODEL_KEYS = ("model", "modelName", "productType", "deviceModel", "modelDisplayName")
_SERIAL_KEYS = ("serialNumber", "serialNo", "serial")
_IDENTIFIER_KEYS = ("associatedBeacon", "identifier", "beaconIdentifier", "stableIdentifier")

# Confirmed against a real OwnedBeacons/<uuid>.record.plist: batteryLevel,
# cloudKitMetadata, groupIdentifier, identifier, isZeus, model, pairingDate,
# privateKey, productId, publicKey, secondarySharedSecret, sharedSecret,
# stableIdentifier, systemVersion, vendorId. Notably there is NO name field,
# so OwnedBeacons supplies a model but never a friendly name.
_KNOWN_METADATA_KEYS = frozenset(
    _NAME_KEYS
    + _EMOJI_KEYS
    + _MODEL_KEYS
    + _SERIAL_KEYS
    + _IDENTIFIER_KEYS
    + ("pairingDate", "batteryLevel", "stableIdentifier", "groupIdentifier", "productId")
)

_MAX_SEARCH_DEPTH = 3


class MetadataParseError(ValueError):
    """A searchpartyd metadata record could not be parsed."""


class EncryptedMetadataError(MetadataParseError):
    """The record is the signed/encrypted on-device form, not readable fields.

    As with location records, a Physical Analyzer export leaves the
    wrapper file (top level a short list) beside a decrypted copy under
    "<uuid>_1.record/<uuid>.record.plist". An expected skip, not a failure.
    """


@dataclass(frozen=True)
class BeaconMetadata:
    """Naming/ownership info for one beacon, from a non-location record."""

    tracker_id: str
    name: Optional[str] = None
    emoji: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    kind: str = "unknown"
    source_file: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def priority(self) -> int:
        return METADATA_PRIORITY.get(self.kind, 0)


def classify_record_path(path: Path) -> str:
    """Return "location" or a metadata kind, based on the owning folder.

    The nearest matching ancestor folder wins. Matched as a substring
    rather than an exact name, because Physical Analyzer has been
    observed to rename/wrap folders on export (e.g. "Items_1.data" around
    "Items.data.decrypted") - an exact match would silently misclassify
    the contents of an "OwnedBeacons_1.data" folder as location fixes.

    Falls back to "location" when no searchpartyd folder is recognisable
    in the path, preserving the behaviour for loose/unusually-exported
    `.record` files.
    """
    for part in reversed([p.lower() for p in path.parts]):
        for dir_name, kind in METADATA_DIRS.items():
            if dir_name in part:
                return kind
        if LOCATION_DIR in part:
            return "location"
    return "location"


def parse_metadata_bytes(
    data: bytes, *, source_file: str, kind: str, tracker_id_hint: Optional[str] = None
) -> BeaconMetadata:
    """Parse one OwnedBeacons/SharedBeacons/BeaconNamingRecord file."""
    fmt = detect_format(data)
    if fmt in ("bplist", "xml_plist"):
        try:
            payload = plistlib.loads(data)
        except Exception as exc:
            raise MetadataParseError(f"{source_file}: could not parse plist: {exc}") from exc
    elif fmt == "json":
        try:
            payload = json.loads(data)
        except Exception as exc:
            raise MetadataParseError(f"{source_file}: could not parse JSON: {exc}") from exc
    else:
        raise MetadataParseError(
            f"{source_file}: unrecognised format (not bplist, XML plist, or JSON)"
        )

    if not isinstance(payload, dict):
        if isinstance(payload, list):
            inner = next(
                (
                    item
                    for item in payload
                    if isinstance(item, dict) and (_KNOWN_METADATA_KEYS & item.keys())
                ),
                None,
            )
            if inner is None:
                raise EncryptedMetadataError(
                    f"{source_file}: top level is a {len(payload)}-element list holding no "
                    "beacon fields - the signed/encrypted on-device form; read the "
                    "decrypted copy instead"
                )
            payload = inner
        else:
            raise MetadataParseError(
                f"{source_file}: expected a dict at top level, got {type(payload).__name__}"
            )

    tracker_id = _find_first(payload, _IDENTIFIER_KEYS) or tracker_id_hint or ""

    return BeaconMetadata(
        tracker_id=str(tracker_id),
        name=_as_str(_find_first(payload, _NAME_KEYS)),
        emoji=_as_str(_find_first(payload, _EMOJI_KEYS)),
        model=_as_str(_find_first(payload, _MODEL_KEYS)),
        serial_number=_as_str(_find_first(payload, _SERIAL_KEYS)),
        kind=kind,
        source_file=source_file,
        raw=payload,
    )


def parse_metadata_file(
    path: Path, *, kind: str, tracker_id_hint: Optional[str] = None
) -> BeaconMetadata:
    """Read and parse one metadata record from disk (read-only)."""
    return parse_metadata_bytes(
        path.read_bytes(), source_file=str(path), kind=kind, tracker_id_hint=tracker_id_hint
    )


def _find_first(payload: Any, keys: tuple[str, ...], _depth: int = 0) -> Any:
    """Find the first present, non-empty value for any of `keys`.

    Searches nested dicts/lists to a bounded depth, since these records
    have been observed to wrap their useful fields at varying levels and
    the exact shape isn't confirmed.
    """
    if _depth > _MAX_SEARCH_DEPTH:
        return None

    if isinstance(payload, dict):
        for key in keys:
            value = payload.get(key)
            if value not in (None, "", {}, []):
                # A nested container under a matching key isn't the value
                # itself - keep descending rather than returning a dict.
                if not isinstance(value, (dict, list)):
                    return value
        for value in payload.values():
            found = _find_first(value, keys, _depth + 1)
            if found is not None:
                return found

    elif isinstance(payload, list):
        for item in payload:
            found = _find_first(item, keys, _depth + 1)
            if found is not None:
                return found

    return None


def _as_str(value: Any) -> Optional[str]:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None
