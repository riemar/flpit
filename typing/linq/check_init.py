"""Static typing contracts for FlpIt/FlpList construction and factories.

Run a supported type checker against this file from the repository root. These
assertions are intended for static analysis; the examples also remain valid
Python when FlpIt is installed.
"""

from collections.abc import Iterable, Iterator
from typing import assert_type

from flpit import FlpIt, FlpList, Grouping, OrderedIt, flp


class Item:
    def __init__(self, item_id: int, label: str) -> None:
        self.item_id = item_id
        self.label = label


ITEMS: tuple[Item, ...] = (Item(1, "one"), Item(2, "two"))


def item_stream() -> Iterator[Item]:
    yield from ITEMS


# --- Direct FlpIt construction ---
from_list = FlpIt([1, 2, 3])
assert_type(from_list, FlpIt[int])

from_tuple: FlpIt[Item] = FlpIt(ITEMS)
assert_type(from_tuple, FlpIt[Item])

source: Iterable[Item] = ITEMS
from_iterable = FlpIt(source)
assert_type(from_iterable, FlpIt[Item])

from_iterator = FlpIt(item_stream())
assert_type(from_iterator, FlpIt[Item])

# FlpIt intentionally requires a source; only FlpList supports an empty
# no-argument constructor.
empty_query: FlpIt[int] = FlpIt([])
assert_type(empty_query, FlpIt[int])

# --- Direct FlpList construction ---
from_list_container = FlpList([1, 2, 3])
assert_type(from_list_container, FlpList[int])

from_typed_container: FlpList[Item] = FlpList(ITEMS)
assert_type(from_typed_container, FlpList[Item])

empty_container: FlpList[int] = FlpList[int]()
assert_type(empty_container, FlpList[int])

# Collection protocol and indexed access are part of the materialized type's
# public construction contract. The __iter__ assertion also guards against
# accidentally degrading item inference to Any.
assert_type(len(from_typed_container), int)
assert_type(from_typed_container[0], Item)
assert_type(from_typed_container[:1], FlpList[Item])
assert_type(next(iter(from_typed_container)), Item)

# --- Public factory module: flpit.flp ---
assert_type(flp.it([1, 2, 3]), FlpIt[int])
assert_type(flp.it(ITEMS), FlpIt[Item])
assert_type(flp.lst([1, 2, 3]), FlpList[int])
assert_type(flp.lst(ITEMS), FlpList[Item])
assert_type(flp.range(10, 3), FlpIt[int])
assert_type(flp.repeat("x", 3), FlpIt[str])

# --- Explicit retagging API ---
assert_type(from_tuple.as_type(str), FlpIt[str])
assert_type(from_typed_container.as_type(str), FlpList[str])

# --- Public generic helper classes ---
ordered = OrderedIt[Item](ITEMS, lambda item: item.label)
assert_type(ordered, OrderedIt[Item])
assert_type(OrderedIt[Item](ITEMS, lambda item: item.item_id, descending=True), OrderedIt[Item])

by_label = Grouping[str, Item]("group", ITEMS)
assert_type(by_label, Grouping[str, Item])
assert_type(by_label.key, str)
assert_type(by_label.to_list(), FlpList[Item])
