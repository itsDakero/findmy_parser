import plistlib
from pathlib import Path
from plistlib import UID

import pytest

from findmy_parser.fmipcore import (
    InventoryParseError,
    is_fmipcore_filename,
    parse_inventory_bytes,
    parse_inventory_file,
)

FMIPCORE = (
    Path(__file__).parent
    / "fixtures/synthetic/private/var/mobile/Library/Caches/com.apple.findmy.fmipcore"
)

TRACKER_A = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
TRACKER_B = "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"


def _build_nskeyedarchiver_items(entries: list[dict], archiver: str = "NSKeyedArchiver") -> bytes:
    """Hand-build a genuine NSKeyedArchiver-wrapped bplist: an NSMutableArray
    of NSMutableDictionary entries, matching the real object-graph shape
    (validated against the vendored ccl_bplist against the structure shown
    in its own README) rather than a simplified stand-in."""
    objects: list = ["$null"]

    def add(obj) -> int:
        objects.append(obj)
        return len(objects) - 1

    array_classdef = add(
        {"$classes": ["NSMutableArray", "NSArray", "NSObject"], "$classname": "NSMutableArray"}
    )
    dict_classdef = add(
        {
            "$classes": ["NSMutableDictionary", "NSDictionary", "NSObject"],
            "$classname": "NSMutableDictionary",
        }
    )

    entry_indices = []
    for entry in entries:
        key_indices = [add(k) for k in entry]
        val_indices = [add(v) for v in entry.values()]
        entry_indices.append(
            add(
                {
                    "$class": UID(dict_classdef),
                    "NS.keys": [UID(i) for i in key_indices],
                    "NS.objects": [UID(i) for i in val_indices],
                }
            )
        )

    root = add({"$class": UID(array_classdef), "NS.objects": [UID(i) for i in entry_indices]})

    structure = {
        "$archiver": archiver,
        "$version": 100000,
        "$top": {"root": UID(root)},
        "$objects": objects,
    }
    return plistlib.dumps(structure, fmt=plistlib.FMT_BINARY)


def test_parses_items_data_json():
    trackers = parse_inventory_file(FMIPCORE / "Items.data")
    assert len(trackers) == 1
    tracker = trackers[0]
    assert tracker.identifier == TRACKER_A
    assert tracker.name == "Backpack AirTag"
    assert tracker.serial_number == "AT-SN-0001"
    assert tracker.model == "AirTag"  # nested productType.productInformation.modelName
    assert tracker.source_kind == "item"
    assert tracker.source_file == str(FMIPCORE / "Items.data")
    assert tracker.raw["productType"]["productInformation"]["modelName"] == "AirTag"


def test_parses_devices_data_json():
    trackers = parse_inventory_file(FMIPCORE / "Devices.data")
    assert len(trackers) == 1
    tracker = trackers[0]
    assert tracker.identifier == TRACKER_B
    assert tracker.name == "Dan's iPhone"
    assert tracker.model == "iPhone16,1"
    assert tracker.source_kind == "device"


def test_bare_list_payload():
    data = b'[{"identifier": "X1", "name": "Foo"}, {"identifier": "X2", "name": "Bar"}]'
    trackers = parse_inventory_bytes(data, source_file="Items.data")
    assert [t.identifier for t in trackers] == ["X1", "X2"]
    assert trackers[0].source_kind == "item"


def test_wrapped_list_payload():
    data = b'{"items": [{"identifier": "X1"}], "meta": {"count": 1}}'
    trackers = parse_inventory_bytes(data, source_file="Items.data")
    assert len(trackers) == 1
    assert trackers[0].identifier == "X1"


def test_single_entry_dict_payload():
    data = b'{"identifier": "OWNER-1", "name": "Owner"}'
    trackers = parse_inventory_bytes(data, source_file="Owner.data")
    assert len(trackers) == 1
    assert trackers[0].source_kind == "owner"


def test_model_extracted_from_nested_producttype_path():
    data = b"""{
        "identifier": "X1",
        "productType": {"productInformation": {"modelName": "AirTag"}}
    }"""
    trackers = parse_inventory_bytes(data, source_file="Items.data")
    assert trackers[0].model == "AirTag"


def test_model_falls_back_to_flat_key_when_not_nested():
    data = b'{"identifier": "X1", "deviceModel": "iPhone16,1"}'
    trackers = parse_inventory_bytes(data, source_file="Devices.data")
    assert trackers[0].model == "iPhone16,1"


def test_model_is_none_when_producttype_present_but_not_nested_as_expected():
    # productType exists but doesn't have the expected nested shape - must
    # not return the raw dict/garbage, just fall through cleanly.
    data = b'{"identifier": "X1", "productType": {"somethingElse": "AirTag"}}'
    trackers = parse_inventory_bytes(data, source_file="Items.data")
    assert trackers[0].model is None


def test_location_lat_lon_extracted():
    data = b'{"identifier": "X1", "location": {"latitude": 1.5, "longitude": -2.5}}'
    trackers = parse_inventory_bytes(data, source_file="Items.data")
    assert trackers[0].last_known_latitude == pytest.approx(1.5)
    assert trackers[0].last_known_longitude == pytest.approx(-2.5)


def test_entry_without_identifier_is_skipped():
    data = b'[{"name": "no id here"}, {"identifier": "X2"}]'
    trackers = parse_inventory_bytes(data, source_file="Items.data")
    assert [t.identifier for t in trackers] == ["X2"]


def test_unrecognised_format_raises():
    with pytest.raises(InventoryParseError):
        parse_inventory_bytes(b"not plist or json", source_file="Items.data")


def test_is_fmipcore_filename():
    assert is_fmipcore_filename("Items.data")
    assert is_fmipcore_filename("Devices.data")
    assert is_fmipcore_filename("SafeLocations.data")
    assert is_fmipcore_filename("Something.data")
    assert not is_fmipcore_filename("random.record")


def test_is_fmipcore_filename_matches_pa_decrypted_suffix():
    # Confirmed real-world PA export naming: "Devices.data.decrypted" etc,
    # not the bare filename.
    assert is_fmipcore_filename("Devices.data.decrypted")
    assert is_fmipcore_filename("Items.data.decrypted")


def test_source_kind_for_pa_decrypted_suffix_still_classified_correctly():
    data = b'{"identifier": "X1", "name": "Test"}'
    trackers = parse_inventory_bytes(data, source_file="Devices.data.decrypted")
    assert trackers[0].source_kind == "device"


def test_nskeyedarchiver_wrapped_items_data_is_decoded():
    data = _build_nskeyedarchiver_items(
        [
            {"identifier": TRACKER_A, "name": "Real Backpack AirTag", "serialNumber": "SN-REAL-1"},
            {"identifier": TRACKER_B, "name": "Real iPhone"},
        ]
    )
    trackers = parse_inventory_bytes(data, source_file="Items.data")
    assert len(trackers) == 2
    assert trackers[0].identifier == TRACKER_A
    assert trackers[0].name == "Real Backpack AirTag"
    assert trackers[0].serial_number == "SN-REAL-1"
    assert trackers[1].identifier == TRACKER_B
    assert trackers[1].name == "Real iPhone"


def test_nskeyedarchiver_plain_plist_regression_unaffected():
    """A plain (non-NSKeyedArchiver) bplist must still parse exactly as
    before - the $archiver check must not misfire on ordinary bplists."""
    data = plistlib.dumps(
        [{"identifier": TRACKER_A, "name": "Plain Bplist AirTag"}], fmt=plistlib.FMT_BINARY
    )
    trackers = parse_inventory_bytes(data, source_file="Items.data")
    assert len(trackers) == 1
    assert trackers[0].name == "Plain Bplist AirTag"


def test_nskeyedarchiver_alternate_archiver_marker_decoded():
    # ccl_bplist itself also recognises the (rarer) "NRKeyedArchiver" marker.
    data = _build_nskeyedarchiver_items(
        [{"identifier": TRACKER_A, "name": "NR-marked entry"}], archiver="NRKeyedArchiver"
    )
    trackers = parse_inventory_bytes(data, source_file="Items.data")
    assert len(trackers) == 1
    assert trackers[0].name == "NR-marked entry"


def test_nskeyedarchiver_xml_variant_raises_clear_error():
    # plistlib's XML writer can't serialise UID objects at all (binary-only
    # feature), which conveniently doesn't matter here: detection only
    # needs the "$archiver" marker itself, and must fail before any UID
    # dereferencing is attempted.
    structure = {"$archiver": "NSKeyedArchiver", "$version": 100000, "$top": {"root": "n/a"}}
    data = plistlib.dumps(structure, fmt=plistlib.FMT_XML)
    with pytest.raises(InventoryParseError, match="NSKeyedArchiver-wrapped XML plist"):
        parse_inventory_bytes(data, source_file="Items.data")


def test_nskeyedarchiver_corrupted_archive_raises_inventoryparseerror():
    structure = {
        "$archiver": "NSKeyedArchiver",
        "$version": 100000,
        "$top": {"root": UID(99)},  # dangling reference - out of range
        "$objects": ["$null"],
    }
    data = plistlib.dumps(structure, fmt=plistlib.FMT_BINARY)
    with pytest.raises(InventoryParseError, match="could not decode"):
        parse_inventory_bytes(data, source_file="Items.data")
