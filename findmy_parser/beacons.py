"""Parse searchpartyd `BeaconEstimatedLocation/<UUID>/*.record` files.

Each `.record` is a single location fix, normally a binary plist. Pure
parsing logic only — no file discovery, no logging/skip-and-continue
policy. Callers (discovery.py, cli.py, the iLEAPP module) decide what to
do with a `RecordParseError`.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import plistlib
from pathlib import Path
from typing import Any, Optional

from .models import LocationFix
from .sniff import detect_format
from .timestamps import normalize_timestamp

# Keys confirmed present, with confirmed types, against real .record
# fixture data (tests/fixtures/.../*.record.plist):
#   associatedBeacon: str (UUID)      identifier: str (UUID)
#   latitude: float                   longitude: float
#   horizontalAccuracy: float         locationSource: int
#   timestamp: datetime               scanDate: datetime
#   cloudKitMetadata: bytes
CONFIRMED_KEYS = frozenset(
    {
        "associatedBeacon",
        "identifier",
        "latitude",
        "longitude",
        "horizontalAccuracy",
        "timestamp",
        "scanDate",
        "locationSource",
        "cloudKitMetadata",
    }
)

# Mentioned in the task spec as "expected" but NOT confirmed against any
# real fixture. Preserved in `raw` when present; never assumed to exist,
# never promoted to a named LocationFix field.
UNCONFIRMED_KEYS = frozenset({"confidence", "status"})


class RecordParseError(ValueError):
    """A `.record` payload could not be parsed as plist or JSON."""


class EncryptedRecordError(RecordParseError):
    """The record is the signed/encrypted on-device form, not a readable fix.

    Raised for the wrapper file a Physical Analyzer export leaves beside
    its decrypted copy. Callers should treat this as an expected skip, not
    a failure: the same record is readable from the decrypted file.
    """


def parse_record_bytes(
    data: bytes, *, source_file: str, tracker_id_hint: Optional[str] = None
) -> LocationFix:
    """Parse the raw bytes of one `.record` file into a LocationFix.

    ``tracker_id_hint`` is used only when the payload itself has no
    ``associatedBeacon``/``identifier`` field — normally the UUID
    resolved by walking up the file's path (see discovery.py).
    """
    fmt = detect_format(data)
    if fmt in ("bplist", "xml_plist"):
        try:
            payload = plistlib.loads(data)
        except Exception as exc:  # plistlib raises several distinct exception types
            raise RecordParseError(f"{source_file}: could not parse plist: {exc}") from exc
    elif fmt == "json":
        try:
            payload = json.loads(data)
        except Exception as exc:
            raise RecordParseError(f"{source_file}: could not parse JSON: {exc}") from exc
    else:
        raise RecordParseError(
            f"{source_file}: unrecognised format (not bplist, XML plist, or JSON)"
        )

    if not isinstance(payload, dict):
        payload = _unwrap_container(payload, source_file)

    return _fix_from_payload(payload, source_file=source_file, tracker_id_hint=tracker_id_hint)


def _unwrap_container(payload: Any, source_file: str) -> dict:
    """Find the usable record inside a non-dict top level, or refuse it.

    A Physical Analyzer export carries each record twice: the on-device
    file, whose top level is a short list (the signed/encrypted wrapper -
    observed as 3 elements), and a decrypted copy beside it under
    "<uuid>_1.record/<uuid>.record.plist", whose top level is the dict of
    actual fields.

    A list is searched for a dict that actually looks like a fix, in case
    some export nests it rather than encrypting it. Failing that the file
    is the wrapper form and raises EncryptedRecordError, which callers
    treat as an expected skip rather than a parse failure - the decrypted
    copy alongside it is where the data is.
    """
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and (CONFIRMED_KEYS & item.keys()):
                return item
        raise EncryptedRecordError(
            f"{source_file}: top level is a {len(payload)}-element list holding no "
            "location fields - the signed/encrypted on-device form; read the "
            "decrypted copy instead"
        )

    raise RecordParseError(
        f"{source_file}: expected a dict at top level, got {type(payload).__name__}"
    )


def parse_record_file(path: Path, *, tracker_id_hint: Optional[str] = None) -> LocationFix:
    """Read and parse a single `.record` file from disk (read-only)."""
    data = path.read_bytes()
    return parse_record_bytes(data, source_file=str(path), tracker_id_hint=tracker_id_hint)


def _fix_from_payload(
    payload: dict[str, Any], *, source_file: str, tracker_id_hint: Optional[str]
) -> LocationFix:
    tracker_id = payload.get("associatedBeacon") or payload.get("identifier") or tracker_id_hint or ""

    ts = normalize_timestamp(payload.get("timestamp"))
    scan = normalize_timestamp(payload.get("scanDate"))

    return LocationFix(
        tracker_id=tracker_id,
        latitude=_as_float(payload.get("latitude")),
        longitude=_as_float(payload.get("longitude")),
        horizontal_accuracy=_as_float(payload.get("horizontalAccuracy")),
        timestamp_utc=ts.iso_utc,
        timestamp_raw=ts.raw,
        scan_date_utc=scan.iso_utc,
        scan_date_raw=scan.raw,
        source_file=source_file,
        raw=payload,
    )


def _as_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def content_hash(fix: LocationFix) -> str:
    """Stable hash of a fix's parsed field values, excluding provenance.

    The same logical record can be exported into more than one nested
    Physical Analyzer output folder. Two `LocationFix` objects built from
    such duplicates should hash identically here so discovery.py can drop
    the extras — `source_file` is intentionally excluded from the hash.
    """
    payload = {
        "tracker_id": fix.tracker_id,
        "latitude": fix.latitude,
        "longitude": fix.longitude,
        "horizontal_accuracy": fix.horizontal_accuracy,
        "timestamp_utc": fix.timestamp_utc,
        "scan_date_utc": fix.scan_date_utc,
        "raw": _jsonable(fix.raw),
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _jsonable(value: Any) -> Any:
    """Recursively coerce plist-only types (datetime, bytes) to JSON-safe values."""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.hex()
    return value
