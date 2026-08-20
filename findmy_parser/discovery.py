"""Recursive file discovery, UUID resolution, correlation, and dedup.

Handles the two things the CLI needs beyond raw parsing:

- Finding relevant files anywhere under an arbitrary root, because a
  Physical Analyzer export wraps the real files in extra, unpredictable
  subfolders (never assume a fixed directory depth).
- Joining `.record` location fixes to their owning tracker (by UUID) and
  to that tracker's fmipcore inventory entry, if any.

Still no reporting/logging side effects beyond the `DiscoveryLog` object
returned alongside the results — callers (cli.py) decide how/whether to
print it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .beacons import RecordParseError, content_hash, parse_record_file
from .fmipcore import InventoryParseError, is_fmipcore_filename, parse_inventory_file
from .models import LocationFix, Tracker

UNRESOLVED_TRACKER_ID = "UNKNOWN"

# Matches a UUID-shaped path component (8-4-4-4-12 groups) by shape, not
# strict hex validity: real fixture data includes a redacted UUID folder
# name ("DFC948EE-XXXX-4D3A-9E44-10B162BF9898") that a strict hex check
# would reject. "XXXX" is not valid hex but is the right shape, and this
# tool needs to resolve it the same way a genuine UUID would resolve.
_UUID_SHAPE_RE = re.compile(
    r"^[0-9A-Za-z]{8}-[0-9A-Za-z]{4}-[0-9A-Za-z]{4}-[0-9A-Za-z]{4}-[0-9A-Za-z]{12}$"
)


def _looks_like_record(name: str) -> bool:
    # Real exported files are not always named exactly "*.record" - the
    # confirmed fixture is "<uuid>.record.plist", sitting inside a PA
    # wrapper folder named "<uuid>_1.record/". Match the substring
    # anywhere in the name rather than trusting a fixed suffix.
    return ".record" in name.lower()


def resolve_tracker_uuid(record_path: Path) -> Optional[str]:
    """Walk up from a `.record` file and return the owning tracker UUID.

    Returns the first ancestor directory name shaped like a UUID,
    starting from the immediate parent and moving up. Never assumes the
    immediate parent *is* the UUID folder, since PA export wrapping can
    insert extra folders below it.
    """
    for parent in record_path.parents:
        if _UUID_SHAPE_RE.match(parent.name):
            return parent.name
    return None


@dataclass
class DiscoveryLog:
    """Run log: what was found, parsed, skipped, or deduplicated, and why."""

    record_files_found: list[str] = field(default_factory=list)
    record_files_parsed: list[str] = field(default_factory=list)
    record_files_skipped: list[tuple[str, str]] = field(default_factory=list)
    record_files_deduped: list[tuple[str, str]] = field(default_factory=list)
    inventory_files_found: list[str] = field(default_factory=list)
    inventory_files_parsed: list[str] = field(default_factory=list)
    inventory_files_skipped: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class DiscoveryResult:
    trackers: dict[str, Tracker]
    fixes_by_tracker: dict[str, list[LocationFix]]
    log: DiscoveryLog

    def all_fixes(self) -> list[LocationFix]:
        """All fixes, tracker-major then chronological, for flat output formats."""
        out: list[LocationFix] = []
        for tracker_id in sorted(self.fixes_by_tracker):
            out.extend(self.fixes_by_tracker[tracker_id])
        return out


def discover_files(root: Path) -> tuple[list[Path], list[Path]]:
    """Recursively find `.record` files and fmipcore inventory files under root.

    `root` may be a single file, in which case it's classified on its own.
    Never writes to `root` - a plain recursive read-only walk.
    """
    if root.is_file():
        records = [root] if _looks_like_record(root.name) else []
        inventory = [root] if is_fmipcore_filename(root.name) else []
        return records, inventory

    records = []
    inventory = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if _looks_like_record(path.name):
            records.append(path)
        elif is_fmipcore_filename(path.name):
            inventory.append(path)
    return sorted(records), sorted(inventory)


def discover(root: Path) -> DiscoveryResult:
    """Discover, parse, deduplicate, and correlate everything under root."""
    root = Path(root)
    log = DiscoveryLog()
    record_paths, inventory_paths = discover_files(root)
    log.record_files_found = [str(p) for p in record_paths]
    log.inventory_files_found = [str(p) for p in inventory_paths]

    trackers: dict[str, Tracker] = {}
    for path in inventory_paths:
        try:
            parsed = parse_inventory_file(path)
        except InventoryParseError as exc:
            log.inventory_files_skipped.append((str(path), str(exc)))
            continue
        log.inventory_files_parsed.append(str(path))
        for tracker in parsed:
            # First entry for a given identifier wins; later duplicates
            # (e.g. the same inventory file re-exported under a nested
            # PA folder) are not logged as a conflict since fmipcore
            # inventory files are not expected to disagree with themselves.
            trackers.setdefault(tracker.identifier, tracker)

    fixes_by_tracker: dict[str, list[LocationFix]] = {}
    seen_hashes: dict[str, str] = {}
    for path in record_paths:
        hint = resolve_tracker_uuid(path)
        try:
            fix = parse_record_file(path, tracker_id_hint=hint)
        except RecordParseError as exc:
            log.record_files_skipped.append((str(path), str(exc)))
            continue
        log.record_files_parsed.append(str(path))

        digest = content_hash(fix)
        if digest in seen_hashes:
            log.record_files_deduped.append((str(path), seen_hashes[digest]))
            continue
        seen_hashes[digest] = str(path)

        group_id = fix.tracker_id or UNRESOLVED_TRACKER_ID
        fixes_by_tracker.setdefault(group_id, []).append(fix)

    for tracker_id, fixes in fixes_by_tracker.items():
        fixes.sort(key=lambda f: f.sort_key())
        if tracker_id not in trackers:
            trackers[tracker_id] = Tracker(identifier=tracker_id, source_kind="unknown")

    return DiscoveryResult(trackers=trackers, fixes_by_tracker=fixes_by_tracker, log=log)
