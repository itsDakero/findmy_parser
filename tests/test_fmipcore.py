from pathlib import Path

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


def test_parses_items_data_json():
    trackers = parse_inventory_file(FMIPCORE / "Items.data")
    assert len(trackers) == 1
    tracker = trackers[0]
    assert tracker.identifier == TRACKER_A
    assert tracker.name == "Backpack AirTag"
    assert tracker.serial_number == "AT-SN-0001"
    assert tracker.source_kind == "item"
    assert tracker.source_file == str(FMIPCORE / "Items.data")
    assert tracker.raw["productType"] == "AirTag"


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
