"""End-to-end tests against the layout confirmed in a real Cellebrite
Physical Analyzer export.

Every record appears twice there: the signed/encrypted on-device file,
whose top level is a 3-element list, and PA's decrypted copy beside it
under "<uuid>_1.record/<uuid>.record.plist". The inventory arrives as
"<Name>_1.data/<Name>.data.decrypted" - a binary plist, not JSON - and
Devices.data keys the beacon UUID as baUUID rather than identifier.

Each of those four details broke an earlier build, so they are pinned
here rather than only in the unit tests.
"""

import csv
from pathlib import Path

import pytest

from findmy_parser.cli import run
from findmy_parser.discovery import discover

PA_ROOT = Path(__file__).parent / "fixtures/pa_export"

BEACON_ITEM = "0C5F7EB4-074C-4DB1-8190-ECF04E6F46C8"
BEACON_DEVICE = "2ED95028-C21F-4572-8B73-BB3790856977"


@pytest.fixture
def result():
    return discover(PA_ROOT)


def test_encrypted_wrappers_are_not_errors(result):
    """The 3-element-list files are the on-device form; they must be
    recognised and skipped, not reported as parse failures."""
    assert result.log.record_files_skipped == []
    assert result.log.metadata_files_skipped == []
    # 3 location wrappers + 1 OwnedBeacons wrapper.
    assert len(result.log.encrypted_records) == 4
    assert all(".record" in p for p in result.log.encrypted_records)


def test_decrypted_copies_supply_the_fixes(result):
    assert len(result.log.record_files_parsed) == 3
    assert all(p.endswith(".record.plist") for p in result.log.record_files_parsed)
    total = sum(len(v) for v in result.fixes_by_tracker.values())
    assert total == 3


def test_wrapper_and_decrypted_copy_are_not_double_counted(result):
    """Each logical record exists as two files but must yield one fix."""
    assert len(result.fixes_by_tracker[BEACON_ITEM]) == 2
    assert len(result.fixes_by_tracker[BEACON_DEVICE]) == 1


def test_bplist_inventory_under_pa_decrypted_name_is_read(result):
    """Items_1.data/Items.data.decrypted - a bplist, not JSON, and not
    named Items.data."""
    assert len(result.log.inventory_files_parsed) == 2
    assert any("Items.data.decrypted" in p for p in result.log.inventory_files_parsed)
    assert any("Devices.data.decrypted" in p for p in result.log.inventory_files_parsed)


def test_item_name_resolves_via_identifier(result):
    tracker = result.trackers[BEACON_ITEM]
    assert tracker.name == "Keys AirTag"
    assert tracker.model == "AirTag"  # nested productType.productInformation.modelName
    assert "Items.data.decrypted" in result.log.name_sources[BEACON_ITEM]


def test_device_name_resolves_via_bauuid(result):
    """Devices.data carries the beacon UUID as baUUID; matching only on
    identifier left these nameless."""
    tracker = result.trackers[BEACON_DEVICE]
    assert tracker.name == "Dan's iPhone"
    assert "Devices.data.decrypted" in result.log.name_sources[BEACON_DEVICE]


def test_nothing_left_unnamed(result):
    assert result.log.unmatched_tracker_ids == []


def test_owned_beacons_supplies_model_but_no_name(result):
    """The real OwnedBeacons key set has model/pairingDate but no name
    field at all, so it can never be the name source."""
    assert len(result.log.metadata_files_parsed) == 1
    path, kind = result.log.metadata_files_parsed[0]
    assert kind == "owned_beacon"
    assert path.endswith(".record.plist")


def test_cli_end_to_end_writes_named_rows(tmp_path):
    out_dir = tmp_path / "out"
    assert run([str(PA_ROOT), "--output-dir", str(out_dir)]) == 0

    with open(out_dir / "findmy_locations.csv", newline="", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))

    assert len(rows) == 3
    assert {r["tracker_name"] for r in rows} == {"Keys AirTag", "Dan's iPhone"}
    assert all(r["latitude"] and r["longitude"] for r in rows)
    assert all(r["timestamp_utc"].endswith("Z") for r in rows)

    log = (out_dir / "run.log").read_text()
    assert "record files skipped: 0" in log
    assert "encrypted on-device records skipped" in log

    report = (out_dir / "findmy_report.html").read_text()
    assert "Keys AirTag" in report
    assert BEACON_ITEM in report


def test_pairing_date_and_battery_from_owned_beacons(result):
    """OwnedBeacons has no name, but it does carry pairingDate and
    batteryLevel - pairing date bounds when the tracker entered the
    account, independently of any location fix."""
    tracker = result.trackers[BEACON_ITEM]
    assert tracker.pairing_date_utc == "2026-02-14T18:30:00Z"
    assert tracker.battery_level == pytest.approx(0.9)
    # The raw value is preserved alongside the normalised one.
    assert tracker.pairing_date_raw is not None


def test_tracker_without_owned_beacon_has_no_pairing_date(result):
    tracker = result.trackers[BEACON_DEVICE]
    assert tracker.pairing_date_utc is None
    assert tracker.battery_level is None


def test_pairing_columns_in_csv_and_report(tmp_path):
    out_dir = tmp_path / "out"
    run([str(PA_ROOT), "--output-dir", str(out_dir)])

    with open(out_dir / "findmy_locations.csv", newline="", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))
    assert "tracker_pairing_date_utc" in rows[0]
    assert "tracker_battery_level" in rows[0]
    paired = [r for r in rows if r["tracker_pairing_date_utc"]]
    assert len(paired) == 2  # the two fixes of the item that has an OwnedBeacons record
    assert paired[0]["tracker_pairing_date_utc"] == "2026-02-14T18:30:00Z"
    assert paired[0]["tracker_battery_level"] == "0.9"

    report = (out_dir / "findmy_report.html").read_text()
    assert "<dt>Paired</dt>" in report
    assert "90%" in report  # 0-1 fraction rendered as a percentage


def test_pa_export_has_no_pairing_anomaly(result):
    """The PA-layout fixture's fixes all follow its pairing date, so the
    check must stay quiet on well-formed data."""
    assert result.log.fixes_before_pairing == []
