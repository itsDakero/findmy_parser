import html.parser
import plistlib
from pathlib import Path

import pytest

from findmy_parser.discovery import discover
from findmy_parser.output.html_writer import write_html

SYNTHETIC_ROOT = Path(__file__).parent / "fixtures/synthetic"
TRACKER_A = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
TRACKER_C = "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC"


class _StrictParser(html.parser.HTMLParser):
    def error(self, message):  # pragma: no cover - only fires on malformed input
        raise AssertionError(message)


@pytest.fixture
def report(tmp_path):
    result = discover(SYNTHETIC_ROOT)
    out = tmp_path / "report.html"
    write_html(result, out, source_root=str(SYNTHETIC_ROOT))
    return out.read_text(encoding="utf-8")


def test_html_is_wellformed(report):
    _StrictParser().feed(report)


def test_one_section_per_tracker(report):
    assert report.count("class='tracker'") == 3


def test_tracker_names_and_uuids_rendered(report):
    assert "Backpack AirTag" in report
    assert "Keys AirTag" in report  # from BeaconNamingRecord
    assert TRACKER_A in report
    assert TRACKER_C in report


def test_beacon_uuid_labelled_for_verification(report):
    assert "Beacon UUID:" in report


def test_location_rows_present_with_coordinates(report):
    assert "37.334606" in report
    assert "-122.009102" in report


def test_source_file_shown_for_every_fix(report):
    # Forensic traceability: each row cites its origin file.
    assert report.count("class='src'") == 6  # 6 total fixes across all trackers


def test_run_log_section_included(report):
    assert "Run log" in report
    assert "Skipped location records" in report
    assert "corrupted.record" in report


def test_self_contained_no_external_requests(report):
    for pattern in ("http://", "https://", "<script", "src=", "@import"):
        assert pattern not in report, f"report must be self-contained, found {pattern!r}"


def test_supports_light_and_dark(report):
    assert "prefers-color-scheme: dark" in report
    assert "color-scheme: light dark" in report


def test_html_escaping_of_hostile_values(tmp_path):
    root = tmp_path / "BeaconEstimatedLocation" / "EEEEEEEE-EEEE-4EEE-8EEE-EEEEEEEEEEEE"
    root.mkdir(parents=True)
    with open(root / "fix.record", "wb") as fp:
        plistlib.dump(
            {
                "associatedBeacon": "EEEEEEEE-EEEE-4EEE-8EEE-EEEEEEEEEEEE",
                "name": "<script>alert('xss')</script>",
                "latitude": 1.0,
                "longitude": 2.0,
            },
            fp,
            fmt=plistlib.FMT_BINARY,
        )
    naming = tmp_path / "BeaconNamingRecord" / "EEEEEEEE-EEEE-4EEE-8EEE-EEEEEEEEEEEE"
    naming.mkdir(parents=True)
    with open(naming / "n.record", "wb") as fp:
        plistlib.dump(
            {
                "associatedBeacon": "EEEEEEEE-EEEE-4EEE-8EEE-EEEEEEEEEEEE",
                "name": "<script>alert('xss')</script>",
            },
            fp,
            fmt=plistlib.FMT_BINARY,
        )

    out = tmp_path / "report.html"
    write_html(discover(tmp_path), out)
    content = out.read_text(encoding="utf-8")
    assert "<script>alert" not in content
    assert "&lt;script&gt;" in content


def test_empty_result_renders_without_error(tmp_path):
    out = tmp_path / "empty.html"
    write_html(discover(tmp_path), out)
    content = out.read_text(encoding="utf-8")
    _StrictParser().feed(content)
    assert "No location fixes found." in content
