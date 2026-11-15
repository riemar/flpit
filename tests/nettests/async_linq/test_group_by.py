"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable GroupByTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/GroupByTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

IGrouping<TKey, T> maps to Grouping (key + FlpList items). The expected values come from FlpIt.group_by.

Adapted (as in tests/nettests/linq/test_group_by.py):
    * group_by(key_selector) is implemented; the elementSelector / resultSelector / IEqualityComparer
      overloads are not (FlpIt.group_by has none of them). Their assertions are split into explicitly
      skipped tests; InterfaceCalls keeps the key-selector-only part.
"""
import random

import pytest

from flpit import AsyncFlpIt, SelectorNoneError, SourceNoneError, flp
from flpit.task import CancellationTokenSource, OperationCanceledError, Task
from nettests.async_linq.async_helpers import (
    TRUE_FALSE_BOOLS, assert_equal, async_test, consume, create_source, create_sources, fill_random_strings, track,
)

_SKIP_ELEMENT = pytest.mark.skip("element selector not implemented yet")
_SKIP_RESULT = pytest.mark.skip("result selector not implemented yet")
_SKIP_COMPARER = pytest.mark.skip("comparer not implemented yet")


async def _identity(i, ct):
    return i


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    with pytest.raises(SelectorNoneError):
        AsyncFlpIt.empty().group_by(None)


def test_Empty_ProducesEmpty():
    assert AsyncFlpIt.empty().group_by(lambda i: i) is AsyncFlpIt.empty()
    assert AsyncFlpIt.empty().group_by(_identity) is AsyncFlpIt.empty()


@async_test
async def test_VariousValues_MatchesEnumerable_String():
    async def length(s, ct):
        return len(s)

    rand = random.Random(42)
    for size in (0, 1, 2, 1000):
        values = fill_random_strings(rand, size)
        expected = list(flp.it(values).group_by(len))
        for source in create_sources(*values):
            await assert_equal(expected, source.group_by(len))
            await assert_equal(expected, source.group_by(length))


@_SKIP_ELEMENT
def test_VariousValues_MatchesEnumerable_String_ElementSelector():
    pass


@_SKIP_RESULT
def test_VariousValues_MatchesEnumerable_String_ResultSelector():
    pass


@_SKIP_COMPARER
def test_VariousValues_MatchesEnumerable_String_Comparer():
    pass


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)

    cts = CancellationTokenSource()

    def cancel_then_key(s):
        cts.cancel()
        return s

    with pytest.raises(OperationCanceledError):
        await consume(source.group_by(cancel_then_key).with_cancellation(cts.token))

    cts = CancellationTokenSource()

    async def cancel_then_key_async(s, ct):
        assert ct is cts.token
        await Task.yield_now()
        cts.cancel()
        return s

    with pytest.raises(OperationCanceledError):
        await consume(source.group_by(cancel_then_key_async).with_cancellation(cts.token))


@_SKIP_ELEMENT
def test_Cancellation_Cancels_ElementSelector():
    pass


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    for use_async in TRUE_FALSE_BOOLS:
        key_selector_count = 0

        def key(i):
            nonlocal key_selector_count
            key_selector_count += 1
            return i % 2

        async def key_async(i, ct):
            return key(i)

        source = track(create_source(1, 2, 3, 4))
        await consume(source.group_by(key_async if use_async else key))
        assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)
        assert key_selector_count == 4


@_SKIP_ELEMENT
def test_InterfaceCalls_ExpectedCounts_ElementAndResultSelectors():
    pass
