"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable MaxByAsyncTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/MaxByAsyncTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * flpit has no runtime generics, so every sequence is None-able (as for FlpIt.max_by): an empty
      sequence gives None; the non-nullable InvalidOperationException half is an explicitly skipped test.
    * MaxByAsync(keySelector, IComparer) is not implemented; the theory runs with the default comparer
      (null / Comparer<T>.Default) and the remaining comparers are an explicitly skipped test.
    * s.CompareTo("3") (culture-sensitive) -> s < "3" (ordinal); the oracle is FlpIt.max_by with the same key.
"""
import pytest

from flpit import AsyncFlpIt, SelectorNoneError, SourceNoneError, flp
from flpit.task import CancellationTokenSource, OperationCanceledError, Task
from nettests.async_linq.async_helpers import (
    async_test, create_source, create_sources, track, unsupported,
)


async def _double(i, ct):
    return i * 2


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)


@pytest.mark.xfail(strict=True, reason="Undecided deviation: flpit validates a None key selector only once there is an element (an empty "
           "source returns None); .NET throws ArgumentNullException('keySelector') at the call")
def test_InvalidInputs_Throws_KeySelector():
    # The keySelector half of upstream InvalidInputs_Throws, split off so the source half above stays a plain
    # test. The sync and async (i, ct) selector overloads are one Python method: one call covers both.
    with pytest.raises(SelectorNoneError):
        AsyncFlpIt.empty().max_by(None)


@async_test
async def test_EmptyInputs_ThrowsForNonNullableTypes():
    async def length(i, ct):
        return len(i)

    async def identity(i, ct):
        return i

    assert await AsyncFlpIt.empty().max_by(len) is None
    assert await AsyncFlpIt.empty().max_by(length) is None
    assert await AsyncFlpIt.empty().max_by(lambda i: i) is None
    assert await AsyncFlpIt.empty().max_by(identity) is None


@pytest.mark.skip("Python only has nullables")
def test_EmptyInputs_NonNullable_Throws():
    pass


@pytest.mark.parametrize("values", [[0], [1], [2, 4, 8], [-1, 2, 5, 6, 7, 8], [1, 8, 2, 7, 3, 6, 4, 5], [-1000, 1000], [-1, -2, -3]])
@async_test
async def test_VariousValues_MatchesEnumerable(values):
    def sync_and_async(key):
        async def key_async(x, ct):
            return key(x)
        return key, key_async

    strings = [str(i) for i in values]
    cases = [
        (values, lambda i: -i),
        (strings, lambda s: s.lower()),
        (strings, lambda s: None),
        (strings, lambda s: None if s < "3" else s),
    ]
    for source in create_sources(*values):
        for items, key in cases:
            actual_source = source if items is values else source.select(str)
            expected = flp.it(items).max_by(key)
            for selector in sync_and_async(key):
                assert await actual_source.max_by(selector) == expected


def test_VariousValues_MatchesEnumerable_Comparer():
    unsupported("max_by(key_selector, comparer=...)")


@async_test
async def test_Cancellation_Cancels():
    source = track(create_source(2, 4))

    cts = CancellationTokenSource()

    def cancel_then_key(i):
        cts.cancel()
        return i

    with pytest.raises(OperationCanceledError):
        await source.max_by(cancel_then_key, token=cts.token)

    cts = CancellationTokenSource()

    async def cancel_then_key_async(i, ct):
        assert ct is cts.token
        await Task.yield_now()
        cts.cancel()
        return i

    with pytest.raises(OperationCanceledError):
        await source.max_by(cancel_then_key_async, token=cts.token)


@pytest.mark.parametrize("use_async", [False, True])
@async_test
async def test_InterfaceCalls_ExpectedCounts(use_async):
    key_selector_count = 0

    def key(i):
        nonlocal key_selector_count
        key_selector_count += 1
        return i

    async def key_async(i, ct):
        return key(i)

    source = track(create_source(2, 4, 8, 16))
    await source.max_by(key_async if use_async else key)
    assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)
    assert key_selector_count == 4
