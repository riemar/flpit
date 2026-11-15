"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable SkipTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/SkipTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * IAsyncEnumerator.Current has no Python equivalent: ``__anext__`` both moves and returns the element,
      so ``current_count`` counts successful moves. .NET's Skip moves past skipped elements without reading
      Current (CurrentCount 1 for Skip(3) over four elements); here every successful move counts (4).
"""
import pytest

from flpit import AsyncFlpIt, SourceNoneError, flp
from nettests.async_linq.async_helpers import (
    INT_CASES, assert_canceled, assert_equal, async_test, canceled_token, consume, create_source, create_sources,
    track,
)


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)


def test_Empty_ProducesEmpty():
    assert AsyncFlpIt.empty().skip(42) is AsyncFlpIt.empty()
    source = create_source(2, 4, 8, 16)
    assert source.skip(0) is source
    assert source.skip(-1) is source


@pytest.mark.parametrize("ints", INT_CASES)
@async_test
async def test_VariousValues_MatchesEnumerable(ints):
    for source in create_sources(*ints):
        for count in (-1, 0, 1, 2, 10):
            await assert_equal(list(flp.it(ints).skip(count)), source.skip(count))
            await assert_equal(ints[max(count, 0):], source.skip(count))


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)
    await assert_canceled(source.skip(1), canceled_token())


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source(1, 2, 3, 4))
    await consume(source.skip(0))
    assert source.move_next_count == 5
    assert source.current_count == 4
    assert source.dispose_count == 1

    source = track(create_source(1, 2, 3, 4))
    await consume(source.skip(3))
    assert source.move_next_count == 5
    assert source.current_count == 4  # .NET: 1 (see module docstring)
    assert source.dispose_count == 1
