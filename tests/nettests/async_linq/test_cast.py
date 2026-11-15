"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Ported to pytest/Python from the .NET Runtime System.Linq.AsyncEnumerable CastTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq.AsyncEnumerable/tests/CastTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an adapted Python port of the source tests for AsyncFlpIt (mapping: async_helpers.py).

Mapping (as in tests/nettests/linq/test_cast.py):
    int? -> int | None,  double -> float,  InvalidCastException -> TypeError
"""
import pytest

from flpit import AsyncFlpIt, SourceNoneError, flp
from nettests.async_linq.async_helpers import (
    assert_equal, async_test, cancel_while_enumerating, consume, create_source, track,
)


class _CastTests:
    pass


def test_InvalidInputs_Throws():
    with pytest.raises(SourceNoneError):
        flp.ait(None)


def test_Empty_ProducesEmpty():
    assert AsyncFlpIt.empty().cast(str) is AsyncFlpIt.empty()
    assert AsyncFlpIt.empty().cast(float) is AsyncFlpIt.empty()


@async_test
async def test_NullAndNonNull_IncludesNulls():
    await assert_equal(["2", None, "8", None], create_source("2", None, "8", None).cast(str))
    await assert_equal(["2", None, "8", None], create_source("2", None, "8", None).cast(object))
    await assert_equal([2, None, 8, None], create_source(2, None, 8, None).cast(int | None))
    await assert_equal([2, 8], create_source(2, 8).cast(int))


@async_test
async def test_IncorrectType_Throws():
    with pytest.raises(TypeError):
        await consume(create_source(2, 8).cast(str))
    with pytest.raises(TypeError):
        await consume(create_source("2", "8").cast(int))
    with pytest.raises(TypeError):
        await consume(create_source("2", "8").cast(_CastTests))


@async_test
async def test_Cancellation_Cancels():
    await cancel_while_enumerating(create_source("2", None, "8", None).cast(str))


@async_test
async def test_InterfaceCalls_ExpectedCounts():
    source = track(create_source("1", "2", "3"))
    await consume(source.cast(str))
    assert source.move_next_count == 4
    assert source.current_count == 3
    assert source.dispose_count == 1
