"""Tests for scripts/artifacts/findMyBeaconLocations.py.

That module is meant to be dropped into an iLEAPP checkout, where
`scripts.ilapfuncs` is real. Here we stand up minimal stand-ins for the
handful of ilapfuncs helpers it uses, so the module's own logic
(UUID resolution, field extraction, timestamp routing) can be exercised
without vendoring iLEAPP itself.
"""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parent.parent / "scripts/artifacts/findMyBeaconLocations.py"

SYNTHETIC_ROOT = Path(__file__).parent / "fixtures/synthetic"
BEACON_LOC = (
    SYNTHETIC_ROOT
    / "private/var/mobile/Library/Caches/com.apple.icloud.searchpartyd/BeaconEstimatedLocation"
)
TRACKER_A = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
TRACKER_C = "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC"


@pytest.fixture
def logged_messages(monkeypatch):
    """Install stub `scripts`/`scripts.ilapfuncs` modules, return the log sink."""
    import plistlib

    messages = []

    def _get_plist_file_content(path):
        try:
            with open(path, "rb") as fp:
                return plistlib.load(fp)
        except Exception:
            return {}

    ilapfuncs = types.ModuleType("scripts.ilapfuncs")
    ilapfuncs.artifact_processor = lambda func: func
    ilapfuncs.convert_plist_date_to_utc = lambda v: v
    ilapfuncs.convert_cocoa_core_data_ts_to_utc = lambda v: ("cocoa", v)
    ilapfuncs.convert_unix_ts_to_utc = lambda v: ("unix", v)
    ilapfuncs.get_plist_file_content = _get_plist_file_content
    ilapfuncs.logfunc = messages.append

    scripts_pkg = types.ModuleType("scripts")
    scripts_pkg.ilapfuncs = ilapfuncs

    monkeypatch.setitem(sys.modules, "scripts", scripts_pkg)
    monkeypatch.setitem(sys.modules, "scripts.ilapfuncs", ilapfuncs)
    yield messages


@pytest.fixture
def findmy_module(logged_messages):
    spec = importlib.util.spec_from_file_location("findMyBeaconLocations", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeContext:
    def __init__(self, files):
        self._files = files

    def get_files_found(self):
        return self._files

    def get_relative_path(self, path):
        return str(Path(path).relative_to(SYNTHETIC_ROOT))


def test_artifacts_v2_dict_shape(findmy_module):
    entry = findmy_module.__artifacts_v2__["findMyBeaconLocations"]
    for key in (
        "name",
        "description",
        "author",
        "creation_date",
        "last_update_date",
        "requirements",
        "category",
        "notes",
        "paths",
        "output_types",
        "artifact_icon",
    ):
        assert key in entry
    assert isinstance(entry["paths"], tuple)
    assert "kml" in entry["output_types"]
    assert entry["category"] == "Find My"
    assert isinstance(entry["paths"], tuple)
    assert "timeline" in entry["output_types"]


def test_resolve_tracker_uuid_matches_pa_wrapped_real_fixture(findmy_module):
    real = (
        Path(__file__).parent
        / "fixtures/DFC948EE-XXXX-4D3A-9E44-10B162BF9898"
        / "2AE881AD-1171-461C-9AC0-C8991DB0284E_1.record"
        / "2AE881AD-1171-461C-9AC0-C8991DB0284E.record.plist"
    )
    assert (
        findmy_module._beacon_uuid(str(real))
        == "DFC948EE-XXXX-4D3A-9E44-10B162BF9898"
    )


def test_convert_timestamp_routes_by_magnitude(findmy_module):
    assert findmy_module._ts(None) == ""
    assert findmy_module._ts(800000000.0) == ("cocoa", 800000000.0)
    assert findmy_module._ts(1780000100.0) == ("unix", 1780000100.0)


def test_end_to_end_over_synthetic_fixtures(findmy_module, logged_messages):
    files = [
        BEACON_LOC / TRACKER_A / "PA_export_1/nested/deep/fix1.record",
        BEACON_LOC / TRACKER_A / "fix2.record",
        BEACON_LOC / TRACKER_C / "corrupted.record",
        BEACON_LOC / TRACKER_C / "json_variant.record",  # not a plist -> skipped
    ]
    context = FakeContext(files)
    headers, rows, source_path = findmy_module.findMyBeaconLocations(context)

    assert ("Latitude" in headers) and ("Longitude" in headers)
    assert ("Timestamp", "datetime") in headers

    # 2 valid bplist records parsed; corrupted + json_variant skipped (not
    # plists, and get_plist_file_content correctly returns {} for both).
    assert len(rows) == 2
    assert len(logged_messages) == 2

    uuids = {row[1] for row in rows}
    assert uuids == {TRACKER_A}

    assert source_path.count("\n") == 1  # 2 parsed files -> 1 newline joiner


def test_falls_back_to_path_uuid_when_payload_lacks_identifier(findmy_module, monkeypatch):
    monkeypatch.setattr(
        findmy_module,
        "get_plist_file_content",
        lambda path: {"latitude": 1.0, "longitude": 2.0},
    )
    context = FakeContext([BEACON_LOC / TRACKER_A / "fix2.record"])
    _, rows, _ = findmy_module.findMyBeaconLocations(context)
    assert rows[0][1] == TRACKER_A


def test_encrypted_record_is_logged_and_skipped(findmy_module, logged_messages, monkeypatch):
    """On-device these caches are encrypted; such a record must be logged
    and skipped rather than emitted as a positionless row."""
    monkeypatch.setattr(
        findmy_module,
        "get_plist_file_content",
        lambda path: {"encryptedData": b"\x00\x01", "signature": b"\x02"},
    )
    context = FakeContext([BEACON_LOC / TRACKER_A / "fix2.record"])
    _, rows, _ = findmy_module.findMyBeaconLocations(context)
    assert rows == []
    assert any("encryptedData" in m for m in logged_messages)


def test_row_shape_matches_headers(findmy_module):
    context = FakeContext([BEACON_LOC / TRACKER_A / "fix2.record"])
    headers, rows, _ = findmy_module.findMyBeaconLocations(context)
    assert len(rows) == 1
    assert len(rows[0]) == len(headers)


def test_kmlgen_required_headers_present_as_plain_strings(findmy_module):
    """kmlgen() bails unless the literal strings 'Latitude' and 'Longitude'
    are in data_headers, and names points from 'Timestamp'."""
    headers, _, _ = findmy_module.findMyBeaconLocations(FakeContext([]))
    assert "Latitude" in headers
    assert "Longitude" in headers
    assert ("Timestamp", "datetime") in headers


def test_paths_glob_matches_real_world_shapes_and_excludes_siblings(findmy_module):
    """iLEAPP matches with fnmatch (where * spans '/'), per
    admin/docs/artifact_info_block.md - so one pattern covers any depth,
    but it must end '*.record*' to catch the confirmed PA layout
    '<uuid>_1.record/<uuid>.record.plist'."""
    import fnmatch
    import os

    patterns = findmy_module.__artifacts_v2__["findMyBeaconLocations"]["paths"]
    base = "root/var/mobile/Library/Caches/com.apple.icloud.searchpartyd"

    def matches(path):
        return any(
            fnmatch.fnmatch(os.path.normcase(path), os.path.normcase(p)) for p in patterns
        )

    assert matches(f"{base}/BeaconEstimatedLocation/UUID-1/x.record")
    assert matches(f"{base}/BeaconEstimatedLocation/UUID-1/UUID-1_1.record/x.record.plist")
    assert matches(f"{base}/BeaconEstimatedLocation/UUID-1/x.record.decrypted")
    assert matches(f"{base}/BeaconEstimatedLocation/UUID-1/a/b/c/x.record")
    assert matches(
        "root/var/root/Library/Caches/com.apple.icloud.searchpartyd"
        "/BeaconEstimatedLocation/UUID-1/x.record"
    )

    # Sibling metadata folders must not be picked up as location fixes.
    assert not matches(f"{base}/OwnedBeacons/UUID-1.record")
    assert not matches(f"{base}/SharedBeacons/UUID-1.record")
    assert not matches(f"{base}/BeaconNamingRecord/UUID-1/n.record")
