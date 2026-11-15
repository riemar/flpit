"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable RangeTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/RangeTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

AsyncEnumerable.Range(start, count) maps to AsyncFlpIt.range(start, count), validated against Int32 like .NET.
"""
import pytest

from flpit import ArgumentOutOfRangeError, AsyncFlpIt
from nettests.async_linq.async_helpers import INT_MAX, INT_MIN, assert_equal, async_test


def test_InvalidInputs_Throws():
    with pytest.raises(ArgumentOutOfRangeError, match="count"):
        AsyncFlpIt.range(-1, -1)
    with pytest.raises(ArgumentOutOfRangeError, match="count"):
        AsyncFlpIt.range(INT_MAX - 1, 3)


def test_Empty_ProducesEmpty():
    assert AsyncFlpIt.range(42, 0) is AsyncFlpIt.empty()


@async_test
async def test_VariousValues_MatchesEnumerable():
    for start in (INT_MIN, -1, 0, 1, 1_000_000):
        for count in (0, 1, 3, 10):
            await assert_equal(list(range(start, start + count)), AsyncFlpIt.range(start, count))
