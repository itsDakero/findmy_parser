"""Normalise Apple timestamps to ISO 8601 UTC.

Apple mixes at least four timestamp representations across Find My
artifacts:

- A native bplist "date" value, which ``plistlib`` already decodes into a
  timezone-naive ``datetime.datetime``. CFDate/bplist dates are always
  stored relative to UTC, so a naive value here is treated as UTC as-is.
- A raw Cocoa-epoch number: seconds (or milliseconds) since 2001-01-01
  00:00:00 UTC. Seen in JSON fields, since JSON has no native date type.
- A raw Unix-epoch number: seconds (or milliseconds) since 1970-01-01
  00:00:00 UTC.

There is no type tag that says which of these a bare number is, so the
format is inferred from its magnitude. Only ``.record``/fmipcore data is
in scope here (plausible dates roughly 2001-2099), which keeps the
seconds-vs-milliseconds and Cocoa-vs-Unix magnitude bands well separated
(see ``_SECONDS_MS_BOUNDARY`` below).
"""

from __future__ import annotations

import datetime
from typing import Any, NamedTuple, Optional

COCOA_EPOCH = datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc)
UNIX_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)

COCOA_EPOCH_UNIX_OFFSET_SECONDS = 978_307_200
"""Seconds between 1970-01-01 (Unix epoch) and 2001-01-01 (Cocoa epoch)."""

_SECONDS_MS_BOUNDARY = 1e11
"""Split point between second-scale and millisecond-scale numbers.

The largest plausible second-scale timestamp for this artifact type
(Unix seconds through year ~2100) is ~4.1e9. The smallest plausible
millisecond-scale timestamp (Unix milliseconds since year ~2000) is
~9.5e11. 1e11 sits in the wide gap between them.
"""


class NormalizedTimestamp(NamedTuple):
    """Result of normalising one raw timestamp value."""

    iso_utc: Optional[str]
    detected_format: Optional[str]
    raw: Any


def normalize_timestamp(value: Any) -> NormalizedTimestamp:
    """Convert a raw timestamp value to ISO 8601 UTC.

    Accepts a ``datetime.datetime`` (as produced by ``plistlib`` for
    native bplist date values), an ``int``/``float`` epoch number in
    Cocoa or Unix seconds/milliseconds (auto-detected by magnitude), or
    ``None``/anything else unrecognised (passed through as unconverted).

    The raw input is always preserved in the returned tuple so forensic
    output never loses the original value.
    """
    if value is None:
        return NormalizedTimestamp(None, None, value)

    if isinstance(value, datetime.datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=datetime.timezone.utc)
        return NormalizedTimestamp(_to_iso(dt), "bplist_date_utc", value)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        dt, fmt = _normalize_numeric(float(value))
        return NormalizedTimestamp(_to_iso(dt), fmt, value)

    return NormalizedTimestamp(None, None, value)


def _normalize_numeric(value: float) -> tuple[datetime.datetime, str]:
    is_milliseconds = abs(value) >= _SECONDS_MS_BOUNDARY
    seconds = value / 1000.0 if is_milliseconds else value
    is_cocoa = seconds < COCOA_EPOCH_UNIX_OFFSET_SECONDS

    epoch = COCOA_EPOCH if is_cocoa else UNIX_EPOCH
    dt = epoch + datetime.timedelta(seconds=seconds)

    fmt = "cocoa" if is_cocoa else "unix"
    fmt += "_milliseconds" if is_milliseconds else "_seconds"
    return dt, fmt


def _to_iso(dt: datetime.datetime) -> str:
    return dt.astimezone(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
