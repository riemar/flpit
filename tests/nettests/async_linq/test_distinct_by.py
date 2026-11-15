"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable DistinctByTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/DistinctByTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * DistinctBy(keySelector, IEqualityComparer) is not implemented: the theory runs with the default
      comparer (null / EqualityComparer<int>.Default); OddEvenComparer is an explicitly skipped test.
    * x / 3 (C# integer division) -> int(x / 3) (truncation toward zero, also for negative x).
    * Callbacks_InvokedOnOriginalContext: SynchronizationContext has no Python equivalent (skipped).
"""
import pytest

from flpit import AsyncFlpIt, SelectorNoneError, SourceNoneError, flp
from flpit.task import CancellationTokenSource, Task
from nettests.async_linq.async_helpers import (
    assert_canceled, assert_equal, async_test, canceled_token, consume, create_source, create_sources,
    not_portable, track, unsupported,
)

_VALUES = [[], [1], [1, 1, 1, 2, 2, 2, 2, 2], [2, 4, 8], [2, 4, 8, 2, 4, 8, 2], [-1, 2, 5, 6, 7, 8]]


async def _identity(x, ct):
    return x


async def _div3(x, ct):
    return int(x / 3)


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    with pytest.raises(SelectorNoneError):
        AsyncFlpIt.empty().distinct_by(None)


def test_Empty_ProducesEmpty():
    assert AsyncFlpIt.empty().distinct_by(lambda i: i) is AsyncFlpIt.empty()
    assert AsyncFlpIt.empty().distinct_by(_identity) is AsyncFlpIt.empty()


@pytest.mark.parametrize("values", _VALUES)
@async_test
async def test_VariousValues_MatchesEnumerable(values):
    for source in create_sources(*values):
        await assert_equal(list(flp.it(values).distinct_by(lambda x: x)), source.distinct_by(lambda x: x))
        await assert_equal(list(flp.it(values).distinct_by(lambda x: x)), source.distinct_by(_identity))
        await assert_equal(list(flp.it(values).distinct_by(lambda x: int(x / 3))), source.distinct_by(lambda x: int(x / 3)))
        await assert_equal(list(flp.it(values).distinct_by(lambda x: int(x / 3))), source.distinct_by(_div3))


def test_VariousValues_MatchesEnumerable_OddEvenComparer():
    unsupported("distinct_by(key_selector, comparer=...)")


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)
    await assert_canceled(source.distinct_by(lambda x: x), canceled_token())

    cts = CancellationTokenSource()

    def cancel_then_key(x):
        cts.cancel()
        return x

    await assert_canceled(source.distinct_by(cancel_then_key), cts.token)

    cts = CancellationTokenSource()

    async def cancel_then_key_async(x, ct):
        assert ct is cts.token
        await Task.yield_now()
        cts.cancel()
        return x

    await assert_canceled(source.distinct_by(cancel_then_key_async), cts.token)


@pytest.mark.parametrize("use_async", [False, True])
@async_test
async def test_InterfaceCalls_ExpectedCounts(use_async):
    source = track(create_source(2, 4, 8, 16))
    func_count = 0

    def key(x):
        nonlocal func_count
        func_count += 1
        return x

    async def key_async(x, ct):
        nonlocal func_count
        func_count += 1
        return x

    await consume(source.distinct_by(key_async if use_async else key))
    assert source.move_next_count == 5
    assert source.current_count == 4
    assert source.dispose_count == 1
    assert func_count == 4


def test_Callbacks_InvokedOnOriginalContext():
    not_portable("SynchronizationContext")
