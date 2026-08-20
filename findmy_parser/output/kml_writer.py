"""KML output: one folder per tracker, with a chronological track (LineString)
plus a timestamped point Placemark per fix.

Fixes missing latitude/longitude are excluded here (KML geometry needs
coordinates) but are never dropped from the CSV/JSON output.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from ..discovery import DiscoveryResult
from ..models import LocationFix, Tracker


def write_kml(result: DiscoveryResult, path: Path) -> None:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "<Document>",
    ]
    for tracker_id in sorted(result.fixes_by_tracker):
        fixes = [
            f
            for f in result.fixes_by_tracker[tracker_id]
            if f.latitude is not None and f.longitude is not None
        ]
        if not fixes:
            continue
        label = _tracker_label(result.trackers.get(tracker_id), tracker_id)
        lines.append(f"<Folder><name>{escape(label)}</name>")
        lines.append(_track_placemark(label, fixes))
        lines.extend(_point_placemark(label, fix) for fix in fixes)
        lines.append("</Folder>")
    lines.append("</Document>")
    lines.append("</kml>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _tracker_label(tracker: Tracker | None, tracker_id: str) -> str:
    if tracker and tracker.name:
        return f"{tracker.name} ({tracker_id})"
    return tracker_id


def _track_placemark(label: str, fixes: list[LocationFix]) -> str:
    coords = " ".join(f"{fix.longitude},{fix.latitude},0" for fix in fixes)
    return (
        f"<Placemark><name>{escape(label)} track</name>"
        "<LineString><tessellate>1</tessellate>"
        f"<coordinates>{coords}</coordinates></LineString>"
        "</Placemark>"
    )


def _point_placemark(label: str, fix: LocationFix) -> str:
    when = fix.timestamp_utc or ""
    time_el = f"<TimeStamp><when>{escape(when)}</when></TimeStamp>" if when else ""
    desc_parts = [
        f"Timestamp: {fix.timestamp_utc}" if fix.timestamp_utc else "",
        f"Horizontal accuracy: {fix.horizontal_accuracy}m"
        if fix.horizontal_accuracy is not None
        else "",
        f"Source: {fix.source_file}",
    ]
    description = escape(" | ".join(p for p in desc_parts if p))
    name = escape(fix.timestamp_utc or label)
    return (
        f"<Placemark><name>{name}</name>{time_el}"
        f"<description>{description}</description>"
        f"<Point><coordinates>{fix.longitude},{fix.latitude},0</coordinates></Point>"
        "</Placemark>"
    )
