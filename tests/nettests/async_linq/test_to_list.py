"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable ToListAsyncTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/ToListAsyncTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

List<T> maps to FlpList.
"""
import pytest

from flpit import FlpList, SourceNoneError, flp
from flpit.task import OperationCanceledError
from nettests.async_linq.async_helpers import async_test, canceled_token, create_source, create_sources, track


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)


@pytest.mark.parametrize("values", [[], [1], [1, 1, 1], [2, 4, 8], [-1, 2, 5, 6, 7, 8], [-1, 2, 5, 6, 7, 8, 6, -1, 5, 14]])
@async_test
async def test_VariousValues_MatchesEnumerable(values):
    for source in create_sources(*values):
        result = await source.to_list()
        assert isinstance(result, FlpList)
        assert result == values
        assert await source.select(str).to_list() == [str(i) for i in values]


@async_test
async def test_Cancellation_Cancels():
    with pytest.raises(OperationCanceledError):
        await create_source(2, 4, 8, 16).to_list(token=canceled_token())


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source(2, 4, 8, 16))
    await source.to_list()
    assert (source.move_next_count, source.current_count, source.dispose_count) == (5, 4, 1)
