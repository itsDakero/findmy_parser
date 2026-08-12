# findmy_parser

Parses Apple Find My cache artifacts from an iOS filesystem extraction.

## What it reads

- `Items.data` — AirTag/tracker metadata (name, emoji, serial, last known location)
- `Devices.data` — paired Apple devices on the same iCloud account
- `.record` files — raw location pings (lat/long/timestamp) from `~/OwnedBeacons/`

## Use case

Built for parsing your own device's Find My data from a full filesystem
extraction — no iCloud or live AirTag access required.

## Status

Early stage. Format support varies by iOS version (JSON vs binary plist).
