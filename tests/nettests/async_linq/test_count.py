"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable CountAsyncTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/CountAsyncTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * LongCountAsync -> count(): Python's int is unbounded, so there is no separate long count (FlpIt has
      none either); the LongCount assertions run against count().
    * IAsyncEnumerator.Current has no Python equivalent; current_count counts successful moves, so the
      parameterless CountAsync() reports 4 where .NET reports CurrentCount 0.
    * Callbacks_InvokedOnOriginalContext: SynchronizationContext has no Python equivalent (skipped).
"""
import pytest

from flpit import AsyncFlpIt, PredicateNoneError, SourceNoneError, flp
from flpit.task import CancellationTokenSource, OperationCanceledError, Task
from nettests.async_linq.async_helpers import (
    TRUE_FALSE_BOOLS, async_test, canceled_token, create_source, create_sources, not_portable, track,
)


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    with pytest.raises(PredicateNoneError):
        AsyncFlpIt.empty().count(None)


@pytest.mark.parametrize("values", [[], [1], [2, 4, 8], [-1, 2, 5, 6, 7, 8], [1, 3, 5, 7]])
@async_test
async def test_VariousValues_MatchesEnumerable(values):
    def predicate(x):
        return x % 2 == 0

    async def predicate_async(x, ct):
        await Task.yield_now()
        return predicate(x)

    for source in create_sources(*values):
        assert await source.count() == len(values)
        assert await source.count(predicate) == sum(map(predicate, values))
        assert await source.all(predicate_async) == all(map(predicate, values))
        assert await source.count(predicate_async) == sum(map(predicate, values))


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)
    with pytest.raises(OperationCanceledError):
        await source.count(lambda x: x < 0, token=canceled_token())

    cts = CancellationTokenSource()

    async def cancel_then_test(x, ct):
        assert ct is cts.token
        await Task.yield_now()
        cts.cancel()
        return x < 0

    with pytest.raises(OperationCanceledError):
        await source.count(cancel_then_test, token=cts.token)


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source(2, 4, 8, 16))
    assert await source.count() == 4
    assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)  # .NET: (5, 0, 1)

    for use_async in TRUE_FALSE_BOOLS:
        def wrap(f):
            if not use_async:
                return f

            async def g(x, ct):
                return f(x)
            return g

        source = track(create_source(2, 4, 8, 16))
        assert await source.count(wrap(lambda x: x > 7)) == 2
        assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)

        source = track(create_source(2, 4, 8, 16))
        assert await source.count(wrap(lambda x: x > 20)) == 0
        assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)

        def throw(x):
            raise Exception()

        source = track(create_source(2, 4, 8, 16))
        with pytest.raises(Exception):
            await source.count(wrap(throw))
        assert (source.move_next_count, source.current_count, source.dispose_count) == (1, 1, 1)


def test_Callbacks_InvokedOnOriginalContext():
    not_portable("SynchronizationContext")
