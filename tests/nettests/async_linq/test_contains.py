"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable ContainsAsyncTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/ContainsAsyncTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * ContainsAsync(value, IEqualityComparer) is not implemented (FlpIt.contains has no comparer either);
      the OddEvenComparer / LengthComparer assertions are split into explicitly skipped tests.
"""
import pytest

from flpit import SourceNoneError, flp
from flpit.task import OperationCanceledError
from nettests.async_linq.async_helpers import (
    async_test, canceled_token, create_source, create_sources, track, unsupported,
)


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)


@pytest.mark.parametrize("values", [[], [1], [2, 4, 8], [-1, 5, 6, 7, 8, 2]])
@async_test
async def test_VariousValues_MatchesEnumerable_Int32(values):
    for source in create_sources(*values):
        assert await source.contains(2) == (2 in values)


@pytest.mark.parametrize("values", [[], ["1"], ["2", "4", "8"], ["-1", "5", "6", "7", "8", "2", "12"]])
@async_test
async def test_VariousValues_MatchesEnumerable_String(values):
    for source in create_sources(*values):
        assert await source.contains("2") == ("2" in values)


def test_VariousValues_MatchesEnumerable_Comparer():
    unsupported("contains(value, comparer=...)")


@async_test
async def test_Cancellation_Cancels():
    with pytest.raises(OperationCanceledError):
        await create_source(1, 3, 5).contains(5, token=canceled_token())


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source(1, 3, 5))
    assert not await source.contains(6)
    assert (source.move_next_count, source.current_count, source.dispose_count) == (4, 3, 1)

    source = track(create_source(1, 3, 5))
    assert await source.contains(1)
    assert (source.move_next_count, source.current_count, source.dispose_count) == (1, 1, 1)
