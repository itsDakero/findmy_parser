import plistlib
from pathlib import Path

import pytest

from findmy_parser.discovery import discover
from findmy_parser.searchpartyd import (
    MetadataParseError,
    classify_record_path,
    parse_metadata_bytes,
)

SYNTHETIC_ROOT = Path(__file__).parent / "fixtures/synthetic"
SEARCHPARTYD = (
    SYNTHETIC_ROOT / "private/var/mobile/Library/Caches/com.apple.icloud.searchpartyd"
)

TRACKER_A = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
TRACKER_C = "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC"


def test_classify_location_vs_metadata_records():
    assert classify_record_path(Path("x/BeaconEstimatedLocation/UUID/a.record")) == "location"
    assert classify_record_path(Path("x/OwnedBeacons/UUID.record")) == "owned_beacon"
    assert classify_record_path(Path("x/SharedBeacons/UUID.record")) == "shared_beacon"
    assert classify_record_path(Path("x/BeaconNamingRecord/UUID/n.record")) == "naming_record"


def test_classify_is_case_insensitive_and_uses_nearest_ancestor():
    assert classify_record_path(Path("x/ownedbeacons/UUID.record")) == "owned_beacon"
    # A metadata folder nested below the location folder still classifies
    # as metadata - nearest matching ancestor wins.
    path = Path("x/BeaconEstimatedLocation/UUID/BeaconNamingRecord/n.record")
    assert classify_record_path(path) == "naming_record"


def test_classify_falls_back_to_location_when_unrecognised():
    assert classify_record_path(Path("loose/export/thing.record")) == "location"


def test_classify_matches_pa_wrapped_folder_names():
    # PA renames/wraps folders on export; an exact-name match would
    # misclassify these as location fixes.
    assert classify_record_path(Path("x/OwnedBeacons_1.data/UUID.record")) == "owned_beacon"
    assert (
        classify_record_path(Path("x/BeaconNamingRecord_1.data/UUID/n.record.decrypted"))
        == "naming_record"
    )
    assert (
        classify_record_path(Path("x/BeaconEstimatedLocation_1.data/UUID/a.record")) == "location"
    )


def test_parses_naming_record_fields():
    data = plistlib.dumps(
        {"associatedBeacon": TRACKER_C, "name": "Keys AirTag", "emoji": "\U0001f511"},
        fmt=plistlib.FMT_BINARY,
    )
    meta = parse_metadata_bytes(data, source_file="n.record", kind="naming_record")
    assert meta.tracker_id == TRACKER_C
    assert meta.name == "Keys AirTag"
    assert meta.emoji == "\U0001f511"


def test_uses_path_hint_when_payload_has_no_identifier():
    data = plistlib.dumps({"name": "Nameless"}, fmt=plistlib.FMT_BINARY)
    meta = parse_metadata_bytes(
        data, source_file="n.record", kind="naming_record", tracker_id_hint=TRACKER_C
    )
    assert meta.tracker_id == TRACKER_C


def test_finds_nested_name_field():
    data = plistlib.dumps(
        {"identifier": TRACKER_C, "metadata": {"info": {"name": "Nested Name"}}},
        fmt=plistlib.FMT_BINARY,
    )
    meta = parse_metadata_bytes(data, source_file="n.record", kind="naming_record")
    assert meta.name == "Nested Name"


def test_unparseable_metadata_raises():
    with pytest.raises(MetadataParseError):
        parse_metadata_bytes(b"\x00\xffnot a plist", source_file="n.record", kind="owned_beacon")


def test_metadata_records_are_not_counted_as_location_fixes():
    """The core bug this module fixes: OwnedBeacons/*.record is named like
    a location record but has no coordinates, and used to be emitted as a
    junk row."""
    result = discover(SYNTHETIC_ROOT)
    owned = SEARCHPARTYD / "OwnedBeacons" / f"{TRACKER_A}.record"
    assert owned.exists()

    all_fix_sources = {f.source_file for f in result.all_fixes()}
    assert str(owned) not in all_fix_sources
    assert any("OwnedBeacons" in p for p, _kind in result.log.metadata_files_parsed)

    # Tracker A keeps exactly its two real location fixes.
    assert len(result.fixes_by_tracker[TRACKER_A]) == 2


def test_naming_record_supplies_name_when_no_inventory_entry():
    """Tracker C has no fmipcore entry at all - its name can only come
    from BeaconNamingRecord."""
    result = discover(SYNTHETIC_ROOT)
    assert result.trackers[TRACKER_C].name == "Keys AirTag"
    assert result.trackers[TRACKER_C].emoji == "\U0001f511"
    assert "naming_record" in result.log.name_sources[TRACKER_C]


def test_inventory_name_wins_over_owned_beacon_name():
    result = discover(SYNTHETIC_ROOT)
    assert result.trackers[TRACKER_A].name == "Backpack AirTag"
    assert "Items.data" in result.log.name_sources[TRACKER_A]


def test_unmatched_tracker_ids_empty_when_all_named():
    result = discover(SYNTHETIC_ROOT)
    assert result.log.unmatched_tracker_ids == []


def test_unmatched_tracker_ids_reports_nameless_trackers(tmp_path):
    record_dir = tmp_path / "BeaconEstimatedLocation" / "DDDDDDDD-DDDD-4DDD-8DDD-DDDDDDDDDDDD"
    record_dir.mkdir(parents=True)
    with open(record_dir / "fix.record", "wb") as fp:
        plistlib.dump(
            {
                "associatedBeacon": "DDDDDDDD-DDDD-4DDD-8DDD-DDDDDDDDDDDD",
                "latitude": 1.0,
                "longitude": 2.0,
            },
            fp,
            fmt=plistlib.FMT_BINARY,
        )
    result = discover(tmp_path)
    assert result.log.unmatched_tracker_ids == ["DDDDDDDD-DDDD-4DDD-8DDD-DDDDDDDDDDDD"]


def test_pairing_date_normalised_and_battery_parsed():
    data = plistlib.dumps(
        {
            "identifier": TRACKER_A,
            "model": "AirTag",
            "pairingDate": __import__("datetime").datetime(2026, 2, 14, 18, 30, 0),
            "batteryLevel": 0.9,
        },
        fmt=plistlib.FMT_BINARY,
    )
    meta = parse_metadata_bytes(data, source_file="o.record", kind="owned_beacon")
    assert meta.pairing_date_utc == "2026-02-14T18:30:00Z"
    assert meta.pairing_date_raw is not None
    assert meta.battery_level == 0.9
    # Confirmed: OwnedBeacons carries no name field.
    assert meta.name is None
    assert meta.model == "AirTag"
