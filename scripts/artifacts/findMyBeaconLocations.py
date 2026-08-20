__artifacts_v2__ = {
    "findMyBeaconLocations": {
        "name": "Find My Beacon Estimated Locations",
        "description": (
            "Location history for AirTags and other Find My-compatible trackers/"
            "devices, parsed from searchpartyd's "
            "BeaconEstimatedLocation/<UUID>/*.record files. Each .record file is "
            "one location fix (latitude, longitude, horizontal accuracy, "
            "timestamp); the .record files under one UUID folder form that "
            "tracker's location history. Complements findMy.py, which currently "
            "only parses FMIPAccounts.plist and does not touch this data or "
            "fmipcore Items.data/Devices.data - this module does not duplicate "
            "or overlap with it."
        ),
        "author": "@findmy_parser",
        "creation_date": "2026-08-12",
        "last_update_date": "2026-08-12",
        "requirements": "none",
        "category": "Locations",
        "notes": (
            "Physical Analyzer exports can wrap the decrypted .record file in "
            "extra, unpredictable subfolders below the owning UUID folder (the "
            "confirmed sample fixture sits two levels down, e.g. "
            "BeaconEstimatedLocation/<uuid>/<uuid>_1.record/<uuid>.record.plist), "
            "so the paths below cover a few extra wildcard depths; widen further "
            "if a real export nests deeper. The owning tracker UUID is resolved "
            "by walking up the file's path for the nearest UUID-shaped folder "
            "name rather than assuming a fixed parent, and by shape "
            "(8-4-4-4-12 groups) rather than strict hex, since real (redacted) "
            "sample data can contain non-hex placeholder characters in an "
            "otherwise UUID-shaped folder name. Only associatedBeacon/"
            "identifier, latitude, longitude, horizontalAccuracy, timestamp, and "
            "scanDate are confirmed against real .record fixture data; fields "
            "sometimes mentioned elsewhere (confidence, status) are not assumed "
            "and are simply not extracted. Per current ilapfuncs.py, there is no "
            "context-provided timezone offset for context-based modules and "
            "convert_utc_human_to_timezone has no live caller in the codebase, "
            "so timestamps are reported as converted UTC datetimes rather than "
            "shifted into a report timezone (matches current module practice)."
        ),
        "paths": (
            "*/Library/Caches/com.apple.icloud.searchpartyd/BeaconEstimatedLocation/*/*.record",
            "*/Library/Caches/com.apple.icloud.searchpartyd/BeaconEstimatedLocation/*/*/*.record",
            "*/Library/Caches/com.apple.icloud.searchpartyd/BeaconEstimatedLocation/*/*/*/*.record",
            "*/Library/Caches/com.apple.icloud.searchpartyd/BeaconEstimatedLocation/*/*/*/*/*.record",
        ),
        "output_types": ["html", "tsv", "timeline", "kml", "lava"],
        "artifact_icon": "map-pin",
        "sample_data": {},
    }
}

import re

from scripts.ilapfuncs import (
    artifact_processor,
    convert_cocoa_core_data_ts_to_utc,
    convert_plist_date_to_utc,
    convert_unix_ts_to_utc,
    get_plist_file_content,
    logfunc,
)

# Matches a UUID-shaped path component (8-4-4-4-12 groups) by shape, not
# strict hex validity - see the "notes" field above for why.
_UUID_SHAPE_RE = re.compile(
    r"^[0-9A-Za-z]{8}-[0-9A-Za-z]{4}-[0-9A-Za-z]{4}-[0-9A-Za-z]{4}-[0-9A-Za-z]{12}$"
)

# The largest plausible Cocoa/Unix *seconds* epoch value for this artifact
# type is far below this; the smallest plausible *milliseconds* value is
# far above it. Mirrors findmy_parser.timestamps._SECONDS_MS_BOUNDARY.
_SECONDS_MS_BOUNDARY = 1e11
# Seconds between the Unix epoch (1970-01-01) and the Cocoa epoch (2001-01-01).
_COCOA_EPOCH_UNIX_OFFSET_SECONDS = 978_307_200


def _resolve_tracker_uuid(file_path):
    """Walk up from a .record file's path and return the owning tracker UUID.

    Physical Analyzer wraps the decrypted file in extra subfolders below
    the true UUID folder, so the immediate parent is not assumed to be
    it - every ancestor is checked, nearest first.
    """
    parts = file_path.replace("\\", "/").split("/")
    for part in reversed(parts[:-1]):
        if _UUID_SHAPE_RE.match(part):
            return part
    return "UNKNOWN"


def _convert_timestamp(value):
    """Convert a .record timestamp field to a UTC datetime.

    Native bplist date values (the only form confirmed against real
    fixture data) go through convert_plist_date_to_utc(). Raw Cocoa/Unix
    epoch numbers (not confirmed in real data, but handled defensively)
    are scaled to seconds and routed to the matching ilapfuncs helper.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000.0 if abs(value) >= _SECONDS_MS_BOUNDARY else value
        if seconds < _COCOA_EPOCH_UNIX_OFFSET_SECONDS:
            return convert_cocoa_core_data_ts_to_utc(seconds)
        return convert_unix_ts_to_utc(seconds)
    return convert_plist_date_to_utc(value)


@artifact_processor
def findMyBeaconLocations(context):
    data_headers = (
        ("Timestamp", "datetime"),
        "Device UUID",
        "Latitude",
        "Longitude",
        "Horizontal Accuracy (m)",
        "Location Source",
        ("Scan Date", "datetime"),
        "Source File",
    )
    data_list = []
    parsed_relative_paths = []

    for file_found in context.get_files_found():
        file_found = str(file_found)
        if ".record" not in file_found.lower():
            continue

        pl = get_plist_file_content(file_found)
        if not isinstance(pl, dict) or not pl:
            logfunc(f"findMyBeaconLocations: could not parse as plist, skipping: {file_found}")
            continue

        tracker_uuid = pl.get("associatedBeacon") or pl.get("identifier")
        if not tracker_uuid:
            tracker_uuid = _resolve_tracker_uuid(file_found)

        data_list.append(
            (
                _convert_timestamp(pl.get("timestamp")),
                tracker_uuid,
                pl.get("latitude"),
                pl.get("longitude"),
                pl.get("horizontalAccuracy"),
                pl.get("locationSource"),
                _convert_timestamp(pl.get("scanDate")),
                context.get_relative_path(file_found),
            )
        )
        parsed_relative_paths.append(context.get_relative_path(file_found))

    source_path = "\n".join(parsed_relative_paths)
    return data_headers, data_list, source_path
