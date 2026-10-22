from decimal import Decimal
from io import BytesIO
from typing import assert_type

from flpit.json import JsonSerializerOptions

from flpit import FlpIt, FlpList, Grouping, OrderedIt, flp


class Record:
    def __init__(self, record_id: int, name: str, department: str, active: bool) -> None:
        self.record_id = record_id
        self.name = name
        self.department = department
        self.active = active

    def __lt__(self, other: "Record") -> bool:
        return self.record_id < other.record_id


RECORD = Record(1, "Ada", "engineering", True)
INACTIVE_RECORD = Record(2, "Linus", "research", False)
OTHER_RECORD = Record(3, "Grace", "engineering", True)
RECORDS = (RECORD, INACTIVE_RECORD, OTHER_RECORD)
QUERY: FlpIt[Record] = flp.it(RECORDS)
CONTAINER: FlpList[Record] = flp.lst(RECORDS)
NUMBERS: FlpIt[int] = flp.it([1, 2, 3])
NUMBER_LIST: FlpList[int] = flp.lst([1, 2, 3])


# ============================================================================
# FlpIt: deferred sequence operators
# ============================================================================
assert_type(QUERY.append(RECORD), FlpIt[Record])
assert_type(QUERY.prepend(RECORD), FlpIt[Record])
assert_type(QUERY.concat([RECORD, INACTIVE_RECORD]), FlpIt[Record])
assert_type(QUERY.any(), bool)
assert_type(QUERY.any(lambda item: item.active), bool)
assert_type(QUERY.all(lambda item: item.active), bool)
assert_type(QUERY.where(lambda item: item.active), FlpIt[Record])
assert_type(QUERY.select(lambda item: item.name), FlpIt[str])
assert_type(QUERY.select_many(lambda item: (item.name, item.department)), FlpIt[str])
assert_type(QUERY.skip(1), FlpIt[Record])
assert_type(QUERY.take(2), FlpIt[Record])

OBJECTS: FlpIt[object] = flp.it([1, "two", 3.0])
assert_type(OBJECTS.cast(int), FlpIt[int])
assert_type(OBJECTS.of_type(int), FlpIt[int])
assert_type(flp.it([1, 2, 1]).distinct(), FlpIt[int])
assert_type(QUERY.distinct_by(lambda item: item.department), FlpIt[Record])

# These assertions express the intended precise zip contract. The current
# FlpIt.zip declaration in src/flpit/core/linq.py returns FlpIt[Any] and has no
# overloads, so a type checker should flag them until that declaration is
# tightened. The parallel FlpList overloads are checked below.
assert_type(QUERY.zip([10, 20]), FlpIt[tuple[Record, int]])
assert_type(QUERY.zip([10, 20], lambda item, n: item.name * n), FlpIt[str])

assert_type(QUERY.chunk(2), FlpIt[FlpList[Record]])
ordered: OrderedIt[Record] = QUERY.order_by(lambda item: item.department)
assert_type(ordered, OrderedIt[Record])
assert_type(QUERY.order_by_descending(lambda item: item.name), OrderedIt[Record])
assert_type(ordered.then_by(lambda item: item.name), OrderedIt[Record])
assert_type(ordered.then_by_descending(lambda item: item.record_id), OrderedIt[Record])
assert_type(QUERY.group_by(lambda item: item.department), FlpIt[Grouping[str, Record]])

# Aggregation / terminal operators.
assert_type(NUMBERS.aggregate(lambda total, value: total + value), int)
assert_type(QUERY.aggregate(lambda total, item: total + item.record_id, 0), int)
assert_type(QUERY.last(), Record)
assert_type(QUERY.last(lambda item: item.active), Record)
assert_type(NUMBERS.min(), int)
assert_type(NUMBERS.max(), int)
assert_type(QUERY.min_by(lambda item: item.record_id), Record)
assert_type(QUERY.max_by(lambda item: item.name), Record)
assert_type(NUMBERS.sum(), int | float | Decimal)
assert_type(QUERY.sum(lambda item: item.record_id), int | float | Decimal)
assert_type(NUMBERS.average(), float | int | Decimal | None)
assert_type(QUERY.average(lambda item: item.record_id), float | int | Decimal | None)
assert_type(NUMBERS.avg(), float | int | Decimal | None)
assert_type(QUERY.count(), int)
assert_type(QUERY.count(lambda item: item.active), int)
assert_type(QUERY.element_at(0), Record)
assert_type(QUERY.first(), Record)
assert_type(QUERY.first(lambda item: item.active), Record)
assert_type(QUERY.first_or_default("missing"), Record | str)
assert_type(QUERY.first_or_default("missing", lambda item: item.record_id == 999), Record | str)
assert_type(QUERY.single(lambda item: item.record_id == 1), Record)
assert_type(QUERY.to_list(), FlpList[Record])


# ============================================================================
# FlpList: collection and LINQ operators
# ============================================================================
assert_type(CONTAINER.any(), bool)
assert_type(CONTAINER.any(lambda item: item.active), bool)
assert_type(CONTAINER.all(lambda item: item.active), bool)
assert_type(CONTAINER.append(RECORD), FlpIt[Record])
assert_type(CONTAINER.prepend(RECORD), FlpIt[Record])
assert_type(CONTAINER.concat([RECORD]), FlpIt[Record])
assert_type(CONTAINER.as_type(str), FlpList[str])
assert_type(CONTAINER.where(lambda item: item.active), FlpIt[Record])
assert_type(CONTAINER.select(lambda item: item.name), FlpIt[str])
assert_type(CONTAINER.select_many(lambda item: (item.name, item.department)), FlpIt[str])
assert_type(CONTAINER.skip(1), FlpIt[Record])
assert_type(CONTAINER.take(2), FlpIt[Record])
assert_type(CONTAINER.cast(int), FlpIt[int])
assert_type(CONTAINER.of_type(int), FlpIt[int])
assert_type(CONTAINER.distinct(), FlpIt[Record])
assert_type(CONTAINER.distinct_by(lambda item: item.department), FlpIt[Record])
assert_type(CONTAINER.zip([1, 2]), FlpIt[tuple[Record, int]])
assert_type(CONTAINER.zip([1, 2], lambda item, n: item.name * n), FlpIt[str])
assert_type(CONTAINER.chunk(2), FlpIt[FlpList[Record]])
assert_type(CONTAINER.order_by(lambda item: item.name), OrderedIt[Record])
assert_type(CONTAINER.order_by_descending(lambda item: item.record_id), OrderedIt[Record])
assert_type(CONTAINER.group_by(lambda item: item.department), FlpIt[Grouping[str, Record]])
assert_type(CONTAINER.aggregate(lambda total, item: total + item.record_id, 0), int)
assert_type(CONTAINER.min(), Record)
assert_type(CONTAINER.min_by(lambda item: item.record_id), Record)
assert_type(CONTAINER.max(), Record)
assert_type(CONTAINER.max_by(lambda item: item.name), Record)
assert_type(CONTAINER.sum(lambda item: item.record_id), int | float | Decimal)
assert_type(CONTAINER.average(lambda item: item.record_id), float | int | Decimal | None)
assert_type(CONTAINER.count(), int)
assert_type(CONTAINER.count(lambda item: item.active), int)
assert_type(CONTAINER.element_at(0), Record)
assert_type(CONTAINER.first(), Record)
assert_type(CONTAINER.first(lambda item: item.active), Record)
assert_type(CONTAINER.last(), Record)
assert_type(CONTAINER.last(lambda item: item.active), Record)
assert_type(CONTAINER.first_or_default("missing"), Record | str)
assert_type(CONTAINER.single(lambda item: item.record_id == 1), Record)
assert_type(CONTAINER.to_list(), FlpList[Record])

# FlpList-specific collection operators and mutation signatures.
MUTABLE: FlpList[Record] = flp.lst([RECORD, INACTIVE_RECORD])
assert_type(MUTABLE.contains(RECORD), bool)
assert_type(MUTABLE.exists(lambda item: item.active), bool)
assert_type(MUTABLE.find(lambda item: item.record_id == 1), Record | None)
assert_type(MUTABLE.find_all(lambda item: item.active), FlpList[Record])
assert_type(MUTABLE.add(RECORD), None)
assert_type(MUTABLE.add_range([RECORD]), None)
assert_type(MUTABLE.insert(0, RECORD), None)
assert_type(MUTABLE.insert_range(0, [INACTIVE_RECORD]), None)
assert_type(MUTABLE.remove(RECORD), bool)
assert_type(MUTABLE.remove_all(lambda item: item.active), int)
assert_type(MUTABLE.reverse(), None)
assert_type(MUTABLE.reverse(0, 1), None)
assert_type(MUTABLE.remove_at(0), None)
assert_type(MUTABLE.remove_range(0, 1), None)
assert_type(MUTABLE.clear(), None)

# Subscription overloads: scalar indexing returns TItem; slicing returns
# FlpList[TItem]. These operations execute only on the local fixture.
assert_type(CONTAINER[0], Record)
assert_type(CONTAINER[:1], FlpList[Record])
CONTAINER[0] = RECORD
CONTAINER[0:1] = [RECORD]
assert_type(RECORD in CONTAINER, bool)
