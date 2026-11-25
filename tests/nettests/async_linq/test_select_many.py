"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable SelectManyTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/SelectManyTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

select_many(selector) accepts a sync or async selector returning a sync or async sequence, which covers
the SelectMany(Func<T, IEnumerable<R>>), (Func<T, CancellationToken, ValueTask<IEnumerable<R>>>) and
(Func<T, IAsyncEnumerable<R>>) overloads.

Adapted:
    * The (value, index) overloads and the (collectionSelector, resultSelector) overloads are not implemented
      (FlpIt.select_many has neither); their assertions are left out.
    * Callbacks_InvokedOnOriginalContext: SynchronizationContext has no Python equivalent (skipped).
"""
import random

import pytest

from flpit import AsyncFlpIt, SelectorNoneError, SourceNoneError, flp
from nettests.async_linq.async_helpers import (
    assert_equal, async_test, cancel_while_enumerating, consume, create_source, create_sources, fill_random_ints,
    not_portable, track, unsupported,
)


def _overloads(selector):
    """The three supported selector shapes for one Func<int, IEnumerable<int>>."""
    async def selector_async(i, ct):
        return selector(i)

    return [selector, selector_async, lambda i: flp.ait(selector(i))]


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    with pytest.raises(SelectorNoneError):
        AsyncFlpIt.empty().select_many(None)


def test_InvalidInputs_Throws_OtherOverloads():
    # The rest of upstream InvalidInputs_Throws: the (item, index) selector overloads ("selector") and the
    # collectionSelector / resultSelector overloads.
    unsupported("select_many((item, index) selector) / select_many(collection_selector, result_selector)")


def test_Empty_ProducesEmpty():
    for selector in _overloads(lambda s: list(s)):
        assert AsyncFlpIt.empty().select_many(selector) is AsyncFlpIt.empty()


@async_test
async def test_VariousValues_MatchesEnumerable():
    rand = random.Random(42)
    for collection_size in (0, 1, 10, 50):
        for _ in (1, 2, 3, 5, 60):
            ints = fill_random_ints(rand, collection_size)
            for source in create_sources(*ints):
                for selector in (lambda i: [], lambda i: [i], lambda i: [i, i * 2]):
                    expected = list(flp.it(ints).select_many(selector))
                    for overload in _overloads(selector):
                        await assert_equal(expected, source.select_many(overload))


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)
    for overload in _overloads(lambda i: [i]):
        await cancel_while_enumerating(source.select_many(overload))


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    for overload in _overloads(lambda i: [i, i + 1, i * 2]):
        source = track(create_source(1, 2, 3, 4))
        await consume(source.select_many(overload))
        assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)


def test_Callbacks_InvokedOnOriginalContext():
    not_portable("SynchronizationContext")
