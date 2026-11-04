"""Self-contained HTML report: one section per tracker, locations beneath it.

Deliberately a single file with inline CSS and no external requests - it
has to open on an offline forensic workstation and survive being copied
around as evidence.

Layout mirrors how the data is actually structured: each tracker is a card
headed by its device details (name, model, serial, and the beacon UUID
spelled out for verification), with that tracker's chronological location
history in a table below it.
"""

from __future__ import annotations

import datetime
import html
from pathlib import Path
from typing import Any, Optional

from ..discovery import DiscoveryResult
from ..models import LocationFix, Tracker

_CSS = """
:root {
  color-scheme: light dark;
  --bg: #f2f2f7;
  --card: #ffffff;
  --card-header: #fbfbfd;
  --label: #1d1d1f;
  --secondary-label: rgba(60, 60, 67, 0.6);
  --tertiary-label: rgba(60, 60, 67, 0.3);
  --separator: rgba(60, 60, 67, 0.18);
  --blue: #0071e3;
  --green: #34c759;
  --orange: #ff9500;
  --red: #ff3b30;
  --fill: rgba(120, 120, 128, 0.12);
  --shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 8px 24px rgba(0, 0, 0, 0.04);
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #000000;
    --card: #1c1c1e;
    --card-header: #242426;
    --label: #f5f5f7;
    --secondary-label: rgba(235, 235, 245, 0.6);
    --tertiary-label: rgba(235, 235, 245, 0.3);
    --separator: rgba(84, 84, 88, 0.65);
    --blue: #0a84ff;
    --green: #30d158;
    --orange: #ff9f0a;
    --red: #ff453a;
    --fill: rgba(120, 120, 128, 0.24);
    --shadow: none;
  }
}

* { box-sizing: border-box; }

body {
  margin: 0;
  padding: 0 20px 80px;
  background: var(--bg);
  color: var(--label);
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display",
    "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-size: 15px;
  line-height: 1.47059;
  -webkit-font-smoothing: antialiased;
}

.wrap { max-width: 1080px; margin: 0 auto; }

header.page {
  padding: 56px 0 32px;
  border-bottom: 1px solid var(--separator);
  margin-bottom: 32px;
}

h1 {
  font-size: 40px;
  line-height: 1.1;
  letter-spacing: -0.015em;
  font-weight: 700;
  margin: 0 0 8px;
}

.subtitle { color: var(--secondary-label); font-size: 17px; margin: 0; }

.meta {
  margin-top: 20px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 10px;
}

.meta div {
  background: var(--card);
  border-radius: 12px;
  padding: 12px 14px;
  box-shadow: var(--shadow);
}

.meta .k {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--secondary-label);
  font-weight: 600;
}

.meta .v { font-size: 22px; font-weight: 600; letter-spacing: -0.01em; margin-top: 2px; }

.tracker {
  background: var(--card);
  border-radius: 18px;
  box-shadow: var(--shadow);
  margin-bottom: 28px;
  overflow: hidden;
}

.tracker > .head {
  padding: 22px 24px;
  background: var(--card-header);
  border-bottom: 1px solid var(--separator);
}

.title-row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }

.avatar {
  width: 46px;
  height: 46px;
  border-radius: 50%;
  background: var(--fill);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  flex: none;
}

h2 {
  font-size: 24px;
  font-weight: 600;
  letter-spacing: -0.012em;
  margin: 0;
  flex: 1 1 auto;
  min-width: 0;
}

h2 .unnamed { color: var(--secondary-label); font-weight: 400; }

.pill {
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 100px;
  background: var(--fill);
  color: var(--secondary-label);
  white-space: nowrap;
}

.pill.count { background: rgba(0, 113, 227, 0.12); color: var(--blue); }
.pill.warn-pill { background: rgba(255, 149, 0, 0.14); color: var(--orange); }

.uuid {
  margin-top: 12px;
  font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  color: var(--secondary-label);
  word-break: break-all;
}

.uuid b { color: var(--label); font-weight: 600; }

dl.details {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 14px 24px;
  margin: 18px 0 0;
}

dl.details > div { min-width: 0; }

dt {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--secondary-label);
  font-weight: 600;
  margin-bottom: 2px;
}

dd { margin: 0; font-size: 15px; word-break: break-word; }
dd.none { color: var(--tertiary-label); }

.table-scroll { overflow-x: auto; -webkit-overflow-scrolling: touch; }

table { border-collapse: collapse; width: 100%; font-size: 14px; }

th {
  text-align: left;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--secondary-label);
  font-weight: 600;
  padding: 12px 16px;
  border-bottom: 1px solid var(--separator);
  white-space: nowrap;
  position: sticky;
  top: 0;
  background: var(--card);
}

td { padding: 11px 16px; border-bottom: 1px solid var(--separator); vertical-align: top; }
tr:last-child td { border-bottom: none; }

td.mono, th.mono {
  font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
  white-space: nowrap;
  /* Coordinates and timestamps get compared digit-by-digit; tabular
     figures keep them in columns so a transposition is visible. */
  font-variant-numeric: tabular-nums;
}

td.src {
  font-size: 11px;
  color: var(--secondary-label);
  max-width: 320px;
  word-break: break-all;
  white-space: normal;
}

.empty { padding: 22px 24px; color: var(--secondary-label); font-style: italic; }

details.raw { border-top: 1px solid var(--separator); }

details.raw summary {
  padding: 13px 24px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 500;
  color: var(--blue);
  list-style: none;
  user-select: none;
}

details.raw summary::-webkit-details-marker { display: none; }
details.raw summary::before { content: "▸ "; display: inline-block; transition: transform 0.15s; }
details.raw[open] summary::before { transform: rotate(90deg); }

details.raw pre {
  margin: 0;
  padding: 0 24px 20px;
  font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  color: var(--secondary-label);
  white-space: pre-wrap;
  word-break: break-word;
}

section.run-log { margin-top: 44px; }

section.run-log h2 { font-size: 22px; margin-bottom: 14px; }

.log-card {
  background: var(--card);
  border-radius: 18px;
  box-shadow: var(--shadow);
  padding: 20px 24px;
}

.log-card h3 {
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--secondary-label);
  margin: 20px 0 8px;
}

.log-card h3:first-child { margin-top: 0; }

.log-card ul { margin: 0; padding-left: 20px; }

.log-card li {
  font-family: ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  color: var(--secondary-label);
  word-break: break-all;
  margin-bottom: 4px;
}

.warn { color: var(--orange); }

footer.page {
  margin-top: 40px;
  padding-top: 20px;
  border-top: 1px solid var(--separator);
  font-size: 12px;
  color: var(--tertiary-label);
}

@media print {
  body { background: #fff; padding: 0; }
  .tracker, .log-card, .meta div { box-shadow: none; border: 1px solid #ddd; }
  details.raw { display: none; }
}
"""


def write_html(result: DiscoveryResult, path: Path, *, source_root: Optional[str] = None) -> None:
    total_fixes = sum(len(v) for v in result.fixes_by_tracker.values())
    generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Find My Report</title>",
        f"<style>{_CSS}</style>",
        "</head><body><div class='wrap'>",
        "<header class='page'>",
        "<h1>Find My Report</h1>",
        "<p class='subtitle'>Beacon location history correlated to tracker inventory</p>",
        "<div class='meta'>",
        _meta_card("Trackers", str(len(result.fixes_by_tracker))),
        _meta_card("Location fixes", str(total_fixes)),
        _meta_card("Files parsed", str(len(result.log.record_files_parsed))),
        _meta_card("Files skipped", str(len(result.log.record_files_skipped))),
        "</div>",
    ]
    if source_root:
        parts.append(f"<p class='uuid' style='margin-top:16px'>Source: {_esc(source_root)}</p>")
    parts.append(f"<p class='uuid'>Generated: {_esc(generated)}</p>")
    parts.append("</header>")

    if not result.fixes_by_tracker:
        parts.append("<div class='tracker'><p class='empty'>No location fixes found.</p></div>")

    for tracker_id in sorted(result.fixes_by_tracker):
        tracker = result.trackers.get(tracker_id)
        fixes = result.fixes_by_tracker[tracker_id]
        parts.append(_tracker_section(tracker_id, tracker, fixes, result))

    parts.append(_run_log_section(result))
    parts.append(
        "<footer class='page'>Generated by findmy_parser &middot; "
        "read-only analysis, input never modified.</footer>"
    )
    parts.append("</div></body></html>")

    path.write_text("\n".join(parts), encoding="utf-8")


def _meta_card(key: str, value: str) -> str:
    return f"<div><div class='k'>{_esc(key)}</div><div class='v'>{_esc(value)}</div></div>"


def _tracker_section(
    tracker_id: str, tracker: Optional[Tracker], fixes: list[LocationFix], result: DiscoveryResult
) -> str:
    name = (tracker.name if tracker else None) or None
    emoji = (tracker.emoji if tracker else None) or "\U0001f4cd"
    title = _esc(name) if name else "<span class='unnamed'>Unnamed tracker</span>"

    kind = tracker.source_kind if tracker else "unknown"
    name_source = result.log.name_sources.get(tracker_id)

    out = [
        "<div class='tracker'><div class='head'>",
        "<div class='title-row'>",
        f"<div class='avatar'>{_esc(emoji)}</div>",
        f"<h2>{title}</h2>",
        f"<span class='pill'>{_esc(kind)}</span>",
        f"<span class='pill count'>{len(fixes)} fixes</span>",
        "<span class='pill warn-pill'>fix predates pairing</span>"
        if any(t == tracker_id for t, _p, _e in result.log.fixes_before_pairing)
        else "",
        "</div>",
        f"<div class='uuid'>Beacon UUID: <b>{_esc(tracker_id)}</b></div>",
        "<dl class='details'>",
        _detail("Model", tracker.model if tracker else None),
        _detail("Serial number", tracker.serial_number if tracker else None),
        _detail_paired(tracker_id, tracker, result),
        _detail("Battery level", _battery(tracker)),
        _detail("First fix", fixes[0].timestamp_utc if fixes else None),
        _detail("Last fix", fixes[-1].timestamp_utc if fixes else None),
        _detail("Name source", name_source),
        _detail("Inventory file", tracker.source_file if tracker else None),
        "</dl></div>",
    ]

    if fixes:
        out.append("<div class='table-scroll'><table><thead><tr>")
        for col, cls in (
            ("Timestamp (UTC)", "mono"),
            ("Latitude", "mono"),
            ("Longitude", "mono"),
            ("Accuracy (m)", "mono"),
            ("Scan date (UTC)", "mono"),
            ("Source file", ""),
        ):
            out.append(f"<th class='{cls}'>{_esc(col)}</th>")
        out.append("</tr></thead><tbody>")
        for fix in fixes:
            out.append(
                "<tr>"
                f"<td class='mono'>{_fmt(fix.timestamp_utc)}</td>"
                f"<td class='mono'>{_fmt(fix.latitude)}</td>"
                f"<td class='mono'>{_fmt(fix.longitude)}</td>"
                f"<td class='mono'>{_fmt(fix.horizontal_accuracy)}</td>"
                f"<td class='mono'>{_fmt(fix.scan_date_utc)}</td>"
                f"<td class='src'>{_esc(fix.source_file)}</td>"
                "</tr>"
            )
        out.append("</tbody></table></div>")
    else:
        out.append("<p class='empty'>No location fixes for this tracker.</p>")

    if tracker and tracker.raw:
        out.append(
            "<details class='raw'><summary>All parsed fields</summary>"
            f"<pre>{_esc(_format_raw(tracker.raw))}</pre></details>"
        )

    out.append("</div>")
    return "".join(out)


def _run_log_section(result: DiscoveryResult) -> str:
    log = result.log
    out = ["<section class='run-log'><h2>Run log</h2><div class='log-card'>"]

    out.append("<h3>Summary</h3><ul>")
    for label, value in (
        ("location .record files found", len(log.record_files_found)),
        ("location .record files parsed", len(log.record_files_parsed)),
        ("location .record files skipped", len(log.record_files_skipped)),
        ("duplicates dropped", len(log.record_files_deduped)),
        ("beacon metadata records parsed", len(log.metadata_files_parsed)),
        ("encrypted on-device records skipped", len(log.encrypted_records)),
        ("inventory files found", len(log.inventory_files_found)),
        ("inventory files parsed", len(log.inventory_files_parsed)),
        ("unreadable during scan", len(log.walk_errors)),
    ):
        out.append(f"<li>{_esc(label)}: {value}</li>")
    out.append("</ul>")

    if log.beacons_without_pairing_date:
        out.append(
            "<h3>Trackers with no pairing date</h3><ul>"
            + "".join(
                f"<li>{_esc(tid)} &mdash; {_esc(reason)}</li>"
                for tid, reason in log.beacons_without_pairing_date
            )
            + "</ul>"
        )
    if log.fixes_before_pairing:
        out.append(
            "<h3 class='warn'>Location fix predating the recorded pairing date</h3>"
            "<ul>"
            + "".join(
                f"<li>{_esc(tid)} &mdash; paired {_esc(pairing)}, "
                f"earliest fix {_esc(earliest)}</li>"
                for tid, pairing, earliest in log.fixes_before_pairing
            )
            + "</ul>"
            "<p style='font-size:12px;color:var(--secondary-label)'>Not interpreted here. "
            "Can indicate a previous pairing to another account, a pairingDate reset by "
            "re-pairing, clock skew, or that pairingDate does not mean what it appears "
            "to.</p>"
        )
    if log.unmatched_tracker_ids:
        out.append(
            "<h3 class='warn'>Trackers with no name from any source</h3><ul>"
            + "".join(f"<li>{_esc(t)}</li>" for t in log.unmatched_tracker_ids)
            + "</ul>"
        )
        if log.inventory_identifiers:
            out.append(
                "<h3>Identifiers present in inventory files "
                "(compare against the UUIDs above)</h3><ul>"
                + "".join(f"<li>{_esc(i)}</li>" for i in sorted(set(log.inventory_identifiers)))
                + "</ul>"
            )

    for heading, entries in (
        ("Skipped location records", log.record_files_skipped),
        ("Skipped metadata records", log.metadata_files_skipped),
        ("Skipped inventory files", log.inventory_files_skipped),
        ("Unreadable during scan", log.walk_errors),
    ):
        if entries:
            out.append(f"<h3 class='warn'>{_esc(heading)}</h3><ul>")
            out.extend(f"<li>{_esc(p)} &mdash; {_esc(reason)}</li>" for p, reason in entries)
            out.append("</ul>")

    out.append("</div></section>")
    return "".join(out)


def _detail_paired(
    tracker_id: str, tracker: Optional[Tracker], result: DiscoveryResult
) -> str:
    """Pairing date, or why there isn't one.

    A beacon with no ownership record at all and one whose record simply
    omits pairingDate mean different things; rendering both as a blank
    would hide that.
    """
    if tracker and tracker.pairing_date_utc:
        return _detail("Paired", tracker.pairing_date_utc)
    reason = next(
        (r for tid, r in result.log.beacons_without_pairing_date if tid == tracker_id), None
    )
    if reason:
        return (
            f"<div><dt>Paired</dt><dd class='none' title='{_esc(reason)}'>"
            f"not recorded &mdash; {_esc(reason.split(' (')[0])}</dd></div>"
        )
    return _detail("Paired", None)


def _battery(tracker: Optional[Tracker]) -> Optional[str]:
    """Battery as a percentage where it looks like a 0-1 fraction."""
    if tracker is None or tracker.battery_level is None:
        return None
    level = tracker.battery_level
    if 0 <= level <= 1:
        return f"{level * 100:.0f}% ({level} as stored)"
    return f"{level} (as stored)"


def _detail(label: str, value: Any) -> str:
    if value in (None, ""):
        return f"<div><dt>{_esc(label)}</dt><dd class='none'>&mdash;</dd></div>"
    return f"<div><dt>{_esc(label)}</dt><dd>{_esc(str(value))}</dd></div>"


def _fmt(value: Any) -> str:
    return "&mdash;" if value is None else _esc(str(value))


def _format_raw(raw: dict, indent: int = 0) -> str:
    """Readable key/value dump of a parsed entry, without JSON's escaping noise."""
    lines = []
    pad = "  " * indent
    for key, value in raw.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.append(_format_raw(value, indent + 1))
        elif isinstance(value, (list, tuple)):
            lines.append(f"{pad}{key}: [{len(value)} item(s)]")
            for item in value:
                if isinstance(item, dict):
                    lines.append(_format_raw(item, indent + 1))
                else:
                    lines.append(f"{pad}  {item!r}")
        elif isinstance(value, bytes):
            lines.append(f"{pad}{key}: <{len(value)} bytes>")
        else:
            lines.append(f"{pad}{key}: {value}")
    return "\n".join(lines)


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)
