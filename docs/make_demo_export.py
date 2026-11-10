"""Builds a synthetic Physical-Analyzer-shaped export for the usage guide (docs/USAGE.md).

Everything here is invented. No real device, account, serial number,
coordinate or name from any examination appears in it, so the screenshots
taken from it need no redaction. Names are deliberately generic
placeholders ("Example Owner", "Demo iPhone").

Run it to rebuild the demo export the guide's screenshots were taken
from:

    python docs/make_demo_export.py demo_export
    findmy-parser demo_export
"""
from __future__ import annotations

import datetime as dt
import plistlib
import shutil
import sys
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "demo_export")

# Invented beacon UUIDs. Version nibble set to 4 so they are well-formed.
TAG_KEYS = "4F2A9C10-7B3E-4A12-9D80-1C5E6B9A4D33"
TAG_BAG = "8E71D4B5-2C90-4F63-8A1B-5D2074E9C6AF"
AIRPODS = "A3C05E27-91D8-4B74-8E29-6F413A0D7B52"
PHONE   = "C7B48F91-6A52-4D08-93EF-2B81057C4E6D"
ORPHAN  = "D9052E13-4F86-41C7-B5A0-83E6792D1CB4"   # no inventory entry


def bplist(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fp:
        plistlib.dump(payload, fp, fmt=plistlib.FMT_BINARY)


def wrapper():
    """The signed on-device form PA leaves beside its decrypted copy."""
    return [1, b"\x00encrypted-payload", b"\x00signature"]


def pa_record(beacon: str, record_uuid: str, payload: dict) -> None:
    base = OUT / "BeaconEstimatedLocation" / beacon
    bplist(base / f"{record_uuid}.record", wrapper())
    bplist(base / f"{record_uuid}_1.record" / f"{record_uuid}.record.plist", payload)


def track(beacon: str, start: dt.datetime, points, source=2, seed=0):
    """Write one fix per (minutes offset, lat, lon, accuracy) point."""
    for n, (mins, lat, lon, acc) in enumerate(points):
        ts = start + dt.timedelta(minutes=mins)
        uuid = f"{seed + n:08X}-0000-4000-8000-{beacon[-12:]}"
        pa_record(beacon, uuid, {
            "associatedBeacon": beacon,
            "identifier": uuid,
            "latitude": lat,
            "longitude": lon,
            "horizontalAccuracy": acc,
            "timestamp": ts,
            "scanDate": ts + dt.timedelta(seconds=3),
            "locationSource": source,
            "cloudKitMetadata": b"",
        })


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)

    day = dt.datetime(2026, 9, 14, 8, 12, 0)

    # Keys AirTag: a short morning journey.
    track(TAG_KEYS, day, [
        (0,    53.480102, -2.242631, 12.0),
        (46,   53.476994, -2.238410, 8.5),
        (118,  53.472318, -2.230975, 35.0),
        (205,  53.468871, -2.221043, 10.0),
        (1_480, 53.480090, -2.242580, 14.0),
    ], seed=0x1001)

    # Bag AirTag: fewer fixes, one of them predating its pairing date,
    # so the guide can show the amber flag.
    track(TAG_BAG, dt.datetime(2026, 9, 10, 19, 4, 0), [
        (0,    53.401228, -2.979410, 22.0),
        (3_120, 53.395511, -2.971008, 48.0),
    ], seed=0x2001)

    # AirPods Pro: a cluster at one address.
    track(AIRPODS, dt.datetime(2026, 9, 14, 21, 38, 0), [
        (0,   53.480240, -2.242900, 9.0),
        (62,  53.480231, -2.242884, 9.5),
        (440, 53.480255, -2.242911, 11.0),
    ], source=1, seed=0x3001)

    # The phone itself, joined by baUUID rather than identifier.
    track(PHONE, dt.datetime(2026, 9, 15, 7, 2, 0), [
        (0,   53.480118, -2.242640, 6.0),
        (95,  53.466402, -2.212887, 18.0),
    ], source=0, seed=0x4001)

    # A beacon with location history but no inventory entry at all.
    track(ORPHAN, dt.datetime(2026, 9, 12, 13, 25, 0), [
        (0,  53.455901, -2.198330, 65.0),
    ], seed=0x5001)

    # --- OwnedBeacons -------------------------------------------------
    owned = OUT / "OwnedBeacons"

    def owned_beacon(beacon: str, payload: dict) -> None:
        bplist(owned / f"{beacon}.record", wrapper())
        bplist(owned / f"{beacon}_1.record" / f"{beacon}.record.plist", payload)

    owned_beacon(TAG_KEYS, {
        "identifier": TAG_KEYS, "model": "AirTag",
        "pairingDate": dt.datetime(2026, 3, 2, 11, 48, 0),
        "batteryLevel": 0.85, "stableIdentifier": "demo-stable-1",
        "groupIdentifier": "demo-group-1", "productId": 1234, "vendorId": 76,
        "systemVersion": "2.0.73", "isZeus": False,
    })
    # Paired AFTER its earliest recorded fix -> the flag case.
    owned_beacon(TAG_BAG, {
        "identifier": TAG_BAG, "model": "AirTag",
        "pairingDate": dt.datetime(2026, 9, 11, 9, 15, 0),
        "batteryLevel": 0.42, "stableIdentifier": "demo-stable-2",
        "productId": 1234, "vendorId": 76, "systemVersion": "2.0.73",
    })
    # No pairingDate key at all -> the "record carries no pairingDate" case.
    owned_beacon(AIRPODS, {
        "identifier": AIRPODS, "model": "AirPods Pro",
        "batteryLevel": 0.6, "stableIdentifier": "demo-stable-3",
        "productId": 8206, "vendorId": 76, "systemVersion": "6A321",
    })

    # --- BeaconNamingRecord -------------------------------------------
    bplist(OUT / "BeaconNamingRecord" / AIRPODS / "naming.record", {
        "associatedBeacon": AIRPODS, "name": "AirPods Pro", "emoji": "\U0001f3a7",
    })

    # --- fmipcore inventory, in PA's decrypted layout ------------------
    bplist(OUT / "Items_1.data" / "Items.data.decrypted", [
        {"identifier": TAG_KEYS, "name": "House Keys", "emoji": "\U0001f511",
         "serialNumber": "DEMOSERIAL001",
         "productType": {"productInformation": {"modelName": "AirTag"}},
         "location": {"latitude": 53.480102, "longitude": -2.242631},
         "batteryStatus": 1, "isAppleItem": True, "role": {"name": "Keys"}},
        {"identifier": TAG_BAG, "name": "Work Bag", "emoji": "\U0001f392",
         "serialNumber": "DEMOSERIAL002",
         "productType": {"productInformation": {"modelName": "AirTag"}},
         "location": {"latitude": 53.401228, "longitude": -2.979410},
         "batteryStatus": 2, "isAppleItem": True},
        {"identifier": AIRPODS, "name": "AirPods Pro", "emoji": "\U0001f3a7",
         "serialNumber": "DEMOSERIAL003",
         "productType": {"productInformation": {"modelName": "AirPods Pro"}},
         "isAppleAudioAccessory": True, "isAppleItem": True},
    ])

    bplist(OUT / "Devices_1.data" / "Devices.data.decrypted", [
        {"id": "demo-device-record-1", "baUUID": PHONE, "name": "Demo iPhone",
         "deviceDisplayName": "iPhone 15 Pro", "rawDeviceModel": "iPhone16,1",
         "deviceStatus": "200"},
    ])

    bplist(OUT / "Owner_1.data" / "Owner.data.decrypted",
           {"name": "Example Owner", "appleId": "owner@example.invalid"})

    files = sum(1 for p in OUT.rglob("*") if p.is_file())
    print(f"demo export written to {OUT} ({files} files)")


if __name__ == "__main__":
    main()
