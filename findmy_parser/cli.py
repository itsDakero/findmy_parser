"""Standalone CLI entry point.

    findmy-parser ROOT [--csv PATH] [--json PATH] [--kml PATH] ...

Wires discovery.discover() (all the real logic) to the output writers and
to Python logging - this module owns all of the run's I/O and reporting,
so everything below it can stay pure.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

from .discovery import DiscoveryResult, discover
from .output.csv_writer import write_csv
from .output.html_writer import write_html
from .output.json_writer import write_json
from .output.kml_writer import write_kml

logger = logging.getLogger("findmy_parser")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="findmy-parser",
        description=(
            "Parse Apple Find My forensic artifacts (fmipcore inventory + "
            "searchpartyd beacon location history) from an iOS full "
            "filesystem extraction or Physical Analyzer export. Read-only: "
            "never writes to, or modifies, the input path."
        ),
    )
    # nargs="+" so an unquoted path containing spaces still works: a
    # Windows path like "D:\\AIRTAG DATA\\PA Export" otherwise arrives as
    # three separate argv entries and argparse rejects the extras.
    parser.add_argument(
        "root",
        nargs="+",
        help="Extraction root, Physical Analyzer export folder, or a single file",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("findmy_parser_output"),
        help="Directory for default output file locations (default: ./findmy_parser_output)",
    )
    parser.add_argument(
        "--csv", type=Path, default=None, help="CSV output path (default: <output-dir>/findmy_locations.csv)"
    )
    parser.add_argument(
        "--json", type=Path, default=None, help="JSON output path (default: <output-dir>/findmy_locations.json)"
    )
    parser.add_argument(
        "--kml", type=Path, default=None, help="KML output path (not written unless given - optional format)"
    )
    parser.add_argument(
        "--html",
        type=Path,
        default=None,
        help="HTML report path (default: <output-dir>/findmy_report.html)",
    )
    parser.add_argument("--no-csv", action="store_true", help="Skip CSV output")
    parser.add_argument("--no-json", action="store_true", help="Skip JSON output")
    parser.add_argument("--no-html", action="store_true", help="Skip HTML report")
    parser.add_argument(
        "--log-file", type=Path, default=None, help="Run log path (default: <output-dir>/run.log)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose (debug) logging")
    return parser


def _configure_logging(verbose: bool) -> None:
    # A Windows `cmd` console is frequently not UTF-8 by default, and
    # tracker names/paths can contain non-ASCII characters (AirTags
    # support emoji names). Without this, logging such a message crashes
    # the whole run with UnicodeEncodeError instead of just that message
    # looking slightly odd.
    try:
        sys.stderr.reconfigure(errors="backslashreplace")
    except (AttributeError, ValueError):
        pass

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def _run_log_text(result: DiscoveryResult) -> str:
    lines = [
        f"record files found: {len(result.log.record_files_found)}",
        f"record files parsed: {len(result.log.record_files_parsed)}",
        f"record files skipped: {len(result.log.record_files_skipped)}",
        f"record files deduplicated: {len(result.log.record_files_deduped)}",
        f"inventory files found: {len(result.log.inventory_files_found)}",
        f"inventory files parsed: {len(result.log.inventory_files_parsed)}",
        f"inventory files skipped: {len(result.log.inventory_files_skipped)}",
        f"beacon metadata records parsed: {len(result.log.metadata_files_parsed)}",
        f"encrypted on-device records skipped (decrypted copy used instead): "
        f"{len(result.log.encrypted_records)}",
        f"beacon metadata records skipped: {len(result.log.metadata_files_skipped)}",
        f"directories/entries unreadable during scan: {len(result.log.walk_errors)}",
        "",
    ]
    if result.log.name_sources:
        lines.append("tracker name sources (tracker -> where the name came from):")
        lines.extend(f"  {tid} -> {src}" for tid, src in sorted(result.log.name_sources.items()))
        lines.append("")
    if result.log.unmatched_tracker_ids:
        lines.append("trackers with location fixes but NO name from any source:")
        lines.extend(f"  {tid}" for tid in result.log.unmatched_tracker_ids)
        lines.append("")
        if result.log.inventory_identifiers:
            lines.append("identifiers present in inventory files (compare against the above):")
            lines.extend(f"  {i}" for i in sorted(set(result.log.inventory_identifiers)))
            lines.append("")
    if result.log.metadata_files_skipped:
        lines.append("beacon metadata records skipped (path: reason):")
        lines.extend(f"  {p}: {reason}" for p, reason in result.log.metadata_files_skipped)
        lines.append("")
    if result.log.walk_errors:
        lines.append("unreadable during scan (path: reason):")
        lines.extend(f"  {path}: {reason}" for path, reason in result.log.walk_errors)
        lines.append("")
    if result.log.record_files_skipped:
        lines.append("record files skipped (path: reason):")
        lines.extend(f"  {path}: {reason}" for path, reason in result.log.record_files_skipped)
        lines.append("")
    if result.log.inventory_files_skipped:
        lines.append("inventory files skipped (path: reason):")
        lines.extend(f"  {path}: {reason}" for path, reason in result.log.inventory_files_skipped)
        lines.append("")
    if result.log.record_files_deduped:
        lines.append("record files deduplicated (duplicate -> kept):")
        lines.extend(f"  {dup} -> {kept}" for dup, kept in result.log.record_files_deduped)
        lines.append("")
    return "\n".join(lines)


def run(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    root = Path(" ".join(args.root))
    if not root.exists():
        logger.error("input path does not exist: %s", root)
        logger.error("if the path contains spaces, wrap it in quotes")
        return 2

    logger.info("scanning %s (read-only)", root)
    result = discover(root)

    for path, reason in result.log.walk_errors:
        logger.warning("could not read during scan %s: %s", path, reason)
    for path, reason in result.log.record_files_skipped:
        logger.warning("skipped .record file %s: %s", path, reason)
    for path, reason in result.log.inventory_files_skipped:
        logger.warning("skipped inventory file %s: %s", path, reason)
    for dup, kept in result.log.record_files_deduped:
        logger.info("duplicate dropped: %s (kept %s)", dup, kept)

    total_fixes = sum(len(v) for v in result.fixes_by_tracker.values())
    logger.info(
        "%d trackers, %d location fixes (%d record files parsed, %d skipped, %d deduplicated)",
        len(result.trackers),
        total_fixes,
        len(result.log.record_files_parsed),
        len(result.log.record_files_skipped),
        len(result.log.record_files_deduped),
    )

    output_dir: Path = args.output_dir
    wrote_any = False

    if not args.no_csv:
        csv_path = args.csv or (output_dir / "findmy_locations.csv")
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        write_csv(result, csv_path)
        logger.info("wrote CSV: %s", csv_path)
        wrote_any = True

    if not args.no_json:
        json_path = args.json or (output_dir / "findmy_locations.json")
        json_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(result, json_path)
        logger.info("wrote JSON: %s", json_path)
        wrote_any = True

    if not args.no_html:
        html_path = args.html or (output_dir / "findmy_report.html")
        html_path.parent.mkdir(parents=True, exist_ok=True)
        write_html(result, html_path, source_root=str(root))
        logger.info("wrote HTML report: %s", html_path)
        wrote_any = True

    if args.kml:
        args.kml.parent.mkdir(parents=True, exist_ok=True)
        write_kml(result, args.kml)
        logger.info("wrote KML: %s", args.kml)
        wrote_any = True

    log_path = args.log_file or (output_dir / "run.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(_run_log_text(result), encoding="utf-8")
    logger.info("wrote run log: %s", log_path)

    if not wrote_any:
        logger.warning("no location output written (--no-csv and --no-json set, --kml not given)")

    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
