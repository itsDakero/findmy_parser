import csv
import json
from pathlib import Path

from findmy_parser.cli import run

SYNTHETIC_ROOT = Path(__file__).parent / "fixtures/synthetic"


def test_run_writes_default_csv_and_json(tmp_path):
    out_dir = tmp_path / "out"
    exit_code = run([str(SYNTHETIC_ROOT), "--output-dir", str(out_dir)])
    assert exit_code == 0

    csv_path = out_dir / "findmy_locations.csv"
    json_path = out_dir / "findmy_locations.json"
    log_path = out_dir / "run.log"
    assert csv_path.exists()
    assert json_path.exists()
    assert log_path.exists()

    with open(csv_path, newline="", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))
    data = json.loads(json_path.read_text())
    assert len(rows) == len(data) == 6

    log_text = log_path.read_text()
    assert "record files found: 10" in log_text  # includes 2 beacon metadata records
    assert "record files parsed: 7" in log_text  # location fixes only
    assert "corrupted.record" in log_text


def test_kml_only_written_when_requested(tmp_path):
    out_dir = tmp_path / "out"
    run([str(SYNTHETIC_ROOT), "--output-dir", str(out_dir)])
    assert not (out_dir / "findmy_locations.kml").exists()

    kml_path = tmp_path / "explicit.kml"
    run([str(SYNTHETIC_ROOT), "--output-dir", str(out_dir), "--kml", str(kml_path)])
    assert kml_path.exists()


def test_no_csv_no_json_flags(tmp_path):
    out_dir = tmp_path / "out"
    run([str(SYNTHETIC_ROOT), "--output-dir", str(out_dir), "--no-csv", "--no-json"])
    assert not (out_dir / "findmy_locations.csv").exists()
    assert not (out_dir / "findmy_locations.json").exists()
    assert (out_dir / "run.log").exists()  # run log always written


def test_nonexistent_root_returns_error_exit_code(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert run([str(missing)]) == 2


def test_single_record_file_input(tmp_path):
    record = (
        SYNTHETIC_ROOT
        / "private/var/mobile/Library/Caches/com.apple.icloud.searchpartyd/BeaconEstimatedLocation"
        / "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB/fix3.record"
    )
    out_dir = tmp_path / "out"
    exit_code = run([str(record), "--output-dir", str(out_dir)])
    assert exit_code == 0
    data = json.loads((out_dir / "findmy_locations.json").read_text())
    assert len(data) == 1


def test_run_never_writes_inside_input_root(tmp_path):
    """Forensic integrity: input path must never be modified."""
    before = sorted(p for p in SYNTHETIC_ROOT.rglob("*"))
    before_mtimes = {p: p.stat().st_mtime_ns for p in before if p.is_file()}

    out_dir = tmp_path / "out"
    run([str(SYNTHETIC_ROOT), "--output-dir", str(out_dir), "--kml", str(tmp_path / "x.kml")])

    after = sorted(p for p in SYNTHETIC_ROOT.rglob("*"))
    after_mtimes = {p: p.stat().st_mtime_ns for p in after if p.is_file()}
    assert before == after
    assert before_mtimes == after_mtimes
