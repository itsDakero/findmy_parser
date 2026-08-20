from pathlib import Path

import pytest

from findmy_parser.beacons import (
    RecordParseError,
    content_hash,
    parse_record_bytes,
    parse_record_file,
)

FIXTURES = Path(__file__).parent / "fixtures"
SYNTHETIC = FIXTURES / "synthetic"
BEACON_LOC = (
    SYNTHETIC
    / "private/var/mobile/Library/Caches/com.apple.icloud.searchpartyd/BeaconEstimatedLocation"
)

REAL_SAMPLE = (
    FIXTURES
    / "DFC948EE-XXXX-4D3A-9E44-10B162BF9898"
    / "2AE881AD-1171-461C-9AC0-C8991DB0284E_1.record"
    / "2AE881AD-1171-461C-9AC0-C8991DB0284E.record.plist"
)


def test_parses_real_sample_fixture():
    fix = parse_record_file(REAL_SAMPLE)
    assert fix.tracker_id == "DFC948EE-XXXX-4D3A-9E44-10B162BF9898"
    assert fix.latitude == pytest.approx(42.72016201997952)
    assert fix.longitude == pytest.approx(-4.620168518106665)
    assert fix.horizontal_accuracy == pytest.approx(19.120163509807824)
    assert fix.timestamp_utc == "2026-07-28T15:43:12Z"
    assert fix.scan_date_utc == "2026-07-28T15:43:12Z"
    assert fix.source_file == str(REAL_SAMPLE)
    # Unconfirmed keys must never be silently invented.
    assert "confidence" not in fix.raw
    assert "status" not in fix.raw
    assert fix.raw["locationSource"] == 2


def test_parses_nested_pa_export_bplist():
    path = BEACON_LOC / "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA" / "PA_export_1" / "nested" / "deep" / "fix1.record"
    fix = parse_record_file(path)
    assert fix.tracker_id == "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
    assert fix.latitude == pytest.approx(37.334606)
    assert fix.timestamp_utc == "2026-06-01T08:00:00Z"


def test_duplicate_record_in_different_pa_branches_has_same_content_hash():
    original = BEACON_LOC / "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA" / "PA_export_1" / "nested" / "deep" / "fix1.record"
    duplicate = BEACON_LOC / "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA" / "PA_export_2" / "another_branch" / "fix1_dup.record"

    fix_a = parse_record_file(original)
    fix_b = parse_record_file(duplicate)

    assert fix_a.source_file != fix_b.source_file
    assert content_hash(fix_a) == content_hash(fix_b)


def test_distinct_fixes_have_different_content_hash():
    fix1 = parse_record_file(BEACON_LOC / "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA" / "fix2.record")
    fix3 = parse_record_file(BEACON_LOC / "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB" / "fix3.record")
    assert content_hash(fix1) != content_hash(fix3)


def test_corrupted_record_raises_record_parse_error():
    path = BEACON_LOC / "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC" / "corrupted.record"
    with pytest.raises(RecordParseError):
        parse_record_file(path)


def test_xml_plist_variant_is_sniffed_and_parsed():
    path = BEACON_LOC / "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC" / "xml_variant.record"
    fix = parse_record_file(path)
    assert fix.tracker_id == "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC"
    assert fix.latitude == pytest.approx(48.8566)


def test_json_variant_is_sniffed_and_parsed():
    path = BEACON_LOC / "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC" / "json_variant.record"
    fix = parse_record_file(path)
    assert fix.tracker_id == "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC"
    assert fix.longitude == pytest.approx(139.6503)
    # Raw Unix-seconds epoch number, not a native plist date.
    assert fix.timestamp_utc == "2026-05-28T20:26:40Z"


def test_numeric_epoch_variant_autodetects_cocoa_and_unix():
    path = BEACON_LOC / "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC" / "numeric_epoch.record"
    fix = parse_record_file(path)
    # timestamp: 800000000.0 as Cocoa seconds
    assert fix.timestamp_utc == "2026-05-09T06:13:20Z"
    # scanDate: 1780000100.0 as Unix seconds
    assert fix.scan_date_utc == "2026-05-28T20:28:20Z"


def test_tracker_id_hint_used_when_payload_lacks_identifier():
    fix = parse_record_bytes(
        b'{"latitude": 1.0, "longitude": 2.0}',
        source_file="synthetic://no-id.record",
        tracker_id_hint="HINTED-UUID",
    )
    assert fix.tracker_id == "HINTED-UUID"


def test_unrecognised_format_raises():
    with pytest.raises(RecordParseError):
        parse_record_bytes(b"neither plist nor json", source_file="synthetic://bad")


def test_non_dict_top_level_raises():
    with pytest.raises(RecordParseError):
        parse_record_bytes(b"[1, 2, 3]", source_file="synthetic://array")
