"""msgspec and native backends must produce the same JSON, objects and errors."""
from __future__ import annotations

import dataclasses
import enum
import io
import json as std_json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

import pytest

import flpit.json as flpit_json
from flpit import FlpList
from flpit.json import (
    JInclude,
    JProp,
    JsonDefaultHandling,
    JsonDeserializationError,
    JsonNamingPolicy,
    JsonSerializationError,
    JsonSerializerOptions,
    JsonUnknownFieldHandling,
)
from flpit.json import _native

msgspec_backend = pytest.importorskip("flpit.json._msgspec", reason="msgspec not installed").Backend
native_backend = _native.Backend
BACKENDS = [msgspec_backend, native_backend]


class Shade(enum.Enum):
    LIGHT = "light"
    DARK = "dark"


class Level(enum.IntEnum):
    LOW = 1
    HIGH = 2


@dataclass
class Leaf:
    label: str
    weight: float = 1.0


@dataclass
class Everything:
    an_int: int
    a_float: float
    a_bool: bool
    a_str: str
    raw_bytes: bytes
    anything: Any
    maybe: int | None
    either: int | str
    shade: Shade
    level: Level
    pick: Literal["a", "b"]
    when: datetime
    day: date
    at: time
    span: timedelta
    money: Decimal
    ident: uuid.UUID
    numbers: list[int]
    pair: tuple[int, str]
    many: tuple[int, ...]
    unique: set[int]
    frozen: frozenset[str]
    by_name: dict[str, Leaf]
    by_number: dict[int, str]
    leaves: FlpList[Leaf]
    nested: list[list[Leaf]]
    renamed: JProp[str].RenamedField = "x"
    _private: JInclude[int] = 0
    optional_leaf: Leaf | None = None
    tags: list[str] = field(default_factory=list)

    @property
    def total(self) -> JInclude[float]:
        return sum(leaf.weight for leaf in self.leaves)


SAMPLE = Everything(
    an_int=-7, a_float=2.5, a_bool=True, a_str="héllo \"quoted\" \n 東京", raw_bytes=b"\x00\xffbytes",
    anything={"k": [1, None, "x", 2.5]}, maybe=None, either="text", shade=Shade.DARK, level=Level.HIGH,
    pick="b",
    when=datetime(2025, 6, 15, 12, 30, 45, 123456, tzinfo=timezone(timedelta(hours=5, minutes=30))),
    day=date(2024, 2, 29), at=time(8, 15, 30, tzinfo=timezone.utc), span=timedelta(days=1, seconds=3661, microseconds=500),
    money=Decimal("12.50"), ident=uuid.UUID(int=42), numbers=[1, 2, 3], pair=(1, "one"), many=(4, 5),
    unique={3, 1, 2}, frozen=frozenset({"z"}), by_name={"a": Leaf("a")}, by_number={1: "one", 20: "twenty"},
    leaves=FlpList([Leaf("x", 0.5), Leaf("y", 2.0)]), nested=[[Leaf("n")]], renamed="r", _private=9,
    optional_leaf=Leaf("o", 3.0), tags=[],
)

OPTIONS = [
    JsonSerializerOptions(),
    JsonSerializerOptions(naming_policy=JsonNamingPolicy.none, default_handling=JsonDefaultHandling.include),
    JsonSerializerOptions(naming_policy=JsonNamingPolicy.kebap, unknown_field_handling=JsonUnknownFieldHandling.disallow),
    JsonSerializerOptions(naming_policy=JsonNamingPolicy.pascal),
]


@pytest.mark.parametrize("jso", OPTIONS, ids=lambda o: f"{o.naming_policy}-{o.default_handling}-{o.unknown_field_handling}")
def test_serialize_parity(jso: JsonSerializerOptions) -> None:
    outputs = {b.name: b.serialize(SAMPLE, Everything, jso) for b in BACKENDS}
    assert outputs["msgspec"] == outputs["native"]


@pytest.mark.parametrize("jso", OPTIONS, ids=lambda o: f"{o.naming_policy}-{o.default_handling}-{o.unknown_field_handling}")
def test_deserialize_parity(jso: JsonSerializerOptions) -> None:
    raw = native_backend.serialize(SAMPLE, Everything, jso)
    results = [b.deserialize(raw, Everything, jso) for b in BACKENDS]
    assert results[0] == results[1] == SAMPLE
    assert type(results[1].leaves) is FlpList


def test_serialize_to_parity() -> None:
    outputs = []
    for backend in BACKENDS:
        buffer = io.BytesIO()
        backend.serialize_to([Leaf("a"), Leaf("b", 2.0)], Leaf, buffer)
        outputs.append(buffer.getvalue())
    assert outputs[0] == outputs[1]


TEMPORAL_INPUTS: dict[type, list[str]] = {
    date: ["2025-06-15", "2024-02-29", "2023-02-29", "2025-6-15", "02025-06-15", "0000-01-01",
           "2025-06-15T00:00", "20250615", "2025-W24-7"],
    time: ["12:30:45", "00:00:00", "23:59:59.9999999", "12:30:45.1234567", "12:30:45z", "12:30:45+05:30",
           "12:30:45-0700", "12:30:45+00:00", "12:30", "1:30:45", "12:30:45.Z", "24:00:00", "12:30:45+24:00",
           "12:30:45,5"],
    datetime: ["2025-06-15T12:30:45", "2025-06-15 12:30:45", "2025-06-15t12:30:45z", "2025-06-15T12:30:45.1Z",
               "2025-06-15T12:30:45.123456789Z", "2025-06-15T12:30:45-00:00", "2025-06-15T12:30:45+23:59",
               "2025-06-15T12:30:45+24:00", "2025-06-15T12:30:45+0530", "2025-06-15T12:30:45+05",
               "2025-06-15T12:30Z", "20250615T123045Z", "2025-06-15T12:30:60", "0001-01-01T00:00:00Z",
               "2025-12-31T23:59:59.9999996Z"],
    timedelta: ["PT1H", "P1DT2H", "-PT0.5S", "P1D", "PT1.5H", "P0D", "PT1M30S", "p1d", "P1DT", "PT", "P",
                "+P1D", "PT0.0000001S", "P1DT1H1M1.5S", "PT36H", "P1W", "P1Y", "1 day"],
}


@pytest.mark.parametrize("tp, text", [(tp, s) for tp, values in TEMPORAL_INPUTS.items() for s in values],
                         ids=lambda v: getattr(v, "__name__", v))
def test_temporal_parsing_parity(tp: type, text: str) -> None:
    Box = dataclasses.make_dataclass("Box", [("value", tp)])
    raw = f'{{"value":"{text}"}}'
    outcomes = []
    for backend in BACKENDS:
        try:
            outcomes.append(("ok", backend.deserialize(raw, Box).value))
        except JsonDeserializationError:
            outcomes.append(("error", None))
    assert outcomes[0] == outcomes[1]
    if outcomes[0][0] == "ok":
        value = outcomes[0][1]
        outputs = {b.name: b.serialize(Box(value), Box) for b in BACKENDS}
        assert outputs["msgspec"] == outputs["native"]


@pytest.mark.parametrize("raw", [
    '{"anInt":1.0}', '{"anInt":true}', '{"aBool":1}', '{"aStr":5}', '{"rawBytes":"not base64!"}',
    '{"shade":"pink"}', '{"level":3}', '{"pick":"c"}', '{"pair":[1]}', '{"pair":[1,2]}',
    '{"byNumber":{"x":"y"}}', '{"leaves":[{"weight":1}]}', '{"leaves":{}}', '{"money":"abc"}',
    '{"ident":"nope"}', '{"aFloat":1e400}', '{"numbers":[1,"2"]}', "[]", "null", "NaN", '{"aFloat":NaN}',
])
def test_invalid_input_parity(raw: str) -> None:
    if raw.startswith("{"):
        # override one field of a valid document (duplicate keys: the last one wins)
        valid = native_backend.serialize(SAMPLE, Everything)
        raw = valid[:-1] + "," + raw[1:]
    for backend in BACKENDS:
        with pytest.raises(JsonDeserializationError):
            backend.deserialize(raw, Everything)


@pytest.mark.parametrize("value", [
    Leaf(label=1, weight=1.0),            # type: ignore[arg-type]
    Leaf(label="x", weight="heavy"),      # type: ignore[arg-type]
])
def test_invalid_value_parity_on_serialize(value: Leaf) -> None:
    for backend in BACKENDS:
        with pytest.raises(JsonSerializationError):
            backend.serialize(value, Leaf)


INCLUDE = JsonSerializerOptions(default_handling=JsonDefaultHandling.include)


@pytest.mark.parametrize("value", [3, 0.1, -0.0, 1250.0, 123456789.123, 1.5, float("nan"), float("inf")])
def test_float_text_parity(value: float) -> None:
    outputs = {b.name: b.serialize(Leaf("x", value), Leaf, INCLUDE) for b in BACKENDS}
    assert outputs["msgspec"] == outputs["native"]


@pytest.mark.parametrize("value", [1e16, 1e-5, 1.5e-7, 5e-324, 1.7976931348623157e308, 1e22])
def test_float_value_parity(value: float) -> None:
    # Exponent spelling may differ (msgspec "1e16", stdlib "1e+16"); the value may not.
    outputs = [std_json.loads(b.serialize(Leaf("x", value), Leaf, INCLUDE))["weight"] for b in BACKENDS]
    assert outputs[0] == outputs[1] == value
    for backend in BACKENDS:
        for other in BACKENDS:
            assert backend.deserialize(other.serialize(Leaf("x", value), Leaf), Leaf).weight == value


def test_csv_parity() -> None:
    from flpit.csv import CsvLoader

    @dataclass
    class Row:
        name: str
        count: int
        ratio: float
        active: bool
        when: date
        note: str | None = None

    raw = "name,count,ratio,active,when\nAda,3,1.5,true,2025-06-15\nBob,1e3,2,FALSE,2024-02-29\n"
    results = []
    previous = flpit_json.get_backend()
    try:
        for name in ("msgspec", "native"):
            flpit_json.set_backend(name)
            results.append([(r.name, r.count, r.ratio, r.active, r.when, r.note)
                            for r in CsvLoader.load_list(raw, Row)])
    finally:
        flpit_json.set_backend(previous)
    assert results[0] == results[1]
