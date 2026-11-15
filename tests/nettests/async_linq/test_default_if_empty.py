"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable DefaultIfEmptyTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/DefaultIfEmptyTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * Python has no default(T), so default_if_empty() requires its default (as FlpIt.default_if_empty does);
      DefaultIfEmpty() over int maps to default_if_empty(0).
"""
import pytest

from flpit import AsyncFlpIt, SourceNoneError, flp
from nettests.async_linq.async_helpers import (
    assert_equal, async_test, cancel_while_enumerating, consume, create_source, create_sources, track,
)


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)
    AsyncFlpIt.empty().default_if_empty(None)


@pytest.mark.parametrize("values", [[], [1], [2, 4, 8], [-1, 2, 5, 6, 7, 8]])
@async_test
async def test_VariousValues_MatchesEnumerable(values):
    for source in create_sources(*values):
        await assert_equal(values or [0], source.default_if_empty(0))
        await assert_equal(values or [42], source.default_if_empty(42))


@async_test
async def test_Cancellation_Cancels():
    await cancel_while_enumerating(create_source(2, 4, 8, 16).default_if_empty(0))


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source(2, 4, 8, 16))
    await consume(source.default_if_empty(0))
    assert source.move_next_count == 5
    assert source.current_count == 4
    assert source.dispose_count == 1

    source = track(AsyncFlpIt.empty())
    await consume(source.default_if_empty(42))
    assert source.move_next_count == 1
    assert source.current_count == 0
    assert source.dispose_count == 1
