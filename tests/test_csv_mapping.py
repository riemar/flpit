"""CSV mapper: column mapping, conversion rules, errors, row shapes and parity with msgspec."""
from __future__ import annotations

import csv
import datetime as dt
import enum
import io
import math
import random
from dataclasses import dataclass, field, make_dataclass
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Literal

import pytest

from flpit import FlpList
from flpit.csv import CsvCol, CsvConversionError, CsvLoader, CsvOptions
from flpit.json import JIgnore, JInclude, JProp, JsonConvert, JsonNamingPolicy, register_type, unregister_type


def load(text: str, model: type, **options: Any) -> list[Any]:
    return list(CsvLoader.load_list(text, model, CsvOptions(**options) if options else None))


def csv_text(*rows: list[str]) -> str:
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    return buffer.getvalue()


class Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


class Level(enum.IntEnum):
    LOW = 1
    HIGH = 2


# ---------------------------------------------------------------------------
# Results and column mapping
# ---------------------------------------------------------------------------

@dataclass
class Person:
    name: str
    age: int


def test_returns_real_dataclass_instances() -> None:
    result = CsvLoader.load_list("name,age\nAda,36\n", Person)
    assert type(result) is FlpList
    assert type(result[0]) is Person
    assert result[0] == Person("Ada", 36)


@dataclass
class Labelled:
    display_name: Annotated[str, CsvCol("Display Label")]
    internal_id: Annotated[str, JProp("id")]
    shorthand: CsvCol[str].Short


def test_column_names_csvcol_then_jprop() -> None:
    result = load(csv_text(["Display Label", "id", "Short"], ["Ada", "u-1", "s"]), Labelled)
    assert result == [Labelled("Ada", "u-1", "s")]


def test_csvcol_does_not_rename_json() -> None:
    raw = JsonConvert.serialize(Labelled("Ada", "u-1", "s"), Labelled)
    assert raw == '{"displayName":"Ada","id":"u-1","shorthand":"s"}'


@dataclass
class WithSkipped:
    name: str
    secret: Annotated[str, JIgnore] = "kept"
    _private: int = 0
    _exposed: JInclude[int] = 0


def test_ignored_and_private_fields_are_not_read() -> None:
    text = csv_text(["name", "secret", "_private", "_exposed"], ["Ada", "from-csv", "5", "7"])
    assert load(text, WithSkipped) == [WithSkipped("Ada", "kept", 0, 7)]


def test_naming_policy_maps_headers() -> None:
    @dataclass
    class Camel:
        first_name: str
        item_count: int

    text = "firstName,itemCount\nAda,3\n"
    assert load(text, Camel, naming_policy=JsonNamingPolicy.camel) == [Camel("Ada", 3)]


def test_extra_columns_are_ignored_and_order_does_not_matter() -> None:
    assert load("age,unused,name\n36,x,Ada\n", Person) == [Person("Ada", 36)]


# ---------------------------------------------------------------------------
# Defaults, missing columns, dataclass flavours
# ---------------------------------------------------------------------------

@dataclass
class WithDefaults:
    name: str
    count: int = 1
    tags: list[str] = field(default_factory=list)
    note: str | None = None
    maybe: int | None = None


def test_missing_optional_columns_use_defaults() -> None:
    result = load("name\nAda\n", WithDefaults)
    assert result == [WithDefaults("Ada", 1, [], None, None)]
    assert result[0].tags is not load("name\nAda\n", WithDefaults)[0].tags   # factory called per row


def test_missing_required_column_raises() -> None:
    with pytest.raises(CsvConversionError, match="no column 'age'"):
        load("name\nAda\n", Person)


def test_header_only_gives_empty_list() -> None:
    assert load("name\n", Person) == []


@dataclass(frozen=True, slots=True, kw_only=True)
class FrozenSlots:
    name: str
    age: int = 0


@dataclass
class WithInitFalse:
    name: str
    computed: int = field(init=False, default=0)


def test_frozen_slots_kw_only_dataclass() -> None:
    assert load("name,age\nAda,36\n", FrozenSlots) == [FrozenSlots(name="Ada", age=36)]


def test_init_false_field_is_assigned_after_construction() -> None:
    result = load("name,computed\nAda,5\n", WithInitFalse)
    assert result[0].name == "Ada" and result[0].computed == 5


def test_post_init_runs() -> None:
    @dataclass
    class Checked:
        age: int

        def __post_init__(self) -> None:
            if self.age < 0:
                raise ValueError("age must not be negative")

    assert load("age\n3\n", Checked) == [Checked(3)]
    with pytest.raises(CsvConversionError, match="must not be negative.*line 3"):
        load("age\n3\n-1\n", Checked)


# ---------------------------------------------------------------------------
# Row shapes
# ---------------------------------------------------------------------------

def test_blank_lines_are_skipped() -> None:
    assert load("name,age\n\nAda,36\n\n", Person) == [Person("Ada", 36)]


def test_short_rows_fill_optional_fields_and_reject_required() -> None:
    assert load("name,note\nAda\n", WithDefaults) == [WithDefaults("Ada")]
    with pytest.raises(CsvConversionError, match="column 'age'"):
        load("name,age\nAda\n", Person)


def test_more_values_than_header_raises() -> None:
    with pytest.raises(ValueError, match="more values than the header"):
        load("name,age\nAda,36,extra\n", Person)


# ---------------------------------------------------------------------------
# Conversions
# ---------------------------------------------------------------------------

@dataclass
class Typed:
    flag: bool
    ratio: float
    when: dt.date
    at: dt.datetime
    span: dt.timedelta
    amount: Decimal
    color: Color
    level: Level
    pick: Literal["a", "b"]
    either: int | float
    maybe: int | None
    text: str | None


def test_typed_values() -> None:
    text = csv_text(
        ["flag", "ratio", "when", "at", "span", "amount", "color", "level", "pick", "either", "maybe", "text"],
        ["TRUE", "1e3", "2024-02-29", "2025-06-15T12:30:45+05:30", "PT1H30M", "12.50", "red", "2", "b", "2.5",
         "null", "null"],
        ["0", "-0.5", "2025-01-01", "1700000000", "90", "-1", "blue", "1", "a", "7", "3", ""],
    )
    first, second = load(text, Typed)
    assert first == Typed(
        True, 1000.0, dt.date(2024, 2, 29),
        dt.datetime(2025, 6, 15, 12, 30, 45, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30))),
        dt.timedelta(hours=1, minutes=30), Decimal("12.50"), Color.RED, Level.HIGH, "b", 2.5, None, "null")
    assert second.at == dt.datetime(2023, 11, 14, 22, 13, 20, tzinfo=dt.timezone.utc)   # Unix time
    assert second.span == dt.timedelta(seconds=90)
    assert type(second.either) is int and second.either == 7
    assert (second.flag, second.maybe, second.text) == (False, 3, "")


@pytest.mark.parametrize("column, bad", [
    ("flag", "yes"), ("ratio", "1,5"), ("when", "15/06/2025"), ("at", "2025-06-15T25:00:00"),
    ("amount", "abc"), ("color", "green"), ("level", "3"), ("pick", "c"), ("either", "x"), ("maybe", ""),
])
def test_invalid_values_report_line_and_column(column: str, bad: str) -> None:
    header = ["flag", "ratio", "when", "at", "span", "amount", "color", "level", "pick", "either", "maybe", "text"]
    good = ["true", "1", "2025-01-01", "2025-01-01T00:00:00", "P1D", "1", "red", "1", "a", "1", "1", "t"]
    bad_row = list(good)
    bad_row[header.index(column)] = bad
    with pytest.raises(CsvConversionError, match=rf"line 3, column '{column}'"):
        load(csv_text(header, good, bad_row), Typed)


def test_registered_types_work_in_cells() -> None:
    class Money:
        def __init__(self, text: str) -> None:
            amount, self.currency = text.split(" ")
            self.amount = Decimal(amount)

        def __eq__(self, other: object) -> bool:
            return isinstance(other, Money) and (self.amount, self.currency) == (other.amount, other.currency)

    Order = make_dataclass("Order", [("total", Money)])
    register_type(Money, decode=Money, encode=lambda m: f"{m.amount} {m.currency}")
    try:
        assert load("total\n12.50 EUR\n", Order)[0].total == Money("12.50 EUR")
        with pytest.raises(CsvConversionError, match="column 'total'"):
            load("total\nbroken\n", Order)
    finally:
        unregister_type(Money)


def test_unsupported_column_type_is_a_type_error() -> None:
    Holder = make_dataclass("Holder", [("values", list[int])])
    with pytest.raises(TypeError, match="cannot hold"):
        load("values\n1\n", Holder)


# ---------------------------------------------------------------------------
# Lazy loading
# ---------------------------------------------------------------------------

def test_load_it_is_lazy_and_closes_the_file(tmp_path: Path) -> None:
    path = tmp_path / "people.csv"
    path.write_text("name,age\nAda,36\nBob,x\n", encoding="utf-8")
    query = CsvLoader.load_it(path, Person)
    iterator = iter(query)
    assert next(iterator) == Person("Ada", 36)
    with pytest.raises(CsvConversionError, match="line 3, column 'age'"):
        next(iterator)


def test_load_it_rejects_non_dataclass_immediately() -> None:
    with pytest.raises(TypeError):
        CsvLoader.load_it("a\n1\n", dict)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Same lenient rules as the previous msgspec-based loader (strict=False conversion)
# ---------------------------------------------------------------------------

PARITY_TYPES: list[Any] = [
    int, float, bool, int | None, float | None, str | None, bool | None, Decimal, dt.date, dt.datetime, dt.time,
    dt.timedelta, Literal["a", "b"], Literal[1, 2], Color, Level, int | float,
]
PARITY_SPECIAL = [
    "0", "-0", "00", "007", "1", "-1", "+1", "1.0", "1.5", ".5", "5.", "1e3", "1E3", "1e+3", "1e-3", "1e16",
    "1e400", "nan", "NaN", "inf", "-Infinity", " 1", "1 ", "1_0", "١", "true", "True", "TRUE", "false", "yes",
    "null", "NULL", "None", "", "x", "a", "b", "red", "RED", "2", "2025-06-15", "2025-6-15", "2023-02-29",
    "0000-01-01", "2025-06-15T12:30:45", "2025-06-15 12:30:45", "2025-06-15t12:30:45z", "2025-06-15T12:30:45Z",
    "2025-06-15T12:30:45+05:30", "2025-06-15T12:30:45-00:00", "2025-06-15T12:30:45+24:00",
    "2025-06-15T12:30:45.1234567Z", "2025-06-15T12:30", "12:30:45", "12:30", "PT1H", "P1D", "-PT0.5S", "1.50",
    "12345678901234567890", "9007199254740993.0", "1700000000", "1.7e308",
]


def _same(expected: tuple[str, Any], actual: tuple[str, Any]) -> bool:
    if expected[0] != actual[0] or expected[0] == "error":
        return expected[0] == actual[0]
    a, b = expected[1], actual[1]
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    if isinstance(a, Decimal) and isinstance(b, Decimal) and a.is_nan() and b.is_nan():
        return True
    if type(a) is not type(b):
        return False
    if isinstance(a, (dt.datetime, dt.time)) and a.utcoffset() != b.utcoffset():
        return False
    return bool(a == b)


@pytest.mark.parametrize("tp", PARITY_TYPES, ids=str)
def test_lenient_rules_match_msgspec(tp: Any) -> None:
    msgspec = pytest.importorskip("msgspec")
    rnd = random.Random(42)
    alphabet = "0123456789.-+eE:TZz tnaflsrue_ "
    values = PARITY_SPECIAL + ["".join(rnd.choice(alphabet) for _ in range(rnd.randint(1, 8))) for _ in range(400)]
    box = make_dataclass("Box", [("value", tp)])
    mismatches = []
    for value in values:
        try:
            actual: tuple[str, Any] = ("ok", load(csv_text(["value"], [value]), box)[0].value)
        except CsvConversionError:
            actual = ("error", None)
        try:
            expected: tuple[str, Any] = ("ok", msgspec.convert(value, tp, strict=False))
        except msgspec.ValidationError:
            expected = ("error", None)
        if not _same(expected, actual):
            mismatches.append((value, expected, actual))
    assert mismatches == []
