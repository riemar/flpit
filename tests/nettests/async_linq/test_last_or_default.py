"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable LastOrDefaultAsyncTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/LastOrDefaultAsyncTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * Python has no default(T): last_or_default(default, predicate=...) takes the default first and always
      (as FlpIt.last_or_default does); LastOrDefaultAsync() over int maps to last_or_default(0).
    * Callbacks_InvokedOnOriginalContext: SynchronizationContext has no Python equivalent (skipped).
"""
import pytest

from flpit import AsyncFlpIt, InvalidOperationError, PredicateNoneError, SourceNoneError, flp
from flpit.task import CancellationTokenSource, OperationCanceledError, Task
from nettests.async_linq.async_helpers import (
    async_test, canceled_token, create_source, create_sources, not_portable, track,
)


async def _is_even(i, ct):
    return i % 2 == 0


def test_Callbacks_InvokedOnOriginalContext():
    not_portable("SynchronizationContext")


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    with pytest.raises(PredicateNoneError):
        AsyncFlpIt.empty().last_or_default(0, None)
    with pytest.raises(PredicateNoneError):
        AsyncFlpIt.empty().last_or_default(42, None)


@async_test
async def test_EmptyInputs_DefaultValueReturned():
    empty = AsyncFlpIt.empty()
    assert await empty.last_or_default(0) == 0
    assert await empty.last_or_default(42) == 42
    assert await empty.last_or_default(0, lambda i: i % 2 == 0) == 0
    assert await empty.last_or_default(42, lambda i: i % 2 == 0) == 42
    assert await empty.last_or_default(0, _is_even) == 0
    assert await empty.last_or_default(42, _is_even) == 42
    source = flp.ait([1, 3, 5])
    assert await source.last_or_default(0, lambda i: i % 2 == 0) == 0
    assert await source.last_or_default(42, lambda i: i % 2 == 0) == 42
    assert await source.last_or_default(0, _is_even) == 0
    assert await source.last_or_default(42, _is_even) == 42


@pytest.mark.parametrize("values", [[1], [2, 4, 8], [-1, 2, 5, 6, 7, 8], [1, 3, 5, 7]])
@async_test
async def test_VariousValues_MatchesEnumerable(values):
    def predicate(i):
        return i < 5

    async def predicate_async(i, ct):
        return predicate(i)

    for source in create_sources(*values):
        assert await source.last_or_default(0) == flp.it(values).last_or_default(0)
        assert await source.last_or_default(0, predicate) == flp.it(values).last_or_default(0, predicate)
        assert await source.last_or_default(0, predicate_async) == flp.it(values).last_or_default(0, predicate)


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)
    with pytest.raises(OperationCanceledError):
        await source.last_or_default(0, token=canceled_token())

    cts = CancellationTokenSource()

    def cancel_then_test(x):
        cts.cancel()
        return x > 32

    with pytest.raises(OperationCanceledError):
        await source.last_or_default(0, cancel_then_test, token=cts.token)

    cts = CancellationTokenSource()

    async def cancel_then_test_async(x, ct):
        assert ct is cts.token
        await Task.yield_now()
        cts.cancel()
        return x > 32

    with pytest.raises(OperationCanceledError):
        await source.last_or_default(0, cancel_then_test_async, token=cts.token)


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    async def is_16(i, ct):
        return i == 16

    for func in (
            lambda s: s.last_or_default(0),
            lambda s: s.last_or_default(0, lambda i: i == 8),
            lambda s: s.last_or_default(0, is_16),
    ):
        source = track(create_source(2, 4, 8, 16))
        await func(source)
        assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)
