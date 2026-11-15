"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable ToAsyncEnumerableTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/ToAsyncEnumerableTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

ToAsyncEnumerable maps to flp.ait(source) / FlpIt.to_async_enumerable(). Source mapping:
    Enumerable.Empty<T>() / T[] -> tuple / range (immutable; empty ones give AsyncFlpIt.empty())
    List<T>                     -> list (mutable, so never replaced by the shared empty sequence)
    HashSet<T> / Queue<T>       -> set / collections.deque
    ReadOnlyCollection<T>       -> tuple
    ToArrayAsync()              -> to_list()

Adapted:
    * SourceImplementsIAsyncEnumerable_ReturnsSameInstance: an AsyncFlpIt is returned as is; another object
      that is both iterable and async iterable is wrapped, and its async iterator is the one enumerated.
"""
from collections import deque

import pytest

from flpit import AsyncFlpIt, SourceNoneError, flp
from nettests.async_linq.async_helpers import (
    assert_equal, async_test, create_source, create_sources, to_pylist, track,
)


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)


def test_Empty_ProducesEmpty():
    empty = AsyncFlpIt.empty()
    assert flp.it(()).to_async_enumerable() is empty
    assert flp.ait(()) is empty
    assert flp.ait(range(0)) is empty
    assert flp.ait([]) is not empty
    assert flp.ait(set()) is not empty
    assert flp.ait(deque()) is not empty


@pytest.mark.parametrize("values", [[], [1], [1, 1, 1], [2, 4, 8], [-1, 2, 5, 6, 7, 8], [-1, 2, 5, 6, 7, 8, 6, -1, 5, 14]])
@async_test
async def test_VariousValues_MatchesEnumerable(values):
    for source in create_sources(*values):
        await assert_equal(values, flp.ait(tuple(await to_pylist(source))))
        await assert_equal(values, flp.ait(await source.to_list()))
        await assert_equal(values, flp.it(await source.to_list()).to_async_enumerable())
        await assert_equal(values, flp.ait(deque(await to_pylist(source))))


class _DualEnumerable:
    def __init__(self, items):
        self._items = items
        self.async_enumerations = 0

    def __iter__(self):
        return iter(self._items)

    async def _aiter(self):
        self.async_enumerations += 1
        for item in self._items:
            yield item

    def __aiter__(self):
        return self._aiter()


@async_test
async def test_SourceImplementsIAsyncEnumerable_ReturnsSameInstance():
    source = create_source(1, 2, 3)
    assert flp.ait(source) is source

    dual = _DualEnumerable([1, 2, 3])
    assert await to_pylist(flp.ait(dual)) == [1, 2, 3]
    assert dual.async_enumerations == 1


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source(2, 4, 8, 16))
    await source.to_list()
    assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)
