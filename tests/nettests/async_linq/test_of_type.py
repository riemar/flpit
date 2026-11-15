"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable OfTypeTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/OfTypeTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).
"""
import pytest

from flpit import AsyncFlpIt, SourceNoneError, flp
from nettests.async_linq.async_helpers import (
    assert_equal, async_test, cancel_while_enumerating, consume, create_source, track,
)


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)


def test_Empty_ProducesEmpty():
    assert AsyncFlpIt.empty().of_type(str) is AsyncFlpIt.empty()
    assert AsyncFlpIt.empty().of_type(int) is AsyncFlpIt.empty()


@async_test
async def test_NullAndNonNull_SkipsNulls():
    await assert_equal(["2", "8"], create_source("2", None, "8", None).of_type(str))
    await assert_equal(["2", "8"], create_source("2", None, "8", None).of_type(object))
    await assert_equal([2, 8], create_source(2, None, 8, None).of_type(int))


@async_test
async def test_Cancellation_Cancels():
    await cancel_while_enumerating(create_source("2", None, "8", None).of_type(str))


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source(2, None, 8, 16))
    await consume(source.of_type(int))
    assert source.move_next_count == 5
    assert source.current_count == 4
    assert source.dispose_count == 1
