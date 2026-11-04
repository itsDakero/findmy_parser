"""Structural diagnostic: report what the input actually is.

    python3 -m findmy_parser.diagnose /path/to/export

Prints the shape of every Find My file found - format, top-level type,
key names, encryption state - and works out locally whether the beacon
UUIDs and the inventory identifiers overlap, which is what decides
whether friendly names can be joined at all.

Deliberately prints no field *values* and no identifiers: key names,
types, counts and verdicts only, so the output is safe to paste into a
bug report or share with someone helping. Pass --show-ids to include
truncated identifiers when you do want to see them yourself.
"""

from __future__ import annotations

import argparse
import json
import plistlib
import sys
from pathlib import Path
from typing import Any, Optional

from .discovery import _looks_like_record, discover_files, resolve_tracker_uuid
from .fmipcore import _IDENTIFIER_KEYS
from .searchpartyd import classify_record_path
from .sniff import detect_format


def _describe(path: Path) -> dict:
    """Format, top-level type and key names of one file. No values."""
    info: dict[str, Any] = {"path": str(path)}
    try:
        data = path.read_bytes()
    except OSError as exc:
        info["error"] = f"unreadable: {exc}"
        return info

    info["bytes"] = len(data)
    info["magic"] = data[:8].hex() if len(data) >= 8 else data.hex()
    info["format"] = detect_format(data)

    payload: Any = None
    if info["format"] in ("bplist", "xml_plist"):
        try:
            payload = plistlib.loads(data)
        except Exception as exc:
            info["parse_error"] = str(exc)
    elif info["format"] == "json":
        try:
            payload = json.loads(data)
        except Exception as exc:
            info["parse_error"] = str(exc)
    else:
        info["parse_error"] = "not bplist, XML plist or JSON"

    if payload is None:
        return info

    info["top_level_type"] = type(payload).__name__
    if isinstance(payload, dict):
        info["keys"] = sorted(payload)
        info["encrypted"] = "encryptedData" in payload and "signature" in payload
        if payload.get("$archiver"):
            info["nskeyedarchiver"] = True
    elif isinstance(payload, list):
        info["entries"] = len(payload)
        # Element types, so the signed/encrypted wrapper form (a short list
        # of opaque values) is distinguishable from a list of real entries.
        info["entry_types"] = [type(e).__name__ for e in payload[:6]]
        first = next((e for e in payload if isinstance(e, dict)), None)
        if first is not None:
            info["first_entry_keys"] = sorted(first)
        else:
            info["wrapper_form"] = True
    return info


def _ids_from_inventory(paths: list[Path]) -> set[str]:
    found: set[str] = set()
    for path in paths:
        info = _describe(path)
        if info.get("parse_error"):
            continue
        try:
            data = path.read_bytes()
            payload = (
                json.loads(data) if info["format"] == "json" else plistlib.loads(data)
            )
        except Exception:
            continue
        entries = payload if isinstance(payload, list) else [payload]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            for key in _IDENTIFIER_KEYS:
                value = entry.get(key)
                if value:
                    found.add(str(value))
    return found


def _print_file(info: dict, show_ids: bool) -> None:
    print(f"  {info['path']}")
    if "error" in info:
        print(f"      ERROR {info['error']}")
        return
    bits = [f"{info['bytes']} bytes", f"format={info['format']}"]
    if info.get("top_level_type"):
        bits.append(f"top-level={info['top_level_type']}")
    if info.get("entries") is not None:
        bits.append(f"entries={info['entries']}")
    print("      " + ", ".join(bits))
    if info.get("parse_error"):
        print(f"      PARSE ERROR: {info['parse_error']}")
    if info.get("encrypted"):
        print("      *** ENCRYPTED (encryptedData + signature) - decrypt via PA first")
    if info.get("nskeyedarchiver"):
        print("      NSKeyedArchiver-wrapped")
    if info.get("entry_types"):
        print(f"      entry types: {', '.join(info['entry_types'])}")
    if info.get("wrapper_form"):
        print("      *** signed/encrypted on-device form (no readable fields);")
        print("          the decrypted copy is the sibling <uuid>_1.record/*.record.plist")
    keys = info.get("keys") or info.get("first_entry_keys")
    if keys:
        label = "keys" if "keys" in info else "first entry keys"
        print(f"      {label}: {', '.join(keys)}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="findmy-parser-diagnose",
        description=(
            "Report the structure of Find My data under a path. Prints key "
            "names, types and counts - never field values."
        ),
    )
    # nargs="+" so an unquoted Windows path containing spaces still works:
    # "D:\\AIRTAG DATA\\PA Export" arrives as three argv entries otherwise.
    parser.add_argument(
        "root", nargs="+", help="Extraction root or PA export folder"
    )
    parser.add_argument(
        "--show-ids",
        action="store_true",
        help="Include truncated identifiers in the output (off by default)",
    )
    args = parser.parse_args(argv)
    root = Path(" ".join(args.root))

    if not root.exists():
        print(f"ERROR: path does not exist: {root}", file=sys.stderr)
        print(
            "If the path contains spaces, wrap it in quotes.",
            file=sys.stderr,
        )
        return 2

    record_paths, inventory_paths, walk_errors = discover_files(root)

    by_kind: dict[str, list[Path]] = {}
    for path in record_paths:
        by_kind.setdefault(classify_record_path(path), []).append(path)

    print(f"ROOT: {root}")
    print()
    print("=== WHAT WAS FOUND ===")
    print(f"  files matching '*.record*' : {len(record_paths)}")
    for kind, paths in sorted(by_kind.items()):
        print(f"      {kind}: {len(paths)}")
    print(f"  fmipcore inventory files   : {len(inventory_paths)}")
    print(f"  unreadable during scan     : {len(walk_errors)}")
    for path, reason in walk_errors[:10]:
        print(f"      {path}: {reason}")

    if not record_paths and not inventory_paths:
        print()
        print("  NOTHING FOUND. Either the path is wrong, or the filenames differ")
        print("  from anything recognised. Listing what IS there, 2 levels down:")
        for child in sorted(root.rglob("*"))[:40]:
            print(f"      {child.relative_to(root)}")
        return 1

    print()
    print("=== INVENTORY FILES (Items.data / Devices.data / ...) ===")
    if not inventory_paths:
        print("  none found")
    for path in inventory_paths[:10]:
        _print_file(_describe(path), args.show_ids)

    for kind in ("location", "naming_record", "owned_beacon", "shared_beacon"):
        paths = by_kind.get(kind) or []
        if not paths:
            continue
        print()
        print(f"=== {kind.upper()} RECORDS (showing up to 3 of {len(paths)}) ===")
        for path in paths[:3]:
            _print_file(_describe(path), args.show_ids)

    # The join question, answered locally.
    print()
    print("=== CAN NAMES BE JOINED? ===")
    beacon_ids: set[str] = set()
    for path in by_kind.get("location") or []:
        uuid = resolve_tracker_uuid(path)
        if uuid:
            beacon_ids.add(uuid)
    inventory_ids = _ids_from_inventory(inventory_paths)

    print(f"  distinct beacon UUIDs (from folder names): {len(beacon_ids)}")
    print(f"  distinct inventory identifiers           : {len(inventory_ids)}")
    overlap = beacon_ids & inventory_ids
    print(f"  overlap                                  : {len(overlap)}")

    if beacon_ids and inventory_ids and not overlap:
        print()
        print("  VERDICT: no overlap. The inventory files do not key on the same")
        print("  identifier as the beacon folders, so names can only come from")
        print("  BeaconNamingRecord / OwnedBeacons.")
    elif overlap:
        print()
        print(f"  VERDICT: {len(overlap)} of {len(beacon_ids)} beacons have an inventory entry.")
    elif not inventory_ids:
        print()
        print("  VERDICT: no inventory identifiers readable - see the inventory")
        print("  section above for why (encrypted? parse error? none found?).")

    if args.show_ids:
        print()
        print("  beacon UUIDs    :", ", ".join(sorted(i[:8] + "..." for i in beacon_ids)) or "-")
        print("  inventory IDs   :", ", ".join(sorted(i[:8] + "..." for i in inventory_ids)) or "-")

    return 0


if __name__ == "__main__":
    sys.exit(main())
