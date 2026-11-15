"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable SingleAsyncTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/SingleAsyncTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

InvalidOperationException -> InvalidOperationError (EmptySequenceError / NoMatchError / Multiple...Error).
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


def test_Callbacks_InvokedOnOriginalContext():
    not_portable("SynchronizationContext")


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    with pytest.raises(PredicateNoneError):
        AsyncFlpIt.empty().single(None)


@async_test
async def test_EmptyInputs_Throws():
    for task in (
            lambda: AsyncFlpIt.empty().single(),
            lambda: AsyncFlpIt.empty().single(lambda i: i % 2 == 0),
            lambda: AsyncFlpIt.empty().single(_is_even),
            lambda: flp.ait([1, 3, 5]).single(lambda i: i % 2 == 0),
            lambda: flp.ait([1, 3, 5]).single(_is_even),
    ):
        first = task()
        with pytest.raises(InvalidOperationError):
            await first


@async_test
async def test_DoubleInputs_Throws():
    for task in (
            lambda: flp.ait([1, 2]).single(),
            lambda: flp.ait([1, 2, 1, 2]).single(lambda i: i % 2 == 0),
            lambda: flp.ait([1, 2, 1, 2]).single(_is_even),
    ):
        single = task()
        with pytest.raises(InvalidOperationError):
            await single


@pytest.mark.parametrize("values", [[1], [2, 4, 8], [-1, 2, 5, 6, 7, 8], [1, 3, 5, 7]])
@async_test
async def test_VariousValues_MatchesEnumerable(values):
    def predicate(i):
        return i == values[-1]

    async def predicate_async(i, ct):
        return predicate(i)

    for source in create_sources(*values):
        if len(values) == 1:
            assert await source.single() == flp.it(values).single()
        assert await source.single(predicate) == flp.it(values).single(predicate)
        assert await source.single(predicate_async) == flp.it(values).single(predicate)


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)
    with pytest.raises(OperationCanceledError):
        await source.single(token=canceled_token())

    cts = CancellationTokenSource()

    def cancel_then_test(x):
        cts.cancel()
        return x > 32

    with pytest.raises(OperationCanceledError):
        await source.single(cancel_then_test, token=cts.token)

    cts = CancellationTokenSource()

    async def cancel_then_test_async(x, ct):
        assert ct is cts.token
        await Task.yield_now()
        cts.cancel()
        return x > 32

    with pytest.raises(OperationCanceledError):
        await source.single(cancel_then_test_async, token=cts.token)


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source(2))
    await source.single()
    assert (source.move_next_count, source.current_count, source.dispose_count) == (2, 1, 1)

    async def is_2(i, ct):
        return i == 2

    for func in (lambda s: s.single(lambda i: i == 8), lambda s: s.single(is_2)):
        source = track(create_source(2, 4, 8, 16))
        await func(source)
        assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)
