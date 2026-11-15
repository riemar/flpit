"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable TakeTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/TakeTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Adapted:
    * Take(Range) is not implemented (FlpIt.take has no Range overload either); the Range assertions
      are left out.
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
    assert AsyncFlpIt.empty().take_last(42) is AsyncFlpIt.empty()
    assert flp.ait([1, 2, 3]).take(0) is AsyncFlpIt.empty()
    assert flp.ait([1, 2, 3]).take(-1) is AsyncFlpIt.empty()


@pytest.mark.parametrize("ints", INT_CASES)
@async_test
async def test_VariousValues_MatchesEnumerable(ints):
    for source in create_sources(*ints):
        for count in (0, 1, 2, 10):
            await assert_equal(list(flp.it(ints).take(count)), source.take(count))
            await assert_equal(ints[:count], source.take(count))


@async_test
async def test_Cancellation_Cancels():
    source = create_source(2, 4, 8, 16)
    await assert_canceled(source.take(1), canceled_token())


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source(1, 2, 3, 4))
    await consume(source.take(1))
    assert source.move_next_count == 1
    assert source.current_count == 1
    assert source.dispose_count == 1

    source = track(create_source(1, 2, 3, 4))
    await consume(source.take(3))
    assert source.move_next_count == 3
    assert source.current_count == 3
    assert source.dispose_count == 1
