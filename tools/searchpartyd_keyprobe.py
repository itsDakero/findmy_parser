"""Probe how iOS encrypts searchpartyd .record files, and which keychain key opens them.

    python tools/searchpartyd_keyprobe.py EXPORT [--keychain KEYCHAIN] [--show-ids]

EXPORT is a Physical Analyzer export or extraction holding the searchpartyd
folders. KEYCHAIN is the extraction's keychain: a decrypted dump (a plist with
a 'genp' list) or UFED's encrypted backup_keychain_v2.plist.

Three stages, each reporting shapes and verdicts but never values:

1. RECORD LAYOUT - standard library only. For encrypted on-device records it
   prints each element's type and length, and where Physical Analyzer's
   decrypted copy sits beside the record, that copy's size, so the layout can be
   read without any key.
2. KEYCHAIN CANDIDATES - lists keychain entries whose access group, service,
   account or label mentions searchparty, beacon, findmy, fmip or airtag. Prints
   their names and the shape of their value (length, raw/hex/plist), never the
   value. A UFED encrypted keychain needs a crypto library to read.
3. TRIAL DECRYPTION - tries each candidate key against sample records under
   AES-GCM and ChaCha20-Poly1305 and several element layouts. A result counts
   only when the authentication tag verifies; where a PA decrypted copy exists
   it also reports whether the plaintext matches it.

Stages 1 and 2 (for a decrypted keychain dump) need only the standard library.
Stage 3, and reading a UFED encrypted keychain, need pycryptodome or
cryptography; whichever is installed is used, and without either those stages
say so and are skipped. Neither is a dependency of findmy_parser itself.

Identifiers (UUIDs) are shown truncated unless --show-ids is passed, and an
account name containing '@' is withheld, so the output is safe to share.
Read-only: nothing under EXPORT or the keychain is written to.
"""
from __future__ import annotations

import argparse
import io
import plistlib
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from findmy_parser._vendor import ccl_bplist  # noqa: E402

SEARCHPARTYD_FOLDERS = (
    "BeaconEstimatedLocation", "OwnedBeacons", "SharedBeacons", "BeaconNamingRecord",
)
CANDIDATE_TERMS = ("searchparty", "beacon", "findmy", "fmip", "airtag")
NAME_FIELDS = ("agrp", "svce", "acct", "labl")
SAMPLES_PER_FOLDER = 3
TAG_LENGTH = 16
KEY_LENGTHS = (16, 24, 32)
UUID_RE = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")


# --------------------------------------------------------------------------
# Crypto backend: optional
# --------------------------------------------------------------------------

# A half-installed library fails in more ways than ImportError: a cryptography
# missing its _cffi_backend raises pyo3's PanicException, which derives from
# BaseException and cannot be imported ahead of time to name it. Any failure
# to import means "not available", never "crash the probe".
_IMPORT_FAILURES = BaseException


def _reraise_interrupts(exc: BaseException) -> None:
    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
        raise exc


class Crypto:
    """AES-GCM and ChaCha20-Poly1305 open, from whichever library is installed."""

    def __init__(self) -> None:
        self.name: Optional[str] = None
        self._aes: Optional[Callable[[bytes, bytes, bytes, bytes], bytes]] = None
        self._chacha: Optional[Callable[[bytes, bytes, bytes, bytes], bytes]] = None
        try:
            from Crypto.Cipher import AES, ChaCha20_Poly1305  # type: ignore

            def aes(key: bytes, nonce: bytes, ct: bytes, tag: bytes) -> bytes:
                return AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(ct, tag)

            def chacha(key: bytes, nonce: bytes, ct: bytes, tag: bytes) -> bytes:
                return ChaCha20_Poly1305.new(key=key, nonce=nonce).decrypt_and_verify(ct, tag)

            self.name, self._aes, self._chacha = "pycryptodome", aes, chacha
            return
        except _IMPORT_FAILURES as exc:  # noqa: BLE001 - see _IMPORT_FAILURES
            _reraise_interrupts(exc)
        try:
            from cryptography.hazmat.primitives.ciphers.aead import (  # type: ignore
                AESGCM, ChaCha20Poly1305)

            def aes(key: bytes, nonce: bytes, ct: bytes, tag: bytes) -> bytes:
                return AESGCM(key).decrypt(nonce, ct + tag, None)

            def chacha(key: bytes, nonce: bytes, ct: bytes, tag: bytes) -> bytes:
                return ChaCha20Poly1305(key).decrypt(nonce, ct + tag, None)

            self.name, self._aes, self._chacha = "cryptography", aes, chacha
        except _IMPORT_FAILURES as exc:  # noqa: BLE001 - see _IMPORT_FAILURES
            _reraise_interrupts(exc)

    @property
    def available(self) -> bool:
        return self.name is not None

    def open(self, cipher: str, key: bytes, nonce: bytes, ct: bytes, tag: bytes) -> Optional[bytes]:
        """Plaintext if the tag verifies, else None. Never raises."""
        fn = self._aes if cipher == "AES-GCM" else self._chacha
        if fn is None:
            return None
        if cipher == "ChaCha20-Poly1305" and (len(key) != 32 or len(nonce) != 12):
            return None
        if cipher == "AES-GCM" and (len(key) not in KEY_LENGTHS or not 8 <= len(nonce) <= 128):
            return None
        try:
            return fn(key, nonce, ct, tag)
        except Exception:  # noqa: BLE001 - any failure means "did not open"
            return None


# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------

def mask(text: str, show_ids: bool) -> str:
    if show_ids:
        return text
    return UUID_RE.sub(lambda m: m.group(0)[:8] + "-…", text)


def shape(value: Any) -> str:
    """Describe a value without revealing it."""
    if value is None:
        return "absent"
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if raw[:8] == b"bplist00":
            try:
                inner = plistlib.loads(raw)
            except Exception:  # noqa: BLE001
                return f"{len(raw)} bytes, bplist (unparseable)"
            if isinstance(inner, dict) and "$archiver" in inner:
                return f"{len(raw)} bytes, NSKeyedArchiver bplist"
            return f"{len(raw)} bytes, bplist {type(inner).__name__} {key_paths(inner)}"
        text = _as_text(raw)
        if text is not None and re.fullmatch(r"(0x)?[0-9A-Fa-f]+", text) and len(text) % 2 == 0:
            return f"{len(raw)} bytes, hex text ({len(text.removeprefix('0x')) // 2} bytes decoded)"
        if text is not None and text.isprintable():
            return f"{len(raw)} bytes, printable text"
        return f"{len(raw)} bytes, raw binary"
    if isinstance(value, str):
        return f"text, {len(value)} chars"
    return type(value).__name__


def key_paths(value: Any, prefix: str = "", depth: int = 0) -> str:
    """Dotted key paths inside a plist, with the type and length at each leaf."""
    out: list[str] = []
    if depth > 4:
        return ""
    if isinstance(value, dict):
        for k, v in value.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                out.append(key_paths(v, p, depth + 1))
            else:
                out.append(f"{p}={_leaf(v)}")
    elif isinstance(value, list):
        out.append(f"{prefix}[list of {len(value)}]")
    return "{" + ", ".join(x for x in out if x) + "}" if not prefix else ", ".join(x for x in out if x)


def _leaf(v: Any) -> str:
    if isinstance(v, (bytes, bytearray)):
        return f"bytes({len(v)})"
    return type(v).__name__


def _as_text(raw: bytes) -> Optional[str]:
    try:
        return raw.decode("ascii").strip().rstrip("\x00")
    except UnicodeDecodeError:
        return None


# --------------------------------------------------------------------------
# Stage 1: record layout
# --------------------------------------------------------------------------

def searchpartyd_folder(path: Path) -> Optional[str]:
    for part in reversed(path.parts[:-1]):
        for folder in SEARCHPARTYD_FOLDERS:
            if folder.lower() in part.lower():
                return folder
    return None


def load_plist(path: Path) -> Any:
    try:
        with open(path, "rb") as fp:
            return plistlib.load(fp)
    except Exception:  # noqa: BLE001
        return None


def pa_sibling(record: Path) -> Optional[Path]:
    """PA's decrypted copy: <stem>_1.record/<stem>.record.plist beside the record."""
    stem = record.name.split(".record")[0]
    for candidate in record.parent.glob(f"{stem}_*.record*/{stem}.record*"):
        if candidate.is_file() and candidate != record:
            return candidate
    return None


def find_encrypted_records(root: Path) -> dict[str, list[Path]]:
    found: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(root.rglob("*.record*")):
        if not path.is_file():
            continue
        folder = searchpartyd_folder(path)
        if folder is None:
            continue
        payload = load_plist(path)
        if isinstance(payload, list):
            found[folder].append(path)
    return found


def element_signature(payload: list) -> str:
    parts = []
    for item in payload:
        if isinstance(item, (bytes, bytearray)):
            tag = "bplist" if bytes(item[:8]) == b"bplist00" else "bytes"
            parts.append(f"{tag}({len(item)})")
        elif isinstance(item, bool):
            parts.append(f"bool({item})")
        elif isinstance(item, int):
            parts.append(f"int({item})")
        else:
            parts.append(type(item).__name__)
    return "[" + ", ".join(parts) + "]"


def stage_layout(records: dict[str, list[Path]], root: Path, show_ids: bool) -> None:
    print("=== 1. RECORD LAYOUT (encrypted on-device records) ===")
    if not records:
        print("  no encrypted searchpartyd records found (top level a plist array)")
        return
    for folder in SEARCHPARTYD_FOLDERS:
        paths = records.get(folder, [])
        if not paths:
            continue
        # Element types/lengths vary only with content length, so summarise by
        # the type sequence and show the first few concrete examples.
        type_shapes = Counter(
            "[" + ", ".join(type(x).__name__ for x in load_plist(p)) + "]" for p in paths
        )
        print(f"\n  {folder}: {len(paths)} encrypted records")
        for shape_, count in type_shapes.most_common():
            print(f"    element types {shape_}: {count} records")
        for path in paths[:SAMPLES_PER_FOLDER]:
            payload = load_plist(path)
            rel = mask(str(path.relative_to(root)), show_ids)
            print(f"    {rel}")
            print(f"        elements: {element_signature(payload)}")
            sibling = pa_sibling(path)
            if sibling is None:
                print("        PA decrypted copy: none found beside it")
                continue
            plain_size = sibling.stat().st_size
            sizes = [len(x) for x in payload if isinstance(x, (bytes, bytearray))]
            diffs = ", ".join(f"{s - plain_size:+d}" for s in sizes)
            print(f"        PA decrypted copy: {plain_size} bytes "
                  f"(each bytes element minus that: {diffs})")
            # A stream cipher's ciphertext is exactly the plaintext's length;
            # a difference of +16 or +28 suggests a tag, or nonce and tag,
            # carried inside the same element. Only indicative: PA may have
            # re-serialised the plist rather than writing the plaintext as is.
    print("\n  (a difference of 0 means ciphertext alone in that element; PA may "
          "re-serialise, so sizes are a hint, not proof)")


# --------------------------------------------------------------------------
# Stage 2: keychain
# --------------------------------------------------------------------------

def _der_read(data: bytes, pos: int) -> tuple[int, bytes, int]:
    """One DER TLV at pos: (tag, content, next_pos)."""
    tag = data[pos]
    pos += 1
    length = data[pos]
    pos += 1
    if length & 0x80:
        n = length & 0x7F
        length = int.from_bytes(data[pos:pos + n], "big")
        pos += n
    return tag, data[pos:pos + length], pos + length


def _der_value(tag: int, content: bytes) -> Any:
    if tag == 0x04:  # OCTET STRING
        return content
    if tag == 0x02:  # INTEGER
        return str(int.from_bytes(content, "big", signed=True))
    if tag == 0x01:  # BOOLEAN
        return str(content != b"\x00")
    return content.decode("utf-8", "replace")


def der_fields(data: bytes) -> dict[str, Any]:
    """A DER SET/SEQUENCE of (key, value) SEQUENCEs, as a dict.

    Mirrors iLEAPP's _der_fields: OCTET STRING values stay bytes, the rest
    become text.
    """
    fields: dict[str, Any] = {}
    _, body, _ = _der_read(data, 0)
    pos = 0
    while pos < len(body):
        tag, pair, pos = _der_read(body, pos)
        if tag not in (0x30, 0x31):
            continue
        ktag, kraw, kend = _der_read(pair, 0)
        vtag, vraw, _ = _der_read(pair, kend)
        fields[str(_der_value(ktag, kraw))] = _der_value(vtag, vraw)
    return fields


def _sf_open(crypto: Crypto, archived: bytes, key: bytes) -> bytes:
    """Open an NSKeyedArchiver-wrapped SFAuthenticatedCiphertext with AES-GCM."""
    plist = ccl_bplist.load(io.BytesIO(archived))
    root = ccl_bplist.deserialise_NsKeyedArchiver(plist)
    plain = crypto.open("AES-GCM", key[:32], bytes(root["SFInitializationVector"]),
                        bytes(root["SFCiphertext"]), bytes(root["SFAuthenticationCode"]))
    if plain is None:
        raise ValueError("tag did not verify")
    return plain


def load_keychain(path: Path, crypto: Crypto) -> tuple[list[dict], str]:
    """Generic-password entries, and a one-line note on how they were read."""
    parsed = load_plist(path)
    if not isinstance(parsed, dict):
        return [], "not a plist dictionary - not a supported keychain dump"
    if "genp" in parsed:
        entries = [e for e in parsed.get("genp") or [] if isinstance(e, dict)]
        return entries, f"decrypted dump: {len(entries)} generic-password entries"
    if "keychainEntries" in parsed:
        if not crypto.available:
            return [], ("UFED encrypted keychain: reading it needs pycryptodome or "
                        "cryptography, and neither is installed and working")
        class_keys = parsed.get("classKeyIdxToUnwrappedMetadataClassKey") or {}
        entries, failures = [], 0
        for wrapped in parsed.get("keychainEntries") or []:
            if not isinstance(wrapped, dict) or "rawData" in wrapped:
                continue
            try:
                meta = wrapped["metadata"]
                metadata_key = _sf_open(crypto, meta["wrappedKey"],
                                        class_keys[str(wrapped["classKeyIdx"])])
                fields = der_fields(_sf_open(crypto, meta["ciphertext"], metadata_key))
                data = wrapped["data"]
                fields.update(der_fields(_sf_open(crypto, data["ciphertext"], data["unwrappedKey"])))
                entries.append(fields)
            except Exception:  # noqa: BLE001
                failures += 1
        note = f"UFED encrypted keychain: {len(entries)} entries decrypted"
        if failures:
            note += f", {failures} could not be"
        return entries, note
    return [], "no 'genp' or 'keychainEntries' - not a supported keychain dump"


def _text(entry: dict, field: str) -> str:
    v = entry.get(field)
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).decode("utf-8", "ignore").rstrip("\x00")
    return "" if v is None else str(v)


def candidate_entries(entries: list[dict]) -> list[tuple[int, dict]]:
    out = []
    for i, e in enumerate(entries):
        names = " ".join(_text(e, f) for f in NAME_FIELDS).lower()
        if any(term in names for term in CANDIDATE_TERMS):
            out.append((i, e))
    return out


def describe_name(entry: dict, show_ids: bool) -> str:
    parts = []
    for f in NAME_FIELDS:
        v = _text(entry, f)
        if not v:
            continue
        if "@" in v and not show_ids:
            v = "<withheld: contains @>"
        parts.append(f"{f}={mask(v, show_ids)}")
    return ", ".join(parts)


def stage_keychain(path: Optional[Path], crypto: Crypto, show_ids: bool) -> list[tuple[int, dict]]:
    print("\n=== 2. KEYCHAIN CANDIDATES ===")
    if path is None:
        print("  no --keychain given; skipped")
        return []
    entries, note = load_keychain(path, crypto)
    print(f"  {note}")
    candidates = candidate_entries(entries)
    print(f"  entries mentioning {'/'.join(CANDIDATE_TERMS)}: {len(candidates)}")
    for i, e in candidates:
        print(f"\n  entry #{i}: {describe_name(e, show_ids)}")
        print(f"      v_Data: {shape(e.get('v_Data'))}")
        if e.get("gena") is not None:
            print(f"      gena:   {shape(e.get('gena'))}")
    return candidates


# --------------------------------------------------------------------------
# Stage 3: trial decryption
# --------------------------------------------------------------------------

def key_candidates(entry: dict) -> Iterator[tuple[str, bytes]]:
    """(description, key) for every plausible reading of an entry's secret."""
    for field in ("v_Data", "gena"):
        raw = entry.get(field)
        if isinstance(raw, str):
            raw = raw.encode()
        if not isinstance(raw, (bytes, bytearray)):
            continue
        raw = bytes(raw)
        if len(raw) in KEY_LENGTHS:
            yield f"{field} raw", raw
        text = _as_text(raw)
        if text:
            hexpart = text.removeprefix("0x")
            if re.fullmatch(r"[0-9A-Fa-f]+", hexpart) and len(hexpart) // 2 in KEY_LENGTHS:
                yield f"{field} hex-decoded", bytes.fromhex(hexpart)
        if raw[:8] == b"bplist00":
            try:
                inner = plistlib.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            for p, v in _byte_leaves(inner):
                if len(v) in KEY_LENGTHS:
                    yield f"{field} plist {p}", v


def _byte_leaves(value: Any, prefix: str = "") -> Iterator[tuple[str, bytes]]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _byte_leaves(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _byte_leaves(v, f"{prefix}[{i}]")
    elif isinstance(value, (bytes, bytearray)):
        yield prefix, bytes(value)


def layouts(payload: list) -> Iterator[tuple[str, bytes, bytes, bytes]]:
    """(name, nonce, ciphertext, tag) for each plausible reading of a record."""
    blobs = [(i, bytes(x)) for i, x in enumerate(payload) if isinstance(x, (bytes, bytearray))]
    # Separate nonce, tag and ciphertext elements (the published macOS layout
    # is [nonce, tag, ciphertext]); try every ordering with a 16-byte tag.
    for ni, n in blobs:
        for ti, t in blobs:
            if ti == ni or len(t) != TAG_LENGTH:
                continue
            for ci, c in blobs:
                if ci in (ni, ti):
                    continue
                yield f"nonce=[{ni}] tag=[{ti}] ciphertext=[{ci}]", n, c, t
    # A nonce element and a ciphertext element carrying its tag at one end.
    for ni, n in blobs:
        for ci, c in blobs:
            if ci == ni or len(c) <= TAG_LENGTH:
                continue
            yield f"nonce=[{ni}] ciphertext+tag=[{ci}]", n, c[:-TAG_LENGTH], c[-TAG_LENGTH:]
            yield f"nonce=[{ni}] tag+ciphertext=[{ci}]", n, c[TAG_LENGTH:], c[:TAG_LENGTH]
    # Everything in one element (as the fmipcore caches do).
    for bi, b in blobs:
        for nlen in (12, 16):
            if len(b) <= nlen + TAG_LENGTH:
                continue
            yield (f"[{bi}] = nonce({nlen})+ciphertext+tag",
                   b[:nlen], b[nlen:-TAG_LENGTH], b[-TAG_LENGTH:])
            yield (f"[{bi}] = nonce({nlen})+tag+ciphertext",
                   b[:nlen], b[nlen + TAG_LENGTH:], b[nlen:nlen + TAG_LENGTH])
    # A bytes element that is itself a plist wrapping the parts.
    for bi, b in blobs:
        if b[:8] != b"bplist00":
            continue
        try:
            inner = plistlib.loads(b)
        except Exception:  # noqa: BLE001
            continue
        values = list(inner.values()) if isinstance(inner, dict) else inner
        if isinstance(values, list):
            for name, n, c, t in layouts(values):
                yield f"inside [{bi}]: {name}", n, c, t


def stage_trial(records: dict[str, list[Path]], candidates: list[tuple[int, dict]],
                crypto: Crypto) -> None:
    print("\n=== 3. TRIAL DECRYPTION ===")
    if not crypto.available:
        print("  skipped: needs pycryptodome or cryptography (neither is installed and working)")
        return
    if not candidates:
        print("  skipped: no keychain candidates")
        return
    print(f"  crypto library: {crypto.name}")
    print("  (no additional authenticated data is tried; a format that uses AAD "
          "would not verify here)")
    keys = [(i, desc, key) for i, e in candidates for desc, key in key_candidates(e)]
    print(f"  candidate keys derived: {len(keys)}")
    if not keys:
        print("  none of the candidate entries holds a 16, 24 or 32 byte value "
              "in any reading tried")
        return

    verified: Counter = Counter()
    for folder in SEARCHPARTYD_FOLDERS:
        for path in records.get(folder, [])[:SAMPLES_PER_FOLDER]:
            payload = load_plist(path)
            sibling = pa_sibling(path)
            opened = False
            for i, desc, key in keys:
                for layout, n, c, t in layouts(payload):
                    for cipher in ("AES-GCM", "ChaCha20-Poly1305"):
                        plain = crypto.open(cipher, key, n, c, t)
                        if plain is None:
                            continue
                        opened = True
                        doc = None
                        try:
                            doc = plistlib.loads(plain)
                        except Exception:  # noqa: BLE001
                            pass
                        match = "no PA copy to compare"
                        if sibling is not None:
                            match = ("MATCHES the PA decrypted copy"
                                     if doc is not None and doc == load_plist(sibling)
                                     else "differs from the PA decrypted copy")
                        what = (f"plist {type(doc).__name__}" if doc is not None
                                else "not a plist")
                        verified[(i, desc, layout, cipher)] += 1
                        print(f"  VERIFIED {folder}: entry #{i} ({desc}), {cipher}, "
                              f"{layout} -> {what}, {match}")
            if not opened:
                print(f"  {folder}: no key and layout tried verified a sample record")

    print()
    if verified:
        print("  VERDICT: a key and layout verified - send this section back.")
    else:
        print("  VERDICT: nothing verified. The key may be elsewhere in the keychain, "
              "wrapped differently, or the records may use AAD or another cipher.")


# --------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="searchpartyd_keyprobe", description=__doc__.split("\n")[0])
    parser.add_argument("root", nargs="+", help="PA export or extraction folder")
    parser.add_argument("--keychain", nargs="+", default=None,
                        help="the extraction's keychain (decrypted dump or backup_keychain_v2.plist)")
    parser.add_argument("--show-ids", action="store_true",
                        help="print identifiers in full (keep off when sharing output)")
    args = parser.parse_args(argv)

    root = Path(" ".join(args.root))
    keychain = Path(" ".join(args.keychain)) if args.keychain else None
    if not root.exists():
        print(f"input path does not exist: {root} (quote paths containing spaces)")
        return 2
    if keychain is not None and not keychain.is_file():
        print(f"keychain file does not exist: {keychain}")
        return 2

    crypto = Crypto()
    print(f"searchpartyd key probe - crypto library: {crypto.name or 'none installed'}\n")
    records = find_encrypted_records(root)
    stage_layout(records, root, args.show_ids)
    candidates = stage_keychain(keychain, crypto, args.show_ids)
    stage_trial(records, candidates, crypto)
    return 0


if __name__ == "__main__":
    sys.exit(main())
