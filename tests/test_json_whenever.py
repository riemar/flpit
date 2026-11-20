"""whenever types are registered automatically when whenever is installed.

Every test runs once per available backend (msgspec, native).
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

w = pytest.importorskip("whenever")

from flpit.json import JsonConvert, JsonDeserializationError, register_type, unregister_type  # noqa: E402

pytestmark = pytest.mark.usefixtures("json_backend")


@dataclass
class Meeting:
    start: w.ZonedDateTime
    length: w.TimeDelta
    repeat: w.ItemizedDateDelta
    day: w.Date
    at: w.Time | None = None


@dataclass
class Moment:
    instant: w.Instant
    local: w.PlainDateTime
    offset: w.OffsetDateTime
    period: w.ItemizedDelta


def test_round_trip_with_lenient_iso_input() -> None:
    raw = ('{"start":"2025-06-15T12:30+02:00[Europe/Berlin]","length":"PT90M",'
           '"repeat":"P1W","day":"20250615","at":"12:30"}')
    meeting = JsonConvert.deserialize(raw, Meeting)
    assert meeting.day == w.Date(2025, 6, 15)
    assert meeting.at == w.Time(12, 30)
    assert meeting.repeat == w.ItemizedDateDelta(weeks=1)

    out = JsonConvert.serialize(meeting, Meeting)
    assert out == ('{"start":"2025-06-15T12:30:00+02:00[Europe/Berlin]","length":"PT1H30M",'
                   '"repeat":"P1W","day":"2025-06-15","at":"12:30:00"}')
    assert JsonConvert.deserialize(out, Meeting) == meeting


def test_more_types_round_trip() -> None:
    raw = ('{"instant":"2025-06-15T10:30:45.123456789Z","local":"2025-06-15T12:30",'
           '"offset":"2025-06-15T12:30:45+05:30","period":"P1Y2M3DT4H"}')
    value = JsonConvert.deserialize(raw, Moment)
    assert value.period == w.ItemizedDelta(years=1, months=2, days=3, hours=4)
    assert JsonConvert.deserialize(JsonConvert.serialize(value, Moment), Moment) == value


@pytest.mark.parametrize("field, bad", [
    ("repeat", '"nonsense"'),
    ("repeat", "7"),
    ("day", '"2025-13-01"'),
    ("start", '"2025-06-15T12:30:45+05:00[Europe/Berlin]"'),  # offset contradicts the zone
])
def test_invalid_values_raise(field: str, bad: str) -> None:
    values = {"start": '"2025-06-15T12:30+02:00[Europe/Berlin]"', "length": '"PT1H"',
              "repeat": '"P1W"', "day": '"2025-06-15"'}
    values[field] = bad
    raw = "{" + ",".join(f'"{k}":{v}' for k, v in values.items()) + "}"
    with pytest.raises(JsonDeserializationError):
        JsonConvert.deserialize(raw, Meeting)


def test_user_registration_overrides_the_default() -> None:
    @dataclass
    class Box:
        day: w.Date

    register_type(w.Date, decode=lambda v: w.Date(2000, 1, 1), encode=lambda d: "fixed")
    try:
        assert JsonConvert.deserialize('{"day":"2025-06-15"}', Box).day == w.Date(2000, 1, 1)
        assert JsonConvert.serialize(Box(w.Date(2025, 6, 15)), Box) == '{"day":"fixed"}'
    finally:
        register_type(w.Date, decode=w.Date.parse_iso, encode=w.Date.format_iso)
