"""
AsyncFlpIt execution invariants (.agents/rules.md) that the migrated .NET tests do not cover:
deferred construction, one-shot sources, borrowed enumerators, Python-native consumption,
cancellation flow into AsyncFlpIt.create factories and the sync <-> async bridges.
"""
import pytest

from flpit import AsyncFlpIt, FlpIt, FlpList, OrderedAsyncIt, flp
from flpit.task import CancellationToken, CancellationTokenSource, OperationCanceledError, Task


def run(coroutine_function, *args):
    return Task.run(coroutine_function, *args).result()


class _CountingAsync:
    """Re-enumerable async iterable that records how often it is enumerated and read."""

    def __init__(self, items):
        self.items = list(items)
        self.enumerations = 0
        self.reads = 0
        self.closed = 0

    async def _gen(self):
        self.enumerations += 1
        try:
            for item in self.items:
                self.reads += 1
                yield item
        finally:
            self.closed += 1

    def __aiter__(self):
        return self._gen()


def test_query_construction_does_not_touch_the_source():
    source = _CountingAsync([3, 1, 2])
    query = (
        flp.ait(source)
        .where(lambda x: x > 0)
        .select(lambda x: x * 2)
        .order_by(lambda x: x)
        .take(2)
        .concat([9])
        .append(10)
    )
    assert source.enumerations == 0
    assert list(query.to_list().result()) == [2, 4, 9, 10]
    assert source.enumerations == 1


def test_callbacks_run_lazily_and_only_when_enumerated():
    calls = []
    query = flp.ait([1, 2, 3]).select(lambda x: calls.append(x) or x)
    assert calls == []
    assert query.first().result() == 1
    assert calls == [1]


def test_re_enumerable_source_stays_re_enumerable():
    source = _CountingAsync([1, 2, 3])
    query = flp.ait(source).select(lambda x: x + 1)
    assert query.to_list().result() == [2, 3, 4]
    assert query.to_list().result() == [2, 3, 4]
    assert source.enumerations == 2


def test_one_shot_async_generator_stays_one_shot():
    async def numbers():
        for i in range(3):
            yield i

    query = flp.ait(numbers()).select(lambda x: x * 10)
    assert query.to_list().result() == [0, 10, 20]
    assert query.to_list().result() == []


def test_borrowed_async_generator_is_not_closed_by_short_circuit():
    async def numbers():
        for i in range(5):
            yield i

    generator = numbers()
    query = flp.ait(generator)
    assert query.first().result() == 0
    # The pipeline did not create the generator, so it did not close it (like FlpIt.take).
    assert query.to_list().result() == [1, 2, 3, 4]


def test_owned_enumerators_are_closed_on_short_circuit():
    source = _CountingAsync(range(100))
    assert flp.ait(source).where(lambda x: x > 2).any().result() is True
    assert source.reads == 4
    assert source.closed == 1


def test_one_shot_sync_iterator_source_stays_one_shot():
    iterator = iter([1, 2, 3])
    query = flp.ait(iterator)
    assert query.first().result() == 1
    assert query.to_list().result() == [2, 3]


def test_python_native_async_for_and_comprehension():
    async def main():
        query = AsyncFlpIt.range(1, 5).where(lambda x: x % 2 == 1)
        looped = []
        async for item in query:
            looped.append(item)
        return looped, [item async for item in query]

    assert run(main) == ([1, 3, 5], [1, 3, 5])


def test_terminal_operators_return_tasks():
    query = flp.ait([1, 2, 3])
    for task in (query.to_list(), query.count(), query.first(), query.any(), query.sum(), query.max()):
        assert isinstance(task, Task)
        task.result()
    assert isinstance(query.to_list().result(), FlpList)


def test_terminal_operators_can_be_awaited_inside_the_runtime():
    async def main():
        query = flp.ait(range(10)).where(lambda x: x % 3 == 0)
        return await query.count(), await query.last(), await query.to_dictionary(lambda x: x, str)

    assert run(main) == (4, 9, {0: "0", 3: "3", 6: "6", 9: "9"})


def test_as_type_returns_self():
    query = flp.ait([1, 2])
    assert query.as_type(int) is query
    ordered = query.order_by(lambda x: x)
    assert isinstance(ordered, OrderedAsyncIt)
    assert ordered.as_type(int) is ordered


def test_order_by_is_stable_and_then_by_augments():
    rows = [("b", 2), ("a", 2), ("c", 1), ("a", 1)]
    query = flp.ait(rows).order_by(lambda r: r[1]).then_by(lambda r: r[0])
    assert query.to_list().result() == [("a", 1), ("c", 1), ("a", 2), ("b", 2)]
    stable = flp.ait(rows).order_by(lambda r: r[1])
    assert stable.to_list().result() == [("c", 1), ("a", 1), ("b", 2), ("a", 2)]


def test_order_by_none_keys_sort_first_like_dotnet_null():
    query = flp.ait([3, None, 1]).order_by(lambda x: x)
    assert query.to_list().result() == [None, 1, 3]
    assert flp.ait([3, None, 1]).order_by_descending(lambda x: x).to_list().result() == [3, 1, None]


def test_create_passes_the_enumeration_token_to_the_factory():
    seen = []

    async def numbers(token: CancellationToken):
        seen.append(token)
        for i in range(100):
            await Task.delay(0, token=token)
            yield i

    cts = CancellationTokenSource()

    async def main():
        async for item in AsyncFlpIt.create(numbers).select(lambda x: x).with_cancellation(cts.token):
            if item == 3:
                cts.cancel()

    with pytest.raises(OperationCanceledError):
        run(main)
    assert seen == [cts.token]


def test_terminal_token_reaches_async_callbacks_and_the_source():
    seen = []

    async def predicate(x, token):
        seen.append(token)
        return x > 1

    cts = CancellationTokenSource()
    assert flp.ait([1, 2, 3]).first(predicate, token=cts.token).result() == 2
    assert seen == [cts.token, cts.token]


def test_with_cancellation_rejects_non_tokens():
    with pytest.raises(TypeError):
        flp.ait([1]).with_cancellation(object())


def test_async_callbacks_receive_the_token_as_last_argument():
    async def double(x, token):
        assert isinstance(token, CancellationToken)
        await Task.yield_now()
        return x * 2

    assert flp.ait([1, 2]).select(double).to_list().result() == [2, 4]


def test_select_many_mixes_sync_and_async_inner_sequences():
    async def inner(x):
        yield x
        yield -x

    query = flp.ait([1, 2]).select_many(lambda x: inner(x) if x == 1 else [x, x])
    assert query.to_list().result() == [1, -1, 2, 2]


def test_sync_flpit_bridges_to_async():
    query = flp.it(range(5)).where(lambda x: x % 2 == 0).to_async_enumerable()
    assert isinstance(query, AsyncFlpIt)
    assert query.select(lambda x: x + 1).to_list().result() == [1, 3, 5]
    assert isinstance(FlpIt([1]).to_async_enumerable(), AsyncFlpIt)


def test_invalid_source_type_is_rejected_eagerly():
    with pytest.raises(TypeError):
        AsyncFlpIt(42)  # type: ignore[arg-type]


def test_long_concat_chains_do_not_nest():
    query = AsyncFlpIt.empty()
    for i in range(5000):
        query = query.concat([i])
    assert query.count().result() == 5000
