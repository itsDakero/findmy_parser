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
`<UUID>` is joined against the `identifier` field in `Items.data` /
`Devices.data` to attach a friendly name, emoji, serial number, and
model. Trackers with no matching inventory entry are still included,
labelled unknown — no location data is ever dropped.

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

Writes `findmy_locations.csv`, `findmy_locations.json`, and a `run.log`
into `./findmy_parser_output/` by default. Options:

```
findmy-parser ROOT [--output-dir DIR] [--csv PATH] [--json PATH]
              [--kml PATH] [--no-csv] [--no-json] [--log-file PATH] [-v]
```

- `ROOT` — an extraction root, a Physical Analyzer export folder, or a
  single file.
- `--kml PATH` — optional KML export for mapping, one track per tracker.
- `-v` — verbose (debug) logging.

## Timestamps

Apple mixes native bplist date values, raw Cocoa-epoch numbers
(seconds/ms since 2001-01-01 UTC), and raw Unix-epoch numbers
(seconds/ms since 1970-01-01 UTC). This tool auto-detects the format by
magnitude and normalises everything to ISO 8601 UTC, while preserving
the original raw value alongside it in the output.

## Status / confirmed schema

Only `.record` fields have been verified against real fixture data
(`tests/fixtures/`): `associatedBeacon`, `identifier`, `latitude`,
`longitude`, `horizontalAccuracy`, `timestamp`, `scanDate`,
`locationSource`, `cloudKitMetadata`. `confidence` and `status` are
mentioned as plausible fields elsewhere but are not confirmed — they are
preserved verbatim if present, never assumed. `Items.data`/`Devices.data`
field names are best-effort (no real fixture was available to verify
them against); see `findmy_parser/fmipcore.py` for the exact fallback
key list used.

## Development

```sh
pip install -e ".[dev]"
pytest
```

`tests/fixtures/synthetic/` is generated (not committed - it's rebuilt
automatically by `tests/conftest.py` before the test session runs, from
`tests/fixtures/generate_synthetic.py`) and covers nested PA-export-style
folders, format edge cases, and dedup cases.

## Part 2: iLEAPP module

`scripts/artifacts/findMyBeaconLocations.py` is a standalone iLEAPP
artifact module (for contribution upstream to
[abrignoni/iLEAPP](https://github.com/abrignoni/iLEAPP)) that adds
`BeaconEstimatedLocation/*.record` support — iLEAPP's own `findMy.py`
module currently only parses `FMIPAccounts.plist` and does not cover
this data. See the module's `__artifacts_v2__` docstring for details.

## License

MIT
