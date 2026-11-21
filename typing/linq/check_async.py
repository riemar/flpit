"""Static inference checks for AsyncFlpIt (run: uv run pyrefly check typing/linq/check_async.py)."""
from collections.abc import AsyncIterator, Coroutine
from typing import Any, Protocol, assert_type

from flpit import (
    AsyncEnumerator, AsyncFlpIt, FlpIt, FlpList, Grouping, IndexTuple, JoinTuple, Lookup, OrderedAsyncIt, ZipTuple,
    async_flpit, flp,
)
from flpit.task import CancellationToken, Task, await_using


class Record:
    def __init__(self, record_id: int, name: str, active: bool) -> None:
        self.record_id = record_id
        self.name = name
        self.active = active


RECORD = Record(1, "Ada", True)
QUERY: AsyncFlpIt[Record] = flp.ait([RECORD])
NUMBERS: AsyncFlpIt[int] = flp.ait([1, 2, 3])


async def is_active(record: Record, token: CancellationToken) -> bool:
    return record.active


async def record_name(record: Record, token: CancellationToken) -> str:
    return record.name


async def numbers(token: CancellationToken) -> AsyncIterator[int]:
    yield 1


async def numbers_stream() -> AsyncIterator[int]:
    yield 1


# --- construction -------------------------------------------------------------------------------
assert_type(flp.ait([1, 2]), AsyncFlpIt[int])
assert_type(flp.it([1, 2]).to_async_enumerable(), AsyncFlpIt[int])
assert_type(flp.lst([1, 2]).to_async_enumerable(), AsyncFlpIt[int])
assert_type(flp.it([1, 2]).order_by(lambda i: i).to_async_enumerable(), AsyncFlpIt[int])  # OrderedIt
assert_type(flp.it([RECORD]).group_by(lambda r: r.active).first().to_async_enumerable(), AsyncFlpIt[Record])  # Grouping
assert_type(flp.ait(tuple[int, ...]((1, 2))), AsyncFlpIt[int])
assert_type(flp.ait(range(3)), AsyncFlpIt[int])
assert_type(flp.ait({1, 2}), AsyncFlpIt[int])
assert_type(flp.ait({"a": 1}), AsyncFlpIt[str])  # iterates the keys
assert_type(flp.ait(x for x in [1, 2]), AsyncFlpIt[int])
assert_type(flp.ait(flp.lst([RECORD])), AsyncFlpIt[Record])
assert_type(flp.ait(QUERY), AsyncFlpIt[Record])  # an AsyncFlpIt is returned as is
assert_type(flp.ait(numbers_stream()), AsyncFlpIt[int])  # any async iterable
assert_type(flp.it([RECORD]).to_async_enumerable().where(is_active).select(record_name), AsyncFlpIt[str])
assert_type(flp.lst([RECORD]).to_async_enumerable().to_list(), Task[FlpList[Record]])
assert_type(AsyncFlpIt.range(0, 3), AsyncFlpIt[int])
assert_type(AsyncFlpIt.repeat("x", 3), AsyncFlpIt[str])
assert_type(AsyncFlpIt.create(numbers), AsyncFlpIt[int])
assert_type(QUERY.with_cancellation(CancellationToken.none()), AsyncFlpIt[Record])

# --- deferred operators: sync and async callbacks ------------------------------------------------
assert_type(QUERY.where(lambda r: r.active), AsyncFlpIt[Record])
assert_type(QUERY.where(is_active), AsyncFlpIt[Record])
assert_type(QUERY.select(lambda r: r.name), AsyncFlpIt[str])
assert_type(QUERY.select(record_name), AsyncFlpIt[str])
assert_type(QUERY.select_many(lambda r: [r.name]), AsyncFlpIt[str])
assert_type(QUERY.index(), AsyncFlpIt[IndexTuple[Record]])
assert_type(QUERY.take(1).skip(1).take_last(1).skip_last(1), AsyncFlpIt[Record])
assert_type(QUERY.distinct_by(lambda r: r.name), AsyncFlpIt[Record])
assert_type(NUMBERS.chunk(2), AsyncFlpIt[FlpList[int]])
assert_type(NUMBERS.zip(["a"]), AsyncFlpIt[ZipTuple[int, str]])
assert_type(QUERY.join([1], lambda r: r.record_id, lambda i: i), AsyncFlpIt[JoinTuple[Record, int]])
assert_type(QUERY.group_by(lambda r: r.active), AsyncFlpIt[Grouping[bool, Record]])
assert_type(QUERY.order_by(lambda r: r.name), OrderedAsyncIt[Record])
assert_type(QUERY.order_by(record_name).then_by_descending(lambda r: r.record_id), OrderedAsyncIt[Record])
assert_type(NUMBERS.cast(int), AsyncFlpIt[int])

# --- terminal operators return Tasks -------------------------------------------------------------
assert_type(QUERY.to_list(), Task[FlpList[Record]])
assert_type(QUERY.first(), Task[Record])
assert_type(QUERY.first(is_active), Task[Record])
assert_type(QUERY.first_or_default(None), Task[Record | None])
assert_type(QUERY.count(), Task[int])
assert_type(QUERY.any(is_active), Task[bool])
assert_type(QUERY.to_dictionary(lambda r: r.record_id), Task[dict[int, Record]])
assert_type(QUERY.to_lookup(lambda r: r.active, lambda r: r.name), Task[Lookup[bool, str]])
assert_type(NUMBERS.aggregate(0, lambda acc, i: acc + i), Task[int])


async def consume() -> None:
    async for record in QUERY:
        assert_type(record, Record)
    assert_type(await QUERY.to_list(), FlpList[Record])
    assert_type(await NUMBERS.count(), int)


# --- @async_flpit: async generator function -> AsyncFlpIt -------------------------------------------
@async_flpit
async def rows(n: int, token: CancellationToken = CancellationToken.none()) -> AsyncIterator[Record]:
    yield RECORD


@async_flpit
async def unannotated(n: int):  # the element type is inferred from the yields
    yield n


class ExpectedRows(Protocol):
    def __call__(self, n: int, token: CancellationToken = ...) -> AsyncFlpIt[Record]: ...


assert_type(rows, ExpectedRows)  # parameters kept, AsyncFlpIt returned
assert_type(rows(3), AsyncFlpIt[Record])
assert_type(rows(3, token=CancellationToken.none()), AsyncFlpIt[Record])
assert_type(unannotated(3), AsyncFlpIt[int])
assert_type(rows(3).where(is_active).select(record_name), AsyncFlpIt[str])
assert_type(rows(3).first(), Task[Record])

# --- AsyncEnumerator: get_async_enumerator() and async with -----------------------------------------
assert_type(QUERY.get_async_enumerator(), AsyncEnumerator[Record])
assert_type(rows(3).get_async_enumerator(CancellationToken.none()), AsyncEnumerator[Record])


# --- @await_using: same signature, same result ------------------------------------------------------
@await_using
async def first_name(n: int) -> str:
    async for record in rows(n):
        return record.name
    return ""


class ExpectedFirstName(Protocol):
    def __call__(self, n: int) -> Coroutine[Any, Any, str]: ...


assert_type(first_name, ExpectedFirstName)


async def scoped() -> None:
    async with rows(3).get_async_enumerator() as items:  # C#: await using (var items = ...)
        assert_type(items, AsyncEnumerator[Record])
        async for record in items:
            assert_type(record, Record)
    async for row in rows(3):  # C#: await foreach
        assert_type(row, Record)
    assert_type(await first_name(3), str)


_ = FlpIt
