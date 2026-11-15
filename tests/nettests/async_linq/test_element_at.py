"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable ElementAtAsyncTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/ElementAtAsyncTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * ElementAtAsync(Index) (including ^n from-end indexes) is not implemented (FlpIt.element_at takes an
      int only); the Index assertions are split into an explicitly skipped test.
    * IAsyncEnumerator.Current has no Python equivalent; current_count counts successful moves
      (ElementAtAsync(3): 4 where .NET reads Current once).
"""
import pytest

from flpit import ArgumentOutOfRangeError, SourceNoneError, flp
from flpit.task import OperationCanceledError
from nettests.async_linq.async_helpers import (
    async_test, canceled_token, create_source, create_sources, track, unsupported,
)


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)


@async_test
async def test_OutOfRange_Throws():
    for length in (0, 1, 2, 10):
        values = list(range(42, 42 + length))
        with pytest.raises(ArgumentOutOfRangeError):
            await flp.ait(values).element_at(-1)
        with pytest.raises(ArgumentOutOfRangeError):
            await flp.ait(values).element_at(length)


@pytest.mark.parametrize("values", [[1], [2, 4, 8], [-1, 2, 5, 6, 7, 8], [1, 3, 5, 7]])
@async_test
async def test_VariousValues_MatchesEnumerable(values):
    for source in create_sources(*values):
        for i in range(len(values)):
            assert await source.element_at(i) == values[i]


def test_VariousValues_MatchesEnumerable_Index():
    unsupported("element_at(Index) / from-end indexes")


@async_test
async def test_Cancellation_Cancels():
    with pytest.raises(OperationCanceledError):
        await create_source(2, 4, 8, 16).element_at(1, token=canceled_token())


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source(2, 4, 8, 16))
    await source.element_at(0)
    assert (source.move_next_count, source.current_count, source.dispose_count) == (1, 1, 1)

    source = track(create_source(2, 4, 8, 16))
    await source.element_at(3)
    assert (source.move_next_count, source.current_count, source.dispose_count) == (4, 4, 1)  # .NET: (4, 1, 1)
