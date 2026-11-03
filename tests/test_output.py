import csv
import json
from pathlib import Path

import pytest

from findmy_parser.discovery import discover
from findmy_parser.output.csv_writer import write_csv
from findmy_parser.output.json_writer import write_json
from findmy_parser.output.kml_writer import write_kml

SYNTHETIC_ROOT = Path(__file__).parent / "fixtures/synthetic"

TRACKER_A = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
TRACKER_B = "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"
TRACKER_C = "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC"


@pytest.fixture
def result():
    return discover(SYNTHETIC_ROOT)


def test_csv_row_count_and_header(tmp_path, result):
    out = tmp_path / "out.csv"
    write_csv(result, out)

    with open(out, newline="", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))

    total_fixes = sum(len(v) for v in result.fixes_by_tracker.values())
    assert len(rows) == total_fixes == 6  # 2 (A) + 1 (B) + 3 (C)
    assert set(rows[0].keys()) >= {
        "tracker_id",
        "tracker_name",
        "latitude",
        "longitude",
        "timestamp_utc",
        "source_file",
        "content_hash",
    }


def test_csv_joins_tracker_name_and_labels_unknown(tmp_path, result):
    out = tmp_path / "out.csv"
    write_csv(result, out)
    with open(out, newline="", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))

    by_tracker = {}
    for row in rows:
        by_tracker.setdefault(row["tracker_id"], []).append(row)

    assert by_tracker[TRACKER_A][0]["tracker_name"] == "Backpack AirTag"
    assert by_tracker[TRACKER_B][0]["tracker_name"] == "Dan's iPhone"
    # No fmipcore entry, but a BeaconNamingRecord supplies the name.
    assert by_tracker[TRACKER_C][0]["tracker_name"] == "Keys AirTag"
    assert by_tracker[TRACKER_C][0]["tracker_source_kind"] == "naming_record"


def test_csv_still_emits_rows_for_tracker_with_no_name_anywhere(tmp_path):
    """A tracker with location fixes but no name from any source must
    still appear - location data is never dropped for lack of a label."""
    import plistlib

    from findmy_parser.discovery import discover

    tracker_dir = tmp_path / "BeaconEstimatedLocation" / "DDDDDDDD-DDDD-4DDD-8DDD-DDDDDDDDDDDD"
    tracker_dir.mkdir(parents=True)
    with open(tracker_dir / "fix.record", "wb") as fp:
        plistlib.dump(
            {
                "associatedBeacon": "DDDDDDDD-DDDD-4DDD-8DDD-DDDDDDDDDDDD",
                "latitude": 10.0,
                "longitude": 20.0,
            },
            fp,
            fmt=plistlib.FMT_BINARY,
        )

    out = tmp_path / "out.csv"
    write_csv(discover(tmp_path), out)
    with open(out, newline="", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))

    assert len(rows) == 1
    assert rows[0]["tracker_name"] == ""
    assert rows[0]["tracker_source_kind"] == "unknown"
    assert rows[0]["latitude"] == "10.0"


def test_csv_sorted_chronologically_per_tracker(tmp_path, result):
    out = tmp_path / "out.csv"
    write_csv(result, out)
    with open(out, newline="", encoding="utf-8") as fp:
        rows = [r for r in csv.DictReader(fp) if r["tracker_id"] == TRACKER_A]
    timestamps = [r["timestamp_utc"] for r in rows]
    assert timestamps == sorted(timestamps)


def test_json_output_matches_csv_row_count(tmp_path, result):
    out = tmp_path / "out.json"
    write_json(result, out)
    data = json.loads(out.read_text())
    total_fixes = sum(len(v) for v in result.fixes_by_tracker.values())
    assert len(data) == total_fixes
    assert all("source_file" in row for row in data)


def test_kml_output_has_one_folder_per_tracker_with_fixes(tmp_path, result):
    out = tmp_path / "out.kml"
    write_kml(result, out)
    content = out.read_text()
    assert content.count("<Folder>") == 3  # A, B, C all have >=1 geolocated fix
    assert "Backpack AirTag" in content
    assert content.count("<LineString>") == 3  # one track per tracker
    assert "<Point>" in content


def test_kml_is_well_formed_xml(tmp_path, result):
    import xml.etree.ElementTree as ET

    out = tmp_path / "out.kml"
    write_kml(result, out)
    ET.parse(out)  # raises if malformed
