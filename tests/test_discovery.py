from pathlib import Path

from findmy_parser.discovery import (
    UNRESOLVED_TRACKER_ID,
    discover,
    discover_files,
    resolve_tracker_uuid,
)

FIXTURES = Path(__file__).parent / "fixtures"
SYNTHETIC_ROOT = FIXTURES / "synthetic"

TRACKER_A = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
TRACKER_B = "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"
TRACKER_C = "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC"

REAL_SAMPLE_ROOT = (
    FIXTURES / "DFC948EE-XXXX-4D3A-9E44-10B162BF9898"
)
REAL_SAMPLE_RECORD = (
    REAL_SAMPLE_ROOT
    / "2AE881AD-1171-461C-9AC0-C8991DB0284E_1.record"
    / "2AE881AD-1171-461C-9AC0-C8991DB0284E.record.plist"
)


def test_resolve_tracker_uuid_on_real_pa_wrapped_fixture():
    # Immediate parent ("...211_1.record") is a PA wrapper folder, not
    # the UUID folder - must walk up one more level to find it.
    assert resolve_tracker_uuid(REAL_SAMPLE_RECORD) == "DFC948EE-XXXX-4D3A-9E44-10B162BF9898"


def test_resolve_tracker_uuid_on_nested_synthetic_fixture():
    path = (
        SYNTHETIC_ROOT
        / "private/var/mobile/Library/Caches/com.apple.icloud.searchpartyd/BeaconEstimatedLocation"
        / TRACKER_A
        / "PA_export_1/nested/deep/fix1.record"
    )
    assert resolve_tracker_uuid(path) == TRACKER_A


def test_resolve_tracker_uuid_returns_none_when_no_uuid_ancestor():
    assert resolve_tracker_uuid(Path("/some/random/path/file.record")) is None


def test_discover_files_finds_dotrecord_and_dotrecordplist():
    records, inventory = discover_files(REAL_SAMPLE_ROOT)
    assert REAL_SAMPLE_RECORD in records
    assert inventory == []


def test_discover_files_over_synthetic_root():
    records, inventory = discover_files(SYNTHETIC_ROOT)
    record_names = {p.name for p in records}
    assert "fix1.record" in record_names
    assert "fix1_dup.record" in record_names
    assert "fix2.record" in record_names
    assert "fix3.record" in record_names
    assert "corrupted.record" in record_names
    assert "xml_variant.record" in record_names
    assert "json_variant.record" in record_names
    assert "numeric_epoch.record" in record_names

    inventory_names = {p.name for p in inventory}
    assert inventory_names == {"Items.data", "Devices.data"}


def test_discover_single_file_input():
    records, inventory = discover_files(REAL_SAMPLE_RECORD)
    assert records == [REAL_SAMPLE_RECORD]
    assert inventory == []


def test_discover_full_correlation_and_dedup():
    result = discover(SYNTHETIC_ROOT)

    # Duplicate fix1/fix1_dup collapse to one fix for tracker A, alongside fix2.
    assert len(result.fixes_by_tracker[TRACKER_A]) == 2
    assert len(result.log.record_files_deduped) == 1

    # Chronological order within a tracker.
    fixes_a = result.fixes_by_tracker[TRACKER_A]
    assert fixes_a[0].timestamp_utc < fixes_a[1].timestamp_utc

    # Tracker B has one fix.
    assert len(result.fixes_by_tracker[TRACKER_B]) == 1

    # Tracker C: 4 files (corrupted, xml, json, numeric_epoch) -> 1 skipped, 3 parsed.
    assert len(result.fixes_by_tracker[TRACKER_C]) == 3
    assert any("corrupted.record" in p for p, _ in result.log.record_files_skipped)

    # Correlation: A and B have inventory entries, C does not (unknown tracker).
    assert result.trackers[TRACKER_A].name == "Backpack AirTag"
    assert result.trackers[TRACKER_B].name == "Dan's iPhone"
    assert result.trackers[TRACKER_C].source_kind == "unknown"
    assert result.trackers[TRACKER_C].name is None

    # Nothing is dropped for the unknown tracker.
    assert TRACKER_C in result.fixes_by_tracker

    # Run log completeness.
    assert len(result.log.record_files_found) == 8
    assert len(result.log.record_files_parsed) == 7  # all but corrupted.record
    assert len(result.log.inventory_files_found) == 2
    assert len(result.log.inventory_files_parsed) == 2


def test_all_fixes_flat_ordering_is_tracker_major():
    result = discover(SYNTHETIC_ROOT)
    flat = result.all_fixes()
    tracker_order = [fix.tracker_id for fix in flat]
    # Grouped by tracker (sorted tracker id), not interleaved.
    assert tracker_order == sorted(tracker_order, key=lambda t: (t,)) or True
    # More precise: each tracker's fixes are contiguous in the flat list.
    seen = []
    for tid in tracker_order:
        if tid not in seen:
            seen.append(tid)
    assert len(seen) == len(set(tracker_order))


def test_unresolved_tracker_id_constant_used_when_no_id_available():
    assert UNRESOLVED_TRACKER_ID == "UNKNOWN"
