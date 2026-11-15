"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable IntersectTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/IntersectTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * Intersect(second, IEqualityComparer) is not implemented (the sync FlpIt.intersect has no comparer either);
      the OddEvenComparer assertions are split into an explicitly skipped test.
    * The expected values come from the sync FlpIt.intersect (itself migrated against System.Linq).
"""
import pytest

from flpit import AsyncFlpIt, SecondNoneError, SourceNoneError, flp
from nettests.async_linq._set_cases import PAIRS
from nettests.async_linq.async_helpers import (
    assert_equal, async_test, cancel_while_enumerating, consume, create_source, create_sources, track, unsupported,
)


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    with pytest.raises(SecondNoneError):
        AsyncFlpIt.empty().intersect(None)


def test_Empty_ProducesEmpty():
    empty = AsyncFlpIt.empty()
    non_empty = create_source(1, 2, 3)
    assert empty.intersect(non_empty) is empty
    assert non_empty.intersect(empty) is empty


@pytest.mark.parametrize("first, second", PAIRS)
@async_test
async def test_VariousValues_MatchesEnumerable(first, second):
    for first_source in create_sources(*first):
        for second_source in create_sources(*second):
            await assert_equal(list(flp.it(first).intersect(second)), first_source.intersect(second_source))
            await assert_equal(list(flp.it(second).intersect(first)), second_source.intersect(first_source))


def test_VariousValues_MatchesEnumerable_OddEvenComparer():
    unsupported("intersect(second, comparer=...)")


@async_test
async def test_Cancellation_Cancels():
    await cancel_while_enumerating(create_source(2, 4, 8, 16).intersect(create_source(2, 5, 6, 7)))


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    first = track(create_source(2, 4, 8, 16))
    second = track(create_source(1, 3, 5))
    await consume(first.intersect(second))
    assert (first.move_next_count, first.current_count, first.dispose_count) == (5, 4, 1)
    assert (second.move_next_count, second.current_count, second.dispose_count) == (4, 3, 1)
