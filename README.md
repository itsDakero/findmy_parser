# findmy_parser

A forensic parser for Apple Find My artifacts from an iOS full filesystem
extraction: the fmipcore device/tracker inventory, and searchpartyd's
beacon location history. Built for parsing your own device's Find My
data — no iCloud or live AirTag access required. Read-only: never writes
to or modifies the input path.

## What it reads

**fmipcore cache** (device/tracker inventory + last known location)

```
/private/var/mobile/Library/Caches/com.apple.findmy.fmipcore/
  Items.data      <- AirTags and third-party Find My accessories
  Devices.data    <- Apple devices on the same iCloud account
  ItemGroups.data, SafeLocations.data, FamilyMembers.data, Owner.data
```

**searchpartyd beacon location history** (the primary value of this tool)

```
.../com.apple.icloud.searchpartyd/BeaconEstimatedLocation/<UUID>/*.record
```

Each `.record` file is one location fix (usually a binary plist); the
`.record` files under one UUID form that tracker's full location history.

**searchpartyd beacon metadata** (where friendly names usually come from)

```
.../com.apple.icloud.searchpartyd/
  OwnedBeacons/<UUID>.record         <- beacons owned by this account
  SharedBeacons/<UUID>.record        <- beacons shared with this account
  BeaconNamingRecord/<UUID>/*.record <- friendly naming info
```

These are named `*.record` too, so the folder — not the filename —
distinguishes them from location fixes; parsing them as fixes would emit
coordinate-less junk rows. They're keyed by the same beacon UUID as
`BeaconEstimatedLocation`, which makes them a more reliable name source
than fmipcore, whose `identifier` may not be the same UUID at all.

A tracker's details are resolved in precedence order: fmipcore
`Items.data`/`Devices.data` first (richest), then `BeaconNamingRecord`,
then `OwnedBeacons`/`SharedBeacons`. The run log records which source
supplied each name.

`OwnedBeacons`/`SharedBeacons` carry no name field at all (confirmed
against a real export), but they do carry `pairingDate` and
`batteryLevel`, which are reported as `tracker_pairing_date_utc`,
`tracker_pairing_date_raw` and `tracker_battery_level`. Pairing date
bounds when a tracker entered the account, independently of any location
fix. Their remaining fields (`stableIdentifier`, `groupIdentifier`,
`productId`, `vendorId`, `systemVersion`, `isZeus`, and the key material)
are preserved on `Tracker.raw` and shown in the HTML report's
collapsible field dump. Trackers with no name from any source still appear in
full — no location data is ever dropped for lack of a label.

## Physical Analyzer exports

Records are encrypted on-device; decrypted copies typically come from a
Cellebrite Physical Analyzer export, which wraps files in extra,
unpredictable subfolders below the UUID folder. This tool never assumes
a fixed directory depth: it recursively scans the whole input path and
identifies each record's owning tracker by walking up its path until it
finds a UUID-shaped folder name, rather than trusting `record.parent`.
The same record re-exported into more than one nested folder is
deduplicated by content hash.

## Install

```sh
pip install -e .
```

## Usage

```sh
findmy-parser /path/to/extraction_or_export
```

Writes `findmy_report.html`, `findmy_locations.csv`,
`findmy_locations.json`, and a `run.log` into `./findmy_parser_output/`
by default. Options:

```
findmy-parser ROOT [--output-dir DIR] [--csv PATH] [--json PATH]
              [--html PATH] [--kml PATH] [--no-csv] [--no-json] [--no-html]
              [--log-file PATH] [-v]
```

- `ROOT` — an extraction root, a Physical Analyzer export folder, or a
  single file.
- `--kml PATH` — optional KML export for mapping, one track per tracker.
- `-v` — verbose (debug) logging.

### HTML report

The default `findmy_report.html` is the readable view: one card per
tracker, headed by that device's details (name, model, serial, and the
beacon UUID spelled out for verification) with its chronological location
history in a table beneath, plus a collapsible dump of every other field
found in its inventory entry. Ends with the full run log, including any
trackers that couldn't be named and the identifiers that *were* found in
the inventory files — so an ID mismatch is diagnosable from the report
itself. Self-contained single file, no external requests, light and dark.

### Diagnosing empty tracker names

First, run the structural diagnostic — it reports what the input actually
is and works out whether a name join is even possible:

```sh
python3 -m findmy_parser.diagnose /path/to/extraction_or_export
```

It prints, per file, the detected format, top-level type, key names, and
whether the file is still in the on-device encrypted form
(`encryptedData` + `signature` — decrypt via PA first). It ends with a
verdict on whether the beacon UUIDs and the inventory identifiers
overlap at all. Deliberately prints key names, types and counts but never
field values or whole identifiers, so the output is safe to share; pass
`--show-ids` to see truncated identifiers yourself.

`run.log` (and the HTML report's run log) covers the same ground after a
real run:

- `inventory files found: 0` — the inventory files aren't being located.
  Check they're under the scanned root; PA often names them
  `Items.data.decrypted` rather than `Items.data`, which is handled.
- `tracker name sources` — lists which file supplied each name.
- `trackers with a location fix PREDATING their recorded pairingDate` —
  flagged automatically, and also marked on the tracker's card in the HTML
  report. The tool records the discrepancy without interpreting it: it can
  indicate a previous pairing to another account, a `pairingDate` reset by
  re-pairing, clock skew, or that `pairingDate` does not mean what it
  appears to.
- `trackers with location fixes but NO name from any source`, followed by
  `identifiers present in inventory files` — if those two lists contain
  different UUIDs, the inventory simply doesn't use the same identifier as
  the beacon records, and names must come from `BeaconNamingRecord`
  instead. Note that `Items.data` keys on `identifier` while
  `Devices.data` keys the beacon UUID as `baUUID`; both are collected.

## Timestamps

Apple mixes native bplist date values, raw Cocoa-epoch numbers
(seconds/ms since 2001-01-01 UTC), and raw Unix-epoch numbers
(seconds/ms since 1970-01-01 UTC). This tool auto-detects the format by
magnitude and normalises everything to ISO 8601 UTC, while preserving
the original raw value alongside it in the output.

## Status / confirmed schema

`.record` fields confirmed against real fixture data (`tests/fixtures/`):
`associatedBeacon`, `identifier`, `latitude`, `longitude`,
`horizontalAccuracy`, `timestamp`, `scanDate`, `locationSource`,
`cloudKitMetadata`. `confidence` and `status` are mentioned as plausible
fields elsewhere but are not confirmed — preserved verbatim if present,
never assumed.

`Items.data` fields confirmed against a real 7-entry sample: `identifier`,
`name`, `serialNumber`, `location`, and critically `productType` — which
is **not** a flat model-name string, it's nested:
`productType.productInformation.modelName`. Also present but not yet
mapped to a `Tracker` field: `address`, `batteryStatus`, `capabilities`,
`crowdSourcedLocation`, `groupIdentifier`, `productIdentifier`,
`isAppleAudioAccessory`, `isAppleItem`, `isFirmwareUpdateMandatory`,
`lostModeMetadata`, `owner`, `partInfo`, `role`, `systemVersion`,
`safeLocations`, `rangeDistanceInMeters` (all preserved on `Tracker.raw`).
`emoji` was not among that sample's keys. `Devices.data`'s exact schema
is still unconfirmed — its field mapping keeps a flat-key fallback
(`model`/`deviceModel`/`modelDisplayName`) as a guess; see
`findmy_parser/fmipcore.py` for the exact key lists used.

`Items.data`/`Devices.data` are also commonly **NSKeyedArchiver**-wrapped
bplists rather than a plain plist/JSON structure (confirmed against real
device data) — `plistlib` alone parses the raw `$objects`/`$top` table but
doesn't dereference it. This is detected automatically and decoded with
the vendored `ccl_bplist` (see below) before the field-name matching
above runs.

## Third-party code

`findmy_parser/_vendor/ccl_bplist.py` is [ccl_bplist](https://github.com/cclgroupltd/ccl-bplist)
by Alex Caithness / CCL Forensics, BSD 3-Clause licensed (full text in the
file itself). It isn't published on PyPI, so it's vendored unmodified
rather than declared as a pip dependency — this keeps the tool
dependency-free and installable offline. See
`findmy_parser/_vendor/NOTICE.md` for details.

## Development

```sh
pip install -e ".[dev]"
pytest
```

`tests/fixtures/synthetic/` and `tests/fixtures/pa_export/` are generated
(not committed - rebuilt
automatically by `tests/conftest.py` before the test session runs, from
`tests/fixtures/generate_synthetic.py`) and covers nested PA-export-style
folders, format edge cases, and dedup cases. `pa_export/` replicates the
layout confirmed in a real Cellebrite Physical Analyzer export, where each
record appears twice (the signed/encrypted on-device file whose top level
is a 3-element list, and PA's decrypted copy under
`<uuid>_1.record/<uuid>.record.plist`) and the inventory arrives as
`<Name>_1.data/<Name>.data.decrypted` as a binary plist.

## Part 2: iLEAPP module

`scripts/artifacts/findMyBeaconLocations.py` is a standalone iLEAPP
artifact module (for contribution upstream to
[abrignoni/iLEAPP](https://github.com/abrignoni/iLEAPP)) that adds
`BeaconEstimatedLocation/*.record` support — iLEAPP's own `findMy.py`
module currently only parses `FMIPAccounts.plist` and does not cover
this data. See the module's `__artifacts_v2__` docstring for details.

## License

MIT
