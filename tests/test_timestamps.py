import datetime

from findmy_parser.timestamps import normalize_timestamp


def test_none_passthrough():
    result = normalize_timestamp(None)
    assert result.iso_utc is None
    assert result.detected_format is None
    assert result.raw is None


def test_naive_datetime_treated_as_utc():
    dt = datetime.datetime(2026, 7, 28, 15, 43, 12)
    result = normalize_timestamp(dt)
    assert result.iso_utc == "2026-07-28T15:43:12Z"
    assert result.detected_format == "bplist_date_utc"
    assert result.raw is dt


def test_aware_datetime_converted_to_utc():
    tz = datetime.timezone(datetime.timedelta(hours=-5))
    dt = datetime.datetime(2026, 7, 28, 10, 43, 12, tzinfo=tz)
    result = normalize_timestamp(dt)
    assert result.iso_utc == "2026-07-28T15:43:12Z"


def test_unix_seconds_detected():
    # 2026-01-01T00:00:00Z
    result = normalize_timestamp(1767225600)
    assert result.detected_format == "unix_seconds"
    assert result.iso_utc == "2026-01-01T00:00:00Z"


def test_unix_milliseconds_detected():
    result = normalize_timestamp(1767225600000)
    assert result.detected_format == "unix_milliseconds"
    assert result.iso_utc == "2026-01-01T00:00:00Z"


def test_cocoa_seconds_detected():
    # 800000000 Cocoa seconds after 2001-01-01 -> 2026-05-08T20:53:20Z
    result = normalize_timestamp(800000000.0)
    assert result.detected_format == "cocoa_seconds"
    expected = datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(
        seconds=800000000.0
    )
    assert result.iso_utc == expected.isoformat().replace("+00:00", "Z")


def test_cocoa_milliseconds_detected():
    result = normalize_timestamp(800000000000.0)
    assert result.detected_format == "cocoa_milliseconds"
    expected = datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc) + datetime.timedelta(
        milliseconds=800000000000.0
    )
    assert result.iso_utc == expected.isoformat().replace("+00:00", "Z")


def test_raw_value_always_preserved():
    result = normalize_timestamp(1767225600)
    assert result.raw == 1767225600


def test_unrecognised_type_passthrough():
    result = normalize_timestamp("not a timestamp")
    assert result.iso_utc is None
    assert result.detected_format is None
    assert result.raw == "not a timestamp"


def test_bool_is_not_treated_as_number():
    # bool is a subclass of int in Python; make sure it's excluded so a
    # stray True/False in parsed data doesn't get treated as epoch 1/0.
    result = normalize_timestamp(True)
    assert result.iso_utc is None
    assert result.detected_format is None
