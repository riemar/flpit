"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable RepeatTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/RepeatTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

AsyncEnumerable.Repeat(element, count) maps to AsyncFlpIt.repeat(element, count).
"""
import pytest

from flpit import ArgumentOutOfRangeError, AsyncFlpIt
from nettests.async_linq.async_helpers import assert_equal, async_test


def test_InvalidInputs_Throws():
    with pytest.raises(ArgumentOutOfRangeError, match="count"):
        AsyncFlpIt.repeat("a", -1)


def test_Empty_ProducesEmpty():
    assert AsyncFlpIt.repeat("42", 0) is AsyncFlpIt.empty()


@async_test
async def test_VariousValues_MatchesEnumerable():
    for count in (0, 1, 10):
        await assert_equal([42] * count, AsyncFlpIt.repeat(42, count))
        await assert_equal(["test"] * count, AsyncFlpIt.repeat("test", count))
        # re-enumerable, like .NET's Repeat
        repeated = AsyncFlpIt.repeat(7, count)
        await assert_equal([7] * count, repeated)
        await assert_equal([7] * count, repeated)
