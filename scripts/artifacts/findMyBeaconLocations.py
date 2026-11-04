__artifacts_v2__ = {
    "findMyBeaconLocations": {
        "name": "Find My Beacon Estimated Locations",
        "description": "Estimated location records for Find My beacons, from the searchpartyd "
                       "BeaconEstimatedLocation cache. One row per .record file; the records "
                       "under one UUID folder form that beacon's location history",
        "author": "@itsDakero, Claude",
        "creation_date": "2026-11-03",
        "last_update_date": "2026-11-03",
        "requirements": "none",
        "category": "Find My",
        "notes": "Complements rather than duplicates the fmipcore artifacts: findMyItems.py and "
                 "findMyCaches.py read Items.data and Devices.data, whose location and "
                 "crowdSourcedLocation dictionaries hold one current position per tracker. This "
                 "artifact reads a different cache, com.apple.icloud.searchpartyd/"
                 "BeaconEstimatedLocation, which holds many timestamped fixes per beacon. No "
                 "existing module reads it. "
                 "Device UUID is taken from the record's own associatedBeacon, or identifier, and "
                 "where neither is present from the nearest UUID-shaped folder in the file's path. "
                 "That folder is not assumed to be the immediate parent: a Cellebrite Physical "
                 "Analyzer export observed on one device wrapped each record a further level down "
                 "and renamed it, as BeaconEstimatedLocation/<uuid>/<uuid>_1.record/"
                 "<uuid>.record.plist. The path below therefore ends *.record* rather than "
                 "*.record, so that a .record.plist or .record.decrypted file is matched too, and "
                 "a single * is enough for the depth because search_files.py matches with fnmatch, "
                 "where * spans / characters. "
                 "The folder name is matched by shape (8-4-4-4-12) rather than as valid hex, "
                 "because the one sample record available carried a redacted group. "
                 "On one examined device (7 beacons, around 100 records) every beacon's "
                 "earliest fix fell after the pairingDate in its OwnedBeacons record, and "
                 "one beacon had an OwnedBeacons record carrying no pairingDate at all; "
                 "what pairingDate marks is not otherwise established. "
                 "Timestamp and Scan Date were native plist date values in that sample and are "
                 "read with convert_plist_date_to_utc; a numeric value is read instead as Cocoa "
                 "seconds below 978307200 and Unix seconds at or above it, which no sample "
                 "confirmed. What each of the two times marks is not established. "
                 "Only associatedBeacon, identifier, latitude, longitude, horizontalAccuracy, "
                 "locationSource, timestamp and scanDate were present in that sample; "
                 "locationSource is reported as stored and no public source defining its values "
                 "was found. Fields named in other write-ups but absent from the sample "
                 "(confidence, status) are not read. "
                 "OwnedBeacons, SharedBeacons and BeaconNamingRecord are sibling folders whose "
                 "files are also named *.record but describe the beacon rather than a position; "
                 "the path below does not match them, so they are not read here and cannot appear "
                 "as positionless rows. Those folders are where a beacon's friendly name is "
                 "expected to live, keyed by the same UUID, but their field names are not "
                 "established and no name is joined here. "
                 "On-device these caches are encrypted: records whose top level holds an "
                 "encryptedData and a signature key are logged and skipped, as findMyCaches.py "
                 "does for the fmipcore files, so 0 rows is not evidence that nothing was "
                 "recorded. "
                 "sample_data is empty because this module has not been run against the test "
                 "image corpus; the one record it was developed against was a single file "
                 "supplied separately, not a corpus image.",
        "paths": ('*/Caches/com.apple.icloud.searchpartyd/BeaconEstimatedLocation/*.record*',),
        "output_types": ["html", "tsv", "timeline", "kml", "lava"],
        "artifact_icon": "map-pin",
        "sample_data": {},
    }
}

import re

from scripts.ilapfuncs import (artifact_processor, convert_cocoa_core_data_ts_to_utc,
                               convert_plist_date_to_utc, convert_unix_ts_to_utc,
                               get_plist_file_content, logfunc)


# A UUID-shaped path component, matched by shape rather than as valid hex:
# see the note on redacted groups in __artifacts_v2__.
UUID_SHAPE = re.compile(r'^[0-9A-Za-z]{8}-[0-9A-Za-z]{4}-[0-9A-Za-z]{4}-'
                        r'[0-9A-Za-z]{4}-[0-9A-Za-z]{12}$')

# Seconds between the Unix epoch and the Cocoa epoch (2001-01-01). A
# second-scale value below this is read as Cocoa, at or above it as Unix.
COCOA_EPOCH_OFFSET = 978307200

# Values at or above this are read as milliseconds: well above the largest
# plausible second-scale value and well below the smallest millisecond one.
MS_BOUNDARY = 1e11


def _beacon_uuid(file_found):
    """The owning beacon UUID: the nearest UUID-shaped folder above the file.

    Physical Analyzer wrapping can put extra folders between the record and
    its UUID folder, so the immediate parent is not assumed to be it.
    """
    parts = file_found.replace('\\', '/').split('/')
    for part in reversed(parts[:-1]):
        if UUID_SHAPE.match(part):
            return part
    return ''


def _ts(value):
    """A record time to UTC. Blank where absent."""
    if value is None or isinstance(value, bool):
        return ''
    if isinstance(value, (int, float)):
        seconds = value / 1000.0 if abs(value) >= MS_BOUNDARY else value
        if seconds < COCOA_EPOCH_OFFSET:
            return convert_cocoa_core_data_ts_to_utc(seconds)
        return convert_unix_ts_to_utc(seconds)
    return convert_plist_date_to_utc(value)


def _is_encrypted(record):
    """True where the record is still the on-device encrypted form."""
    return 'encryptedData' in record and 'signature' in record


@artifact_processor
def findMyBeaconLocations(context):
    data_headers = (('Timestamp', 'datetime'), 'Device UUID', 'Latitude', 'Longitude',
                    'Horizontal Accuracy', 'locationSource (as stored)',
                    ('Scan Date', 'datetime'), 'Record Identifier', 'Source File')
    data_list = []
    sources = []

    for file_found in context.get_files_found():
        file_found = str(file_found)
        if '.record' not in file_found.lower():
            continue

        record = get_plist_file_content(file_found)
        if not isinstance(record, dict) or not record:
            logfunc(f'{file_found} could not be read as a plist; skipped')
            continue
        if _is_encrypted(record):
            logfunc(f'{file_found} holds encryptedData and a signature; not read')
            continue

        uuid = record.get('associatedBeacon') or record.get('identifier') or _beacon_uuid(file_found)
        relative = context.get_relative_path(file_found)
        sources.append(relative)

        data_list.append((
            _ts(record.get('timestamp')),
            uuid,
            record.get('latitude', ''),
            record.get('longitude', ''),
            record.get('horizontalAccuracy', ''),
            record.get('locationSource', ''),
            _ts(record.get('scanDate')),
            record.get('identifier', ''),
            relative))

    return data_headers, data_list, '\n'.join(sources)
