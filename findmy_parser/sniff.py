"""Format sniffing shared by beacons.py and fmipcore.py.

Both `.record` files and fmipcore `.data` files may be a binary plist, an
XML plist, or JSON depending on iOS version and export tooling — never
trust the file extension, sniff the magic bytes instead.
"""

from __future__ import annotations

BPLIST_MAGIC = b"bplist00"


def detect_format(data: bytes) -> str:
    """Return one of "bplist", "xml_plist", "json", or "unknown"."""
    stripped = data.lstrip()
    if stripped.startswith(BPLIST_MAGIC):
        return "bplist"
    if stripped.startswith(b"<?xml") or stripped.startswith(b"<plist"):
        return "xml_plist"
    if stripped[:1] in (b"{", b"["):
        return "json"
    return "unknown"
