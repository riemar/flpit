"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable ExceptByTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/ExceptByTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * ExceptBy(second, keySelector, IEqualityComparer) is not implemented; the OddEvenComparer assertions
      are split into an explicitly skipped test. int.Parse -> int.
"""
import pytest

from flpit import AsyncFlpIt, SecondNoneError, SelectorNoneError, SourceNoneError, flp
from flpit.task import CancellationTokenSource, Task
from nettests.async_linq._set_cases import PAIRS
from nettests.async_linq.async_helpers import (
    assert_canceled, assert_equal, async_test, cancel_while_enumerating, consume, create_source, create_sources,
    track, unsupported,
)


async def _parse(x, ct):
    return int(x)


async def _identity(i, ct):
    return i


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    with pytest.raises(SecondNoneError):
        AsyncFlpIt.empty().except_by(None, len)
    with pytest.raises(SelectorNoneError):
        AsyncFlpIt.empty().except_by(AsyncFlpIt.empty(), None)


def test_Empty_ProducesEmpty():
    assert AsyncFlpIt.empty().except_by(create_source(1, 2, 3), lambda i: i) is AsyncFlpIt.empty()
    assert AsyncFlpIt.empty().except_by(create_source(1, 2, 3), _identity) is AsyncFlpIt.empty()


@pytest.mark.parametrize("first_ints, second", PAIRS)
@async_test
async def test_VariousValues_MatchesEnumerable(first_ints, second):
    first = [str(x) for x in first_ints]
    for first_source in create_sources(*first):
        for second_source in create_sources(*second):
            expected = list(flp.it(first).except_by(second, int))
            await assert_equal(expected, first_source.except_by(second_source, int))
            await assert_equal(expected, first_source.except_by(second_source, _parse))


def test_VariousValues_MatchesEnumerable_OddEvenComparer():
    unsupported("except_by(second, key_selector, comparer=...)")


@async_test
async def test_Cancellation_Cancels():
    first = create_source(2, 4, 8, 16)
    second = create_source(1, 3, 5)
    await cancel_while_enumerating(first.except_by(second, lambda x: x))

    cts = CancellationTokenSource()

    def cancel_then_key(x):
        cts.cancel()
        return x

    await assert_canceled(first.except_by(second, cancel_then_key), cts.token)

    cts = CancellationTokenSource()

    async def cancel_then_key_async(x, ct):
        assert ct is cts.token
        await Task.yield_now()
        cts.cancel()
        return x

    await assert_canceled(first.except_by(second, cancel_then_key_async), cts.token)


@pytest.mark.parametrize("use_async", [False, True])
@async_test
async def test_InterfaceCalls_ExpectedCounts(use_async):
    first = track(create_source(2, 4, 8, 16, 32, 64))
    second = track(create_source(1, 3, 5))
    func_count = 0

    def key(x):
        nonlocal func_count
        func_count += 1
        return x

    async def key_async(x, ct):
        return key(x)

    await consume(first.except_by(second, key_async if use_async else key))
    assert (first.move_next_count, first.current_count, first.dispose_count) == (7, 6, 1)
    assert (second.move_next_count, second.current_count, second.dispose_count) == (4, 3, 1)
    assert func_count == 6
