"""Type registry: FlpList by default, user value types, user collections, whenever.

Every test runs once per available backend (msgspec, native).
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest

from flpit import FlpList
from flpit.json import (
    JsonConvert,
    JsonDefaultHandling,
    JsonDeserializationError,
    JsonSerializationError,
    JsonSerializerOptions,
    register_collection,
    register_type,
    unregister_type,
)

pytestmark = pytest.mark.usefixtures("json_backend")

deserialize = JsonConvert.deserialize
serialize = JsonConvert.serialize

INCLUDE = JsonSerializerOptions(default_handling=JsonDefaultHandling.include)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

@dataclass
class Employee:
    name: str
    salary: int


@dataclass
class Department:
    name: str
    employees: FlpList[Employee]


@dataclass
class Matrix:
    rows: FlpList[FlpList[int]]


@dataclass
class OptionalTeam:
    members: FlpList[str] | None = None


@dataclass
class TeamWithDefault:
    name: str
    members: FlpList[str] = field(default_factory=FlpList)


class Money:
    """A user type the backends know nothing about."""

    def __init__(self, amount: Decimal, currency: str) -> None:
        self.amount = amount
        self.currency = currency

    @classmethod
    def parse(cls, text: Any) -> Money:
        if not isinstance(text, str):
            raise TypeError("money must be a string")
        amount, currency = text.split(" ")
        if len(currency) != 3:
            raise ValueError(f"invalid currency {currency!r}")
        return cls(Decimal(amount), currency)

    def format(self) -> str:
        return f"{self.amount} {self.currency}"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Money) and (self.amount, self.currency) == (other.amount, other.currency)

    def __repr__(self) -> str:
        return f"Money({self.format()!r})"


@dataclass
class Invoice:
    total: Money
    lines: list[Money]
    by_category: dict[str, Money]
    discount: Money | None = None


class Bag:
    """A user collection: unordered, stored as a JSON array."""

    def __init__(self, items: Any = ()) -> None:
        self._items = set(items)

    def __iter__(self) -> Iterator[Any]:
        return iter(sorted(self._items))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Bag) and self._items == other._items

    def __repr__(self) -> str:
        return f"Bag({sorted(self._items)!r})"


@dataclass
class Basket:
    fruit: Bag


@pytest.fixture
def money_type() -> Iterator[None]:
    register_type(Money, decode=Money.parse, encode=Money.format)
    try:
        yield
    finally:
        unregister_type(Money)


@pytest.fixture
def bag_type() -> Iterator[None]:
    register_collection(Bag, base=set)
    try:
        yield
    finally:
        unregister_type(Bag)


# ---------------------------------------------------------------------------
# FlpList is registered by default
# ---------------------------------------------------------------------------

class TestFlpListByDefault:
    def test_deserializes_into_flplist(self) -> None:
        raw = '{"name":"Eng","employees":[{"name":"Ada","salary":1},{"name":"Bob","salary":2}]}'
        result = deserialize(raw, Department)
        assert type(result.employees) is FlpList
        assert type(result.employees[0]) is Employee
        assert result.employees.select(lambda e: e.salary).sum() == 3

    def test_round_trip(self) -> None:
        value = Department("Eng", FlpList([Employee("Ada", 1), Employee("Bob", 2)]))
        raw = serialize(value, Department)
        assert raw == '{"name":"Eng","employees":[{"name":"Ada","salary":1},{"name":"Bob","salary":2}]}'
        assert deserialize(raw, Department) == value

    def test_nested_flplists(self) -> None:
        value = Matrix(FlpList([FlpList([1, 2]), FlpList([3])]))
        raw = serialize(value, Matrix)
        assert raw == '{"rows":[[1,2],[3]]}'
        result = deserialize(raw, Matrix)
        assert type(result.rows) is FlpList and type(result.rows[0]) is FlpList
        assert result == value

    def test_flplist_root_target(self) -> None:
        result = deserialize('[{"name":"Ada","salary":1}]', FlpList[Employee])
        assert type(result) is FlpList
        assert result[0] == Employee("Ada", 1)
        assert serialize(result, FlpList[Employee]) == '[{"name":"Ada","salary":1}]'

    def test_optional_flplist(self) -> None:
        assert deserialize('{}', OptionalTeam).members is None
        assert deserialize('{"members":null}', OptionalTeam).members is None
        result = deserialize('{"members":["a","b"]}', OptionalTeam)
        assert type(result.members) is FlpList and list(result.members) == ["a", "b"]

    def test_empty_default_flplist_is_written(self) -> None:
        # Empty registered collections are written even when excluding defaults
        # (msgspec can only detect empty builtin containers; both backends agree).
        assert serialize(TeamWithDefault("x"), TeamWithDefault) == '{"name":"x","members":[]}'
        assert serialize(TeamWithDefault("x"), TeamWithDefault, INCLUDE) == '{"name":"x","members":[]}'

    def test_missing_field_uses_default_factory(self) -> None:
        result = deserialize('{"name":"x"}', TeamWithDefault)
        assert type(result.members) is FlpList and len(result.members) == 0

    @pytest.mark.parametrize("raw", [
        '{"name":"Eng","employees":"nope"}',
        '{"name":"Eng","employees":{"name":"Ada","salary":1}}',
        '{"name":"Eng","employees":[{"name":"Ada","salary":"lots"}]}',
        '{"name":"Eng","employees":[1]}',
    ])
    def test_invalid_items_raise(self, raw: str) -> None:
        with pytest.raises(JsonDeserializationError):
            deserialize(raw, Department)


# ---------------------------------------------------------------------------
# User value types
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("money_type")
class TestRegisteredValueType:
    def test_round_trip_in_fields_lists_dicts_and_optionals(self) -> None:
        value = Invoice(
            total=Money(Decimal("12.50"), "EUR"),
            lines=[Money(Decimal("10.00"), "EUR"), Money(Decimal("2.50"), "EUR")],
            by_category={"food": Money(Decimal("12.50"), "EUR")},
            discount=Money(Decimal("1"), "EUR"),
        )
        raw = serialize(value, Invoice)
        assert raw == ('{"total":"12.50 EUR","lines":["10.00 EUR","2.50 EUR"],'
                       '"byCategory":{"food":"12.50 EUR"},"discount":"1 EUR"}')
        assert deserialize(raw, Invoice) == value

    def test_optional_value_type_defaults_to_none(self) -> None:
        result = deserialize('{"total":"1 EUR","lines":[],"byCategory":{}}', Invoice)
        assert result.discount is None

    @pytest.mark.parametrize("bad", ['"12.50 EURO"', "12.5", '"no-space"'])
    def test_decode_errors_become_deserialization_errors(self, bad: str) -> None:
        raw = f'{{"total":{bad},"lines":[],"byCategory":{{}}}}'
        with pytest.raises(JsonDeserializationError):
            deserialize(raw, Invoice)

    def test_registering_again_replaces_the_handler(self) -> None:
        register_type(Money, decode=lambda v: Money(Decimal(v), "EUR"), encode=lambda m: str(m.amount))
        value = Invoice(Money(Decimal("3"), "EUR"), [], {})
        raw = serialize(value, Invoice)
        assert raw == '{"total":"3","lines":[],"byCategory":{}}'
        assert deserialize(raw, Invoice) == value


def test_unregistered_type_is_rejected() -> None:
    @dataclass
    class Unknown:
        total: Money

    with pytest.raises((TypeError, JsonDeserializationError)):
        deserialize('{"total":"1 EUR"}', Unknown)
    with pytest.raises((TypeError, JsonSerializationError)):
        serialize(Unknown(Money(Decimal(1), "EUR")), Unknown)


# ---------------------------------------------------------------------------
# User collections
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("bag_type")
class TestRegisteredCollection:
    def test_round_trip(self) -> None:
        value = Basket(Bag(["pear", "apple"]))
        raw = serialize(value, Basket)
        assert raw == '{"fruit":["apple","pear"]}'
        result = deserialize(raw, Basket)
        assert type(result.fruit) is Bag
        assert result == value

    def test_duplicates_collapse_through_set_base(self) -> None:
        assert deserialize('{"fruit":["apple","apple"]}', Basket) == Basket(Bag(["apple"]))

    def test_non_array_raises(self) -> None:
        with pytest.raises(JsonDeserializationError):
            deserialize('{"fruit":"apple"}', Basket)


# ---------------------------------------------------------------------------
# Registry API
# ---------------------------------------------------------------------------

class TestRegistryApi:
    def test_rejects_non_types(self) -> None:
        with pytest.raises(TypeError):
            register_type("Money", decode=str, encode=str)  # type: ignore[arg-type]
        with pytest.raises(TypeError):
            register_collection(Bag, base=dict)

    def test_rejects_non_callables(self) -> None:
        with pytest.raises(TypeError):
            register_type(Money, decode="parse", encode=str)  # type: ignore[arg-type]

    def test_unregister_reports_whether_something_was_removed(self) -> None:
        assert unregister_type(Money) is False
        register_type(Money, decode=Money.parse, encode=Money.format)
        assert unregister_type(Money) is True
