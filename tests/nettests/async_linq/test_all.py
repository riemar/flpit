"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable AllAsyncTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/AllAsyncTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * Callbacks_InvokedOnOriginalContext: SynchronizationContext has no Python equivalent (skipped).
"""
import pytest

from flpit import AsyncFlpIt, PredicateNoneError, SourceNoneError, flp
from flpit.task import CancellationTokenSource, OperationCanceledError, Task
from nettests.async_linq.async_helpers import (
    TRUE_FALSE_BOOLS, async_test, create_source, create_sources, not_portable, track,
)


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    with pytest.raises(PredicateNoneError):
        AsyncFlpIt.empty().all(None)


@pytest.mark.parametrize("values", [[], [1], [2, 4, 8], [-1, 2, 5, 6, 7, 8]])
@async_test
async def test_VariousValues_MatchesEnumerable(values):
    def predicate(x):
        return x % 2 == 0

    async def predicate_async(x, ct):
        await Task.yield_now()
        return predicate(x)

    for source in create_sources(*values):
        assert await source.all(predicate) == all(map(predicate, values))
        assert await source.all(predicate_async) == all(map(predicate, values))


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)
    cts = CancellationTokenSource()
    cts.cancel()
    with pytest.raises(OperationCanceledError):
        await source.all(lambda x: x % 2 == 0, token=cts.token)

    cts = CancellationTokenSource()

    async def cancel_then_test(x, ct):
        assert ct is cts.token
        await Task.yield_now()
        cts.cancel()
        return x % 2 == 0

    with pytest.raises(OperationCanceledError):
        await source.all(cancel_then_test, token=cts.token)


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    for use_async in TRUE_FALSE_BOOLS:
        def wrap(f):
            if not use_async:
                return f

            async def g(x, ct):
                return f(x)
            return g

        source = track(create_source(2, 4, 8, 16))
        assert await source.all(wrap(lambda x: x % 2 == 0))
        assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)

        source = track(create_source(2, 4, 8, 16))
        assert not await source.all(wrap(lambda x: x < 4))
        assert (source.move_next_count, source.current_count, source.dispose_count) == (2, 2, 1)

        def throw(x):
            raise Exception()

        source = track(create_source(2, 4, 8, 16))
        with pytest.raises(Exception):
            await source.all(wrap(throw))
        assert (source.move_next_count, source.current_count, source.dispose_count) == (1, 1, 1)


def test_Callbacks_InvokedOnOriginalContext():
    not_portable("SynchronizationContext")
