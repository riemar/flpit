"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable DistinctTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/DistinctTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * Distinct(IEqualityComparer) is not implemented (FlpIt.distinct has no comparer either); the
      OddEvenComparer assertions are split into an explicitly skipped test.
"""
import pytest

from flpit import AsyncFlpIt, SourceNoneError, flp
from nettests.async_linq.async_helpers import (
    assert_canceled, assert_equal, async_test, canceled_token, consume, create_source, create_sources, track,
    unsupported,
)

_VALUES = [[], [1], [1, 1, 1, 2, 2, 2, 2, 2], [2, 4, 8], [2, 4, 8, 2, 4, 8, 2], [-1, 2, 5, 6, 7, 8]]


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)


def test_Empty_ProducesEmpty():
    assert AsyncFlpIt.empty().distinct() is AsyncFlpIt.empty()


@pytest.mark.parametrize("values", _VALUES)
@async_test
async def test_VariousValues_MatchesEnumerable(values):
    for source in create_sources(*values):
        await assert_equal(list(dict.fromkeys(values)), source.distinct())


def test_VariousValues_MatchesEnumerable_Comparer():
    unsupported("distinct(comparer=...)")


@async_test
async def test_Cancellation_Cancels():
    await assert_canceled(create_source(2, 4, 8, 16).distinct(), canceled_token())


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source(2, 4, 8, 16))
    await consume(source.distinct())
    assert source.move_next_count == 5
    assert source.current_count == 4
    assert source.dispose_count == 1
