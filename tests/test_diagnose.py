import json
import plistlib
from pathlib import Path

from findmy_parser.diagnose import main

SYNTHETIC_ROOT = Path(__file__).parent / "fixtures/synthetic"


def test_reports_synthetic_root_structure(capsys):
    assert main([str(SYNTHETIC_ROOT)]) == 0
    out = capsys.readouterr().out
    assert "files matching '*.record*' : 10" in out
    assert "location: 8" in out
    assert "naming_record: 1" in out
    assert "owned_beacon: 1" in out
    assert "fmipcore inventory files   : 2" in out
    # Key names are reported, which is what identifies an unknown schema.
    assert "associatedBeacon" in out
    assert "horizontalAccuracy" in out


def test_reports_join_verdict(capsys):
    main([str(SYNTHETIC_ROOT)])
    out = capsys.readouterr().out
    assert "CAN NAMES BE JOINED?" in out
    assert "2 of 3 beacons have an inventory entry" in out


def test_prints_no_field_values_by_default(capsys):
    """Output must be safe to paste: key names and counts, never values."""
    main([str(SYNTHETIC_ROOT)])
    out = capsys.readouterr().out
    # Values from the fixtures that must not appear.
    for value in ("Backpack AirTag", "Keys AirTag", "AT-SN-0001", "37.334606", "Dan's iPhone"):
        assert value not in out, f"diagnostic leaked a field value: {value!r}"


def test_identifiers_withheld_unless_requested(capsys):
    full_uuid = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
    main([str(SYNTHETIC_ROOT)])
    assert "beacon UUIDs    :" not in capsys.readouterr().out

    main([str(SYNTHETIC_ROOT), "--show-ids"])
    out = capsys.readouterr().out
    assert "beacon UUIDs    :" in out
    # Even then they're truncated, not printed whole.
    assert "AAAAAAAA..." in out
    assert full_uuid not in out.split("beacon UUIDs")[1]


def test_flags_encrypted_inventory(tmp_path, capsys):
    fmipcore = tmp_path / "Caches/com.apple.findmy.fmipcore"
    fmipcore.mkdir(parents=True)
    with open(fmipcore / "Items.data", "wb") as fp:
        plistlib.dump({"encryptedData": b"\x01", "signature": b"\x02"}, fp, fmt=plistlib.FMT_BINARY)

    main([str(tmp_path)])
    out = capsys.readouterr().out
    assert "ENCRYPTED (encryptedData + signature)" in out
    assert "no inventory identifiers readable" in out


def test_reports_no_overlap_verdict(tmp_path, capsys):
    """The case that matters: inventory and beacon folders keyed differently."""
    fmipcore = tmp_path / "Caches/com.apple.findmy.fmipcore"
    fmipcore.mkdir(parents=True)
    (fmipcore / "Items.data").write_text(json.dumps([{"identifier": "TOTALLY-OTHER-ID"}]))

    record_dir = tmp_path / "BeaconEstimatedLocation" / "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
    record_dir.mkdir(parents=True)
    with open(record_dir / "fix.record", "wb") as fp:
        plistlib.dump({"latitude": 1.0, "longitude": 2.0}, fp, fmt=plistlib.FMT_BINARY)

    main([str(tmp_path)])
    out = capsys.readouterr().out
    assert "VERDICT: no overlap" in out
    assert "BeaconNamingRecord / OwnedBeacons" in out


def test_lists_contents_when_nothing_recognised(tmp_path, capsys):
    (tmp_path / "SomeExport").mkdir()
    (tmp_path / "SomeExport/readme.txt").write_text("x")

    assert main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "NOTHING FOUND" in out
    assert "SomeExport/readme.txt" in out


def test_missing_path_returns_error(tmp_path, capsys):
    assert main([str(tmp_path / "nope")]) == 2


def test_unquoted_path_with_spaces_is_accepted(tmp_path, capsys):
    """A Windows path with spaces arrives as several argv entries when
    unquoted; joining them back is friendlier than rejecting the extras."""
    spaced = tmp_path / "AIRTAG DATA" / "AIRTAG TEST" / "PA Export"
    (spaced / "Caches/com.apple.findmy.fmipcore").mkdir(parents=True)
    (spaced / "Caches/com.apple.findmy.fmipcore/Items.data").write_text(
        json.dumps([{"identifier": "X1", "name": "n"}])
    )

    # As the shell would split it.
    argv = str(spaced).split(" ")
    assert len(argv) > 1
    assert main(argv) == 0
    assert "fmipcore inventory files   : 1" in capsys.readouterr().out


def test_missing_spaced_path_hints_about_quoting(tmp_path, capsys):
    assert main([str(tmp_path / "no such"), "folder"]) == 2
    assert "wrap it in quotes" in capsys.readouterr().err
