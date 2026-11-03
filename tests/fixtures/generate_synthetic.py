"""Regenerates tests/fixtures/synthetic/.

Not a test itself (no test_/​_test naming, so pytest won't collect it) —
a one-off generator kept for reproducibility. Run with:

    python tests/fixtures/generate_synthetic.py

Builds a full synthetic extraction root exercising:
- Physical Analyzer's unpredictable extra nesting around .record files
  (fix1.record appears twice, at different depths, with identical
  content — a dedup case).
- A tracker with no matching inventory entry (unknown-tracker case).
- A corrupted/unparseable .record (skip-and-continue case).
- Format sniffing: bplist, XML plist, and JSON variants of a .record.
- A .record using raw numeric epoch timestamps (Cocoa- and Unix-seconds)
  instead of native bplist date values, to exercise timestamps.py's
  magnitude-based auto-detection.
- fmipcore Items.data / Devices.data as JSON, cross-referencing two of
  the tracker UUIDs used above (the third is intentionally unmatched).
- Sibling searchpartyd folders (OwnedBeacons/, SharedBeacons/,
  BeaconNamingRecord/) present but not the focus of these fixtures.
"""

from __future__ import annotations

import datetime
import json
import plistlib
from pathlib import Path

ROOT = Path(__file__).parent / "synthetic"

TRACKER_A = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"  # AirTag, has an Items.data entry
TRACKER_B = "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"  # Apple device, has a Devices.data entry
TRACKER_C = "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC"  # no inventory entry -> unknown tracker

SEARCHPARTYD = (
    ROOT
    / "private/var/mobile/Library/Caches/com.apple.icloud.searchpartyd"
)
FMIPCORE = ROOT / "private/var/mobile/Library/Caches/com.apple.findmy.fmipcore"
BEACON_LOC = SEARCHPARTYD / "BeaconEstimatedLocation"


def write_bplist(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fp:
        plistlib.dump(payload, fp, fmt=plistlib.FMT_BINARY)


def write_xml_plist(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fp:
        plistlib.dump(payload, fp, fmt=plistlib.FMT_XML)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def main() -> None:
    # --- Tracker A: fix1 duplicated across two nested PA export branches,
    # plus a later fix2 ---
    fix1 = {
        "associatedBeacon": TRACKER_A,
        "identifier": "11111111-1111-4111-8111-111111111111",
        "latitude": 37.334606,
        "longitude": -122.009102,
        "horizontalAccuracy": 12.5,
        "timestamp": datetime.datetime(2026, 6, 1, 8, 0, 0),
        "scanDate": datetime.datetime(2026, 6, 1, 8, 0, 1),
        "locationSource": 1,
        "cloudKitMetadata": b"",
    }
    write_bplist(
        BEACON_LOC / TRACKER_A / "PA_export_1" / "nested" / "deep" / "fix1.record",
        fix1,
    )
    # Same logical record re-exported under a different PA wrapper path.
    write_bplist(
        BEACON_LOC / TRACKER_A / "PA_export_2" / "another_branch" / "fix1_dup.record",
        fix1,
    )
    fix2 = {
        **fix1,
        "latitude": 37.335,
        "longitude": -122.01,
        "horizontalAccuracy": 8.0,
        "timestamp": datetime.datetime(2026, 6, 2, 9, 30, 0),
        "scanDate": datetime.datetime(2026, 6, 2, 9, 30, 2),
    }
    write_bplist(BEACON_LOC / TRACKER_A / "fix2.record", fix2)

    # --- Tracker B: single fix, no PA wrapping ---
    fix3 = {
        "associatedBeacon": TRACKER_B,
        "identifier": "22222222-2222-4222-8222-222222222222",
        "latitude": 51.5074,
        "longitude": -0.1278,
        "horizontalAccuracy": 5.2,
        "timestamp": datetime.datetime(2026, 6, 3, 12, 0, 0),
        "scanDate": datetime.datetime(2026, 6, 3, 12, 0, 0),
        "locationSource": 0,
        "cloudKitMetadata": b"",
    }
    write_bplist(BEACON_LOC / TRACKER_B / "fix3.record", fix3)

    # --- Tracker C: no inventory entry, plus edge-case format files ---
    (BEACON_LOC / TRACKER_C).mkdir(parents=True, exist_ok=True)
    (BEACON_LOC / TRACKER_C / "corrupted.record").write_bytes(
        b"\x00\x01\xffnot a plist or json at all"
    )

    xml_fix = {
        "associatedBeacon": TRACKER_C,
        "identifier": "33333333-3333-4333-8333-333333333333",
        "latitude": 48.8566,
        "longitude": 2.3522,
        "horizontalAccuracy": 15.0,
        "timestamp": datetime.datetime(2026, 6, 4, 6, 0, 0),
        "scanDate": datetime.datetime(2026, 6, 4, 6, 0, 0),
        "locationSource": 2,
    }
    write_xml_plist(BEACON_LOC / TRACKER_C / "xml_variant.record", xml_fix)

    json_fix = {
        "associatedBeacon": TRACKER_C,
        "identifier": "44444444-4444-4444-8444-444444444444",
        "latitude": 35.6762,
        "longitude": 139.6503,
        "horizontalAccuracy": 20.0,
        # Raw Unix-seconds epoch number rather than a native date value.
        "timestamp": 1780000000,
        "scanDate": 1780000005,
        "locationSource": 2,
    }
    write_json(BEACON_LOC / TRACKER_C / "json_variant.record", json_fix)

    # Raw numeric epoch values instead of native bplist dates: one
    # Cocoa-seconds, one Unix-seconds, to exercise magnitude auto-detect.
    numeric_epoch_fix = {
        "associatedBeacon": TRACKER_C,
        "identifier": "55555555-5555-4555-8555-555555555555",
        "latitude": -33.8688,
        "longitude": 151.2093,
        "horizontalAccuracy": 30.0,
        "timestamp": 800000000.0,  # Cocoa seconds -> 2026-05-09T06:13:20Z
        "scanDate": 1780000100.0,  # Unix seconds -> 2026-05-28T20:28:20Z
        "locationSource": 2,
    }
    write_bplist(BEACON_LOC / TRACKER_C / "numeric_epoch.record", numeric_epoch_fix)

    # --- Sibling searchpartyd folders ---
    # These are all named "*.record" like the location fixes, so they
    # exercise classify_record_path(): they must NOT be parsed as
    # coordinate-less location fixes, and they're a name source keyed by
    # the same beacon UUID.
    (SEARCHPARTYD / "SharedBeacons").mkdir(parents=True, exist_ok=True)
    (SEARCHPARTYD / "SharedBeacons" / ".keep").write_text("")

    # Tracker A also has an fmipcore entry, so its inventory name wins over
    # this one - exercises the precedence rule.
    write_bplist(
        SEARCHPARTYD / "OwnedBeacons" / f"{TRACKER_A}.record",
        {
            "identifier": TRACKER_A,
            "name": "Owned Beacon Name (should lose to Items.data)",
            "model": "AirTag",
            "pairingDate": datetime.datetime(2026, 1, 1, 0, 0, 0),
        },
    )

    # Tracker C has NO fmipcore entry - this naming record is the only
    # place its friendly name exists, which is the real-world case that
    # motivated parsing these folders at all.
    write_bplist(
        SEARCHPARTYD / "BeaconNamingRecord" / TRACKER_C / "naming.record",
        {
            "associatedBeacon": TRACKER_C,
            "name": "Keys AirTag",
            "emoji": "\U0001f511",
        },
    )

    # --- fmipcore inventory: Items.data (JSON), Devices.data (JSON) ---
    # Shape confirmed against real Items.data: model name is nested at
    # productType.productInformation.modelName, not a flat string field.
    items_data = [
        {
            "identifier": TRACKER_A,
            "name": "Backpack AirTag",
            "emoji": "\U0001f392",
            "serialNumber": "AT-SN-0001",
            "productType": {"productInformation": {"modelName": "AirTag"}},
        }
    ]
    write_json(FMIPCORE / "Items.data", items_data)

    devices_data = [
        {
            "identifier": TRACKER_B,
            "name": "Dan's iPhone",
            "deviceModel": "iPhone16,1",
            "modelDisplayName": "iPhone 15 Pro",
        }
    ]
    write_json(FMIPCORE / "Devices.data", devices_data)

    print(f"Synthetic fixtures written under {ROOT}")


if __name__ == "__main__":
    main()
