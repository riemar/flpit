"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable FirstAsyncTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/FirstAsyncTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

InvalidOperationException -> InvalidOperationError (EmptySequenceError / NoMatchError).
Callbacks_InvokedOnOriginalContext: SynchronizationContext has no Python equivalent (skipped).
"""
import pytest

from flpit import AsyncFlpIt, InvalidOperationError, PredicateNoneError, SourceNoneError, flp
from flpit.task import CancellationTokenSource, OperationCanceledError, Task
from nettests.async_linq.async_helpers import (
    async_test, canceled_token, create_source, create_sources, not_portable, track,
)


async def _is_even(i, ct):
    return i % 2 == 0


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    with pytest.raises(PredicateNoneError):
        AsyncFlpIt.empty().first(None)


@async_test
async def test_EmptyInputs_Throws():
    first = AsyncFlpIt.empty().first()
    with pytest.raises(InvalidOperationError):
        await first
    first = AsyncFlpIt.empty().first(lambda i: i % 2 == 0)
    with pytest.raises(InvalidOperationError):
        await first
    first = AsyncFlpIt.empty().first(_is_even)
    with pytest.raises(InvalidOperationError):
        await first
    first = flp.ait([1, 3, 5]).first(lambda i: i % 2 == 0)
    with pytest.raises(InvalidOperationError):
        await first
    first = flp.ait([1, 3, 5]).first(_is_even)
    with pytest.raises(InvalidOperationError):
        await first


@pytest.mark.parametrize("values", [[1], [2, 4, 8], [-1, 2, 5, 6, 7, 8], [1, 3, 5, 7]])
@async_test
async def test_VariousValues_MatchesEnumerable(values):
    def predicate(i):
        return i == values[-1]

    async def predicate_async(i, ct):
        return predicate(i)

    for source in create_sources(*values):
        assert await source.first() == flp.it(values).first()
        assert await source.first(predicate) == flp.it(values).first(predicate)
        assert await source.first(predicate_async) == flp.it(values).first(predicate)


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)
    with pytest.raises(OperationCanceledError):
        await source.first(token=canceled_token())

    cts = CancellationTokenSource()

    def cancel_then_test(x):
        cts.cancel()
        return x > 32

    with pytest.raises(OperationCanceledError):
        await source.first(cancel_then_test, token=cts.token)

    cts = CancellationTokenSource()

    async def cancel_then_test_async(x, ct):
        assert ct is cts.token
        await Task.yield_now()
        cts.cancel()
        return x > 32

    with pytest.raises(OperationCanceledError):
        await source.first(cancel_then_test_async, token=cts.token)


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source(2, 4, 8, 16))
    await source.first()
    assert (source.move_next_count, source.current_count, source.dispose_count) == (1, 1, 1)

    source = track(create_source(2, 4, 8, 16))
    await source.first(lambda i: i == 8)
    assert (source.move_next_count, source.current_count, source.dispose_count) == (3, 3, 1)

    async def is_16(i, ct):
        return i == 16

    source = track(create_source(2, 4, 8, 16))
    await source.first(is_16)
    assert (source.move_next_count, source.current_count, source.dispose_count) == (4, 4, 1)


def test_Callbacks_InvokedOnOriginalContext():
    not_portable("SynchronizationContext")
