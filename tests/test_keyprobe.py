"""tools/searchpartyd_keyprobe.py: the parts that need only the standard library.

Trial decryption needs a crypto library, which findmy_parser does not depend
on, so it is exercised only where one is installed and working.
"""
from __future__ import annotations

import importlib.util
import plistlib
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "searchpartyd_keyprobe", Path(__file__).parent.parent / "tools" / "searchpartyd_keyprobe.py"
)
kp = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(kp)

UUID = "4F2A9C10-7B3E-4A12-9D80-1C5E6B9A4D33"


def _bp(obj) -> bytes:
    return plistlib.dumps(obj, fmt=plistlib.FMT_BINARY)


def test_finds_encrypted_records_and_their_pa_copies(tmp_path):
    folder = tmp_path / "BeaconEstimatedLocation" / UUID
    (folder / "R_1.record").mkdir(parents=True)
    (folder / "R.record").write_bytes(_bp([b"n" * 12, b"t" * 16, b"c" * 40]))
    (folder / "R_1.record" / "R.record.plist").write_bytes(_bp({"latitude": 1.0}))

    records = kp.find_encrypted_records(tmp_path)
    assert [p.name for p in records["BeaconEstimatedLocation"]] == ["R.record"]
    assert kp.pa_sibling(records["BeaconEstimatedLocation"][0]).name == "R.record.plist"
    assert kp.element_signature([1, b"x" * 12, True]) == "[int(1), bytes(12), bool(True)]"


def test_candidates_are_filtered_and_private_names_withheld():
    entries = [
        {"agrp": "com.example.app", "svce": "x", "v_Data": b"k" * 32},
        {"agrp": "com.apple.icloud.searchpartyd", "labl": "BeaconStore", "v_Data": b"k" * 32},
        {"agrp": "com.apple.findmy", "acct": "owner@example.invalid", "v_Data": b"x"},
    ]
    picked = kp.candidate_entries(entries)
    assert [i for i, _ in picked] == [1, 2]
    described = kp.describe_name(picked[1][1], show_ids=False)
    assert "owner@example.invalid" not in described
    assert "withheld" in described
    assert kp.mask(f"folder/{UUID}/x", show_ids=False) == "folder/4F2A9C10-…/x"


def test_shape_never_reveals_a_value():
    secret = bytes(range(32))
    assert kp.shape(secret) == "32 bytes, raw binary"
    wrapped = kp.shape(_bp({"symmetricKey": {"key": {"data": secret}}}))
    assert "symmetricKey.key.data=bytes(32)" in wrapped
    assert secret.hex() not in wrapped


def test_key_candidates_cover_raw_hex_and_wrapped_forms():
    key = bytes(range(32))
    found = dict(
        (desc, k)
        for entry in (
            {"v_Data": key},
            {"v_Data": key.hex().encode()},
            {"gena": b"0x" + key.hex().encode()},
            {"v_Data": _bp({"symmetricKey": {"key": {"data": key}}})},
        )
        for desc, k in kp.key_candidates(entry)
    )
    assert found["v_Data raw"] == key
    assert found["v_Data hex-decoded"] == key
    assert found["gena hex-decoded"] == key
    assert found["v_Data plist symmetricKey.key.data"] == key


def test_der_fields_reads_key_value_pairs():
    def tlv(tag, content):
        return bytes([tag, len(content)]) + content

    pairs = tlv(0x30, tlv(0x0C, b"agrp") + tlv(0x0C, b"com.apple.icloud.searchpartyd"))
    pairs += tlv(0x30, tlv(0x0C, b"v_Data") + tlv(0x04, b"\x01\x02"))
    assert kp.der_fields(tlv(0x31, pairs)) == {
        "agrp": "com.apple.icloud.searchpartyd",
        "v_Data": b"\x01\x02",
    }


def test_layouts_include_the_published_macos_form_and_int_first_forms():
    names = {name for name, *_ in kp.layouts([b"n" * 12, b"t" * 16, b"c" * 40])}
    assert "nonce=[0] tag=[1] ciphertext=[2]" in names
    names = {name for name, *_ in kp.layouts([1, b"n" * 12, b"c" * 40])}
    assert "nonce=[1] ciphertext+tag=[2]" in names


def test_trial_decryption_when_a_crypto_library_works():
    crypto = kp.Crypto()
    if not crypto.available:
        pytest.skip("no working crypto library installed")
    import os

    key, nonce, plain = bytes(range(32)), os.urandom(12), _bp({"latitude": 1.0})
    if crypto.name == "pycryptodome":
        from Crypto.Cipher import AES  # type: ignore

        ct, tag = AES.new(key, AES.MODE_GCM, nonce=nonce).encrypt_and_digest(plain)
    else:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # type: ignore

        sealed = AESGCM(key).encrypt(nonce, plain, None)
        ct, tag = sealed[:-16], sealed[-16:]
    hits = [
        name
        for name, n, c, t in kp.layouts([nonce, tag, ct])
        if crypto.open("AES-GCM", key, n, c, t) == plain
    ]
    assert hits == ["nonce=[0] tag=[1] ciphertext=[2]"]
    assert crypto.open("AES-GCM", bytes(32), nonce, ct, tag) is None
